# Security and publication policy

- Never commit `.env`, credentials, signing certificates, private registries, local databases, logs, generated schemas, caches or local builds.
- `.env.example` contains empty cloud configuration fields only. Values prefixed with `VITE_` become visible in compiled applications; never place service-role credentials or other secrets there.
- The default release is built without Supabase configuration. Cloud synchronization is experimental and opt-in for development.
- Before a commit: stage an explicit file list and run `python3 scripts/audit_public.py --staged`; then scan an exported staged tree with `gitleaks dir --redact`.
- CI scans the full Git history with Gitleaks and checks source files for private paths, private addresses and environment configuration. It never prints matching credential values.
- Release artifacts are built on GitHub-hosted runners from the tagged commit, with lockfiles and a restricted artifact allowlist. Local binaries and application data are never uploaded.
- Starting with v0.2.1, updates are opt-in and signed with a dedicated Tauri updater key. The app requires a signed version, rejects downgrades and only resolves release assets from this repository over HTTPS. Installation is explicitly initiated by the user.
- The updater public key is committed in `src-tauri/tauri.conf.json`. The private key must stay outside the checkout, backed up securely, and stored only as the `TAURI_SIGNING_PRIVATE_KEY` GitHub Actions secret. Never rotate or lose it casually: installed clients trust that key.
- CI signs the final packaged bytes (including the repacked macOS archive), verifies signatures with the embedded public key, and publishes manifests only after both platforms pass. PR builds do not receive the signing secret.
- Updater signatures are independent of OS code signing. New macOS releases must pass Developer ID Application signing, hardened runtime, Apple notarization, stapling, Gatekeeper and final archive verification. Missing credentials or any failed check blocks publication. Historical v0.2.1 and earlier installers remain unsigned/unnotarized by Apple; Windows Authenticode is still not configured.
- Apple certificate exports and API private keys are stored in GitHub Secrets, never in Git or frontend variables. CI materializes the API key only in a restricted temporary file, then removes it. Local CSR bootstrap files are encrypted/restricted and kept outside the repository. Do not paste private material into chat, PRs or logs.
- Main is developed through pull requests with required source-audit and desktop-build checks. Release tags must point at commits already merged into main; published version tags are immutable. See CONTRIBUTING.md.

Report suspected vulnerabilities privately using the repository's Security advisories page. Do not include credentials in public issues.
