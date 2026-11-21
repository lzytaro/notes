"""Exercise packaging on disposable fixtures; these are not platform runtime tests."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('package_release.py').resolve()


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='notes-package-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'package.json').write_text('{"version":"0.1.0"}\n')
        for args in [
            ['init', '-q'],
            ['add', 'package.json'],
            ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'],
        ]:
            subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)
        self.sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.root, text=True).strip()

    def put(self, name, data=b'fixture bytes'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def package(self, platform):
        return subprocess.run([sys.executable, str(SCRIPT), '--platform', platform], cwd=self.root, capture_output=True, text=True)

    def verify(self, platform, installers):
        output = self.root / 'release-assets'
        self.assertEqual({p.name for p in output.iterdir()}, set(installers) | {f'SOURCE-{platform}.json', f'SHA256SUMS-{platform}.txt'})
        metadata = json.loads((output / f'SOURCE-{platform}.json').read_text())
        self.assertEqual(metadata['commit'], self.sha)
        self.assertEqual(metadata['platform'], platform)
        for line in (output / f'SHA256SUMS-{platform}.txt').read_text().splitlines():
            digest, name = line.split('  ', 1)
            self.assertEqual(digest, hashlib.sha256((output / name).read_bytes()).hexdigest())

    def test_windows_only_packages_installers(self):
        self.put('src-tauri/target/release/bundle/nsis/app.exe')
        self.put('src-tauri/target/release/bundle/msi/app.msi')
        self.put('src-tauri/target/release/bundle/debug.log', b'must not be uploaded')
        result = self.package('windows-x64')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.verify('windows-x64', ['notes_0.1.0_windows-x64.exe', 'notes_0.1.0_windows-x64.msi'])

    def test_macos_archive_has_no_builder_identity(self):
        root = 'src-tauri/target/universal-apple-darwin/release/bundle/'
        self.put(root + 'macos/Paper.app/Contents/MacOS/paper')
        self.put(root + 'dmg/app.dmg')
        result = self.package('macos-universal')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.verify('macos-universal', ['notes_0.1.0_macos-universal.app.tar.gz', 'notes_0.1.0_macos-universal.dmg'])
        with tarfile.open(self.root / 'release-assets/notes_0.1.0_macos-universal.app.tar.gz') as archive:
            for member in archive.getmembers():
                self.assertEqual((member.uid, member.gid, member.uname, member.gname), (0, 0, '', ''))
                self.assertTrue(member.name.startswith('Paper.app'))

    def test_refuses_stale_release_directory(self):
        self.put('release-assets/stale.txt')
        result = self.package('windows-x64')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must be empty', result.stderr)

    def test_refuses_missing_or_ambiguous_installers(self):
        self.assertNotEqual(self.package('windows-x64').returncode, 0)
        self.put('src-tauri/target/release/bundle/nsis/first.exe')
        self.put('src-tauri/target/release/bundle/nsis/second.exe')
        self.assertNotEqual(self.package('windows-x64').returncode, 0)


if __name__ == '__main__':
    unittest.main()
