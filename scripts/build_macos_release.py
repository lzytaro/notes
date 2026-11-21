"""Build, Developer-ID sign and notarize an application and its DMG using CI secrets."""
import base64
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid
from macos_release import run_checked, signing_team, verify_app, verify_signature

REQUIRED_SECRETS = (
    'APPLE_CERTIFICATE', 'APPLE_CERTIFICATE_PASSWORD', 'APPLE_SIGNING_IDENTITY',
    'APPLE_API_ISSUER', 'APPLE_API_KEY', 'APPLE_API_PRIVATE_KEY',
)
NOTARIZATION_POLL_SECONDS = 30
NOTARIZATION_TIMEOUT_SECONDS = 4 * 60 * 60
TOTAL_NOTARIZATION_TIMEOUT_SECONDS = 5 * 60 * 60


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


def submission_id(result):
    """Extract a notarytool submission UUID without echoing its output."""
    output = b'\n'.join(part for part in [result.stdout, result.stderr] if part).decode(errors='replace')
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get('id'), str):
            try:
                return str(uuid.UUID(value['id']))
            except ValueError:
                pass
    match = re.search(r'(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])', output, re.IGNORECASE)
    if match:
        return str(uuid.UUID(match.group(0)))
    raise ValueError('Apple notarization did not return a submission ID; release blocked')


def wait_for_notarization(submission, key_path, key_id, issuer, label, *, timeout_seconds=NOTARIZATION_TIMEOUT_SECONDS, poll_seconds=NOTARIZATION_POLL_SECONDS):
    """Poll Apple without tying the release to notarytool's one-shot wait timeout."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = run_checked([
            'xcrun', 'notarytool', 'info', submission,
            '--key', str(key_path), '--key-id', key_id, '--issuer', issuer,
            '--output-format', 'json',
        ], f'{label} status', timeout=120)
        try:
            response = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            raise RuntimeError(f'{label} returned an unreadable status; release blocked') from None
        status = response.get('status')
        if status == 'Accepted':
            return
        if status in {'Invalid', 'Rejected'}:
            raise ValueError(f'{label} was rejected by Apple ({status}); release blocked')
        if status not in {'In Progress', 'Submitted', 'Accepted'}:
            raise RuntimeError(f'{label} returned unexpected status; release blocked')
        if time.monotonic() >= deadline:
            raise RuntimeError(f'{label} did not finish within the allowed window; release blocked')
        time.sleep(poll_seconds)


def remaining_timeout(deadline, label):
    seconds = int(deadline - time.monotonic())
    if seconds <= 0:
        raise RuntimeError(f'{label} exceeded the shared notarization window; release blocked')
    return min(seconds, NOTARIZATION_TIMEOUT_SECONDS)


def create_dmg(app, destination, volume_name, identity):
    """Create a DMG from the already-stapled app without rebuilding or resigning it."""
    with tempfile.TemporaryDirectory(prefix='notes-dmg-staging-') as staging_name:
        staging = Path(staging_name)
        run_checked(['ditto', '--rsrc', '--extattr', '--acl', str(app), str(staging / app.name)], 'DMG app staging')
        run_checked(['ln', '-s', '/Applications', str(staging / 'Applications')], 'DMG Applications link')
        run_checked(['hdiutil', 'create', '-volname', volume_name, '-srcfolder', str(staging), '-ov', '-format', 'UDZO', str(destination)], 'DMG creation')
    run_checked(['codesign', '--force', '--sign', identity, '--timestamp', str(destination)], 'DMG code signing')


def build():
    if sys.platform != 'darwin':
        raise ValueError('Signed macOS releases must be built on macOS')
    env = os.environ.copy()
    validate_credentials(env)
    version = json.loads(Path('package.json').read_text())['version']
    with tempfile.TemporaryDirectory(prefix='notes-apple-', dir=env.get('RUNNER_TEMP')) as temporary:
        key_path = Path(temporary) / 'AuthKey.p8'
        # An on-runner path is not a repository secret. Only file CONTENTS are stored in Secrets.
        with open(key_path, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as key:
            key.write(env.pop('APPLE_API_PRIVATE_KEY').strip() + '\n')
        env['APPLE_API_KEY_PATH'] = str(key_path)
        # Never fall back to an Apple ID/password inherited from the environment.
        for name in ['APPLE_ID', 'APPLE_PASSWORD', 'APPLE_TEAM_ID']:
            env.pop(name, None)
        run_checked(['openssl', 'ec', '-in', str(key_path), '-pubout', '-out', os.devnull], 'API private key validation')
        # Tauri's built-in notarization waits inside the build command. On a first
        # submission Apple can take several hours, so build the signed app first
        # with API credentials removed, then submit and poll explicitly below.
        build_env = env.copy()
        for name in ['APPLE_API_ISSUER', 'APPLE_API_KEY', 'APPLE_API_KEY_PATH', 'APPLE_API_PRIVATE_KEY', 'APPLE_ID', 'APPLE_PASSWORD', 'APPLE_TEAM_ID']:
            build_env.pop(name, None)
        print('Building Universal app and importing the Developer ID certificate.', flush=True)
        run_checked(['npm', 'run', 'tauri', '--', 'build', '--ci', '--target', 'universal-apple-darwin', '--bundles', 'app', '--', '--locked'], 'Signed Tauri application build', env=build_env, timeout=2400)
        bundle = Path('src-tauri/target/universal-apple-darwin/release/bundle')
        apps = list((bundle / 'macos').glob('*.app'))
        if len(apps) != 1:
            raise ValueError('Expected exactly one universal macOS app')
        app = apps[0]
        verify_signature(app, env['APPLE_SIGNING_IDENTITY'], executable=True)

        app_zip = Path(temporary) / f'{app.stem}.zip'
        run_checked(['ditto', '-c', '-k', '--keepParent', str(app), str(app_zip)], 'Application archive creation')
        result = run_checked([
            'xcrun', 'notarytool', 'submit', str(app_zip),
            '--key', str(key_path), '--key-id', env['APPLE_API_KEY'], '--issuer', env['APPLE_API_ISSUER'],
            '--output-format', 'json',
        ], 'Application notarization submission', timeout=300)
        app_submission = submission_id(result)
        print('Application submitted to Apple; polling until the decision is available.', flush=True)
        notarization_deadline = time.monotonic() + TOTAL_NOTARIZATION_TIMEOUT_SECONDS
        wait_for_notarization(app_submission, key_path, env['APPLE_API_KEY'], env['APPLE_API_ISSUER'], 'Application notarization', timeout_seconds=remaining_timeout(notarization_deadline, 'Application notarization'))
        for attempt in range(3):
            try:
                run_checked(['xcrun', 'stapler', 'staple', str(app)], 'Application ticket stapling')
                break
            except RuntimeError:
                if attempt == 2:
                    raise
                time.sleep(15)
        run_checked(['xcrun', 'stapler', 'validate', str(app)], 'Application ticket verification')

        # Create the DMG from the stapled app directly. Tauri's DMG-only bundle
        # pass rebuilds the app and would discard its ticket.
        dmg_dir = bundle / 'dmg'
        dmg_dir.mkdir(parents=True, exist_ok=True)
        for previous in dmg_dir.glob('*.dmg'):
            previous.unlink()
        dmg = dmg_dir / f'notes_{version}_macos-universal.dmg'
        verify_app(app, env['APPLE_SIGNING_IDENTITY'], version)
        create_dmg(app, dmg, f'纸笺 {version}', env['APPLE_SIGNING_IDENTITY'])
        verify_signature(dmg, env['APPLE_SIGNING_IDENTITY'], executable=False)
        print('Application verified. Submitting the signed DMG to Apple.', flush=True)
        result = run_checked([
            'xcrun', 'notarytool', 'submit', str(dmg),
            '--key', str(key_path), '--key-id', env['APPLE_API_KEY'], '--issuer', env['APPLE_API_ISSUER'],
            '--output-format', 'json',
        ], 'DMG notarization submission', timeout=300)
        dmg_submission = submission_id(result)
        wait_for_notarization(dmg_submission, key_path, env['APPLE_API_KEY'], env['APPLE_API_ISSUER'], 'DMG notarization', timeout_seconds=remaining_timeout(notarization_deadline, 'DMG notarization'))
        for attempt in range(3):
            try:
                run_checked(['xcrun', 'stapler', 'staple', str(dmg)], 'DMG ticket stapling')
                break
            except RuntimeError:
                if attempt == 2:
                    raise
                time.sleep(15)
        run_checked(['xcrun', 'stapler', 'validate', str(dmg)], 'DMG ticket verification')
    print('App and DMG signed, notarized and stapled; temporary API key removed.', flush=True)


if __name__ == '__main__':
    try:
        build()
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit('macOS signed release failed; sensitive tool output withheld') from None
