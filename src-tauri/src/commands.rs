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
    let duration = if audio_data.is_empty() {
        0.0
    } else {
        audio_data.len() as f64 / 16000.0
    };

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

    let duration = if audio_data.is_empty() {
        0.0
    } else {
        audio_data.len() as f64 / 16000.0
    };

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
            // Fallback: use a meaningful message
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
            if is_chinese_text(text) { "en2zh" } else { "zh2en" }
        }
        _ => "en2zh",
    }
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
    
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
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
        "max_tokens": 1024,
    });
    
    let mut req = client.post(&api_url).json(&body);
    
    // Add authorization header if API key is set
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
    
    let translation = data["choices"][0]["message"]["content"]
        .as_str()
        .unwrap_or("")
        .trim()
        .to_string();
    
    if translation.is_empty() {
        return Err("LLM返回了空结果".into());
    }
    
    Ok(translation)
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
