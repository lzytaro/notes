# 纸笺 · 随手记录

面向 macOS 和 Windows 的轻量待办桌面应用，使用 Tauri、Rust、React 和 TypeScript。

**当前版本为预览版。** 支持本地任务、日期/提醒设置、重复任务、标签、主题、托盘入口和桌面组件。云同步仍处于实验阶段，默认发行包未连接任何云服务。

## 安装与发布

在本仓库的 Releases 页面下载 macOS Universal DMG / App 压缩包，或 Windows x64 EXE / MSI。每个平台附带 SHA-256 校验文件和源代码提交号。

从 v0.2.1 起，在「设置 → 软件更新」中可手动检查更新，或开启自动检查并下载。自动更新默认关闭，开启后在启动时和每 6 小时检查 GitHub Releases；下载后验证签名，点击「安装并重新启动」才会安装。可查看发布说明、下载进度和错误重试。切换「接收预览版本」可接收本仓库的预发布版本。

v0.1.0 需要先手动安装一次 v0.2.1 或更高版本。更新包使用专用密钥签名，但安装包仍未做 Apple 公证或 Windows Authenticode 签名。请先使用非重要数据体验。详细边界见 [发布说明](docs/RELEASE_NOTES.md)。

## 本地开发

需要 Node.js 22.12+（CI 使用 24）、Rust stable，以及对应平台的 Tauri 开发依赖。

```bash
npm ci
npm run dev
# 启动桌面版本
npm run desktop:dev
```

```bash
npm test
npm run build
cargo check --locked --manifest-path src-tauri/Cargo.toml
npm run desktop:build
```

桌面端任务保存到应用目录下的 SQLite；浏览器预览使用 localStorage。首次打开包含虚构示例任务。关闭主窗口会隐藏到托盘，完全退出请使用托盘菜单。

## 可选云服务配置

开发者可复制 `.env.example` 为 `.env.local` 并配置自己的 Supabase 项目，应用 `supabase/migrations/` 下的迁移。`VITE_` 变量会被编译进前端，因此只能使用公开客户端配置，不能放入服务端密钥或 service-role key。

云登录与多设备同步尚未完成端到端验收，桌面认证重定向和离线冲突处理仍需完善。发行 CI 不注入这些配置。

## CI 与发布流程

- 提交与 PR：公开文件检查、Gitleaks 全历史扫描、领域测试、前端构建，以及 macOS Universal / Windows x64 安装包构建。
- 版本标签 `v*`：核对标签和包版本；两个平台全部通过后生成带校验和的 GitHub 预发布版本。
- 发布包的最终字节经 Tauri 签名，并使用应用内置公钥验证；发布清单匹配 macOS 两种架构及 Windows EXE/MSI 安装方式。
- 流水线只上传安装包、更新签名/清单、校验和及源代码提交号，不上传整个构建目录、日志、环境文件或本机产物。
- 版本发布使用最小权限；第三方 Actions 固定到提交 SHA。

维护者配置与签名备份见 [自动更新维护说明](docs/UPDATES.md)。

提交前请运行 `python3 scripts/audit_public.py --staged`，并遵守 [公开与安全规则](SECURITY.md)。
