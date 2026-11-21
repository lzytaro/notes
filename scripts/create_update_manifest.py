"""Build the public Tauri manifest only after both signed platform builds pass."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from macos_release import require_macos_verification


def create_manifest(root, version, notes):
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', version):
        raise ValueError('Invalid release version')
    metadata = []
    for platform in ['macos-universal', 'windows-x64']:
        source = json.loads((root / f'SOURCE-{platform}.json').read_text())
        if source['version'] != version or source.get('updater_signed') is not True:
            raise ValueError('Both platform packages must be signed for this version')
        if platform == 'macos-universal':
            require_macos_verification(source)
        for line in (root / f'SHA256SUMS-{platform}.txt').read_text().splitlines():
            checksum, filename = line.split('  ', 1)
            if Path(filename).name != filename or hashlib.sha256((root / filename).read_bytes()).hexdigest() != checksum:
                raise ValueError('Artifact checksum mismatch')
        metadata.append(source)
    if metadata[0]['commit'] != metadata[1]['commit']:
        raise ValueError('Platform packages were built from different commits')
    platforms = {}
    for targets, filename in [
        (['darwin-aarch64', 'darwin-x86_64'], f'notes_{version}_macos-universal.app.tar.gz'),
        (['windows-x86_64', 'windows-x86_64-nsis'], f'notes_{version}_windows-x64.exe'),
        (['windows-x86_64-msi'], f'notes_{version}_windows-x64.msi'),
    ]:
        if not (root / filename).is_file():
            raise ValueError('Missing updater artifact')
        signature = (root / (filename + '.sig')).read_text().strip()
        # Cryptographic verification happens in the app; catch missing version
        # binding here so an unusable release cannot be published accidentally.
        decoded = base64.b64decode(signature, validate=True).decode()
        if not any(line.startswith('trusted comment:') and f'version:{version}' in line.split() for line in decoded.splitlines()):
            raise ValueError('Signature must bind the release version')
        for target in targets:
            platforms[target] = {'signature': signature, 'url': f'https://github.com/lzytaro/notes/releases/download/v{version}/{filename}'}
    return {'version': version, 'notes': notes, 'pub_date': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), 'platforms': platforms}


if __name__ == '__main__':
    version = json.loads(Path('package.json').read_text())['version']
    root = Path('release-assets')
    manifest = create_manifest(root, version, Path('docs/RELEASE_NOTES.md').read_text())
    (root / 'latest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print('Generated signed update manifest for macOS Universal and Windows x64 (NSIS/MSI).')
