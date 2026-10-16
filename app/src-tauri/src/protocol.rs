//! JSON-lines protocol between the shell and the engine, independent of Tauri
//! so it can be unit-tested without a window.

use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Mutex;

/// Outcome delivered to a waiting caller.
pub type CallResult = Result<Value, String>;

/// A parsed line from the engine's stdout.
#[derive(Debug, PartialEq)]
pub enum Incoming {
    /// `{"id": n, "result": ...}` or `{"id": n, "error": "..."}`.
    Response { id: u64, result: CallResult },
    /// `{"event": "<name>", "data": ...}` (no id). Holds the whole object.
    Event(Value),
}

/// Serialise a request as one line (including the trailing newline).
pub fn encode_request(id: u64, method: &str, params: Value) -> String {
    // The contract says params is an object; normalise null/missing to {}.
    let params = match params {
        Value::Null => Value::Object(Map::new()),
        other => other,
    };
    let mut line = json!({ "id": id, "method": method, "params": params }).to_string();
    line.push('\n');
    line
}

/// Parse one stdout line. Returns `Err` for blank, non-JSON or unrecognised lines.
pub fn parse_line(line: &str) -> Result<Incoming, String> {
    let line = line.trim();
    if line.is_empty() {
        return Err("empty line".into());
    }
    let value: Value =
        serde_json::from_str(line).map_err(|e| format!("invalid JSON from engine: {e}"))?;
    let obj = value
        .as_object()
        .ok_or_else(|| "engine line is not a JSON object".to_string())?;

    if let Some(id) = obj.get("id").and_then(Value::as_u64) {
        let result = match obj.get("error") {
            Some(err) if !err.is_null() => Err(match err {
                Value::String(s) => s.clone(),
                other => other.to_string(),
            }),
            _ => Ok(obj.get("result").cloned().unwrap_or(Value::Null)),
        };
        return Ok(Incoming::Response { id, result });
    }
    if obj.get("event").map_or(false, Value::is_string) {
        return Ok(Incoming::Event(value));
    }
    Err(format!("unrecognised engine line: {line}"))
}

/// Callers waiting for a response, keyed by request id.
#[derive(Default)]
pub struct Pending {
    waiters: Mutex<HashMap<u64, Sender<CallResult>>>,
    closed: Mutex<Option<String>>,
}

impl Pending {
    /// Register interest in `id` before the request is written.
    /// If the engine has already gone away, the receiver yields that error at once.
    pub fn register(&self, id: u64) -> Receiver<CallResult> {
        let (tx, rx) = channel();
        if let Some(reason) = self.closed.lock().unwrap().clone() {
            let _ = tx.send(Err(reason));
        } else {
            self.waiters.lock().unwrap().insert(id, tx);
        }
        rx
    }

    /// Drop a waiter (e.g. the write failed).
    pub fn forget(&self, id: u64) {
        self.waiters.lock().unwrap().remove(&id);
    }

    /// Route a parsed line: responses go to their waiter; events are returned
    /// so the caller can emit them. Responses for unknown ids are dropped.
    pub fn dispatch(&self, incoming: Incoming) -> Option<Value> {
        match incoming {
            Incoming::Response { id, result } => {
                if let Some(tx) = self.waiters.lock().unwrap().remove(&id) {
                    let _ = tx.send(result);
                }
                None
            }
            Incoming::Event(v) => Some(v),
        }
    }

    /// Fail every pending caller and refuse new ones (engine exited).
    pub fn close(&self, reason: &str) {
        *self.closed.lock().unwrap() = Some(reason.to_string());
        for (_, tx) in self.waiters.lock().unwrap().drain() {
            let _ = tx.send(Err(reason.to_string()));
        }
    }

    pub fn len(&self) -> usize {
        self.waiters.lock().unwrap().len()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encodes_request_line() {
        let line = encode_request(7, "build", json!({"folder": "/x"}));
        assert!(line.ends_with('\n'));
        let v: Value = serde_json::from_str(line.trim()).unwrap();
        assert_eq!(v, json!({"id": 7, "method": "build", "params": {"folder": "/x"}}));
        let v: Value = serde_json::from_str(encode_request(1, "ping", Value::Null).trim()).unwrap();
        assert_eq!(v["params"], json!({}));
    }

    #[test]
    fn parses_result_and_error_responses() {
        assert_eq!(
            parse_line(r#"{"id": 3, "result": {"ok": true}}"#).unwrap(),
            Incoming::Response { id: 3, result: Ok(json!({"ok": true})) }
        );
        assert_eq!(
            parse_line("{\"id\": 4, \"error\": \"no such folder\"}\n").unwrap(),
            Incoming::Response { id: 4, result: Err("no such folder".into()) }
        );
        assert_eq!(
            parse_line(r#"{"id": 5, "result": null}"#).unwrap(),
            Incoming::Response { id: 5, result: Ok(Value::Null) }
        );
    }

    #[test]
    fn parses_event_line() {
        let line = r#"{"event": "progress", "data": {"done": 2, "total": 9}}"#;
        match parse_line(line).unwrap() {
            Incoming::Event(v) => {
                assert_eq!(v["event"], "progress");
                assert_eq!(v["data"]["total"], 9);
            }
            other => panic!("expected event, got {other:?}"),
        }
    }

    #[test]
    fn rejects_garbage() {
        assert!(parse_line("").is_err());
        assert!(parse_line("Traceback (most recent call last):").is_err());
        assert!(parse_line("[1,2]").is_err());
        assert!(parse_line(r#"{"hello": 1}"#).is_err());
    }

    #[test]
    fn routes_responses_by_id_and_returns_events() {
        let pending = Pending::default();
        let rx1 = pending.register(1);
        let rx2 = pending.register(2);
        assert_eq!(pending.len(), 2);

        // Out-of-order responses reach the right caller.
        assert!(pending.dispatch(parse_line(r#"{"id": 2, "result": "two"}"#).unwrap()).is_none());
        assert!(pending.dispatch(parse_line(r#"{"id": 1, "error": "boom"}"#).unwrap()).is_none());
        assert_eq!(rx2.recv().unwrap(), Ok(json!("two")));
        assert_eq!(rx1.recv().unwrap(), Err("boom".to_string()));
        assert!(pending.is_empty());

        // Unknown ids are ignored; events are handed back for emitting.
        assert!(pending.dispatch(parse_line(r#"{"id": 99, "result": 1}"#).unwrap()).is_none());
        let ev = pending
            .dispatch(parse_line(r#"{"event": "log", "data": "hi"}"#).unwrap())
            .unwrap();
        assert_eq!(ev, json!({"event": "log", "data": "hi"}));
    }

    #[test]
    fn close_fails_pending_and_future_callers() {
        let pending = Pending::default();
        let rx = pending.register(1);
        pending.close("engine exited");
        assert_eq!(rx.recv().unwrap(), Err("engine exited".to_string()));
        let late = pending.register(2);
        assert_eq!(late.recv().unwrap(), Err("engine exited".to_string()));
    }
}
