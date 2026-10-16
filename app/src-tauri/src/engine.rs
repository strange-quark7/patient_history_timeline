//! Lifecycle of the engine child process: lazy start, request/response
//! correlation, event forwarding, restart after a crash, kill on exit.

use crate::protocol::{encode_request, parse_line, Pending};
use serde_json::Value;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;

/// Env var naming the engine executable (or a command such as `python -m medtimeline`).
pub const ENGINE_ENV: &str = "MEDTIMELINE_ENGINE";
/// Default engine executable looked up on PATH.
pub const ENGINE_DEFAULT: &str = "medtimeline";
/// Tauri sidecar name (bundle.externalBin `binaries/medtimeline-engine`). Tauri
/// installs it next to the app executable with the target triple stripped.
pub const SIDECAR_NAME: &str = "medtimeline-engine";

/// Resolve the engine command line (program + leading args, without `serve`).
/// Order: bundled sidecar next to the current executable, then `$MEDTIMELINE_ENGINE`
/// (split on whitespace), then `medtimeline` from PATH.
pub fn resolve_engine_command() -> Vec<String> {
    if let Some(sidecar) = sidecar_path() {
        return vec![sidecar.to_string_lossy().into_owned()];
    }
    if let Ok(cmd) = std::env::var(ENGINE_ENV) {
        let parts: Vec<String> = cmd.split_whitespace().map(str::to_owned).collect();
        if !parts.is_empty() {
            return parts;
        }
    }
    vec![ENGINE_DEFAULT.to_string()]
}

fn sidecar_path() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let candidate = exe
        .parent()?
        .join(format!("{SIDECAR_NAME}{}", std::env::consts::EXE_SUFFIX));
    candidate.is_file().then_some(candidate)
}

struct EngineProcess {
    child: Child,
    stdin: ChildStdin,
    pending: Arc<Pending>,
}

impl EngineProcess {
    fn spawn<F>(command: &[String], on_event: F) -> Result<Self, String>
    where
        F: Fn(Value) + Send + 'static,
    {
        let (program, args) = command
            .split_first()
            .ok_or_else(|| "empty engine command".to_string())?;
        // The parent environment (including ANTHROPIC_API_KEY) is inherited by default.
        let mut cmd = Command::new(program);
        cmd.args(args)
            .arg("serve")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        #[cfg(windows)]
        {
            // Keep the engine from opening a console window next to the app.
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = cmd
            .spawn()
            .map_err(|e| {
                format!(
                    "could not start engine `{}`: {e} (set {ENGINE_ENV} or put `{ENGINE_DEFAULT}` on PATH)",
                    command.join(" ")
                )
            })?;
        let stdin = child.stdin.take().ok_or("engine stdin unavailable")?;
        let stdout = child.stdout.take().ok_or("engine stdout unavailable")?;
        let pending = Arc::new(Pending::default());

        let reader_pending = Arc::clone(&pending);
        thread::Builder::new()
            .name("engine-reader".into())
            .spawn(move || {
                for line in BufReader::new(stdout).lines() {
                    let Ok(line) = line else { break };
                    if line.trim().is_empty() {
                        continue;
                    }
                    match parse_line(&line) {
                        Ok(incoming) => {
                            if let Some(event) = reader_pending.dispatch(incoming) {
                                on_event(event);
                            }
                        }
                        Err(e) => eprintln!("[engine] {e}"),
                    }
                }
                reader_pending.close("engine process exited");
            })
            .map_err(|e| format!("could not start engine reader thread: {e}"))?;

        Ok(Self { child, stdin, pending })
    }

    /// Its output can end a moment before the OS reports the exit, so a closed
    /// output also counts as dead; otherwise the next call would hit the old one.
    fn is_alive(&mut self) -> bool {
        !self.pending.is_closed() && matches!(self.child.try_wait(), Ok(None))
    }

    fn kill(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        self.pending.close("engine stopped");
    }
}

impl Drop for EngineProcess {
    fn drop(&mut self) {
        self.kill();
    }
}

/// Managed Tauri state holding the (lazily started) engine.
pub struct EngineState {
    process: Mutex<Option<EngineProcess>>,
    next_id: AtomicU64,
    /// Fixed command for tests; `None` means resolve at spawn time.
    command: Option<Vec<String>>,
}

impl Default for EngineState {
    fn default() -> Self {
        Self { process: Mutex::new(None), next_id: AtomicU64::new(1), command: None }
    }
}

impl EngineState {
    /// State that always launches `command` (plus `serve`). Used by tests.
    pub fn with_command(command: Vec<String>) -> Self {
        Self { command: Some(command), ..Self::default() }
    }

    /// Send one request and block until its response arrives (or the engine dies).
    /// `on_event` is used only if this call has to (re)start the engine.
    pub fn call<F>(&self, method: &str, params: Value, on_event: F) -> Result<Value, String>
    where
        F: Fn(Value) + Send + 'static,
    {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let rx = {
            let mut guard = self.process.lock().map_err(|_| "engine state poisoned")?;
            if !guard.as_mut().map_or(false, EngineProcess::is_alive) {
                // Drop (and reap) any dead process before starting a new one.
                *guard = None;
                let command = self.command.clone().unwrap_or_else(resolve_engine_command);
                *guard = Some(EngineProcess::spawn(&command, on_event)?);
            }
            let proc = guard.as_mut().expect("engine just ensured");
            let rx = proc.pending.register(id);
            let line = encode_request(id, method, params);
            if let Err(e) = proc.stdin.write_all(line.as_bytes()).and_then(|_| proc.stdin.flush()) {
                proc.pending.forget(id);
                *guard = None; // kill it; next call restarts
                return Err(format!("could not write to engine: {e}"));
            }
            rx
        }; // lock released: other calls proceed while we wait
        rx.recv()
            .unwrap_or_else(|_| Err("engine process exited".to_string()))
    }

    /// Kill the engine if running (called on app exit).
    pub fn shutdown(&self) {
        if let Ok(mut guard) = self.process.lock() {
            *guard = None;
        }
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use serde_json::json;
    use std::sync::mpsc::channel;
    use std::time::Duration;

    /// A tiny fake engine: emits an event, echoes params, errors on "fail",
    /// exits on "die".
    const FAKE: &str = r#"
import json, sys
assert sys.argv[1] == "serve"
for line in sys.stdin:
    req = json.loads(line)
    if req["method"] == "die":
        sys.exit(1)
    print(json.dumps({"event": "progress", "data": {"id": req["id"]}}), flush=True)
    if req["method"] == "fail":
        print(json.dumps({"id": req["id"], "error": "bad request"}), flush=True)
    else:
        print(json.dumps({"id": req["id"], "result": req["params"]}), flush=True)
"#;

    fn fake_engine() -> Option<EngineState> {
        Command::new("python3").arg("--version").output().ok()?;
        Some(EngineState::with_command(vec!["python3".into(), "-c".into(), FAKE.into()]))
    }

    #[test]
    fn round_trip_events_errors_and_restart() {
        let Some(engine) = fake_engine() else {
            eprintln!("python3 not available; skipping");
            return;
        };
        let (tx, rx) = channel();
        let r = engine.call("echo", json!({"a": 1}), move |e| tx.send(e).unwrap());
        assert_eq!(r, Ok(json!({"a": 1})));
        let ev = rx.recv_timeout(Duration::from_secs(5)).unwrap();
        assert_eq!(ev["event"], "progress");

        assert_eq!(engine.call("fail", json!({}), |_| {}), Err("bad request".into()));
        assert!(engine.call("die", json!({}), |_| {}).is_err());
        // Next call transparently restarts the engine.
        assert_eq!(engine.call("echo", json!({"b": 2}), |_| {}), Ok(json!({"b": 2})));
        engine.shutdown();
    }
}
