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
        run_checked(['openssl', 'pkey', '-in', str(key_path), '-check', '-noout'], 'API private key validation')
        print('Building Universal app; importing Developer ID certificate, signing, notarizing and stapling with Tauri.', flush=True)
        run_checked(['npm', 'run', 'tauri', '--', 'build', '--ci', '--target', 'universal-apple-darwin', '--bundles', 'app,dmg', '--', '--locked'], 'Signed Tauri build and application notarization', env=env, timeout=4200)
        bundle = Path('src-tauri/target/universal-apple-darwin/release/bundle')
        apps, dmgs = list((bundle / 'macos').glob('*.app')), list((bundle / 'dmg').glob('*.dmg'))
        if len(apps) != 1 or len(dmgs) != 1:
            raise ValueError('Expected exactly one app and DMG')
        verify_app(apps[0], env['APPLE_SIGNING_IDENTITY'], version)
        verify_signature(dmgs[0], env['APPLE_SIGNING_IDENTITY'], executable=False)
        print('Application verified. Submitting the signed DMG to Apple notarization.', flush=True)
        result = run_checked(['xcrun', 'notarytool', 'submit', str(dmgs[0]), '--key', str(key_path), '--key-id', env['APPLE_API_KEY'], '--issuer', env['APPLE_API_ISSUER'], '--wait', '--timeout', '30m', '--output-format', 'json'], 'DMG notarization', timeout=1900)
        response = json.loads(result.stdout)
        if response.get('status') != 'Accepted':
            raise ValueError('Apple did not accept the DMG notarization; no release will be published')
        for attempt in range(3):
            try:
                run_checked(['xcrun', 'stapler', 'staple', str(dmgs[0])], 'DMG ticket stapling')
                break
            except RuntimeError:
                if attempt == 2:
                    raise
                time.sleep(15)
        run_checked(['xcrun', 'stapler', 'validate', str(dmgs[0])], 'DMG ticket verification')
    print('App and DMG signed, notarized and stapled; temporary API key removed.', flush=True)


if __name__ == '__main__':
    try:
        build()
    except (ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit('macOS signed release failed; sensitive tool output withheld') from None
