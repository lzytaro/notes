import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from create_update_manifest import create_manifest


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='notes-manifest-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for platform, extensions in [('macos-universal', ['app.tar.gz']), ('windows-x64', ['exe', 'msi'])]:
            files = []
            for ext in extensions:
                package = self.root / f'notes_1.2.3_{platform}.{ext}'
                package.write_bytes(b'fixture')
                signature = self.root / (package.name + '.sig')
                # Manifest tests validate packaging, not cryptography. Rust tests
                # separately exercise real signatures and tampered payloads.
                signature.write_text(base64.b64encode(b'untrusted comment: fixture\nfixture\ntrusted comment: timestamp:1\tfile:fixture\tversion:1.2.3\nfixture').decode())
                files.extend([package, signature])
            source = self.root / f'SOURCE-{platform}.json'
            source.write_text(json.dumps({'version': '1.2.3', 'commit': 'abc123', 'updater_signed': True}))
            files.append(source)
            (self.root / f'SHA256SUMS-{platform}.txt').write_text(''.join(f'{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n' for f in files))

    def test_selects_matching_installer_and_universal_architectures(self):
        manifest = create_manifest(self.root, '1.2.3', '发布说明')
        self.assertEqual(manifest['notes'], '发布说明')
        platforms = manifest['platforms']
        self.assertEqual(platforms['darwin-aarch64'], platforms['darwin-x86_64'])
        self.assertTrue(platforms['windows-x86_64-msi']['url'].endswith('.msi'))
        self.assertTrue(platforms['windows-x86_64-nsis']['url'].endswith('.exe'))

    def test_refuses_tampered_package_or_signature(self):
        (self.root / 'notes_1.2.3_windows-x64.exe').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            create_manifest(self.root, '1.2.3', '')

    def test_refuses_wrong_version_or_unsigned_build(self):
        with self.assertRaisesRegex(ValueError, 'signed'):
            create_manifest(self.root, '2.0.0', '')
        source = self.root / 'SOURCE-windows-x64.json'
        data = json.loads(source.read_text()); data['updater_signed'] = False
        source.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'signed'):
            create_manifest(self.root, '1.2.3', '')

    def test_refuses_unsigned_version_comment_even_with_matching_checksums(self):
        for platform in ['macos-universal', 'windows-x64']:
            sums = self.root / f'SHA256SUMS-{platform}.txt'
            filenames = [line.split('  ')[1] for line in sums.read_text().splitlines()]
            for name in filenames:
                if name.endswith('.sig'):
                    (self.root / name).write_text(base64.b64encode(b'trusted comment: timestamp:1\tfile:fixture').decode())
            sums.write_text(''.join(f'{hashlib.sha256((self.root / name).read_bytes()).hexdigest()}  {name}\n' for name in filenames))
        with self.assertRaisesRegex(ValueError, 'bind'):
            create_manifest(self.root, '1.2.3', '')


if __name__ == '__main__':
    unittest.main()
