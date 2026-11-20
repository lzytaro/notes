"""Collect only distributables, never upload the build directory or local machine output."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--platform', required=True, choices=['macos-universal', 'windows-x64'])
args = parser.parse_args()
version = json.loads(Path('package.json').read_text())['version']
target = Path('src-tauri/target')
out = Path('release-assets')
out.mkdir(exist_ok=True)
if args.platform == 'macos-universal':
    root = target / 'universal-apple-darwin/release/bundle'
    apps = list((root / 'macos').glob('*.app'))
    dmgs = list((root / 'dmg').glob('*.dmg'))
    if len(apps) != 1 or len(dmgs) != 1:
        raise SystemExit('Expected exactly one universal macOS app and DMG')
    with tarfile.open(out / f'notes_{version}_macos-universal.app.tar.gz', 'w:gz') as archive:
        archive.add(apps[0], arcname=apps[0].name)
    shutil.copyfile(dmgs[0], out / f'notes_{version}_macos-universal.dmg')
else:
    root = target / 'release/bundle'
    for folder, extension in [('nsis', 'exe'), ('msi', 'msi')]:
        files = list((root / folder).glob(f'*.{extension}'))
        if len(files) != 1:
            raise SystemExit(f'Expected exactly one {extension} installer')
        shutil.copyfile(files[0], out / f'notes_{version}_windows-x64.{extension}')
sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
metadata = {'version': version, 'commit': sha, 'platform': args.platform, 'signed': False}
(out / f'SOURCE-{args.platform}.json').write_text(json.dumps(metadata, indent=2) + '\n')
files = sorted(out.iterdir())
(out / f'SHA256SUMS-{args.platform}.txt').write_text(''.join(f'{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n' for f in files))
print(f'Packaged {args.platform}: {len(files)} files plus checksums')
