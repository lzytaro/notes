# 自动更新

## 使用

- 在桌面版「设置 → 软件更新」打开「自动检查并下载」。默认关闭；手动检查始终可用。
- 应用启动时检查一次，之后每 6 小时检查。主窗口隐藏在托盘时继续运行，完全退出后不检查。休眠/断网恢复后会补检查到期的计划。
- 自动模式发现新版本后下载，完成后显示轻提示。安装前验证签名与签名绑定的版本，再由用户点击「安装并重新启动」。不会自行安装或重启。
- 关闭自动模式会停止后续检查和下载；已经开始的下载会完成。更新包暂存在进程内存，退出后需重新下载。
- 默认仅接收正式版。本仓库当前发布预览版本，需要开启「接收预览版本」才能收到。草稿、较低版本、仅构建元数据变化均不算升级。
- 读取 GitHub 发布说明时按纯文本展示，不执行 HTML。无更新时也能查看当前频道最新发布的说明。
- 网络错误按 15 分钟起指数退避，最长 6 小时；GitHub 限流提示等待时间。自动检查与手动检查共用互斥状态，避免重复请求和下载。
- v0.1.0 没有此功能，需要先手动安装 v0.2.0。正式版频道没有发布时，会显示「暂无正式发布」。

## 发布与密钥

应用只访问 `lzytaro/notes` 的公开 GitHub Releases，不需要用户提供 GitHub token。

`src-tauri/tauri.conf.json` 的 `plugins.updater.pubkey` 是公开验证密钥。配对私钥放在仓库外的受限目录，并在 GitHub Actions 配置为 `TAURI_SIGNING_PRIVATE_KEY`。当前密钥不设额外密码，由本地文件权限和 GitHub Secrets 保护；应另行安全备份。不要将私钥、证书、密码放入源码或前端环境变量。

发布时保持 `package.json`、锁文件、Cargo 包版本和 Tauri 配置版本一致，再推送 `v<版本>` 标签。CI 会：

1. 完成源码审计、密钥扫描、前端/原生测试和 macOS Universal / Windows x64 构建。
2. 只收集允许的安装文件，并清除 macOS 归档的构建机所有者信息。
3. 使用 Tauri CLI 的 `signer sign --app-version` 签名最终文件，生成 `.sig`。私钥只注入签名步骤，签名工具输出不会写入日志。
4. 使用应用内置公钥验证实际包和签名绑定版本，防止配置了不匹配的私钥。
5. 生成含签名文件的校验和；两个平台的源提交和版本一致后生成 `latest.json`。
6. 上传所有文件后才公开 GitHub 预发布版本。缺少签名密钥或任一校验失败都会阻止发布。

清单目标包含 `darwin-aarch64`、`darwin-x86_64`、`windows-x86_64-nsis`、`windows-x86_64-msi`。Windows 会沿用安装时使用的安装器类型；通用 `windows-x86_64` 目标供未标记安装类型的构建使用。

更新签名与 macOS/Windows 的发行者代码签名不同。目前仍未做 Apple 公证或 Authenticode 签名。浏览器预览不会下载或安装桌面更新。

## 验证

```bash
npm test
npm run build
cargo test --locked --manifest-path src-tauri/Cargo.toml --lib
python3 scripts/test_package_release.py
python3 scripts/test_update_manifest.py
# 显式执行只读的 GitHub 联网检查
cargo test --locked --manifest-path src-tauri/Cargo.toml --lib live_github_release_metadata -- --ignored
```

原生测试验证真实签名、篡改拒绝、版本替换拒绝及 GitHub 资源匹配。前端测试覆盖定时、重复调用、频道、断网、限流和失败重试。安装涉及系统权限与重启，双平台构建和这些测试不等同于完整的双平台实机升级验收。
