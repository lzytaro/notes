import unittest
from audit_public import inspect


class AuditTests(unittest.TestCase):
    def test_environment_values_are_rejected(self):
        self.assertTrue(inspect('.env', b'VALUE=x'))
        self.assertTrue(inspect('.env.example', b'VITE_SUPABASE_URL=https://example.invalid'))
        self.assertFalse(inspect('.env.example', b'VITE_SUPABASE_URL=\nVITE_SUPABASE_ANON_KEY=\n'))

    def test_private_values_are_redacted(self):
        path = b'/Users/' + b'example' + b'/workspace'
        token = b'ghp_' + b'A' * 36
        self.assertIn('personal-path', inspect('README.md', path))
        self.assertIn('token', inspect('src/file.ts', token))
        self.assertIn('private-address', inspect('file.txt', b'192.' + b'168.1.25'))

    def test_generated_files_are_rejected(self):
        self.assertTrue(inspect('src-tauri/target/bundle/app', b''))
        self.assertTrue(inspect('notes.db', b''))
        self.assertFalse(inspect('src/types.ts', b'export type Task = {}'))


if __name__ == '__main__':
    unittest.main()
