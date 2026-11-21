"""Local bootstrap for Apple credentials. Never echo passwords or private keys.

CSR/private key files must live outside the repository. GitHub Secrets receive
values through stdin, while temporary certificate exports are always removed.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import uuid
from macos_release import signing_team

REPOSITORY = 'lzytaro/notes'
ROOT = Path(__file__).resolve().parents[1]
SECRET_NAMES = ['APPLE_CERTIFICATE', 'APPLE_CERTIFICATE_PASSWORD', 'APPLE_SIGNING_IDENTITY', 'APPLE_API_ISSUER', 'APPLE_API_KEY', 'APPLE_API_PRIVATE_KEY']


def outside_repository(path):
    resolved = Path(path).expanduser().resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise ValueError('Credential files must be outside the repository')
    return resolved


def command(args, *, data=None, env=None):
    result = subprocess.run(args, input=data, env=env, capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError(f'{Path(args[0]).name} operation failed (sensitive output withheld)')
    return result.stdout


def private_file(path, content):
    with open(path, 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
        output.write(content)


def create_csr(directory):
    directory = outside_repository(directory)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    private_key, password, csr = [directory / name for name in ['developer-id-private.pem', 'private-key-password.txt', 'DeveloperID.csr']]
    if any(path.exists() for path in [private_key, password, csr]):
        raise ValueError('CSR files already exist; refusing to overwrite an existing private key')
    private_file(password, secrets.token_urlsafe(48))
    try:
        command(['openssl', 'genpkey', '-algorithm', 'RSA', '-aes-256-cbc', '-pkeyopt', 'rsa_keygen_bits:2048', '-pass', f'file:{password}', '-out', str(private_key)])
        private_key.chmod(0o600)
        command(['openssl', 'req', '-new', '-key', str(private_key), '-passin', f'file:{password}', '-subj', '/CN=Notes Desktop Release', '-out', str(csr)])
        command(['openssl', 'req', '-in', str(csr), '-verify', '-noout'])
    except Exception:
        # Keep any generated key for recovery; never silently generate a replacement.
        raise ValueError('CSR generation did not complete; inspect the private directory before retrying (output withheld)') from None
    print(f'CSR ready: {csr}\nEncrypted private key retained outside the repository with restricted permissions.')


def configure_secrets(directory, certificate, api_key, key_id, issuer, replace):
    directory, certificate, api_key = map(outside_repository, [directory, certificate, api_key])
    private_key, password = directory / 'developer-id-private.pem', directory / 'private-key-password.txt'
    if not all(path.is_file() for path in [private_key, password, certificate, api_key]):
        raise ValueError('Missing CSR private key, password, Apple certificate, or API key file')
    if not re.fullmatch(r'[A-Z0-9]{10,}', key_id):
        raise ValueError('API Key ID has an invalid format')
    try:
        uuid.UUID(issuer)
    except ValueError:
        raise ValueError('API Issuer ID must be a UUID for a team API key') from None
    command(['openssl', 'ec', '-in', str(api_key), '-pubout', '-out', os.devnull])
    existing = json.loads(command(['gh', 'secret', 'list', '--repo', REPOSITORY, '--json', 'name']))
    if not replace and any(item['name'] in SECRET_NAMES for item in existing):
        raise ValueError('Apple secrets already exist. Use --replace only for an intentional replacement or resuming a partial setup')
    with tempfile.TemporaryDirectory(prefix='notes-certificate-', dir=directory) as temporary:
        cert_pem, p12 = Path(temporary) / 'certificate.pem', Path(temporary) / 'certificate.p12'
        try:
            command(['openssl', 'x509', '-inform', 'DER', '-in', str(certificate), '-out', str(cert_pem)])
        except ValueError:
            command(['openssl', 'x509', '-inform', 'PEM', '-in', str(certificate), '-out', str(cert_pem)])
        command(['openssl', 'x509', '-in', str(cert_pem), '-checkend', '86400', '-noout'])
        certificate_public = command(['openssl', 'x509', '-in', str(cert_pem), '-pubkey', '-noout'])
        key_public = command(['openssl', 'pkey', '-in', str(private_key), '-passin', f'file:{password}', '-pubout'])
        if certificate_public.strip() != key_public.strip():
            raise ValueError('Apple certificate does not match this CSR private key')
        subject = command(['openssl', 'x509', '-in', str(cert_pem), '-noout', '-subject', '-nameopt', 'sep_multiline,sname,utf8']).decode()
        match = re.search(r'^\s*CN\s*=\s*(.+)$', subject, re.MULTILINE)
        identity = match.group(1).strip() if match else ''
        signing_team(identity)
        p12_password = secrets.token_urlsafe(48)
        export_env = {**os.environ, 'NOTES_P12_PASSWORD': p12_password}
        command(['openssl', 'pkcs12', '-export', '-inkey', str(private_key), '-passin', f'file:{password}', '-in', str(cert_pem), '-out', str(p12), '-passout', 'env:NOTES_P12_PASSWORD'], env=export_env)
        p12.chmod(0o600)
        values = dict(zip(SECRET_NAMES, [base64.b64encode(p12.read_bytes()), p12_password.encode(), identity.encode(), issuer.encode(), key_id.encode(), api_key.read_bytes()]))
        for name, value in values.items():
            command(['gh', 'secret', 'set', name, '--repo', REPOSITORY], data=value)
            print(f'Configured {name} (value hidden)', flush=True)
    print('Apple Secrets configured; temporary .p12 export removed. Keep encrypted bootstrap files and the API key in a secure backup outside Git.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', default=Path.home() / '.config/notes-apple-signing', type=Path)
    commands = parser.add_subparsers(dest='operation', required=True)
    commands.add_parser('csr')
    configure = commands.add_parser('configure')
    configure.add_argument('--certificate', required=True, type=Path)
    configure.add_argument('--api-key', required=True, type=Path)
    configure.add_argument('--key-id', required=True)
    configure.add_argument('--issuer', required=True)
    configure.add_argument('--replace', action='store_true')
    args = parser.parse_args()
    # Apply before OpenSSL creates any file, not just after it returns.
    os.umask(0o077)
    try:
        if args.operation == 'csr':
            create_csr(args.directory)
        else:
            configure_secrets(args.directory, args.certificate, args.api_key, args.key_id, args.issuer, args.replace)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error) if isinstance(error, ValueError) else 'Credential setup failed (details withheld)') from None
