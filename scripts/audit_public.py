"""Fail closed on private files/values in Git's publishable snapshot; never print matches."""
import argparse
import json
import re
import subprocess
from pathlib import PurePosixPath
from urllib.parse import urlsplit


PATTERNS = {
    "private-key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "token": rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})",
    "JWT": rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    "personal-path": rb"(?:/(?:Users)/[^\s/]+/|/(?:home)/[^\s/]+/|[A-Z]:\\Users\\[^\\\s]+\\|/var/(?:folders)/|/opt/(?:homebrew)/)",
    "private-address": rb"\b(?:192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)\b",
    "URL-credentials": rb"https?://[^\s/:]+:[^\s/@]+@",
}
PRIVATE_PARTS = {"node_modules", "target", "dist", "gen", ".idea", ".vscode", ".codex", ".agents", ".orca", "audit-output", "release-assets"}
PRIVATE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".p8", ".cer", ".der", ".csr", ".keychain", ".keychain-db", ".db", ".sqlite", ".sqlite3", ".log", ".map", ".tsbuildinfo"}


def inspect(name, content):
    path = PurePosixPath(name)
    errors = []
    if PRIVATE_PARTS.intersection(path.parts) or path.suffix in PRIVATE_SUFFIXES or path.name in {".npmrc", ".netrc", ".DS_Store"}:
        errors.append("private/generated file")
    if path.name.startswith(".env") and path.name != ".env.example":
        errors.append("environment file")
    for reason, pattern in PATTERNS.items():
        if re.search(pattern, content):
            errors.append(reason)
    if path.name == ".env.example":
        for line in content.decode().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            if value and not (key == "VITE_SUPABASE_REDIRECT_URL" and value == "http://localhost:5173/"):
                errors.append("populated environment example")
    if path.name == "package-lock.json":
        for package in json.loads(content).get("packages", {}).values():
            if "resolved" in package and urlsplit(package["resolved"]).hostname != "registry.npmjs.org":
                errors.append("non-public dependency registry")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true", help="Read the exact Git index instead of HEAD")
    args = parser.parse_args()
    source = ":" if args.staged else "HEAD:"
    command = ["git", "ls-files", "-z"] if args.staged else ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"]
    names = subprocess.check_output(command).decode().strip("\0").split("\0")
    failures = []
    for name in filter(None, names):
        content = subprocess.check_output(["git", "show", source + name])
        for reason in inspect(name, content):
            failures.append(f"{name}: {reason} (value redacted)")
    if failures:
        print("Public-source audit failed:\n" + "\n".join(failures))
        raise SystemExit(1)
    print(f"Public-source audit passed: {len(names)} files; no private paths, environment files or credential patterns detected.")


if __name__ == "__main__":
    main()
