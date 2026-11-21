"""Collect only distributables, never upload the build directory or local machine output."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path, PurePosixPath


def public_metadata(member):
    """Strip builder identity and reject links that leave the application bundle."""
    path = PurePosixPath(member.name)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Archive entry escapes the application bundle')
    if path.name.startswith('.env') or path.suffix in {'.db', '.sqlite', '.log'} or path.name == '.DS_Store':
        raise ValueError('Private or generated application data found in bundle')
    if member.issym() or member.islnk():
        target = PurePosixPath(member.linkname)
        depth = len(path.parts) - 1
        if target.is_absolute():
            raise ValueError('Absolute archive link is not allowed')
        for part in target.parts:
            depth += -1 if part == '..' else 0 if part == '.' else 1
            if depth < 1:
                raise ValueError('Archive link leaves the application bundle')
    member.uid = member.gid = 0
    member.uname = member.gname = ''
    member.pax_headers = {}
    return member

parser = argparse.ArgumentParser()
parser.add_argument('--platform', required=True, choices=['macos-universal', 'windows-x64'])
parser.add_argument('--sign-updates', action='store_true', help='Sign the exact packaged bytes; requires the CI signing secret')
args = parser.parse_args()
version = json.loads(Path('package.json').read_text())['version']
target = Path('src-tauri/target')
out = Path('release-assets')
if out.exists() and any(out.iterdir()):
    raise SystemExit('Release output directory must be empty; refusing to upload stale files')
out.mkdir(exist_ok=True)
if args.platform == 'macos-universal':
    root = target / 'universal-apple-darwin/release/bundle'
    apps = list((root / 'macos').glob('*.app'))
    dmgs = list((root / 'dmg').glob('*.dmg'))
    if len(apps) != 1 or len(dmgs) != 1:
        raise SystemExit('Expected exactly one universal macOS app and DMG')
    with tarfile.open(out / f'notes_{version}_macos-universal.app.tar.gz', 'w:gz') as archive:
        archive.add(apps[0], arcname=apps[0].name, filter=public_metadata)
    shutil.copyfile(dmgs[0], out / f'notes_{version}_macos-universal.dmg')
else:
    root = target / 'release/bundle'
    for folder, extension in [('nsis', 'exe'), ('msi', 'msi')]:
        files = list((root / folder).glob(f'*.{extension}'))
        if len(files) != 1:
            raise SystemExit(f'Expected exactly one {extension} installer')
        shutil.copyfile(files[0], out / f'notes_{version}_windows-x64.{extension}')
sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
if args.sign_updates:
    if not os.environ.get('TAURI_SIGNING_PRIVATE_KEY'):
        raise SystemExit('Missing updater signing secret; refusing unsigned release')
    artifacts = [out / f'notes_{version}_macos-universal.app.tar.gz'] if args.platform == 'macos-universal' else [out / f'notes_{version}_windows-x64.{ext}' for ext in ['exe', 'msi']]
    for artifact in artifacts:
        # Never put a secret in argv or emit signer output, including error output.
        command = ['node', 'node_modules/@tauri-apps/cli/tauri.js', 'signer', 'sign', '--app-version', version, str(artifact)]
        result = subprocess.run(command, capture_output=True)
        signature = Path(str(artifact) + '.sig')
        if result.returncode or not signature.exists() or not signature.read_text().strip():
            raise SystemExit('Updater signing failed (signer output withheld)')
metadata = {'version': version, 'commit': sha, 'platform': args.platform, 'signed': False, 'updater_signed': args.sign_updates}
(out / f'SOURCE-{args.platform}.json').write_text(json.dumps(metadata, indent=2) + '\n')
files = sorted(out.iterdir())
(out / f'SHA256SUMS-{args.platform}.txt').write_text(''.join(f'{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n' for f in files))
print(f'Packaged {args.platform}: {len(files)} files plus checksums')
