"""Only immutable version tags on merged main history may publish a release."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tomllib


def check_release(tag, commit, main_ref='origin/main'):
    if not re.fullmatch(r'v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?', tag):
        raise ValueError('Release tag must use vMAJOR.MINOR.PATCH (optional prerelease suffix)')
    version = tag[1:]
    package = json.loads(Path('package.json').read_text())
    lock = json.loads(Path('package-lock.json').read_text())
    cargo = tomllib.loads(Path('src-tauri/Cargo.toml').read_text())
    cargo_lock = tomllib.loads(Path('src-tauri/Cargo.lock').read_text())
    native = next(p for p in cargo_lock['package'] if p['name'] == cargo['package']['name'])
    versions = [package['version'], lock['version'], lock['packages']['']['version'], cargo['package']['version'], native['version'], json.loads(Path('src-tauri/tauri.conf.json').read_text())['version']]
    if any(v != version for v in versions):
        raise ValueError('Tag, application versions and lockfile versions must match')
    def git(*args):
        return subprocess.check_output(['git', *args], text=True, stderr=subprocess.DEVNULL).strip()
    if git('rev-parse', 'HEAD') != git('rev-parse', commit + '^{commit}') or git('rev-parse', tag + '^{commit}') != git('rev-parse', 'HEAD'):
        raise ValueError('Release tag must identify the checked-out commit')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', 'HEAD', main_ref], capture_output=True).returncode:
        raise ValueError('Release commit must already be merged into main')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    parser.add_argument('--commit', default='HEAD')
    parser.add_argument('--main-ref', default='origin/main')
    args = parser.parse_args()
    try:
        check_release(args.tag, args.commit, args.main_ref)
    except (ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error) if isinstance(error, ValueError) else 'Release policy verification failed') from None
    print('Release versions, tag identity and merged main ancestry verified.')
