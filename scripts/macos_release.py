"""Developer ID / notarization checks for the actual files that will be shipped.

All command output is captured: certificates, account identifiers and credentials
must not accidentally become public CI logs. A failing check always blocks release.
"""
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tarfile
import tempfile

VERIFICATION_FIELDS = (
    'developer_id', 'hardened_runtime', 'app_stapled', 'app_gatekeeper',
    'dmg_stapled', 'dmg_gatekeeper', 'dmg_contents_verified', 'archive_verified',
)


def run_checked(command, label, *, env=None, timeout=120):
    if env is None:
        env = {name: value for name, value in os.environ.items() if not name.startswith(('APPLE_', 'TAURI_SIGNING_'))}
    try:
        result = subprocess.run(command, capture_output=True, env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(f'{label} could not finish; release blocked') from None
    if result.returncode:
        raise RuntimeError(f'{label} failed; release blocked (tool output withheld)')
    return result


def signing_team(identity):
    match = re.fullmatch(r'Developer ID Application: .+ \(([A-Z0-9]{10})\)', identity or '')
    if not match:
        raise ValueError('A Developer ID Application identity is required; ad-hoc and development identities are rejected')
    return match.group(1)


def validate_signature_details(details, identity, executable):
    team = signing_team(identity)
    if f'Authority={identity}' not in details.splitlines() or f'TeamIdentifier={team}' not in details.splitlines():
        raise ValueError('Code signature does not match the configured Developer ID identity')
    if not re.search(r'^Timestamp=.+', details, re.MULTILINE):
        raise ValueError('Code signature has no secure timestamp')
    if executable and not re.search(r'flags=.*\bruntime\b', details):
        raise ValueError('Hardened runtime must be enabled')


def verify_signature(path, identity, *, executable):
    flags = ['--deep'] if executable else []
    run_checked(['codesign', '--verify', *flags, '--strict', '--verbose=2', str(path)], 'Code signature verification')
    result = run_checked(['codesign', '--display', '--verbose=4', str(path)], 'Code signature inspection')
    validate_signature_details((result.stdout + result.stderr).decode(errors='replace'), identity, executable)


def verify_app(app, identity, version):
    app = Path(app)
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'com.lzytaro.notes' or info.get('CFBundleShortVersionString') != version:
        raise ValueError('Application identity or version does not match this release')
    verify_signature(app, identity, executable=True)
    entitlements = run_checked(['codesign', '--display', '--entitlements', ':-', str(app)], 'Entitlement inspection').stdout
    if entitlements.strip() and plistlib.loads(entitlements).get('com.apple.security.get-task-allow'):
        raise ValueError('A release must not grant debugger access')
    run_checked(['xcrun', 'stapler', 'validate', str(app)], 'Application notarization ticket verification')
    run_checked(['spctl', '--assess', '--type', 'execute', '--verbose=4', str(app)], 'Application Gatekeeper assessment')


def verify_archive(archive_path, identity, version):
    with tempfile.TemporaryDirectory(prefix='notes-archive-verify-') as temporary:
        root = Path(temporary)
        with tarfile.open(archive_path, 'r:gz') as archive:
            # No absolute paths, path traversal, escaping links or special files.
            archive.extractall(root, filter='data')
        apps = list(root.glob('*.app'))
        if len(apps) != 1 or len(list(root.iterdir())) != 1:
            raise ValueError('Updater archive must contain exactly one application')
        verify_app(apps[0], identity, version)


def verify_distribution(app, dmg, archive, identity, version):
    if sys.platform != 'darwin':
        raise RuntimeError('macOS release verification must run on macOS')
    verify_app(app, identity, version)
    verify_signature(dmg, identity, executable=False)
    run_checked(['xcrun', 'stapler', 'validate', str(dmg)], 'DMG notarization ticket verification')
    run_checked(['spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature', '--verbose=4', str(dmg)], 'DMG Gatekeeper assessment')
    with tempfile.TemporaryDirectory(prefix='notes-dmg-verify-') as temporary:
        mount = Path(temporary) / 'mount'
        mount.mkdir()
        run_checked(['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(dmg)], 'Read-only DMG mount')
        try:
            apps = list(mount.glob('*.app'))
            if len(apps) != 1:
                raise ValueError('DMG must contain exactly one application')
            verify_app(apps[0], identity, version)
        finally:
            try:
                run_checked(['hdiutil', 'detach', str(mount)], 'DMG detach')
            except RuntimeError:
                run_checked(['hdiutil', 'detach', '-force', str(mount)], 'DMG forced detach')
    # Verify AFTER repacking: the updater tarball must retain the staple and signature.
    verify_archive(archive, identity, version)
    return {field: True for field in VERIFICATION_FIELDS}


def require_macos_verification(source):
    checks = source.get('macos_verification', {})
    if source.get('signed') is not True or source.get('notarized') is not True or any(checks.get(field) is not True for field in VERIFICATION_FIELDS):
        raise ValueError('macOS release must pass Developer ID, notarization, ticket, Gatekeeper and final archive checks')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--dmg', required=True, type=Path)
    parser.add_argument('--archive', required=True, type=Path)
    args = parser.parse_args()
    version = json.loads(Path('package.json').read_text())['version']
    try:
        verify_distribution(args.app, args.dmg, args.archive, os.environ.get('APPLE_SIGNING_IDENTITY', ''), version)
    except (RuntimeError, ValueError, OSError, plistlib.InvalidFileException, tarfile.TarError):
        raise SystemExit('macOS distribution verification failed; release blocked (details withheld)') from None
    print('Developer ID, notarization tickets, Gatekeeper, DMG contents and final updater archive verified.')
