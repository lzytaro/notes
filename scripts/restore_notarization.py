"""Restore only a checkpoint produced by this repository's same release tag."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def validate_run(run, repository, commit, tag):
    if (run.get('repository', {}).get('full_name') != repository
            or run.get('head_sha') != commit or run.get('head_branch') != tag
            or run.get('path') != '.github/workflows/build.yml'
            or run.get('event') not in {'push', 'workflow_dispatch'}
            or run.get('status') != 'completed'):
        raise ValueError('Checkpoint must come from a completed release run of the same repository, tag and commit')


def restore(run_id):
    if not re.fullmatch(r'[1-9][0-9]*', run_id):
        raise ValueError('Recovery run ID must be a positive integer')
    repository, tag, commit = [os.environ[name] for name in ['GITHUB_REPOSITORY', 'GITHUB_REF_NAME', 'GITHUB_SHA']]
    if os.environ.get('GITHUB_REF_TYPE') != 'tag':
        raise ValueError('Checkpoint recovery must run on a release tag')
    def api(path):
        return json.loads(subprocess.check_output(['gh', 'api', f'repos/{repository}/{path}']))
    run = api(f'actions/runs/{run_id}')
    validate_run(run, repository, commit, tag)
    # Never silently fall back to an earlier attempt's stale receipt.
    name = f'macos-notarization-{run_id}-{run["run_attempt"]}'
    root = Path('artifacts/notarization')
    if root.exists() and any(root.iterdir()):
        raise ValueError('Recovery destination must be empty')
    subprocess.run(['gh', 'run', 'download', run_id, '--repo', repository, '--name', name, '--dir', str(root)], check=True)
    allowed = {'state.json', 'app.zip', 'installer.dmg'}
    if not (root / 'state.json').is_file() or any(p.name not in allowed or p.is_symlink() or not p.is_file() for p in root.iterdir()):
        raise ValueError('Unexpected files in notarization checkpoint')
    print('Recovered signed bytes and submission receipts from the same release commit.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    try:
        restore(args.run_id)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error) if isinstance(error, ValueError) else 'Checkpoint recovery failed') from None
