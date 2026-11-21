# 纸笺 v0.2.4 — 预览版

本版为 macOS 引入 Developer ID Application 签名与 Apple 公证。发行流水线只在 App、DMG 和最终更新归档全部验证通过后公开安装包。

## macOS 发行改进

- Universal App 使用 Developer ID Application 证书签名，开启 hardened runtime，并附带安全时间戳。
- App 与 DMG 均提交 Apple 公证并附加票据；校验签名、Gatekeeper，以及 DMG 内的应用。
- 更新用 `.app.tar.gz` 在重新打包后再次解压验签和验证票据，随后生成 Tauri updater 签名。
- Apple 仍在处理时保存原始签名文件、校验和和提交 ID；可在同标签的新 CI 运行中恢复，避免重复构建或提交。
- DMG 使用独立临时钥匙串签名，并从已附加票据的 App 生成，保留应用签名和票据。
- 缺少凭据、公证被拒绝或任何最终文件校验失败，都会阻止发行。

## 版本与发布管理

- 功能分支与发布分支通过 PR 和必需 CI 检查合入受保护的 main。
- 发布标签不可移动或删除，必须来自已合并的主分支提交，版本与锁文件必须一致。
- 签名凭据通过 GitHub Secrets 注入；源代码与发布包不包含私钥或本机数据。

## 升级与下载

- macOS：下载本版 Universal DMG，将纸笺安装到 Applications 后运行。
- Windows x64：继续提供 EXE / MSI；Windows 尚未配置 Authenticode 签名。
- v0.2.1 用户可开启「接收预览版本」后检查更新；v0.1.0 没有更新器，需要手动安装新版本。
- 更新包继续使用原有 updater 公钥验证，并且必须由用户点击安装和重新启动。

## 仍在预览阶段

默认发行包没有云服务配置，Supabase 登录/同步尚未完成真实多设备验收。提醒和更新依赖应用运行。请保留任务备份；签名和公证不等于所有业务功能已完成实机验收。
