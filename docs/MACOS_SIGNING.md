# macOS 签名与 Apple 公证

纸笺继续通过 GitHub Releases 分发，不上架 Mac App Store。正式 macOS 包必须使用 Developer ID Application 证书，开启 hardened runtime，经过 Apple 公证并附加票据。Tauri updater 的更新签名是另一层校验，不能替代 Developer ID 或公证。

## 一次性准备

需要 Apple Developer Program 账号。签发 Developer ID 证书需要 Account Holder 权限；创建团队 API Key 需要 Account Holder 或 Admin 权限。

### 1. 生成 CSR

在仓库中执行本地工具（该工具兼容 Python 3.9+）：

```bash
python3 scripts/apple_credentials.py csr
```

它会在仓库外的 `~/.config/notes-apple-signing/` 生成 `DeveloperID.csr`、加密 RSA 私钥和私钥密码文件。目录权限为 700，私密文件为 600。已有文件时拒绝覆盖，不会生成另一个不匹配的私钥。只将公开的 CSR 上传到 Apple。

### 2. 签发 Developer ID Application 证书

在 Apple Developer 的 Certificates, Identifiers & Profiles 中新增 **Developer ID Application**，上传刚生成的 CSR，下载 `.cer`。不要选择 Apple Development、Apple Distribution 或 Developer ID Installer；本项目分发的是 App/DMG。

### 3. 创建 App Store Connect 团队 API Key

在 App Store Connect 的 Users and Access → Integrations → App Store Connect API → Team Keys 创建用于公证的团队密钥。下载 `.p8`，记录 Key ID 与 Issuer ID。首次使用 API 可能需要 Account Holder 开通访问。

选择具有公证权限的角色，按团队最小权限策略配置。此流程使用团队 API Key + Issuer；不要用 Apple ID 主密码，也不要把个人类型 API Key 与 Issuer 混用。Apple 私钥仅能下载一次，请安全备份。

### 4. 从本地文件配置 Secrets

证书和 `.p8` 文件应放在仓库之外（例如个人 Downloads 目录）。先确保 `gh auth status` 已登录有权限管理仓库 Secrets 的账号，再执行：

```bash
python3 scripts/apple_credentials.py configure \
  --certificate /path/outside/repository/developerID_application.cer \
  --api-key /path/outside/repository/AuthKey_KEYID.p8 \
  --key-id KEYID \
  --issuer ISSUER_UUID
```

工具会核对证书有效期、证书类型、证书与 CSR 私钥是否匹配，创建受密码保护的临时 `.p12`，并通过 stdin 上传 Secrets。密码和私钥不出现在命令行参数或日志中。临时 `.p12` 自动删除；保留加密的 CSR 私钥及密码、证书和 `.p8` 的安全备份，不要提交到 Git。

已存在 Apple Secrets 时默认拒绝覆盖。只有确实需要替换或恢复部分完成的配置时才传 `--replace`。

| GitHub Secret | 内容 |
| --- | --- |
| `APPLE_CERTIFICATE` | 含私钥的 `.p12` 的 Base64 内容 |
| `APPLE_CERTIFICATE_PASSWORD` | `.p12` 密码 |
| `APPLE_SIGNING_IDENTITY` | 证书中的完整 Developer ID Application 名称 |
| `APPLE_API_ISSUER` | 团队 API 的 Issuer UUID |
| `APPLE_API_KEY` | API Key ID，不是私钥内容 |
| `APPLE_API_PRIVATE_KEY` | 下载的 `.p8` 完整内容 |

`APPLE_API_KEY_PATH` **不是要配置的 Secret**：CI 将 `.p8` 内容写入 runner 临时目录，权限为 600，再把这个临时路径传给 Tauri 和 notarytool。任务结束或失败时会清理临时文件。证书导入与临时签名钥匙串由 Tauri 管理。

## 自动发布顺序

1. 在经过 PR 合并的 `main` 提交上创建新的版本标签；不移动现有标签。
2. 版本与主分支归属检查通过后构建 Universal App。仅发布构建注入 Apple Secrets，且不使用 `--no-sign`。
3. Tauri 导入 Developer ID 证书并从内到外签名二进制；CI 随后创建 App 归档，单独提交公证并轮询状态。首次公证可能需要数小时，因此不把发布绑定在一次 `tauri build` 的等待超时上。
4. App 获得 `Accepted` 后附加并验证 App 票据，再从已附加票据的 App 重新生成 DMG；单独提交 DMG 公证，等待 `Accepted` 后附加并验证 DMG 票据。
5. 对 App 执行 `codesign --verify --deep --strict --verbose=2`、`spctl --assess --type execute --verbose=4` 和 `xcrun stapler validate`；检查身份、secure timestamp、hardened runtime，并拒绝 debugger entitlement。
6. 验证 DMG 签名、公证票据和 Gatekeeper；只读挂载 DMG 后，验证里面的 App。
7. 重新打包更新用 `.app.tar.gz`，解压最终归档，再验证其 App 签名和票据，防止打包过程丢失公证信息。
8. 对最终更新文件生成 Tauri updater 签名，验证内置公钥与版本绑定，生成校验和与 `SOURCE` 验证记录。
9. 发布任务要求 macOS 的全部验证记录为真，两个平台都通过后才上传并公开 GitHub Release。

缺少凭据、签名或票据不匹配、公证被拒绝、Gatekeeper 不接受、归档验证失败，都阻止发布。Windows 维持现有构建与 updater 签名，暂不引入 Authenticode。

## 验收边界

单元测试验证失败分支和编排逻辑，不能证明某张证书已通过 Apple 公证。首次真实验收必须以一个新版本在标签流水线中完成，并检查公开下载的 `.app`、DMG 和更新归档。

历史 `v0.2.1` 及以前的 macOS 文件仍未做 Developer ID 签名与公证；新流程不会将它们改写为“已公证”。首次已公证版本的发布，应在凭据配置和真实流水线成功之后进行。

官方参考：

- [Apple Developer ID certificates](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/)
- [App Store Connect API](https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api/)
- [Tauri macOS signing](https://v2.tauri.app/distribute/sign/macos/)
