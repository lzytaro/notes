"""Sign and notarize macOS releases, retaining exact bytes and receipts for recovery."""
import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import secrets
import shlex
import shutil
import stat
import sys
import tempfile
import time
import uuid
import zipfile
from macos_release import run_checked, signing_team, verify_app, verify_signature

REQUIRED_SECRETS = (
    'APPLE_CERTIFICATE', 'APPLE_CERTIFICATE_PASSWORD', 'APPLE_SIGNING_IDENTITY',
    'APPLE_API_ISSUER', 'APPLE_API_KEY', 'APPLE_API_PRIVATE_KEY',
)
CHECKPOINT = Path('artifacts/notarization')
BUNDLE = Path('src-tauri/target/universal-apple-darwin/release/bundle')
WAIT_SECONDS = 10 * 60


class NotarizationPending(RuntimeError):
    """The job can resume from its saved checkpoint after Apple finishes processing."""


def validate_credentials(env):
    missing = [name for name in REQUIRED_SECRETS if not env.get(name, '').strip()]
    if missing:
        raise ValueError('Missing GitHub Secrets: ' + ', '.join(missing))
    signing_team(env['APPLE_SIGNING_IDENTITY'])
    if not re.fullmatch(r'[A-Z0-9]{10,}', env['APPLE_API_KEY']):
        raise ValueError('APPLE_API_KEY must contain the Key ID, not the private key')
    try:
        uuid.UUID(env['APPLE_API_ISSUER'])
        base64.b64decode(''.join(env['APPLE_CERTIFICATE'].split()), validate=True)
    except (ValueError, TypeError):
        raise ValueError('Invalid certificate encoding or API issuer format') from None
    private_key = env['APPLE_API_PRIVATE_KEY'].strip()
    if not private_key.startswith('-----BEGIN ' + 'PRIVATE KEY-----') or not private_key.endswith('-----END ' + 'PRIVATE KEY-----'):
        raise ValueError('APPLE_API_PRIVATE_KEY must contain the complete downloaded .p8 file')



def private_file(path, content):
    with open(path, 'xb', opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
        output.write(content)


@contextmanager
def dmg_signing_keychain(env):
    """Tauri removes its own keychain. Import an isolated one just for the DMG."""
    with tempfile.TemporaryDirectory(prefix='notes-dmg-sign-', dir=env.get('RUNNER_TEMP')) as temporary:
        keychain = Path(temporary) / 'signing.keychain-db'
        certificate = Path(temporary) / 'certificate.p12'
        private_file(certificate, base64.b64decode(env['APPLE_CERTIFICATE']))
        password = secrets.token_urlsafe(32)
        original = shlex.split(run_checked(['security', 'list-keychains', '-d', 'user'], 'Keychain list').stdout.decode())
        try:
            run_checked(['security', 'create-keychain', '-p', password, str(keychain)], 'Temporary keychain creation')
            run_checked(['security', 'unlock-keychain', '-p', password, str(keychain)], 'Temporary keychain unlock')
            run_checked(['security', 'import', str(certificate), '-f', 'pkcs12', '-k', str(keychain), '-P', env['APPLE_CERTIFICATE_PASSWORD'], '-T', '/usr/bin/codesign'], 'DMG signing certificate import')
            run_checked(['security', 'set-key-partition-list', '-S', 'apple-tool:,apple:,codesign:', '-s', '-k', password, str(keychain)], 'DMG signing key access')
            yield keychain
        finally:
            try:
                run_checked(['security', 'list-keychains', '-d', 'user', '-s', *original], 'Keychain list restoration')
            finally:
                if keychain.exists():
                    run_checked(['security', 'delete-keychain', str(keychain)], 'Temporary keychain cleanup')


def create_dmg(app, destination, volume_name, env):
    """Package the stapled app directly, preserving its code signature and ticket."""
    with tempfile.TemporaryDirectory(prefix='notes-dmg-staging-') as temporary:
        staging = Path(temporary)
        run_checked(['ditto', '--rsrc', '--extattr', '--acl', str(app), str(staging / app.name)], 'DMG app staging')
        (staging / 'Applications').symlink_to('/Applications')
        run_checked(['hdiutil', 'create', '-volname', volume_name, '-srcfolder', str(staging), '-format', 'UDZO', str(destination)], 'DMG creation', timeout=300)
    with dmg_signing_keychain(env) as keychain:
        run_checked(['codesign', '--force', '--sign', env['APPLE_SIGNING_IDENTITY'], '--keychain', str(keychain), '--timestamp', str(destination)], 'DMG code signing')
    verify_signature(destination, env['APPLE_SIGNING_IDENTITY'], executable=False)


def digest(path):
    with open(path, 'rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def save_state(root, state):
    temporary = root / 'state.json.tmp'
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(root / 'state.json')


def load_state(root, version, commit):
    state = json.loads((root / 'state.json').read_text())
    if state.get('format') != 1 or state.get('version') != version or state.get('commit') != commit:
        raise ValueError('Notarization checkpoint belongs to another version or commit')
    for name, filename in [('app', 'app.zip'), ('dmg', 'installer.dmg')]:
        record = state.get(name)
        if record is None and name == 'dmg':
            continue
        if not isinstance(record, dict) or record.get('sha256') != digest(root / filename):
            raise ValueError('Notarization checkpoint checksum mismatch')
        submission = record.get('submission')
        if submission is not None:
            uuid.UUID(submission)
    return state


def parse_response(result):
    try:
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, TypeError):
        raise ValueError('Apple returned an unreadable response; release blocked') from None


def submit(root, state, name, path, auth):
    record = state[name]
    if record.get('submission'):
        return record['submission']
    if record.get('submission_started'):
        raise ValueError('Submission receipt is missing. Inspect Apple history before any resubmission; release blocked')
    # Persist intent before the network operation. An ambiguous network failure
    # must never cause an automatic duplicate submission on recovery.
    record['submission_started'] = True
    save_state(root, state)
    result = run_checked(['xcrun', 'notarytool', 'submit', str(path), *auth, '--output-format', 'json'], f'{name} notarization submission', timeout=300)
    response = parse_response(result)
    try:
        identifier = str(uuid.UUID(response['id']))
    except (KeyError, ValueError, TypeError):
        raise ValueError('Apple did not return a valid submission ID; release blocked') from None
    record['submission'] = identifier
    save_state(root, state)
    print(f'{name} submission receipt saved.', flush=True)
    return identifier


def wait_for_notarization(submission, auth, label, *, timeout_seconds=WAIT_SECONDS, poll_seconds=30):
    deadline = time.monotonic() + timeout_seconds
    last_status = None
    while True:
        try:
            result = run_checked(['xcrun', 'notarytool', 'info', submission, *auth, '--output-format', 'json'], f'{label} status', timeout=90)
        except RuntimeError:
            # A transient read failure does not discard the known submission.
            if time.monotonic() >= deadline:
                raise NotarizationPending(f'{label} status is unavailable; resume from the saved checkpoint') from None
            time.sleep(poll_seconds)
            continue
        response = parse_response(result)
        if response.get('id') != submission:
            raise ValueError('Apple returned a different submission ID; release blocked')
        status = response.get('status')
        if status not in {'Accepted', 'Invalid', 'Rejected', 'In Progress', 'Submitted'}:
            raise ValueError('Apple returned an unexpected status; release blocked')
        if status != last_status:
            print(f'{label}: {status}', flush=True)
            last_status = status
        if status == 'Accepted':
            return
        if status in {'Invalid', 'Rejected'}:
            raise ValueError(f'{label} was rejected by Apple; release blocked')
        if time.monotonic() >= deadline:
            raise NotarizationPending(f'{label} is still processing; resume from the saved checkpoint')
        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))


def staple(path, label):
    for attempt in range(3):
        try:
            run_checked(['xcrun', 'stapler', 'staple', str(path)], f'{label} ticket stapling')
            run_checked(['xcrun', 'stapler', 'validate', str(path)], f'{label} ticket verification')
            return
        except RuntimeError:
            if attempt == 2:
                raise
            time.sleep(15)


def restore_app(archive, destination, app_name):
    # Artifacts are accepted only from the same reviewed tag run, and are still
    # checked before extraction, then verified against the Developer ID identity.
    with zipfile.ZipFile(archive) as zipped:
        for entry in zipped.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] not in {app_name, '__MACOSX'} or '\\' in entry.filename:
                raise ValueError('Unsafe path in notarization checkpoint')
            if stat.S_ISLNK(entry.external_attr >> 16):
                target = zipped.read(entry).decode()
                resolved = posixpath.normpath(str(path.parent / target))
                if target.startswith('/') or not resolved.startswith(app_name + '/'):
                    raise ValueError('Escaping link in notarization checkpoint')
    run_checked(['ditto', '-x', '-k', str(archive), str(destination)], 'Signed app checkpoint extraction')
    app = destination / app_name
    if not app.is_dir() or app.is_symlink():
        raise ValueError('Notarization checkpoint has no application')
    return app


def build(*, resume=False, checkpoint=CHECKPOINT, wait_seconds=WAIT_SECONDS):
    if sys.platform != 'darwin':
        raise ValueError('Signed macOS releases must be built on macOS')
    env = os.environ.copy()
    validate_credentials(env)
    config = json.loads(Path('src-tauri/tauri.conf.json').read_text())
    version = json.loads(Path('package.json').read_text())['version']
    app_name = config['productName'] + '.app'
    commit = run_checked(['git', 'rev-parse', 'HEAD'], 'Source commit lookup').stdout.decode().strip()
    checkpoint = Path(checkpoint)
    if resume:
        state = load_state(checkpoint, version, commit)
    else:
        if checkpoint.exists() and any(checkpoint.iterdir()):
            raise ValueError('Checkpoint already exists. Use --resume instead of rebuilding or resubmitting')
        checkpoint.mkdir(parents=True, exist_ok=True)
        state = {'format': 1, 'version': version, 'commit': commit}
    with tempfile.TemporaryDirectory(prefix='notes-apple-', dir=env.get('RUNNER_TEMP')) as temporary:
        key_path = Path(temporary) / 'AuthKey.p8'
        private_file(key_path, (env.pop('APPLE_API_PRIVATE_KEY').strip() + '\n').encode())
        run_checked(['openssl', 'ec', '-in', str(key_path), '-pubout', '-out', os.devnull], 'API private key validation')
        auth = ['--key', str(key_path), '--key-id', env['APPLE_API_KEY'], '--issuer', env['APPLE_API_ISSUER']]
        app_dir = BUNDLE / 'macos'
        if resume:
            if app_dir.exists() and any(app_dir.iterdir()):
                raise ValueError('Application output must be empty before restoring a checkpoint')
            app_dir.mkdir(parents=True, exist_ok=True)
            app = restore_app(checkpoint / 'app.zip', app_dir, app_name)
        else:
            build_env = {k: v for k, v in env.items() if not k.startswith(('APPLE_API_', 'TAURI_SIGNING_')) and k not in {'APPLE_ID', 'APPLE_PASSWORD', 'APPLE_TEAM_ID'}}
            print('Building and Developer-ID signing the Universal app.', flush=True)
            run_checked(['npm', 'run', 'tauri', '--', 'build', '--ci', '--target', 'universal-apple-darwin', '--bundles', 'app', '--', '--locked'], 'Signed Tauri application build', env=build_env, timeout=2400)
            app = app_dir / app_name
            verify_signature(app, env['APPLE_SIGNING_IDENTITY'], executable=True)
            run_checked(['ditto', '-c', '-k', '--keepParent', '--sequesterRsrc', str(app), str(checkpoint / 'app.zip')], 'Signed app checkpoint creation')
            state['app'] = {'sha256': digest(checkpoint / 'app.zip')}
            save_state(checkpoint, state)
        verify_signature(app, env['APPLE_SIGNING_IDENTITY'], executable=True)
        app_submission = submit(checkpoint, state, 'app', checkpoint / 'app.zip', auth)
        wait_for_notarization(app_submission, auth, 'Application notarization', timeout_seconds=wait_seconds)
        staple(app, 'Application')
        verify_app(app, env['APPLE_SIGNING_IDENTITY'], version)
        # The stored app.zip remains the exact bytes originally submitted to
        # Apple. Every resume staples the restored original only after Accepted.
        if not state.get('dmg'):
            temporary_dmg = Path(temporary) / 'installer.dmg'
            create_dmg(app, temporary_dmg, f'纸笺 {version}', env)
            shutil.copyfile(temporary_dmg, checkpoint / 'installer.dmg')
            state['dmg'] = {'sha256': digest(checkpoint / 'installer.dmg')}
            save_state(checkpoint, state)
        verify_signature(checkpoint / 'installer.dmg', env['APPLE_SIGNING_IDENTITY'], executable=False)
        dmg_submission = submit(checkpoint, state, 'dmg', checkpoint / 'installer.dmg', auth)
        wait_for_notarization(dmg_submission, auth, 'DMG notarization', timeout_seconds=wait_seconds)
        dmg_dir = BUNDLE / 'dmg'
        dmg_dir.mkdir(parents=True, exist_ok=True)
        if any(dmg_dir.iterdir()):
            raise ValueError('DMG output must be empty; refusing stale output')
        dmg = dmg_dir / f'notes_{version}_macos-universal.dmg'
        shutil.copyfile(checkpoint / 'installer.dmg', dmg)
        staple(dmg, 'DMG')
        verify_signature(dmg, env['APPLE_SIGNING_IDENTITY'], executable=False)
    print('App and DMG signed, notarized and stapled. Final distribution verification follows.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    try:
        build(resume=args.resume)
    except NotarizationPending as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(75) from None
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit('macOS signed release failed; sensitive tool output withheld') from None
