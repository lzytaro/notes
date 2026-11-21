# 开发与版本管理

本项目采用 GitHub Flow：`main` 保持可构建，日常修改通过短期分支和 Pull Request 合入。不直接在 `main` 开发，也不通过管理员绕过检查。

## 分支与合并

- 新功能：`feat/<topic>`；修复：`fix/<topic>`；维护：`chore/<topic>`。
- 发布准备：`release/v<version>`，集中更新版本、锁文件和发布说明。
- 从最新 `main` 创建分支；每个 PR 只处理一个明确目标。提交前执行公开源码审计和密钥扫描。
- PR 必须通过 `Source audit and tests`、`Build macos-universal`、`Build windows-x64`，并解决所有 review conversations。
- 使用 squash merge，合并后删除短期分支；禁止强制推送或删除 `main`。
- 当前为单维护者仓库：强制 PR 和 CI，但不设置“必须由另一人批准”，避免维护者无法合并自己的 PR。有协作者后再启用独立 reviewer 要求。

```bash
git switch main
git pull --ff-only
git switch -c feat/example
# 修改、验证、审计、提交，然后推送该分支并创建 PR
git push -u origin feat/example
gh pr create --base main --head feat/example --body-file /path/to/pr-description.md
```

PR 和 `main` 的构建不导入 Apple 凭据，也不提交公证。它们的安装包是 CI 测试产物，不能当作正式发行包。

## 发布

采用 SemVer。发布标签不可移动或删除；修复源码导致的失败发行时创建新的版本。Apple 仍在处理时，可沿用同一标签、原始签名文件和提交 ID 恢复公证，操作见 [macOS 签名说明](docs/MACOS_SIGNING.md#公证等待与恢复)。

1. 创建 `release/v<version>` 分支，在同一个 PR 更新 `package.json`、`package-lock.json`（含根包条目）、`src-tauri/Cargo.toml`、`src-tauri/Cargo.lock` 和 `src-tauri/tauri.conf.json`，并更新 `docs/RELEASE_NOTES.md`。
2. 所有检查通过后 squash merge 到 `main`。
3. 获取合并后的 `main`，从合并后的提交创建 annotated tag `v<version>`。不要给 squash 前的功能分支提交打发布标签。
4. 标签流水线核对六处版本、标签指向以及提交已进入 `main`，然后构建双平台安装包。
5. macOS 必须完成 Developer ID 签名、Apple 公证、票据附加和 Gatekeeper 验证；所有更新包再做 Tauri updater 签名。
6. 两个平台与最终文件全部验证通过后，流水线才公开 GitHub Release。当前产品仍处于预览阶段，Release 保持 prerelease。

```bash
git switch main
git pull --ff-only
git tag -a v<version> -m '纸笺 v<version>'
git push origin v<version>
```

`v0.1.0`、`v0.2.1` 是采用新 macOS 签名策略之前发布的历史版本；保留其文件与标签，不原地替换安装包。

## 本地验证

维护脚本使用 Python 3.12+；CI 固定配置 Python 3.12。macOS 自带 Python 3.9 不适合运行完整发布校验。

```bash
npm test
npm run build
cargo test --locked --manifest-path src-tauri/Cargo.toml --lib
python3.12 -m unittest discover -s scripts -p 'test_*.py'
actionlint .github/workflows/build.yml
python3.12 scripts/audit_public.py --staged
```

Apple 凭据准备与真实公证验收见 [macOS 签名说明](docs/MACOS_SIGNING.md)。
