"""Exercise release rejection paths; these tests do not substitute for Apple notarization."""
import base64
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from build_macos_release import validate_credentials
from build_macos_release import build, submission_id, wait_for_notarization
from apple_credentials import create_csr
import apple_credentials as credentials
from macos_release import (VERIFICATION_FIELDS, require_macos_verification, run_checked,
                           signing_team, validate_signature_details, verify_app, verify_archive)

IDENTITY = 'Developer ID Application: Fixture (ABCDEFGHIJ)'
DETAILS = f'Authority={IDENTITY}\nTeamIdentifier=ABCDEFGHIJ\nTimestamp=Nov 21, 2026\nCodeDirectory v=20500 flags=0x10000(runtime)\n'


class SigningTests(unittest.TestCase):
    def test_real_crypto_bootstrap_uploads_only_via_stdin_and_cleans_export(self):
        original = credentials.command
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()) as output:
            root = Path(temporary)
            create_csr(root)
            certificate, api_key = root / 'fixture.cer', root / 'fixture.p8'
            original(['openssl', 'req', '-new', '-x509', '-key', str(root / 'developer-id-private.pem'), '-passin', f'file:{root / "private-key-password.txt"}', '-subj', '/CN=' + IDENTITY, '-days', '2', '-out', str(certificate)])
            original(['openssl', 'genpkey', '-algorithm', 'EC', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-out', str(api_key)])
            uploads = {}
            def local_only(args, **options):
                if args[0] == 'gh':
                    if args[2] == 'list': return b'[]'
                    self.assertEqual(args[2], 'set')
                    value = options['data']
                    self.assertTrue(value not in ' '.join(args).encode())
                    uploads[args[3]] = value
                    return b''
                return original(args, **options)
            with patch.object(credentials, 'command', side_effect=local_only):
                credentials.configure_secrets(root, certificate, api_key, 'ABCDEFGHIJ', '00000000-0000-4000-8000-000000000001', False)
            self.assertEqual(set(uploads), set(credentials.SECRET_NAMES))
            self.assertTrue(all(value not in output.getvalue().encode() for value in uploads.values()))
            self.assertFalse(list(root.glob('notes-certificate-*')))

    def test_csr_uses_encrypted_key_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            with redirect_stdout(io.StringIO()):
                create_csr(temporary)
            key = Path(temporary) / 'developer-id-private.pem'
            self.assertIn(b'ENCRYPTED', key.read_bytes())
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            self.assertEqual((Path(temporary) / 'private-key-password.txt').stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, 'overwrite'): create_csr(temporary)

    def test_key_is_private_temporary_and_removed_on_success_or_rejection(self):
        for status in ['Accepted', 'Invalid']:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'package.json').write_text('{"version":"1.2.3"}')
                bundle = root / 'src-tauri/target/universal-apple-darwin/release/bundle'
                (bundle / 'macos/Fixture.app').mkdir(parents=True)
                (bundle / 'dmg').mkdir(); (bundle / 'dmg/Fixture.dmg').touch()
                env = {'RUNNER_TEMP': temporary, 'APPLE_SIGNING_IDENTITY': IDENTITY, 'APPLE_API_KEY': 'ABCDEFGHIJ', 'APPLE_API_ISSUER': '00000000-0000-4000-8000-000000000001', 'APPLE_CERTIFICATE': base64.b64encode(b'fixture').decode(), 'APPLE_CERTIFICATE_PASSWORD': 'fixture-password', 'APPLE_API_PRIVATE_KEY': '-----BEGIN ' + 'PRIVATE KEY-----\nfixture\n-----END ' + 'PRIVATE KEY-----'}
                key_paths = []
                def run(command, label, **options):
                    if command[0] == 'npm':
                        child_env = options['env']
                        self.assertNotIn('APPLE_API_PRIVATE_KEY', child_env)
                        self.assertNotIn('APPLE_API_KEY_PATH', child_env)
                        if 'build' in command:
                            self.assertNotIn('--no-sign', command)
                        else:
                            self.assertIn('--no-sign', command)
                    if command[0] == 'xcrun' and command[1:3] == ['notarytool', 'submit']:
                        index = len(key_paths)
                        key_paths.append(Path(options.get('env', {}).get('APPLE_API_KEY_PATH', temporary)) / str(index))
                        identifier = '00000000-0000-4000-8000-' + f'{index + 1:012d}'
                        return subprocess.CompletedProcess(command, 0, json.dumps({'id': identifier, 'status': 'In Progress'}).encode(), b'')
                    if command[0] == 'xcrun' and command[1:3] == ['notarytool', 'info']:
                        return subprocess.CompletedProcess(command, 0, json.dumps({'status': status}).encode(), b'')
                    return subprocess.CompletedProcess(command, 0, b'', b'')
                previous = Path.cwd()
                try:
                    os.chdir(root)
                    with patch.dict(os.environ, env, clear=True), patch('build_macos_release.sys.platform', 'darwin'), patch('build_macos_release.run_checked', side_effect=run), patch('build_macos_release.verify_app'), patch('build_macos_release.verify_signature'), redirect_stdout(io.StringIO()):
                        if status == 'Accepted': build()
                        else:
                            with self.assertRaisesRegex(ValueError, 'rejected by Apple'): build()
                finally:
                    os.chdir(previous)
                self.assertGreaterEqual(len(key_paths), 1)

    def test_notarization_submission_id_and_status_are_parsed_without_output(self):
        result = subprocess.CompletedProcess([], 0, b'{"id":"00000000-0000-4000-8000-000000000123","status":"In Progress"}', b'')
        self.assertEqual(submission_id(result), '00000000-0000-4000-8000-000000000123')
        with patch('build_macos_release.run_checked', return_value=subprocess.CompletedProcess([], 0, b'{"status":"Accepted"}', b'')):
            with patch('build_macos_release.time.monotonic', side_effect=[0, 1]):
                wait_for_notarization('00000000-0000-4000-8000-000000000123', '/tmp/AuthKey.p8', 'ABCDEFGHIJ', '00000000-0000-4000-8000-000000000001', 'Fixture notarization', timeout_seconds=10, poll_seconds=0)

    def test_missing_credentials_report_names_only(self):
        with self.assertRaisesRegex(ValueError, 'APPLE_CERTIFICATE') as error:
            validate_credentials({'APPLE_CERTIFICATE_PASSWORD': 'do-not-print-this'})
        self.assertNotIn('do-not-print-this', str(error.exception))

    def test_rejects_wrong_certificate_types_and_missing_signature_features(self):
        for identity in ['-', 'Apple Development: Fixture (ABCDEFGHIJ)', 'Developer ID Installer: Fixture (ABCDEFGHIJ)']:
            with self.assertRaises(ValueError): signing_team(identity)
        validate_signature_details(DETAILS, IDENTITY, True)
        for details in [DETAILS.replace('ABCDEFGHIJ', 'KLMNOPQRST'), DETAILS.replace('Timestamp=', 'Signed Time='), DETAILS.replace('(runtime)', '(none)'), 'Signature=adhoc']:
            with self.assertRaises(ValueError): validate_signature_details(details, IDENTITY, True)

    def test_tool_errors_do_not_disclose_output(self):
        result = subprocess.CompletedProcess([], 1, b'private material', b'private material')
        with patch('macos_release.subprocess.run', return_value=result):
            with self.assertRaises(RuntimeError) as error:
                run_checked(['unused'], 'Fixture check')
        self.assertNotIn('private material', str(error.exception))

    def make_app(self, root):
        app = Path(root) / 'Fixture.app'
        (app / 'Contents').mkdir(parents=True)
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.lzytaro.notes', 'CFBundleShortVersionString': '1.2.3'}))
        return app

    def test_gatekeeper_or_missing_staple_blocks_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = self.make_app(temporary)
            for rejected in ['Application notarization ticket verification', 'Application Gatekeeper assessment']:
                def run(command, label):
                    if label == rejected: raise RuntimeError('rejected')
                    return subprocess.CompletedProcess(command, 0, b'', DETAILS.encode())
                with patch('macos_release.run_checked', side_effect=run):
                    with self.assertRaises(RuntimeError): verify_app(app, IDENTITY, '1.2.3')

    def test_debugger_entitlement_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = self.make_app(temporary)
            def run(command, label):
                output = plistlib.dumps({'com.apple.security.get-task-allow': True}) if label == 'Entitlement inspection' else b''
                return subprocess.CompletedProcess(command, 0, output, DETAILS.encode())
            with patch('macos_release.run_checked', side_effect=run):
                with self.assertRaisesRegex(ValueError, 'debugger'): verify_app(app, IDENTITY, '1.2.3')

    def test_final_archive_is_extracted_and_checked_not_just_original_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = self.make_app(temporary)
            archive = Path(temporary) / 'app.tar.gz'
            with tarfile.open(archive, 'w:gz') as output: output.add(app, arcname=app.name)
            with patch('macos_release.verify_app') as verify:
                verify_archive(archive, IDENTITY, '1.2.3')
                self.assertNotEqual(verify.call_args.args[0], app)
                self.assertEqual(verify.call_args.args[1:], (IDENTITY, '1.2.3'))

    def test_metadata_requires_every_verification(self):
        source = {'signed': True, 'notarized': True, 'macos_verification': {field: True for field in VERIFICATION_FIELDS}}
        require_macos_verification(source)
        for field in VERIFICATION_FIELDS:
            bad = {**source, 'macos_verification': {**source['macos_verification'], field: False}}
            with self.assertRaises(ValueError): require_macos_verification(bad)


if __name__ == '__main__':
    unittest.main()
