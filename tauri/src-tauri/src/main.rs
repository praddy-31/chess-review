// Chess Review - native (Tauri v2) shell.
//
// Starts the local engine process (the frozen Python sidecar shipped in
// Resources/engine/, or `python3 engine/server.py` when run from source),
// waits for its "LISTENING <port> <token>" line, and opens the main window on
// http://127.0.0.1:<port>/#<token>. The engine exits by itself when this app
// quits or crashes (its stdin pipe closes); on a normal quit it is also killed.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

struct Engine(Mutex<Option<Child>>);

fn home() -> PathBuf {
    let var = if cfg!(windows) { "USERPROFILE" } else { "HOME" };
    PathBuf::from(std::env::var(var).unwrap_or_else(|_| ".".into()))
}

/// The engine's data folder (engine.log goes there). Keep in step with
/// engine/system.py `data_dir()`; CHESS_REVIEW_DATA overrides both.
fn data_dir() -> PathBuf {
    let d = if let Ok(d) = std::env::var("CHESS_REVIEW_DATA") {
        PathBuf::from(d)
    } else if cfg!(target_os = "macos") {
        home().join("Library/Application Support/Chess Review")
    } else if cfg!(windows) {
        std::env::var("APPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|_| home().join("AppData").join("Roaming"))
            .join("Chess Review")
    } else {
        std::env::var("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|_| home().join(".local/share"))
            .join("chess-review")
    };
    let _ = fs::create_dir_all(&d);
    d
}

/// Folders where Stockfish and lc0 usually live, which an app started from
/// Finder or a desktop menu doesn't have on its PATH.
fn engine_dirs() -> Vec<PathBuf> {
    if cfg!(target_os = "macos") {
        vec!["/opt/homebrew/bin".into(), "/usr/local/bin".into()]
    } else if cfg!(windows) {
        vec![]
    } else {
        vec!["/usr/games".into(), "/usr/local/bin".into()]
    }
}

/// The engine command: the bundled executable if present, else the source tree.
fn engine_command(app: &AppHandle) -> Result<Command, String> {
    if let Ok(res) = app.path().resource_dir() {
        let exe = res.join("engine").join(format!("chess-engine{}", std::env::consts::EXE_SUFFIX));
        if exe.exists() {
            return Ok(Command::new(exe));
        }
    }
    let src = std::env::var("CHESS_REVIEW_ENGINE_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../engine"));
    let script = src.join("server.py");
    if script.exists() {
        let venv = if cfg!(windows) { src.join(".venv/Scripts/python.exe") } else { src.join(".venv/bin/python3") };
        let mut c = if venv.exists() {
            Command::new(venv)
        } else if cfg!(windows) {
            Command::new("python")
        } else {
            Command::new("python3")
        };
        c.arg(script);
        return Ok(c);
    }
    Err("the engine is missing from the app bundle".into())
}

fn start_engine(app: &AppHandle) -> Result<(Child, u16, String), String> {
    let mut cmd = engine_command(app)?;
    let log = OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(data_dir().join("engine.log"))
        .map_err(|e| e.to_string())?;
    // Finder-launched apps get a bare PATH; add the usual engine folders so Stockfish / lc0 are found.
    let mut dirs = engine_dirs();
    if let Some(p) = std::env::var_os("PATH") {
        dirs.extend(std::env::split_paths(&p));
    }
    let path = std::env::join_paths(dirs).map_err(|e| e.to_string())?;
    // Windows: give the engine a console without a window, so neither it nor
    // the Stockfish it starts (which shares that console) flashes one up.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = cmd
        .arg("--parent-pipe")
        .env("PATH", path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::from(log))
        .spawn()
        .map_err(|e| format!("could not start the engine: {e}"))?;
    let stdout = child.stdout.take().ok_or("no stdout")?;
    let (tx, rx) = mpsc::channel::<String>();
    std::thread::spawn(move || {
        let mut first = true;
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if first {
                let _ = tx.send(line);
                first = false;
            } // keep draining so the pipe never fills
        }
    });
    let line = match rx.recv_timeout(Duration::from_secs(30)) {
        Ok(l) => l,
        Err(_) => {
            let _ = child.kill();
            return Err("the engine did not answer within 30 s".into());
        }
    };
    let parts: Vec<&str> = line.split_whitespace().collect();
    if parts.len() == 3 && parts[0] == "LISTENING" {
        if let Ok(port) = parts[1].parse::<u16>() {
            return Ok((child, port, parts[2].to_string()));
        }
    }
    let _ = child.kill();
    Err(format!("unexpected engine output: {line}"))
}

fn main() {
    let app = tauri::Builder::default()
        .manage(Engine(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            match start_engine(&handle) {
                Ok((child, port, token)) => {
                    *app.state::<Engine>().0.lock().unwrap() = Some(child);
                    let url = format!("http://127.0.0.1:{port}/#{token}");
                    WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url.parse().unwrap()))
                        .title("Chess Review")
                        .inner_size(1320.0, 900.0)
                        .min_inner_size(900.0, 620.0)
                        .build()?;
                }
                Err(e) => {
                    let q: String = e
                        .chars()
                        .map(|c| if c.is_ascii_alphanumeric() { c.to_string() } else { format!("%{:02X}", c as u32 & 0xFF) })
                        .collect();
                    WebviewWindowBuilder::new(app, "error", WebviewUrl::App(format!("index.html?err={q}").into()))
                        .title("Chess Review")
                        .inner_size(640.0, 420.0)
                        .build()?;
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the app");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = handle.state::<Engine>().0.lock().unwrap().take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}
