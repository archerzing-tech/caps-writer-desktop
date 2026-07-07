use crate::sidecar::SidecarManager;
use crate::state::{AppState, RecordingState};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State};
use base64::Engine;
use tauri_plugin_dialog::DialogExt;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub model_type: String,
    pub language: String,
    pub format_num: bool,
    pub hotwords_enabled: bool,
    pub llm_enabled: bool,
    pub paste_on_finish: bool,
    pub save_audio: bool,
    pub trash_punc: String,
    pub gpu: String,
    #[serde(default)]
    pub realtime_enabled: bool,
    #[serde(default)]
    pub translate_direction: String,
    #[serde(default)]
    pub translate_enabled: bool,
    #[serde(default)]
    pub custom_models_dir: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            model_type: "qwen_asr".into(),
            language: "auto".into(),
            format_num: true,
            hotwords_enabled: true,
            llm_enabled: true,
            paste_on_finish: true,
            save_audio: true,
            trash_punc: "，。,.".into(),
            gpu: "cpu".into(),
            realtime_enabled: false,
            translate_direction: "auto".into(),
            translate_enabled: false,
            custom_models_dir: String::new(),
        }
    }
}

#[tauri::command]
pub fn get_server_status(state: State<'_, AppState>) -> Result<bool, String> {
    let val = *state.server_running.lock().map_err(|e| e.to_string())?;
    println!("[command] get_server_status = {}", val);
    Ok(val)
}

/// Send an audio chunk for realtime transcription (does not change recording state)
#[tauri::command]
pub async fn send_audio_chunk(
    app: AppHandle,
    state: State<'_, AppState>,
    audio_data: Vec<f32>,
) -> Result<(), String> {
    // Short-circuit: no audio data to process
    if audio_data.is_empty() {
        return Ok(());
    }

    let duration = audio_data.len() as f64 / 16000.0;

    let port = {
        let p = state.server_port.lock().map_err(|e| e.to_string())?;
        *p
    };

    // Send audio chunk to ASR server
    let result_text = match send_audio_to_asr(&audio_data, port).await {
        Ok(text) => text,
        Err(e) => {
            let _ = app.emit("server-log", format!("[Realtime] ASR chunk failed: {}", e));
            return Ok(());
        }
    };

    if result_text.trim().is_empty() {
        return Ok(());
    }

    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();

    let _ = app.emit(
        "transcription",
        serde_json::json!({
            "text": result_text,
            "is_final": true,
            "duration": duration,
            "timestamp": now,
        }),
    );
    Ok(())
}

#[tauri::command]
pub fn get_recording_state(state: State<'_, AppState>) -> Result<RecordingState, String> {
    state.recording.lock().map(|r| r.clone()).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn start_recording(app: AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    let mut rec = state.recording.lock().map_err(|e| e.to_string())?;
    *rec = RecordingState::Recording;
    let _ = app.emit("recording-state", "recording");
    Ok(())
}

#[tauri::command]
pub async fn stop_recording(
    app: AppHandle,
    state: State<'_, AppState>,
    audio_data: Vec<f32>,
) -> Result<(), String> {
    // Mark recording as idle
    {
        let mut rec = state.recording.lock().map_err(|e| e.to_string())?;
        *rec = RecordingState::Idle;
    }

    // Short-circuit: no audio data to process (e.g. realtime mode)
    if audio_data.is_empty() {
        let _ = app.emit("recording-state", "idle");
        return Ok(());
    }

    let duration = audio_data.len() as f64 / 16000.0;

    let port = {
        let p = state.server_port.lock().map_err(|e| e.to_string())?;
        *p
    };

    // Emit processing state
    let _ = app.emit("recording-state", "processing");

    // Try to send audio to Python ASR server via WebSocket
    let result_text = match send_audio_to_asr(&audio_data, port).await {
        Ok(text) => text,
        Err(e) => {
            let _ = app.emit("server-log", format!("ASR request failed: {}", e));
            format!("[ASR offline] Audio: {:.1}s, {} samples", duration, audio_data.len())
        }
    };

    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs_f64();

    let _ = app.emit(
        "transcription",
        serde_json::json!({
            "text": result_text,
            "is_final": true,
            "duration": duration,
            "timestamp": now,
        }),
    );
    let _ = app.emit("recording-state", "idle");
    Ok(())
}

/// Send PCM float32 audio to the Python ASR server and get transcribed text back.
async fn send_audio_to_asr(audio_data: &[f32], port: u16) -> Result<String, String> {
    use tokio_tungstenite::connect_async;
    use tokio_tungstenite::tungstenite::Message;
    use futures_util::StreamExt;
    use futures_util::SinkExt;

    let url = format!("ws://127.0.0.1:{}", port);
    let (ws_stream, _) = connect_async(&url)
        .await
        .map_err(|e| format!("WebSocket connect: {}", e))?;

    let (mut write, mut read) = ws_stream.split();

    // Base64-encode the PCM float32 audio
    let audio_bytes: Vec<u8> = audio_data
        .iter()
        .flat_map(|&s| s.to_le_bytes().to_vec())
        .collect();
    let b64 = base64::engine::general_purpose::STANDARD.encode(&audio_bytes);

    let msg = serde_json::json!({
        "type": "audio",
        "task_id": format!("tauri_{}", std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()),
        "source": "mic",
        "data_base64": b64,
        "is_final": true,
        "time_start": 0.0,
        "language": "auto",
    });

    write
        .send(Message::Text(msg.to_string()))
        .await
        .map_err(|e| format!("WebSocket send: {}", e))?;

    // Receive response
    let response = read
        .next()
        .await
        .ok_or("No response from ASR server")?
        .map_err(|e| format!("WebSocket recv: {}", e))?;

    let text = match response {
        Message::Text(t) => t,
        Message::Binary(b) => String::from_utf8_lossy(&b).to_string(),
        _ => return Err("Unexpected WebSocket message type".into()),
    };

    let parsed: serde_json::Value =
        serde_json::from_str(&text).map_err(|e| format!("JSON parse: {}", e))?;

    // Close the connection gracefully
    let _ = write.send(Message::Close(None)).await;

    let result = parsed
        .get("text")
        .and_then(|v| v.as_str())
        .unwrap_or("(empty result)")
        .to_string();

    Ok(result)
}

fn config_path() -> Result<std::path::PathBuf, String> {
    let dir = std::env::var("APPDATA")
        .or_else(|_| std::env::var("HOME"))
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| std::env::current_dir().unwrap_or_default())
        .join("caps-writer-desktop");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("config.json"))
}

#[tauri::command]
pub fn save_config(config: AppConfig) -> Result<(), String> {
    let path = config_path()?;
    let s = serde_json::to_string_pretty(&config).map_err(|e| e.to_string())?;
    std::fs::write(&path, &s).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn load_config() -> Result<AppConfig, String> {
    let path = match config_path() {
        Ok(p) => p,
        Err(_) => return Ok(AppConfig::default()),
    };
    match std::fs::read_to_string(&path) {
        Ok(s) => serde_json::from_str(&s).map_err(|e| e.to_string()),
        Err(_) => Ok(AppConfig::default()),
    }
}

#[tauri::command]
pub fn copy_to_clipboard(app: AppHandle, text: String) -> Result<(), String> {
    use tauri_plugin_clipboard_manager::ClipboardExt;
    app.clipboard().write_text(text).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn pick_audio_file(app: AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    let file = app
        .dialog()
        .file()
        .add_filter("Audio", &["wav", "mp3", "m4a", "flac", "ogg", "aac"])
        .blocking_pick_file();
    Ok(file.map(|f| f.to_string()))
}

#[tauri::command]
pub async fn pick_model_dir(app: AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;
    let folder = app
        .dialog()
        .file()
        .blocking_pick_folder();
    Ok(folder.map(|f| f.to_string()))
}

#[tauri::command]
pub async fn start_server(app: AppHandle, state: State<'_, AppState>) -> Result<String, String> {
    let already = { *state.server_running.lock().map_err(|e| e.to_string())? };
    if already {
        return Err("Server already running".into());
    }

    let sidecar = SidecarManager::new(app.clone());
    let port = sidecar.start().await.map_err(|e| e.to_string())?;

    {
        let mut r = state.server_running.lock().map_err(|e| e.to_string())?;
        *r = true;
        *state.server_port.lock().map_err(|e| e.to_string())? = port;
    }

    app.manage(sidecar);
    Ok(format!("Server started on port {}", port))
}

#[tauri::command]
pub async fn stop_server(app: AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    if let Some(s) = app.try_state::<SidecarManager>() {
        s.stop().await.map_err(|e| e.to_string())?;
    }
    *state.server_running.lock().map_err(|e| e.to_string())? = false;
    Ok(())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TranscriptionEntry {
    pub text: String,
    pub time: f64,
}

#[tauri::command]
pub async fn export_transcriptions(
    app: AppHandle,
    entries: Vec<TranscriptionEntry>,
    format: String,
) -> Result<String, String> {
    let (filter_name, extension, default_name) = match format.as_str() {
        "srt" => ("SubRip Subtitle (*.srt)", "srt", "transcription.srt"),
        "json" => ("JSON File (*.json)", "json", "transcription.json"),
        _ => ("Text File (*.txt)", "txt", "transcription.txt"),
    };

    let file = app
        .dialog()
        .file()
        .add_filter(filter_name, &[extension])
        .set_file_name(default_name)
        .blocking_save_file();

    let path = match file {
        Some(p) => p,
        None => return Err("用户取消了保存".into()),
    };

    // Reverse entries to get chronological order (newest first -> oldest first)
    let chrono: Vec<&TranscriptionEntry> = entries.iter().rev().collect();

    let content = match format.as_str() {
        "srt" => format_srt(&chrono),
        "json" => format_json(&chrono),
        _ => format_txt(&chrono),
    };

    let path_str = path.to_string();
    std::fs::write(&path_str, &content).map_err(|e| format!("写入文件失败: {}", e))?;

    // Return the file name for display purposes
    let file_name = std::path::Path::new(&path_str)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| "unknown".into());

    Ok(file_name)
}

fn format_txt(entries: &[&TranscriptionEntry]) -> String {
    entries
        .iter()
        .map(|e| e.text.as_str())
        .collect::<Vec<_>>()
        .join("\n")
}

fn format_srt(entries: &[&TranscriptionEntry]) -> String {
    let mut result = String::new();
    for (i, entry) in entries.iter().enumerate() {
        // Use cumulative time for start, assume each segment is ~2s or gap
        let start_secs = entries[0..i].iter().enumerate().fold(0.0, |acc, (j, e)| {
            let gap = if j + 1 < entries.len() {
                let next = &entries[j + 1];
                if next.time > e.time { next.time - e.time } else { 2.0 }
            } else {
                2.0
            };
            acc + gap.min(10.0) // Cap gap at 10s
        });

        let end_secs = start_secs + 2.0;

        result.push_str(&format!(
            "{}\n{} --> {}\n{}\n\n",
            i + 1,
            srt_time(start_secs),
            srt_time(end_secs),
            entry.text
        ));
    }
    result
}

fn srt_time(secs: f64) -> String {
    let h = (secs as u64) / 3600;
    let m = ((secs as u64) % 3600) / 60;
    let s = (secs as u64) % 60;
    let ms = ((secs.fract() * 1000.0).round() as u64).min(999);
    format!("{:02}:{:02}:{:02},{:03}", h, m, s, ms)
}

fn format_json(entries: &[&TranscriptionEntry]) -> String {
    let total_chars: usize = entries.iter().map(|e| e.text.chars().count()).sum();
    let total_time = if entries.len() >= 2 {
        let first = entries.first().unwrap().time;
        let last = entries.last().unwrap().time;
        if last > first { last - first } else { 0.0 }
    } else {
        0.0
    };

    let items: Vec<serde_json::Value> = entries
        .iter()
        .map(|e| {
            let ts = e.time;
            let date = chrono_datetime(ts);
            serde_json::json!({
                "text": e.text,
                "timestamp": ts,
                "time": date,
            })
        })
        .collect();

    let output = serde_json::json!({
        "meta": {
            "exported_at": chrono_datetime(
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs_f64()
            ),
            "total_entries": entries.len(),
            "total_chars": total_chars,
            "total_duration_secs": total_time.round() as u64,
            "source": "CapsWriter Desktop",
        },
        "entries": items,
    });

    serde_json::to_string_pretty(&output).unwrap_or_else(|_| "{}".into())
}

// ============================================================
// History: Local Storage of Transcription Records (by date)
// ============================================================

/// Get the directory where history files are stored
fn history_dir() -> Result<std::path::PathBuf, String> {
    let dir = std::env::var("APPDATA")
        .or_else(|_| std::env::var("HOME"))
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| std::env::current_dir().unwrap_or_default())
        .join("caps-writer-desktop")
        .join("history");
    std::fs::create_dir_all(&dir).map_err(|e| format!("创建历史目录失败: {}", e))?;
    Ok(dir)
}

/// Get the file path for a given date string (YYYY-MM-DD)
fn history_file_path(date: &str) -> Result<std::path::PathBuf, String> {
    Ok(history_dir()?.join(format!("{}.json", date)))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    pub text: String,
    pub time: f64,       // unix timestamp
    pub duration: f64,   // seconds
    pub date: String,    // YYYY-MM-DD
}

/// Save a single transcription entry to the date-based history file
#[tauri::command]
pub fn save_history(entry: HistoryEntry) -> Result<(), String> {
    let path = history_file_path(&entry.date)?;
    
    // Read existing entries
    let mut entries: Vec<HistoryEntry> = if path.exists() {
        let content = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        Vec::new()
    };
    
    // Add new entry (prepend for newest first)
    entries.insert(0, entry);
    
    // Write back
    let content = serde_json::to_string_pretty(&entries).map_err(|e| e.to_string())?;
    std::fs::write(&path, &content).map_err(|e| e.to_string())?;
    
    Ok(())
}

/// Get a sorted list of all dates that have history records
#[tauri::command]
pub fn get_history_dates() -> Result<Vec<String>, String> {
    let dir = history_dir()?;
    let mut dates: Vec<String> = Vec::new();
    
    if let Ok(rd) = std::fs::read_dir(&dir) {
        for entry in rd.flatten() {
            if let Some(name) = entry.path().file_stem() {
                let s = name.to_string_lossy().to_string();
                // Only include YYYY-MM-DD formatted files
                if s.len() == 10 && s.chars().filter(|&c| c == '-').count() == 2 {
                    dates.push(s);
                }
            }
        }
    }
    
    // Sort descending (newest first)
    dates.sort_by(|a, b| b.cmp(a));
    Ok(dates)
}

/// Get all entries for a specific date (YYYY-MM-DD)
#[tauri::command]
pub fn get_history_by_date(date: String) -> Result<Vec<HistoryEntry>, String> {
    let path = history_file_path(&date)?;
    if !path.exists() {
        return Ok(Vec::new());
    }
    let content = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let entries: Vec<HistoryEntry> = serde_json::from_str(&content).unwrap_or_default();
    Ok(entries)
}

/// Search history entries by text query
#[tauri::command]
pub fn search_history(query: String) -> Result<Vec<HistoryEntry>, String> {
    let dir = history_dir()?;
    let q = query.to_lowercase();
    let mut results: Vec<HistoryEntry> = Vec::new();
    
    if let Ok(rd) = std::fs::read_dir(&dir) {
        for dir_entry in rd.flatten() {
            if let Ok(content) = std::fs::read_to_string(dir_entry.path()) {
                if let Ok(entries) = serde_json::from_str::<Vec<HistoryEntry>>(&content) {
                    for e in entries {
                        if e.text.to_lowercase().contains(&q) {
                            results.push(e);
                        }
                    }
                }
            }
        }
    }
    
    // Sort by time descending
    results.sort_by(|a, b| b.time.partial_cmp(&a.time).unwrap_or(std::cmp::Ordering::Equal));
    Ok(results)
}

/// Delete a specific history entry by date and index
#[tauri::command]
pub fn delete_history_entry(date: String, index: usize) -> Result<(), String> {
    let path = history_file_path(&date)?;
    if !path.exists() {
        return Ok(());
    }
    
    let content = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let mut entries: Vec<HistoryEntry> = serde_json::from_str(&content).unwrap_or_default();
    
    if index < entries.len() {
        entries.remove(index);
    }
    
    let content = serde_json::to_string_pretty(&entries).map_err(|e| e.to_string())?;
    std::fs::write(&path, &content).map_err(|e| e.to_string())?;
    
    Ok(())
}

/// Clear ALL history entries (delete all JSON files in history dir)
#[tauri::command]
pub fn clear_all_history() -> Result<(), String> {
    let dir = history_dir()?;
    if let Ok(rd) = std::fs::read_dir(&dir) {
        for entry in rd.flatten() {
            let path = entry.path();
            if path.extension().map_or(false, |ext| ext == "json") {
                let _ = std::fs::remove_file(&path);
            }
        }
    }
    Ok(())
}

// ============================================================
// Translation: Chinese-English via LLM (OpenAI/Ollama)
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TranslateRequest {
    pub text: String,
    pub direction: String, // "zh2en" or "en2zh"
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmSettings {
    pub backend: String,  // "openai" or "ollama"
    pub api_url: String,
    pub model: String,
    pub api_key: String,
}

fn load_llm_settings() -> LlmSettings {
    // Try to read from app config first (same directory as config.json)
    let dir = std::env::var("APPDATA")
        .or_else(|_| std::env::var("HOME"))
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| std::env::current_dir().unwrap_or_default())
        .join("caps-writer-desktop");
    
    let config_path = dir.join("llm_config.json");
    if let Ok(content) = std::fs::read_to_string(&config_path) {
        if let Ok(settings) = serde_json::from_str::<LlmSettings>(&content) {
            return settings;
        }
    }
    
    // Fallback defaults: DeepSeek (Chinese API, recommended)
    LlmSettings {
        backend: "deepseek".into(),
        api_url: "https://api.deepseek.com/v1".into(),
        model: "deepseek-chat".into(),
        api_key: String::new(),
    }
}

/// Detect if text is primarily Chinese (returns true) or English (returns false)
fn is_chinese_text(text: &str) -> bool {
    let chinese_chars = text.chars().filter(|c| {
        let cp = *c as u32;
        (0x4E00..=0x9FFF).contains(&cp) || (0x3400..=0x4DBF).contains(&cp)
    }).count();
    let total_alphabetic = text.chars().filter(|c| c.is_alphabetic()).count();
    if total_alphabetic == 0 && chinese_chars == 0 { return true; }
    chinese_chars as f64 / (chinese_chars + total_alphabetic) as f64 > 0.3
}

/// Resolve translation direction: auto-detect or use explicit direction
fn resolve_translate_direction(text: &str, direction: &str) -> &'static str {
    match direction {
        "zh2en" => "zh2en",
        "en2zh" => "en2zh",
        "auto" => {
            // If text is Chinese, translate to English (zh2en)
            // If text is English/other, translate to Chinese (en2zh)
            if is_chinese_text(text) { "zh2en" } else { "en2zh" }
        }
        _ => "en2zh",
    }
}

/// Send a chat completion request to the configured LLM and return the response content.
/// Shared helper for translate_text, polish_text, and test_llm_connection.
async fn llm_request(
    settings: &LlmSettings,
    system_prompt: &str,
    user_prompt: &str,
    timeout_secs: u64,
    max_tokens: u32,
) -> Result<String, String> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(timeout_secs))
        .build()
        .map_err(|e| format!("创建HTTP客户端失败: {}", e))?;
    let api_url = settings.api_url.trim_end_matches('/').to_string() + "/chat/completions";

    let body = serde_json::json!({
        "model": settings.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    });

    let mut req = client.post(&api_url).json(&body);
    if !settings.api_key.is_empty() {
        req = req.header("Authorization", format!("Bearer {}", settings.api_key));
    }

    let response = req.send().await.map_err(|e| format!("LLM请求失败: {}", e))?;

    if !response.status().is_success() {
        let status = response.status();
        let body_text = response.text().await.unwrap_or_default();
        return Err(format!("LLM返回错误 ({}): {}", status, body_text));
    }

    let data: serde_json::Value = response.json().await.map_err(|e| format!("解析响应失败: {}", e))?;

    let content = data["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .trim()
        .to_string();

    if content.is_empty() {
        return Err("LLM返回了空结果".into());
    }

    Ok(content)
}

/// Translate text between Chinese and English using configured LLM
#[tauri::command]
pub async fn translate_text(request: TranslateRequest) -> Result<String, String> {
    let settings = load_llm_settings();

    let resolved = resolve_translate_direction(&request.text, &request.direction);
    let (system_prompt, user_prompt) = match resolved {
        "zh2en" => (
            "You are a professional translator. Translate the following Chinese text to English. Output ONLY the translation, no explanations, no quotes.",
            format!("Chinese: {}\nEnglish:", request.text)
        ),
        _ => (
            "You are a professional translator. Translate the following English text to Chinese. Output ONLY the translation, no explanations, no quotes.",
            format!("English: {}\nChinese:", request.text)
        ),
    };

    llm_request(&settings, &system_prompt, &user_prompt, 30, 1024).await
}

/// Test LLM connection by sending a minimal request
#[tauri::command]
pub async fn test_llm_connection(settings: LlmSettings) -> Result<String, String> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .build()
        .map_err(|e| format!("创建HTTP客户端失败: {}", e))?;
    let api_url = settings.api_url.trim_end_matches('/').to_string() + "/chat/completions";

    let body = serde_json::json!({
        "model": settings.model,
        "messages": [
            {"role": "user", "content": "Hi"}
        ],
        "max_tokens": 5,
    });

    let mut req = client.post(&api_url).json(&body);
    if !settings.api_key.is_empty() {
        req = req.header("Authorization", format!("Bearer {}", settings.api_key));
    }

    let response = req.send().await.map_err(|e| format!("连接失败: {}", e))?;

    if !response.status().is_success() {
        let status = response.status();
        let body_text = response.text().await.unwrap_or_default();
        return Err(format!("API返回错误 ({}): {}", status, body_text));
    }

    let data: serde_json::Value = response.json().await.map_err(|e| format!("解析响应失败: {}", e))?;
    let reply = data["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .trim()
        .to_string();

    let model_used = data["model"].as_str().unwrap_or(&settings.model);

    Ok(format!("✅ 连接成功！模型: {}, 响应: {}", model_used, reply.chars().take(40).collect::<String>()))
}

/// Save LLM settings to config file
#[tauri::command]
pub fn save_llm_config(settings: LlmSettings) -> Result<(), String> {
    let dir = std::env::var("APPDATA")
        .or_else(|_| std::env::var("HOME"))
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| std::env::current_dir().unwrap_or_default())
        .join("caps-writer-desktop");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let content = serde_json::to_string_pretty(&settings).map_err(|e| e.to_string())?;
    std::fs::write(dir.join("llm_config.json"), &content).map_err(|e| e.to_string())?;
    Ok(())
}

/// Load LLM settings from config file
#[tauri::command]
pub fn load_llm_config() -> Result<LlmSettings, String> {
    Ok(load_llm_settings())
}

// ============================================================
// LLM Polish: Punctuation + Sentence Segmentation + Typo Fix
// ============================================================

/// Polish ASR transcription text using LLM: fix punctuation, sentence breaks, typos.
#[tauri::command]
pub async fn polish_text(text: String) -> Result<String, String> {
    let settings = load_llm_settings();

    let system_prompt = "你是一个专业的语音识别文本润色助手。请对以下语音识别结果进行润色：\n\
1. 修正标点符号（添加缺失的句号、逗号、问号等，修正错误的标点）\n\
2. 合理断句（将长句分割为合理的短句，按语义分段）\n\
3. 修正错别字和常见的语音识别错误（同音字、近音字等）\n\
\n要求：\n\
- 保持原意不变，不要添加或删除实质性内容\n\
- 不要改变说话人的语气和风格\n\
- 直接输出润色后的文本，不要添加任何解释、注释或额外内容";

    llm_request(&settings, system_prompt, &text, 60, 4096).await
}

// ============================================================
// Hotwords: Load / Save
// ============================================================

fn hotwords_path() -> Result<std::path::PathBuf, String> {
    let dir = std::env::var("APPDATA")
        .or_else(|_| std::env::var("HOME"))
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| std::env::current_dir().unwrap_or_default())
        .join("caps-writer-desktop");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir.join("hotwords.txt"))
}

#[tauri::command]
pub fn load_hotwords() -> Result<String, String> {
    let path = hotwords_path()?;
    if !path.exists() {
        return Ok(String::new());
    }
    std::fs::read_to_string(&path).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn save_hotwords(content: String) -> Result<(), String> {
    let path = hotwords_path()?;
    std::fs::write(&path, &content).map_err(|e| e.to_string())
}

/// Format a unix timestamp as a human-readable date-time string
fn chrono_datetime(unix_ts: f64) -> String {
    let secs = unix_ts as i64;
    match time::OffsetDateTime::from_unix_timestamp(secs) {
        Ok(dt) => {
            let local_offset = time::UtcOffset::current_local_offset().unwrap_or(time::UtcOffset::UTC);
            let local_dt = dt.to_offset(local_offset);
            format!(
                "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
                local_dt.year(),
                local_dt.month() as u8,
                local_dt.day(),
                local_dt.hour(),
                local_dt.minute(),
                local_dt.second(),
            )
        }
        Err(_) => format!("{}", unix_ts),
    }
}

// ============================================================
// One-click Model Download from HuggingFace (sherpa-onnx-qwen3-asr)
// ============================================================

const MODEL_REPO: &str = "cattle12/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25";

fn model_root_dir() -> std::path::PathBuf {
    std::env::var("APPDATA")
        .or_else(|_| std::env::var("HOME"))
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| std::env::current_dir().unwrap_or_default())
        .join("caps-writer-desktop")
        .join("models")
}

fn model_target_dir() -> std::path::PathBuf {
    model_root_dir().join(MODEL_REPO)
}

#[tauri::command]
pub async fn download_qwen3_asr_model(app: AppHandle) -> Result<String, String> {
    let target_dir = model_target_dir();
    let sentinel = target_dir.join("DOWNLOAD_OK");

    if sentinel.exists() {
        let _ = app.emit(
            "model-download-progress",
            serde_json::json!({
                "status": "already_installed",
                "path": target_dir.to_string_lossy(),
            }),
        );
        return Ok(format!("模型已就绪: {}", target_dir.to_string_lossy()));
    }

    // Spawn the actual download so the Invoke promise returns immediately.
    // Progress is reported via Tauri events on `model-download-progress`.
    let app_clone = app.clone();
    let dir_for_task = target_dir.clone();
    tauri::async_runtime::spawn(async move {
        if let Err(e) = run_hf_download(app_clone.clone(), dir_for_task).await {
            eprintln!("[model-download] error: {}", e);
            let _ = app_clone.emit(
                "model-download-progress",
                serde_json::json!({
                    "status": "error",
                    "message": e,
                }),
            );
        }
    });
    Ok("下载已启动，请观察下方进度条".into())
}

async fn run_hf_download(
    app: AppHandle,
    target_dir: std::path::PathBuf,
) -> Result<String, String> {
    std::fs::create_dir_all(&target_dir)
        .map_err(|e| format!("创建模型目录失败: {}", e))?;

    let _ = app.emit(
        "model-download-progress",
        serde_json::json!({
            "status": "fetching_manifest",
            "repo": MODEL_REPO,
        }),
    );
    println!("[model-download] fetching HF tree manifest for {}", MODEL_REPO);

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .connect_timeout(std::time::Duration::from_secs(15))
        .user_agent("CapsWriter-Desktop/0.2")
        .build()
        .map_err(|e| format!("创建HTTP客户端失败: {}", e))?;

    let manifest_url = format!(
        "https://huggingface.co/api/models/{}/tree/main",
        MODEL_REPO
    );
    let resp = client
        .get(&manifest_url)
        .send()
        .await
        .map_err(|e| format!("获取HF清单失败: {}", e))?;
    if !resp.status().is_success() {
        return Err(format!("HF清单返回 HTTP {}", resp.status()));
    }
    let page: Vec<serde_json::Value> = resp
        .json()
        .await
        .map_err(|e| format!("解析HF清单失败: {}", e))?;

    let files: Vec<(String, u64)> = page
        .into_iter()
        .filter(|item| {
            item.get("type").and_then(|v| v.as_str()) == Some("file")
        })
        .filter_map(|item| {
            let path = item.get("path").and_then(|v| v.as_str())?.to_string();
            let size = item
                .get("size")
                .and_then(|v| v.as_u64())
                .unwrap_or(0);
            Some((path, size))
        })
        .collect();

    if files.is_empty() {
        return Err("HF清单中没有可下载文件".into());
    }

    let total_bytes: u64 = files.iter().map(|(_, s)| *s).sum();
    println!(
        "[model-download] {} files, {:.1} MB total",
        files.len(),
        total_bytes as f64 / 1_000_000.0
    );
    let _ = app.emit(
        "model-download-progress",
        serde_json::json!({
            "status": "downloading",
            "files_total": files.len(),
            "bytes_total": total_bytes,
        }),
    );

    let mut received_total: u64 = 0;
    for (i, (path, expected_size)) in files.iter().enumerate() {
        let file_path = target_dir.join(path);
        if let Some(parent) = file_path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }

        // Resumability: skip file if local size already matches expected size.
        if file_path.exists() {
            if let Ok(meta) = std::fs::metadata(&file_path) {
                if meta.len() == *expected_size && *expected_size > 0 {
                    println!(
                        "[model-download] skip existing {} ({} bytes)",
                        path, expected_size
                    );
                    received_total += expected_size;
                    let _ = app.emit(
                        "model-download-progress",
                        serde_json::json!({
                            "status": "progress",
                            "filename": path,
                            "files_done": i,
                            "files_total": files.len(),
                            "bytes_received": received_total,
                            "bytes_total": total_bytes,
                            "skipped": true,
                        }),
                    );
                    continue;
                }
            }
        }

        let file_url = format!(
            "https://huggingface.co/{}/resolve/main/{}",
            MODEL_REPO, path
        );
        println!(
            "[model-download] GET {} -> {}",
            file_url,
            file_path.display()
        );
        let resp = client
            .get(&file_url)
            .send()
            .await
            .map_err(|e| format!("下载 {} 失败: {}", path, e))?;
        if !resp.status().is_success() {
            return Err(format!("HTTP {} 下载 {}", resp.status(), path));
        }

        let mut dest = std::fs::File::create(&file_path)
            .map_err(|e| format!("创建 {} 失败: {}", file_path.display(), e))?;

        // Buffer writes to ~256 KB chunks to balance I/O syscalls vs emit frequency.
        let mut buf: Vec<u8> = Vec::with_capacity(256 * 1024);
        let mut received: u64 = 0;
        let mut last_emit = std::time::Instant::now();
        use futures_util::StreamExt;
        let mut stream = resp.bytes_stream();
        while let Some(chunk_res) = stream.next().await {
            let chunk = chunk_res.map_err(|e| format!("读取 {} 失败: {}", path, e))?;
            buf.extend_from_slice(&chunk);
            if buf.len() >= 256 * 1024 {
                std::io::Write::write_all(&mut dest, &buf)
                    .map_err(|e| format!("写入 {} 失败: {}", file_path.display(), e))?;
                received += buf.len() as u64;
                buf.clear();
            }
            // Throttle emits to roughly every 250 ms to avoid event flood.
            if last_emit.elapsed() >= std::time::Duration::from_millis(250) {
                let _ = app.emit(
                    "model-download-progress",
                    serde_json::json!({
                        "status": "progress",
                        "filename": path,
                        "files_done": i,
                        "files_total": files.len(),
                        "bytes_received": received_total + received + buf.len() as u64,
                        "bytes_total": total_bytes,
                    }),
                );
                last_emit = std::time::Instant::now();
            }
        }
        if !buf.is_empty() {
            std::io::Write::write_all(&mut dest, &buf)
                .map_err(|e| format!("写入 {} 失败: {}", file_path.display(), e))?;
            received += buf.len() as u64;
        }
        std::io::Write::flush(&mut dest)
            .map_err(|e| format!("flush {} 失败: {}", file_path.display(), e))?;
        drop(dest);
        received_total += received;
        println!(
            "[model-download] done {} ({} bytes)",
            path, received
        );
    }

    // Sentinel file: confirms all downloads succeeded.
    std::fs::write(
        &sentinel_path(),
        format!(
            "ok @ {}\nrepo: {}\n",
            chrono_datetime(
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs_f64()
            ),
            MODEL_REPO
        ),
    )
    .map_err(|e| e.to_string())?;

    let _ = app.emit(
        "model-download-progress",
        serde_json::json!({
            "status": "complete",
            "path": target_dir.to_string_lossy(),
            "bytes_received": received_total,
            "bytes_total": total_bytes,
        }),
    );
    println!(
        "[model-download] COMPLETE — {} bytes to {}",
        received_total,
        target_dir.display()
    );

    Ok(format!(
        "下载完成: {} ({:.1} MB)",
        target_dir.display(),
        received_total as f64 / 1_000_000.0
    ))
}

fn sentinel_path() -> std::path::PathBuf {
    model_target_dir().join("DOWNLOAD_OK")
}

#[tauri::command]
pub fn check_model_status() -> Result<serde_json::Value, String> {
    let target_dir = model_target_dir();
    let ready = target_dir.join("DOWNLOAD_OK").exists();
    let size_bytes: u64 = if target_dir.exists() {
        walk_dir_size(&target_dir).unwrap_or(0)
    } else {
        0
    };
    Ok(serde_json::json!({
        "path": target_dir.to_string_lossy(),
        "ready": ready,
        "size_bytes": size_bytes,
        "repo": MODEL_REPO,
        "size_mb": (size_bytes as f64 / 1_000_000.0).round(),
    }))
}

fn walk_dir_size(p: &std::path::Path) -> std::io::Result<u64> {
    let mut total = 0u64;
    if p.is_file() {
        return Ok(std::fs::metadata(p)?.len());
    }
    for entry in std::fs::read_dir(p)? {
        let entry = entry?;
        let ft = entry.file_type()?;
        if ft.is_file() {
            total += entry.metadata()?.len();
        } else if ft.is_dir() {
            total += walk_dir_size(&entry.path())?;
        }
    }
    Ok(total)
}
