mod commands;
mod sidecar;
mod state;
mod tray;

use commands::*;
use state::AppState;
use tauri::{Emitter, Manager};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_fs::init())
        .manage(AppState::new())
        .setup(|app| {
            let handle = app.handle();

            // Build system tray
            let _ = tray::build_tray(handle);

            // Auto-start the Python sidecar (frontend polls for status)
            let app_handle = handle.clone();
            tauri::async_runtime::spawn(async move {
                println!("[launcher] Starting sidecar...");
                let sidecar = sidecar::SidecarManager::new(app_handle.clone());
                match sidecar.start().await {
                    Ok(port) => {
                        println!("[launcher] sidecar ready, emitting server-status=true");
                        // Update AppState so get_server_status() returns true
                        match app_handle.try_state::<AppState>() {
                            Some(s) => {
                                println!("[launcher] AppState found, updating server_running=true");
                                match s.server_running.lock() {
                                    Ok(mut r) => *r = true,
                                    Err(e) => println!("[launcher] server_running lock error: {}", e),
                                }
                                match s.server_port.lock() {
                                    Ok(mut p) => *p = port,
                                    Err(e) => println!("[launcher] server_port lock error: {}", e),
                                }
                            }
                            None => println!("[launcher] AppState NOT FOUND via try_state!"),
                        }
                        let _ = app_handle.emit("server-status", true);
                        let _ = app_handle.emit(
                            "server-log",
                            format!("ASR server started on port {}", port),
                        );
                        app_handle.manage(sidecar);
                    }
                    Err(e) => {
                        println!("[launcher] sidecar failed: {}", e);
                        let _ = app_handle.emit("server-status", false);
                        let _ = app_handle.emit(
                            "server-log",
                            format!("Failed to start ASR server: {}", e),
                        );
                    }
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            start_server,
            stop_server,
            start_recording,
            stop_recording,
            send_audio_chunk,
            get_recording_state,
            get_server_status,
            save_config,
            load_config,
            copy_to_clipboard,
            pick_audio_file,
            pick_model_dir,
            export_transcriptions,
            save_history,
            get_history_dates,
            get_history_by_date,
            search_history,
            delete_history_entry,
            clear_all_history,
            translate_text,
            polish_text,
            test_llm_connection,
            save_llm_config,
            load_llm_config,
            load_hotwords,
            save_hotwords,
            download_qwen3_asr_model,
            check_model_status,
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let _ = window.hide();
                api.prevent_close();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
