use serde::Serialize;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};

#[derive(Debug, Serialize)]
pub struct AppInfo {
    pub name: &'static str,
    pub version: &'static str,
    pub platform: &'static str,
}

mod commands {
    use super::{AppInfo, WebviewUrl, WebviewWindowBuilder};
    use tauri::{AppHandle, Manager};

    #[tauri::command]
    pub fn get_app_info() -> AppInfo {
        AppInfo {
            name: "纸笺",
            version: env!("CARGO_PKG_VERSION"),
            platform: std::env::consts::OS,
        }
    }

    #[tauri::command]
    pub fn show_main_window(app: AppHandle) -> Result<(), String> {
        super::focus_main_window(&app);
        Ok(())
    }

    #[tauri::command]
    pub fn open_widget(app: AppHandle, kind: String) -> Result<(), String> {
        if !matches!(kind.as_str(), "next" | "today" | "capture") {
            return Err("unknown widget".into());
        }
        let label = format!("widget-{kind}");
        if let Some(window) = app.get_webview_window(&label) {
            let _ = window.show();
            let _ = window.set_focus();
            return Ok(());
        }

        let url = WebviewUrl::App(format!("index.html?widget={kind}").into());
        WebviewWindowBuilder::new(&app, &label, url)
            .title("纸笺组件")
            .inner_size(340.0, 250.0)
            .min_inner_size(280.0, 180.0)
            .decorations(false)
            .transparent(true)
            .always_on_top(true)
            .visible_on_all_workspaces(true)
            .skip_taskbar(true)
            .resizable(true)
            .build()
            .map(|_| ())
            .map_err(|error| error.to_string())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_sql::Builder::default().build())
        .invoke_handler(tauri::generate_handler![
            commands::get_app_info,
            commands::show_main_window,
            commands::open_widget
        ])
        .setup(|app| {
            let show = MenuItem::with_id(app, "show", "显示纸笺", true, None::<&str>)?;
            let quick_add = MenuItem::with_id(app, "quick-add", "快速记录", true, None::<&str>)?;
            let widget = MenuItem::with_id(app, "widget", "显示桌面组件", true, None::<&str>)?;
            let separator = tauri::menu::PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "退出纸笺", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quick_add, &widget, &separator, &quit])?;

            TrayIconBuilder::new()
                .icon(app.default_window_icon().expect("default window icon").clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main_window(app),
                    "quick-add" => {
                        show_main_window(app);
                        let _ = app.emit("open-quick-add", ());
                    }
                    "widget" => {
                        let _ = commands::open_widget(app.clone(), "next".into());
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main_window(tray.app_handle());
                    }
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn focus_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn show_main_window(app: &tauri::AppHandle) {
    focus_main_window(app);
}
