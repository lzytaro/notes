# Security and publication policy

- Never commit `.env`, credentials, signing certificates, private registries, local databases, logs, generated schemas, caches or local builds.
- `.env.example` contains empty cloud configuration fields only. Values prefixed with `VITE_` become visible in compiled applications; never place service-role credentials or other secrets there.
- The default release is built without Supabase configuration. Cloud synchronization is experimental and opt-in for development.
- Before a commit: stage an explicit file list and run `python3 scripts/audit_public.py --staged`; then scan an exported staged tree with `gitleaks dir --redact`.
- CI scans the full Git history with Gitleaks and checks source files for private paths, private addresses and environment configuration. It never prints matching credential values.
- Release artifacts are built on GitHub-hosted runners from the tagged commit, with lockfiles and a restricted artifact allowlist. Local binaries and application data are never uploaded.
- The initial release is unsigned and not notarized. Automatic updates are not enabled.

Report suspected vulnerabilities privately using the repository's Security advisories page. Do not include credentials in public issues.
