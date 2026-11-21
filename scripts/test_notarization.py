"""Behavioral recovery tests: pending/rejected decisions must never publish or resubmit."""
import base64
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import build_macos_release as release
from restore_notarization import validate_run

IDENTITY = 'Developer ID Application: Fixture (ABCDEFGHIJ)'
COMMIT = 'a' * 40
APP_ID = '00000000-0000-4000-8000-000000000001'
DMG_ID = '00000000-0000-4000-8000-000000000002'


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        old = Path.cwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.temp.name)
        Path('package.json').write_text('{"version":"1.2.3"}')
        Path('src-tauri').mkdir()
        Path('src-tauri/tauri.conf.json').write_text('{"productName":"Fixture"}')
        self.env = {
            'RUNNER_TEMP': self.temp.name, 'APPLE_SIGNING_IDENTITY': IDENTITY,
            'APPLE_API_KEY': 'ABCDEFGHIJ', 'APPLE_API_ISSUER': APP_ID,
            'APPLE_CERTIFICATE': base64.b64encode(b'fixture').decode(),
            'APPLE_CERTIFICATE_PASSWORD': 'fixture-password',
            'APPLE_API_PRIVATE_KEY': '-----BEGIN ' + 'PRIVATE KEY-----\nfixture\n-----END ' + 'PRIVATE KEY-----',
        }
        self.status = {APP_ID: 'In Progress', DMG_ID: 'In Progress'}
        self.submits = []
        self.build_count = 0
        self.dmg_count = 0
        self.key_paths = []
        self.calls = []

    def command(self, command, label, **options):
        self.calls.append(command)
        output = b''
        if command[:2] == ['git', 'rev-parse']:
            output = COMMIT.encode()
        elif command[0] == 'npm':
            self.build_count += 1
            self.assertNotIn('--no-sign', command)
            self.assertFalse(any(k.startswith('APPLE_API_') for k in options['env']))
            self.assertNotIn('APPLE_PASSWORD', options['env'])
            app = release.BUNDLE / 'macos/Fixture.app/Contents'
            app.mkdir(parents=True)
            (app / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.lzytaro.notes', 'CFBundleShortVersionString': '1.2.3'}))
            (app / 'binary').write_bytes(b'signed executable')
        elif command[:3] == ['ditto', '-c', '-k']:
            source, target = Path(command[-2]), Path(command[-1])
            with zipfile.ZipFile(target, 'w') as archive:
                for f in source.rglob('*'):
                    if f.is_file(): archive.write(f, f.relative_to(source.parent))
        elif command[:3] == ['ditto', '-x', '-k']:
            with zipfile.ZipFile(command[3]) as archive:
                archive.extractall(command[4])
        elif command[:3] == ['xcrun', 'notarytool', 'submit']:
            key = Path(command[command.index('--key') + 1])
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            self.key_paths.append(key)
            identifier = APP_ID if command[3].endswith('.zip') else DMG_ID
            self.submits.append(identifier)
            output = json.dumps({'id': identifier}).encode()
        elif command[:3] == ['xcrun', 'notarytool', 'info']:
            output = json.dumps({'id': command[3], 'status': self.status[command[3]]}).encode()
        return subprocess.CompletedProcess(command, 0, output, b'')

    def make_dmg(self, app, destination, volume, env):
        self.dmg_count += 1
        destination.write_bytes(b'signed DMG with stapled app')

    def attempt(self, resume=False):
        with patch.dict(os.environ, self.env, clear=True), patch.object(release.sys, 'platform', 'darwin'), patch.object(release, 'run_checked', side_effect=self.command), patch.object(release, 'verify_signature'), patch.object(release, 'verify_app'), patch.object(release, 'create_dmg', side_effect=self.make_dmg), redirect_stdout(io.StringIO()):
            release.build(resume=resume, wait_seconds=0)

    def fresh_runner(self):
        shutil.rmtree('src-tauri/target', ignore_errors=True)

    def test_new_runner_resumes_exact_submissions_without_rebuild(self):
        with self.assertRaises(release.NotarizationPending): self.attempt()
        self.assertFalse(any(key.exists() for key in self.key_paths))
        state = release.load_state(release.CHECKPOINT, '1.2.3', COMMIT)
        self.assertEqual(state['app']['submission'], APP_ID)
        original_app = (release.CHECKPOINT / 'app.zip').read_bytes()
        self.fresh_runner()
        self.status[APP_ID] = 'Accepted'
        with self.assertRaises(release.NotarizationPending): self.attempt(resume=True)
        original_dmg = (release.CHECKPOINT / 'installer.dmg').read_bytes()
        self.fresh_runner()
        self.status[DMG_ID] = 'Accepted'
        self.attempt(resume=True)
        self.assertEqual(self.submits, [APP_ID, DMG_ID])
        self.assertEqual((self.build_count, self.dmg_count), (1, 1))
        self.assertEqual((release.CHECKPOINT / 'app.zip').read_bytes(), original_app)
        self.assertEqual((release.CHECKPOINT / 'installer.dmg').read_bytes(), original_dmg)
        self.assertEqual((release.BUNDLE / 'dmg/notes_1.2.3_macos-universal.dmg').read_bytes(), original_dmg)
        self.assertFalse(any(key.exists() for key in self.key_paths))

    def test_rejected_app_blocks_dmg_and_keeps_receipt(self):
        self.status[APP_ID] = 'Invalid'
        with self.assertRaisesRegex(ValueError, 'rejected'): self.attempt()
        self.assertEqual(self.dmg_count, 0)
        self.assertEqual(self.submits, [APP_ID])
        self.assertFalse(any(key.exists() for key in self.key_paths))

    def test_rejected_dmg_never_reaches_release_directory(self):
        self.status.update({APP_ID: 'Accepted', DMG_ID: 'Invalid'})
        with self.assertRaisesRegex(ValueError, 'rejected'): self.attempt()
        self.assertFalse((release.BUNDLE / 'dmg').exists())

    def test_changed_bytes_or_commit_are_rejected_before_restore(self):
        with self.assertRaises(release.NotarizationPending): self.attempt()
        with self.assertRaisesRegex(ValueError, 'another version or commit'):
            release.load_state(release.CHECKPOINT, '1.2.4', COMMIT)
        with self.assertRaisesRegex(ValueError, 'another version or commit'):
            release.load_state(release.CHECKPOINT, '1.2.3', 'b' * 40)
        with (release.CHECKPOINT / 'app.zip').open('ab') as output: output.write(b'tampered')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            release.load_state(release.CHECKPOINT, '1.2.3', COMMIT)

    def test_missing_receipt_never_repeats_ambiguous_submission(self):
        with self.assertRaises(release.NotarizationPending): self.attempt()
        state = release.load_state(release.CHECKPOINT, '1.2.3', COMMIT)
        del state['app']['submission']
        release.save_state(release.CHECKPOINT, state)
        self.fresh_runner()
        with self.assertRaisesRegex(ValueError, 'receipt is missing'): self.attempt(resume=True)
        self.assertEqual(self.submits, [APP_ID])

    def test_source_run_must_be_same_reviewed_release(self):
        run = {'repository': {'full_name': 'lzytaro/notes'}, 'head_sha': COMMIT, 'head_branch': 'v1.2.3', 'path': '.github/workflows/build.yml', 'event': 'push', 'status': 'completed'}
        validate_run(run, 'lzytaro/notes', COMMIT, 'v1.2.3')
        for suffix in ['@main', '@refs/tags/v1.2.3']:
            validate_run({**run, 'path': run['path'] + suffix}, 'lzytaro/notes', COMMIT, 'v1.2.3')
        for field, value in [('head_sha', 'b' * 40), ('head_branch', 'main'), ('path', 'other.yml'), ('event', 'pull_request'), ('status', 'in_progress'), ('repository', {'full_name': 'fork/notes'})]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_run({**run, field: value}, 'lzytaro/notes', COMMIT, 'v1.2.3')

    def test_restore_rejects_zip_path_traversal(self):
        with zipfile.ZipFile('bad.zip', 'w') as output: output.writestr('../outside', 'unsafe')
        with self.assertRaisesRegex(ValueError, 'Unsafe path'):
            release.restore_app(Path('bad.zip'), Path('output'), 'Fixture.app')

    def test_apple_response_cannot_accept_another_submission(self):
        for response in [
            {'id': DMG_ID, 'status': 'Accepted'},
            {'id': APP_ID, 'status': 'Unknown'},
        ]:
            with self.subTest(response=response), patch.object(release, 'run_checked', return_value=subprocess.CompletedProcess([], 0, json.dumps(response).encode(), b'')):
                with self.assertRaises(ValueError):
                    release.wait_for_notarization(APP_ID, [], 'Application', timeout_seconds=0)

    def test_temporary_status_error_retains_the_submission_for_recovery(self):
        with patch.object(release, 'run_checked', side_effect=RuntimeError('read unavailable')):
            with self.assertRaises(release.NotarizationPending):
                release.wait_for_notarization(APP_ID, [], 'Application', timeout_seconds=0)

    def test_dmg_keychain_and_export_are_removed_after_signing_failure(self):
        paths = []
        commands = []
        def run(command, label, **options):
            commands.append(command)
            if command[1] == 'create-keychain':
                paths.append(Path(command[-1])); paths[-1].touch()
            if command[1] == 'import':
                export = Path(command[2])
                self.assertEqual(export.stat().st_mode & 0o777, 0o600)
                self.assertEqual(export.read_bytes(), b'fixture')
            if command[1] == 'delete-keychain': Path(command[-1]).unlink()
            return subprocess.CompletedProcess(command, 0, b'"original.keychain-db"\n' if command[1] == 'list-keychains' and '-s' not in command else b'', b'')
        with patch.object(release, 'run_checked', side_effect=run):
            with self.assertRaisesRegex(RuntimeError, 'sign failure'):
                with release.dmg_signing_keychain(self.env) as keychain:
                    self.assertTrue(keychain.exists())
                    raise RuntimeError('sign failure')
        self.assertTrue(any(c[1:4] == ['list-keychains', '-d', 'user'] and '-s' in c and 'original.keychain-db' in c for c in commands))
        self.assertFalse(any(p.parent.exists() for p in paths))


if __name__ == '__main__':
    unittest.main()
