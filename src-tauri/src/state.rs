use serde::{Deserialize, Serialize};
use std::sync::Mutex;

/// App recording state
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum RecordingState {
    Idle,
    Recording,
    Processing,
    Transcribing,
}

/// Application state shared across the Tauri app
pub struct AppState {
    pub recording: Mutex<RecordingState>,
    pub server_running: Mutex<bool>,
    pub server_port: Mutex<u16>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            recording: Mutex::new(RecordingState::Idle),
            server_running: Mutex::new(false),
            server_port: Mutex::new(6016),
        }
    }
}
