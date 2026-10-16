//! Tauri shell for Patient History Timeline.
//!
//! The Python engine runs as a long-lived child process (`<engine> serve`)
//! speaking JSON lines over stdin/stdout:
//!
//! * request  (shell -> engine): `{"id": <u64>, "method": "<string>", "params": {...}}`
//! * response (engine -> shell): `{"id": <u64>, "result": <json>}` or `{"id": <u64>, "error": "<message>"}`
//! * event    (engine -> shell): `{"event": "<name>", "data": <json>}`, forwarded to the
//!   frontend as the Tauri event `engine-event` with the whole object as payload.
//!
//! The frontend talks to it through the single command
//! `engine_call(method, params) -> Result<Value, String>`.

pub mod engine;
pub mod protocol;

use engine::EngineState;
use tauri::{Emitter, Manager, RunEvent};

/// Name of the Tauri event that carries engine event lines to the frontend.
pub const ENGINE_EVENT: &str = "engine-event";

#[tauri::command]
async fn engine_call(
    app: tauri::AppHandle,
    method: String,
    params: serde_json::Value,
) -> Result<serde_json::Value, String> {
    // Everything here (spawning, writing, waiting minutes for `build`) blocks,
    // so keep it off the main thread and off the async executor.
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<EngineState>();
        let emitter = app.clone();
        state.call(&method, params, move |event| {
            let _ = emitter.emit(ENGINE_EVENT, event);
        })
    })
    .await
    .map_err(|e| format!("engine call task failed: {e}"))?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(EngineState::default())
        .invoke_handler(tauri::generate_handler![engine_call])
        .build(tauri::generate_context!())
        .expect("error while building Patient History Timeline");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<EngineState>().shutdown();
        }
    });
}
