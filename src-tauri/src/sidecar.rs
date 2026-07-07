use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::path::PathBuf;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::ShellExt;
use tokio::sync::Mutex;
use tokio::net::TcpStream;

/// Manages the Python ASR server process
pub struct SidecarManager {
    app: AppHandle,
    child: Arc<Mutex<Option<tauri_plugin_shell::process::CommandChild>>>,
    running: Arc<AtomicBool>,
    port: Arc<Mutex<u16>>,
}

impl SidecarManager {
    pub fn new(app: AppHandle) -> Self {
        Self {
            app,
            child: Arc::new(Mutex::new(None)),
            running: Arc::new(AtomicBool::new(false)),
            port: Arc::new(Mutex::new(6016)),
        }
    }

    fn get_script_path(&self) -> Result<PathBuf, String> {
        let mut candidates: Vec<PathBuf> = Vec::new();

        if let Ok(res_dir) = self.app.path().resource_dir() {
            candidates.push(res_dir.join("_up_").join("sidecar").join("caps-writer-server.py"));
            candidates.push(res_dir.join("sidecar").join("caps-writer-server.py"));
        }

        let cwd = std::env::current_dir().unwrap_or_default();
        candidates.push(cwd.join("sidecar").join("caps-writer-server.py"));
        if let Some(parent) = cwd.parent() {
            candidates.push(parent.join("sidecar").join("caps-writer-server.py"));
        }
        if let Ok(exe) = std::env::current_exe() {
            if let Some(parent) = exe.parent() {
                candidates.push(parent.join("sidecar").join("caps-writer-server.py"));
            }
        }

        for candidate in &candidates {
            if candidate.exists() {
                return Ok(candidate.clone());
            }
        }

        Err("Sidecar script not found: sidecar/caps-writer-server.py".into())
    }

    pub async fn start(&self) -> Result<u16, String> {
        if self.running.load(Ordering::SeqCst) {
            return Ok(*self.port.lock().await);
        }

        let script_path = self.get_script_path()?;
        let script_str = script_path.to_string_lossy().to_string();
        println!("[sidecar] script path: {}", script_str);

        // Verify the script exists
        if !script_path.exists() {
            return Err(format!("Script not found: {}", script_str));
        }
        println!("[sidecar] script exists, checking python...");

        // Quick check: can we find python? Prefer `python`, fall back to `python3`
        // (macOS Sonoma+ drops the unversioned `python` symlink).
        let mut python_bin = "python";
        if std::process::Command::new(python_bin).arg("--version").output().is_err() {
            python_bin = "python3";
        }
        match std::process::Command::new(python_bin).arg("--version").output() {
            Ok(out) => println!("[sidecar] {} check: {}", python_bin, String::from_utf8_lossy(&out.stdout).trim()),
            Err(e) => println!("[sidecar] {} check FAILED: {}", python_bin, e),
        }

        // Read user-configured custom_models_dir from config.json (highest priority).
        // This is the primary fix for the bundled .app not finding the user-installed
        // model directory (which lives outside /Applications, e.g. in a dev tree).
        // On macOS the Tauri UI saves config to ~/Library/Application Support/…
        // but APPDATA (Windows) or bare HOME could also be valid.
        let config_path = if cfg!(target_os = "macos") {
            std::env::var("HOME")
                .map(std::path::PathBuf::from)
                .unwrap_or_else(|_| std::env::current_dir().unwrap_or_default())
                .join("Library")
                .join("Application Support")
                .join("caps-writer-desktop")
                .join("config.json")
        } else {
            std::env::var("APPDATA")
                .or_else(|_| std::env::var("HOME"))
                .map(std::path::PathBuf::from)
                .unwrap_or_else(|_| std::env::current_dir().unwrap_or_default())
                .join("caps-writer-desktop")
                .join("config.json")
        };
        println!("[sidecar] reading config from: {}", config_path.display());
        let user_models_dir: Option<std::path::PathBuf> = std::fs::read_to_string(&config_path)
            .ok()
            .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
            .and_then(|v| v.get("custom_models_dir").and_then(|x| x.as_str()).map(String::from))
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .map(std::path::PathBuf::from)
            .filter(|p| p.exists() && p.is_dir());

        if let Some(ref u) = user_models_dir {
            println!("[sidecar] using custom_models_dir from config: {}", u.display());
        }

        // Resolve models directory relative to the script path: HIGHEST priority
        // is the user-specified custom dir; otherwise fall through to the auto-detect chain.
        let models_dir = user_models_dir
            .or_else(|| {
                script_path
                    .parent()
                    .and_then(|p| p.parent())
                    .map(|p| p.join("models"))
                    .filter(|p| p.exists())
            })
            .or_else(|| {
                // Fallback: check alongside executable
                std::env::current_exe().ok().and_then(|exe| {
                    exe.parent()
                        .map(|p| p.join("models"))
                        .filter(|p| p.exists())
                })
            })
            .or_else(|| {
                // Fallback: check cwd/models
                std::env::current_dir()
                    .ok()
                    .map(|p| p.join("models"))
                    .filter(|p| p.exists())
            })
            .or_else(|| {
                // Fallback: ~/Library/Application Support/caps-writer-desktop/models (macOS user data)
                std::env::var("HOME").ok().map(|h| {
                    PathBuf::from(h).join("Library").join("Application Support")
                        .join("caps-writer-desktop").join("models")
                }).filter(|p| p.exists())
            })
            .or_else(|| {
                // Fallback: ~/Documents/caps-writer-desktop/models
                std::env::var("HOME").ok().map(|h| {
                    PathBuf::from(h).join("Documents").join("caps-writer-desktop")
                        .join("models")
                }).filter(|p| p.exists())
            })
            .or_else(|| {
                // Fallback: respect CW_MODEL_DIR env var (overrides all)
                std::env::var("CW_MODEL_DIR").ok().map(PathBuf::from).filter(|p| p.exists())
            });

        // Loud remediation banner when we couldn't find any models dir AND the
        // user hasn't set CW_MODEL_DIR externally.
        if models_dir.is_none() && std::env::var("CW_MODEL_DIR").is_err() {
            println!("[sidecar] ===================================================================");
            println!("[sidecar] ERROR: No 'models' dir found near executable, and CW_MODEL_DIR is unset.");
            println!("[sidecar] To enable real Qwen3-ASR, do ONE of:");
            println!("[sidecar]   1. export CW_MODEL_DIR=/path/to/dir/containing/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25");
            println!("[sidecar]   2. Place the model folder under <project>/models/  (auto-detected by Python)");
            println!("[sidecar]   3. Place the model folder under ~/Library/Application Support/caps-writer-desktop/models/  (auto-detected)");
            println!("[sidecar] Without these, the sidecar will fall back to mock-recognition (demo text).");
            println!("[sidecar] ===================================================================");
        }

        // Kill any stale process occupying port 6016
        self.kill_stale_on_port(6016).await;

        let mut cmd = self.app.shell().command(python_bin).arg(&script_str);
        if let Some(md) = &models_dir {
            cmd = cmd.env("CW_MODEL_DIR", md.to_string_lossy().to_string());
        }
        // Force Python unbuffered stdout/stderr so [Server]/[ASR]/[Mock] log lines
        // stream to the Rust sidecar immediately (otherwise they get trapped in the
        // CPython block buffer when stdout/stderr are not connected to a TTY).
        cmd = cmd.env("PYTHONUNBUFFERED", "1");

        // Pass GPU provider (cpu/dml) to the sidecar — reuse the same config path
        let config_file = config_path.clone();
        if let Ok(config_content) = std::fs::read_to_string(&config_file) {
            if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&config_content) {
                if let Some(gpu) = parsed.get("gpu").and_then(|v| v.as_str()) {
                    cmd = cmd.env("CW_PROVIDER", gpu);
                    println!("[sidecar] setting CW_PROVIDER={}", gpu);
                }
            }
        }

        let command = cmd;

        let (mut rx, child) = command
            .spawn()
            .map_err(|e| format!("Failed to spawn Python sidecar: {}", e))?;

        *self.child.lock().await = Some(child);
        *self.port.lock().await = 6016;
        self.running.store(true, Ordering::SeqCst); // Mark as starting

        let app_handle = self.app.clone();

        // Start forwarding stdout/stderr logs in background immediately
        let fwd_app = app_handle.clone();
        let fwd_running = self.running.clone();
        tokio::spawn(async move {
            use tauri_plugin_shell::process::CommandEvent;
            loop {
                tokio::select! {
                    event = rx.recv() => {
                        match event {
                            Some(CommandEvent::Stdout(bytes)) => {
                                let s = String::from_utf8_lossy(&bytes).trim().to_string();
                                if !s.is_empty() { let _ = fwd_app.emit("server-log", s); }
                            }
                            Some(CommandEvent::Stderr(bytes)) => {
                                let s = String::from_utf8_lossy(&bytes).trim().to_string();
                                if !s.is_empty() { let _ = fwd_app.emit("server-log", s); }
                            }
                            Some(CommandEvent::Terminated(_)) => {
                                fwd_running.store(false, Ordering::SeqCst);
                                let _ = fwd_app.emit("server-status", false);
                                break;
                            }
                            None => break,
                            _ => {}
                        }
                    }
                }
            }
        });

        println!("[sidecar] spawned, probing port 6016...");

        // Wait for the server to be ready by probing port 6016
        let port = 6016;
        let max_retries = 40; // 40 * 500ms = 20s total
        let mut ready = false;
        for i in 0..max_retries {
            tokio::time::sleep(Duration::from_millis(500)).await;
            // Check if process died (log-forwarding task sets running to false on Terminated)
            if !self.running.load(Ordering::SeqCst) {
                break;
            }
            match TcpStream::connect(("127.0.0.1", port)).await {
                Ok(_) => {
                    println!("[sidecar] port {} open at attempt {}", port, i + 1);
                    ready = true;
                    break;
                }
                Err(_) => {
                    if i == 0 || (i + 1) % 10 == 0 {
                        println!("[sidecar] port {} not ready (attempt {}/{})", port, i + 1, max_retries);
                    }
                }
            }
        }

        if !ready {
            println!("[sidecar] TIMEOUT - server did not become ready");
            self.running.store(false, Ordering::SeqCst);
            if let Some(c) = self.child.lock().await.take() {
                let _ = c.kill();
            }
            return Err("ASR server did not start within 20 seconds. Check that Python dependencies are installed.".into());
        }
        println!("[sidecar] server ready, returning Ok");

        Ok(6016)
    }

    pub async fn stop(&self) -> Result<(), String> {
        if !self.running.load(Ordering::SeqCst) {
            return Ok(());
        }
        self.running.store(false, Ordering::SeqCst);
        if let Some(child) = self.child.lock().await.take() {
            let _ = child.kill();
        }
        Ok(())
    }

    #[allow(dead_code)]
    pub fn is_running(&self) -> bool {
        self.running.load(Ordering::SeqCst)
    }

    #[allow(dead_code)]
    pub async fn get_port(&self) -> u16 {
        *self.port.lock().await
    }

    /// Kill any process that occupies the given port.
    /// Uses `netstat -ano` + `taskkill /F /PID <pid>` on Windows.
    async fn kill_stale_on_port(&self, port: u16) {
        // If port is free, nothing to do
        if TcpStream::connect(("127.0.0.1", port)).await.is_err() {
            return;
        }
        println!("[sidecar] port {} is occupied, looking for stale process...", port);

        // Find PID using netstat
        if let Ok(out) = std::process::Command::new("netstat")
            .args(["-ano"])
            .output()
        {
            let stdout = String::from_utf8_lossy(&out.stdout);
            for line in stdout.lines() {
                // Lines like: "TCP    127.0.0.1:6016    0.0.0.0:0    LISTENING    12345"
                if line.contains(&format!(":{}", port)) && line.contains("LISTENING") {
                    if let Some(pid_str) = line.split_whitespace().last() {
                        if let Ok(pid) = pid_str.parse::<u32>() {
                            println!("[sidecar] killing stale PID {} on port {}", pid, port);
                            let _ = std::process::Command::new("taskkill")
                                .args(["/F", "/PID", &pid.to_string()])
                                .output();
                            tokio::time::sleep(Duration::from_secs(1)).await;
                            return;
                        }
                    }
                }
            }
        }
    }
}

impl Drop for SidecarManager {
    fn drop(&mut self) {
        self.running.store(false, Ordering::SeqCst);
    }
}
