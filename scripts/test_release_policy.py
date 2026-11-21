import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('check_release.py').resolve()


class ReleasePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='notes-release-policy-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'src-tauri').mkdir()
        for name, content in {
            'package.json': '{"version":"1.2.3"}',
            'package-lock.json': '{"version":"1.2.3","packages":{"":{"version":"1.2.3"}}}',
            'src-tauri/tauri.conf.json': '{"version":"1.2.3"}',
            'src-tauri/Cargo.toml': '[package]\nname="notes-desktop"\nversion="1.2.3"\n',
            'src-tauri/Cargo.lock': 'version=4\n[[package]]\nname="notes-desktop"\nversion="1.2.3"\n',
        }.items():
            (self.root / name).write_text(content)
        self.git('init', '-q'); self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('add', '.'); self.git('commit', '-qm', 'base')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        self.git('switch', '-qc', 'release/1.2.3')
        (self.root / 'change.txt').write_text('release change')
        self.git('add', '.'); self.git('commit', '-qm', 'release')
        self.git('tag', '-a', 'v1.2.3', '-m', 'fixture release')

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, stderr=subprocess.DEVNULL)

    def check(self, tag='v1.2.3'):
        return subprocess.run([sys.executable, str(SCRIPT), '--tag', tag], cwd=self.root, capture_output=True, text=True)

    def test_unmerged_feature_tag_is_rejected(self):
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('merged into main', result.stderr)

    def test_merged_tag_and_all_versions_are_accepted(self):
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        self.assertEqual(self.check().returncode, 0)

    def test_lockfile_mismatch_blocks_release(self):
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        path = self.root / 'package-lock.json'
        lock = json.loads(path.read_text()); lock['packages']['']['version'] = '1.2.2'
        path.write_text(json.dumps(lock))
        self.assertIn('lockfile versions must match', self.check().stderr)

    def test_tag_must_point_at_checked_out_commit(self):
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')
        (self.root / 'other.txt').write_text('later change')
        self.git('add', '.'); self.git('commit', '-qm', 'later')
        self.assertIn('checked-out commit', self.check().stderr)


if __name__ == '__main__':
    unittest.main()
