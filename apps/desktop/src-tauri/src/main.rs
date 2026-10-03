// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri_plugin_dialog::DialogExt;
use tauri::Manager;
mod backend;
use backend::{Backend, BackendStatus};

#[tauri::command]
fn backend_status(state: tauri::State<Backend>) -> BackendStatus { state.status() }
#[tauri::command]
fn retry_backend(state: tauri::State<Backend>) -> BackendStatus { state.retry() }
#[tauri::command]
fn backend_log_path(state: tauri::State<Backend>) -> String { state.log_path.to_string_lossy().into() }
#[tauri::command]
async fn select_directory(window: tauri::Window) -> Result<Option<String>, String> {
    window.dialog().file().blocking_pick_folder().map(|fp| fp.into_path().map(|p| p.to_string_lossy().into()).map_err(|e|e.to_string())).transpose()
}
#[tauri::command]
async fn select_database(window: tauri::Window) -> Result<Option<String>, String> {
    window.dialog().file().add_filter("SQLite", &["db", "sqlite", "sqlite3"]).blocking_pick_file().map(|fp| fp.into_path().map(|p| p.to_string_lossy().into()).map_err(|e|e.to_string())).transpose()
}

#[tauri::command]
async fn select_video(window: tauri::Window) -> Result<Option<String>, String> {
    let file_path = window
        .dialog()
        .file()
        .add_filter("Video", &["mp4", "mov", "mkv", "avi"])
        .blocking_pick_file();

    match file_path {
        Some(fp) => {
            let path = fp.into_path().map_err(|e| e.to_string())?;
            Ok(Some(path.to_string_lossy().to_string()))
        }
        None => Ok(None),
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_http::init())
        .setup(|app| {
            let data = std::env::var_os("MRA_DATA_DIR").map(std::path::PathBuf::from).unwrap_or_else(|| app.path().local_data_dir().unwrap().join("MotionReferenceAnalyzer"));
            let service=Backend::new(app.path().resource_dir()?, data);
            service.start(); app.manage(service); Ok(())
        })
        .invoke_handler(tauri::generate_handler![select_video, select_directory, select_database, backend_status, retry_backend, backend_log_path])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app,event| { if let tauri::RunEvent::Exit = event { app.state::<Backend>().stop(); } });
}
