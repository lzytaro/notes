//! Only the main window can request updates. URLs, versions and signatures are
//! resolved in Rust; the webview never supplies an executable or download URL.
use reqwest::Client;
use semver::Version;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;
use tauri::{ipc::Channel, AppHandle, State, WebviewWindow};
use tauri_plugin_updater::{Update, UpdaterExt};
use tokio::sync::Mutex;

const RELEASES: &str = "https://api.github.com/repos/lzytaro/notes/releases";
const REPOSITORY: &str = "https://github.com/lzytaro/notes/releases/download/";
const MAX_PACKAGE: u64 = 512 * 1024 * 1024;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateError {
    message: String,
    retry_at: Option<u64>,
}

impl UpdateError {
    fn new(message: &str) -> Self {
        Self {
            message: message.into(),
            retry_at: None,
        }
    }
}

#[derive(Deserialize)]
struct Asset {
    name: String,
    browser_download_url: String,
    size: u64,
}

#[derive(Deserialize)]
struct Release {
    tag_name: String,
    name: Option<String>,
    body: Option<String>,
    published_at: Option<String>,
    draft: bool,
    prerelease: bool,
    assets: Vec<Asset>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ReleaseInfo {
    version: String,
    name: String,
    notes: String,
    published_at: Option<String>,
    prerelease: bool,
    available: bool,
    installable: bool,
    unavailable_reason: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CheckResult {
    current_version: String,
    release: Option<ReleaseInfo>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DownloadProgress {
    downloaded: u64,
    total: Option<u64>,
}

struct Pending {
    update: Update,
    bytes: Option<Vec<u8>>,
}

#[derive(Default)]
pub struct UpdateState(Mutex<Option<Pending>>);

fn main_only(window: &WebviewWindow) -> Result<(), UpdateError> {
    if window.label() != "main" {
        return Err(UpdateError::new("请在主窗口管理更新。"));
    }
    Ok(())
}

fn release_version(release: &Release, preview: bool) -> Option<Version> {
    let version = Version::parse(release.tag_name.strip_prefix('v')?).ok()?;
    if release.draft || (!preview && (release.prerelease || !version.pre.is_empty())) {
        return None;
    }
    Some(version)
}

fn latest(releases: &[Release], preview: bool) -> Option<(&Release, Version)> {
    releases
        .iter()
        .filter_map(|r| release_version(r, preview).map(|v| (r, v)))
        .max_by(|a, b| a.1.cmp_precedence(&b.1))
}

fn trusted_asset(url: &str, tag: &str, filename: &str) -> bool {
    url == format!("{REPOSITORY}{tag}/{filename}")
}

fn http_client(timeout: Duration) -> Result<Client, UpdateError> {
    let _ = rustls::crypto::ring::default_provider().install_default();
    Client::builder()
        .user_agent(concat!("notes-desktop/", env!("CARGO_PKG_VERSION")))
        .https_only(true)
        .timeout(timeout)
        .build()
        .map_err(|_| UpdateError::new("无法初始化更新连接。"))
}

async fn get_json(client: &Client, url: &str) -> Result<(Value, bool), UpdateError> {
    let mut response = client
        .get(url)
        .send()
        .await
        .map_err(|_| UpdateError::new("无法连接 GitHub，请检查网络后重试。"))?;
    if response.status().as_u16() == 403 || response.status().as_u16() == 429 {
        let mut error = UpdateError::new("GitHub 暂时限制了请求频率，请稍后再试。");
        error.retry_at = response
            .headers()
            .get("x-ratelimit-reset")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.parse::<u64>().ok())
            .map(|v| v * 1000);
        if error.retry_at.is_none() {
            error.retry_at = response
                .headers()
                .get("retry-after")
                .and_then(|v| v.to_str().ok())
                .and_then(|v| v.parse::<u64>().ok())
                .map(|seconds| {
                    std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .unwrap_or_default()
                        .as_millis() as u64
                        + seconds * 1000
                });
        }
        return Err(error);
    }
    if !response.status().is_success() {
        return Err(UpdateError::new("暂时无法读取发布信息，请稍后重试。"));
    }
    let has_next = response
        .headers()
        .get("link")
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.contains("rel=\"next\""));
    let mut data = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| UpdateError::new("发布信息下载中断。"))?
    {
        if data.len() + chunk.len() > 4 * 1024 * 1024 {
            return Err(UpdateError::new("发布信息过大，已停止检查。"));
        }
        data.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&data)
        .map(|json| (json, has_next))
        .map_err(|_| UpdateError::new("发布信息格式不正确。"))
}

fn validate_update(
    update: &Update,
    release: &Release,
    version: &Version,
) -> Result<(), UpdateError> {
    let filename = update
        .download_url
        .path_segments()
        .and_then(|mut v| v.next_back())
        .unwrap_or_default();
    let asset = release.assets.iter().find(|a| a.name == filename);
    if update.version != version.to_string()
        || !trusted_asset(update.download_url.as_str(), &release.tag_name, filename)
        || asset.is_none_or(|a| {
            a.browser_download_url != update.download_url.as_str()
                || a.size == 0
                || a.size > MAX_PACKAGE
        })
        || update.signature.trim().is_empty()
    {
        return Err(UpdateError::new("更新清单与发布文件不匹配，已停止更新。"));
    }
    Ok(())
}

#[tauri::command]
pub async fn check_for_updates(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, UpdateState>,
    include_prerelease: bool,
) -> Result<CheckResult, UpdateError> {
    main_only(&window)?;
    let mut pending = state
        .0
        .try_lock()
        .map_err(|_| UpdateError::new("更新操作正在进行，请稍候。"))?;
    // A failed new check must never leave an older candidate installable.
    *pending = None;
    let client = http_client(Duration::from_secs(30))?;
    let mut releases = Vec::new();
    for page in 1..=10 {
        let (json, has_next) =
            get_json(&client, &format!("{RELEASES}?per_page=100&page={page}")).await?;
        let mut batch: Vec<Release> = serde_json::from_value(json)
            .map_err(|_| UpdateError::new("GitHub 发布信息格式不正确。"))?;
        releases.append(&mut batch);
        if !has_next {
            break;
        }
        if page == 10 {
            return Err(UpdateError::new("发布记录过多，无法确认最新版本。"));
        }
    }
    let current = app.package_info().version.clone();
    let mut result = CheckResult {
        current_version: current.to_string(),
        release: None,
    };
    let Some((release, version)) = latest(&releases, include_prerelease) else {
        return Ok(result);
    };
    let available = version.cmp_precedence(&current).is_gt();
    let mut info = ReleaseInfo {
        version: version.to_string(),
        name: release
            .name
            .clone()
            .unwrap_or_else(|| release.tag_name.clone()),
        notes: release.body.clone().unwrap_or_default(),
        published_at: release.published_at.clone(),
        prerelease: release.prerelease || !version.pre.is_empty(),
        available,
        installable: false,
        unavailable_reason: None,
    };
    if available {
        if let Some(manifest) = release.assets.iter().find(|a| a.name == "latest.json") {
            if !trusted_asset(
                &manifest.browser_download_url,
                &release.tag_name,
                "latest.json",
            ) {
                return Err(UpdateError::new("更新清单来源不正确。"));
            }
            let (raw, _) = get_json(&client, &manifest.browser_download_url).await?;
            if raw.get("version").and_then(Value::as_str) != Some(version.to_string().as_str()) {
                return Err(UpdateError::new("更新清单版本与发布标签不一致。"));
            }
            let updater = app
                .updater_builder()
                .endpoints(vec![manifest
                    .browser_download_url
                    .parse()
                    .map_err(|_| UpdateError::new("更新清单地址无效。"))?])
                .map_err(|_| UpdateError::new("更新清单必须使用安全连接。"))?
                .configure_client(|c| c.https_only(true).timeout(Duration::from_secs(600)))
                .version_comparator(|current, remote| {
                    remote.version.cmp_precedence(&current).is_gt()
                })
                .build()
                .map_err(|_| UpdateError::new("无法初始化更新器。"))?;
            let update = updater
                .restore_update(raw)
                .map_err(|_| UpdateError::new("该发布的更新清单无效或不支持当前平台。"))?
                .ok_or_else(|| UpdateError::new("没有更高版本可供更新。"))?;
            validate_update(&update, release, &version)?;
            info.installable = true;
            *pending = Some(Pending {
                update,
                bytes: None,
            });
        } else {
            info.unavailable_reason =
                Some("此版本尚未提供签名更新包，请等待发布完成后重试。".into());
        }
    }
    result.release = Some(info);
    Ok(result)
}

#[tauri::command]
pub async fn download_update(
    window: WebviewWindow,
    state: State<'_, UpdateState>,
    on_progress: Channel<DownloadProgress>,
) -> Result<(), UpdateError> {
    main_only(&window)?;
    let mut guard = state
        .0
        .try_lock()
        .map_err(|_| UpdateError::new("更新操作正在进行，请稍候。"))?;
    let pending = guard
        .as_mut()
        .ok_or_else(|| UpdateError::new("请先检查更新。"))?;
    if pending.bytes.is_some() {
        return Ok(());
    }
    let mut downloaded = 0;
    let mut last_event = std::time::Instant::now();
    // Bound the response even if the upstream asset metadata/content length is wrong.
    let client = http_client(Duration::from_secs(600))?;
    let mut response = client
        .get(pending.update.download_url.clone())
        .send()
        .await
        .and_then(|r| r.error_for_status())
        .map_err(|_| UpdateError::new("更新包下载失败，请检查网络后重试。"))?;
    let total = response.content_length();
    if total.is_some_and(|v| v > MAX_PACKAGE) {
        return Err(UpdateError::new("更新包大小异常。"));
    }
    let mut bytes = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| UpdateError::new("下载中断，请重试。"))?
    {
        downloaded += chunk.len() as u64;
        if downloaded > MAX_PACKAGE {
            return Err(UpdateError::new("更新包大小异常，已停止下载。"));
        }
        bytes.extend_from_slice(&chunk);
        if last_event.elapsed() >= Duration::from_millis(100) {
            let _ = on_progress.send(DownloadProgress { downloaded, total });
            last_event = std::time::Instant::now();
        }
    }
    pending
        .update
        .verify(&bytes)
        .map_err(|_| UpdateError::new("更新包签名或版本校验失败，已拒绝安装。请重新检查更新。"))?;
    let _ = on_progress.send(DownloadProgress {
        downloaded,
        total: Some(downloaded),
    });
    pending.bytes = Some(bytes);
    Ok(())
}

#[tauri::command]
pub async fn install_update(
    app: AppHandle,
    window: WebviewWindow,
    state: State<'_, UpdateState>,
) -> Result<(), UpdateError> {
    main_only(&window)?;
    let guard = state
        .0
        .try_lock()
        .map_err(|_| UpdateError::new("更新操作正在进行，请稍候。"))?;
    let pending = guard
        .as_ref()
        .ok_or_else(|| UpdateError::new("请先检查并下载更新。"))?;
    let bytes = pending
        .bytes
        .as_ref()
        .ok_or_else(|| UpdateError::new("更新包尚未下载完成。"))?;
    pending
        .update
        .install(bytes)
        .map_err(|_| UpdateError::new("安装未完成，请确认应用位于可写目录，并稍后重试。"))?;
    app.restart();
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture_update(version: &str) -> Update {
        let mut context = tauri::test::mock_context(tauri::test::noop_assets());
        context.config_mut().plugins.0.insert(
            "updater".into(),
            serde_json::json!({
                "pubkey": include_str!("../tests/fixtures/updater-public.txt").trim(),
                "requireSignedVersion": true,
                "endpoints": ["https://github.com/lzytaro/notes/releases/latest/download/latest.json"]
            }),
        );
        let app = tauri::test::mock_builder()
            .plugin(
                tauri_plugin_updater::Builder::new()
                    .pubkey(include_str!("../tests/fixtures/updater-public.txt").trim())
                    .build(),
            )
            .build(context)
            .unwrap();
        app.updater_builder()
            .target("fixture")
            .build()
            .unwrap()
            .restore_update(serde_json::json!({
                "version": version,
                "platforms": { "fixture": {
                    "url": "https://github.com/lzytaro/notes/releases/download/v99.0.0/fixture.txt",
                    "signature": include_str!("../tests/fixtures/updater-signature.txt").trim()
                }}
            }))
            .unwrap()
            .unwrap()
    }
    #[test]
    fn verifies_real_signature_and_rejects_tampering_and_version_substitution() {
        let update = fixture_update("99.0.0");
        let payload = include_bytes!("../tests/fixtures/updater-payload.txt");
        assert!(update.verify(payload).is_ok());
        assert!(update.verify(b"tampered bytes").is_err());
        assert!(fixture_update("100.0.0").verify(payload).is_err());
    }
    #[test]
    #[ignore = "Verifies CI release artifacts against the public key shipped in the app"]
    fn release_artifacts_match_embedded_key() {
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
        let config: Value = serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let version = config["version"].as_str().unwrap();
        let mut context = tauri::test::mock_context(tauri::test::noop_assets());
        context
            .config_mut()
            .plugins
            .0
            .insert("updater".into(), config["plugins"]["updater"].clone());
        let app = tauri::test::mock_builder()
            .plugin(tauri_plugin_updater::Builder::new().build())
            .build(context)
            .unwrap();
        let updater = app
            .updater_builder()
            .target("fixture")
            .endpoints(vec![
                "https://github.com/lzytaro/notes/releases/latest/download/latest.json"
                    .parse()
                    .unwrap(),
            ])
            .unwrap()
            .version_comparator(|_, _| true)
            .build()
            .unwrap();
        let mut count = 0;
        for entry in std::fs::read_dir(root.join("release-assets")).unwrap() {
            let path = entry.unwrap().path();
            if path.extension().and_then(|v| v.to_str()) != Some("sig") {
                continue;
            }
            let package = path.with_extension("");
            let update = updater.restore_update(serde_json::json!({
                "version": version,
                "platforms": { "fixture": {
                    "url": format!("https://github.com/lzytaro/notes/releases/download/v{version}/{}", package.file_name().unwrap().to_str().unwrap()),
                    "signature": std::fs::read_to_string(&path).unwrap().trim()
                }}
            })).unwrap().unwrap();
            update
                .verify(&std::fs::read(&package).unwrap())
                .expect("release signature must match embedded public key and version");
            count += 1;
        }
        assert!(count > 0, "release must contain signed update packages");
    }
    #[test]
    fn manifest_must_match_published_asset_and_version() {
        let update = fixture_update("99.0.0");
        let mut release = release("v99.0.0", false);
        release.assets.push(Asset {
            name: "fixture.txt".into(),
            browser_download_url: update.download_url.to_string(),
            size: 40,
        });
        assert!(validate_update(&update, &release, &Version::parse("99.0.0").unwrap()).is_ok());
        assert!(validate_update(&update, &release, &Version::parse("100.0.0").unwrap()).is_err());
        release.assets[0].size = MAX_PACKAGE + 1;
        assert!(validate_update(&update, &release, &Version::parse("99.0.0").unwrap()).is_err());
    }
    #[test]
    #[ignore = "Read-only live GitHub network check; run explicitly"]
    fn live_github_release_metadata() {
        tauri::async_runtime::block_on(async {
            let client = http_client(Duration::from_secs(30)).unwrap();
            let (json, _) = get_json(&client, &format!("{RELEASES}?per_page=100"))
                .await
                .unwrap();
            let releases: Vec<Release> = serde_json::from_value(json).unwrap();
            assert!(latest(&releases, true).is_some());
        });
    }
    fn release(tag: &str, preview: bool) -> Release {
        Release {
            tag_name: tag.into(),
            name: None,
            body: None,
            published_at: None,
            draft: false,
            prerelease: preview,
            assets: vec![],
        }
    }
    #[test]
    fn selects_semver_not_publication_order_and_filters_channels() {
        let releases = vec![
            release("v0.9.0", false),
            release("v0.10.0", false),
            release("v1.0.0-rc.1", true),
        ];
        assert_eq!(latest(&releases, false).unwrap().1.to_string(), "0.10.0");
        assert_eq!(latest(&releases, true).unwrap().1.to_string(), "1.0.0-rc.1");
        assert!(latest(&[release("v1.0.0", true)], false).is_none());
        assert!(latest(&[release("v1.0.0-rc.1", false)], false).is_none());
    }
    #[test]
    fn rejects_drafts_invalid_tags_and_build_metadata_as_upgrade() {
        let mut draft = release("v9.0.0", false);
        draft.draft = true;
        assert!(latest(&[draft, release("release-next", false)], true).is_none());
        assert!(Version::parse("1.0.0+2")
            .unwrap()
            .cmp_precedence(&Version::parse("1.0.0+1").unwrap())
            .is_eq());
    }
    #[test]
    fn asset_must_be_https_and_exact_repo_tag_and_name() {
        assert!(trusted_asset(
            &format!("{REPOSITORY}v1.0.0/latest.json"),
            "v1.0.0",
            "latest.json"
        ));
        for url in [
            "http://github.com/lzytaro/notes/releases/download/v1.0.0/latest.json",
            "https://github.com/other/notes/releases/download/v1.0.0/latest.json",
            "https://github.com/lzytaro/notes/releases/download/v0.1.0/latest.json",
        ] {
            assert!(!trusted_asset(url, "v1.0.0", "latest.json"));
        }
    }
}
