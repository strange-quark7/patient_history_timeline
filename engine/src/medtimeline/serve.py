"""The service the desktop app talks to.

Default transport is JSON lines on stdin/stdout (the Tauri shell runs this as a
child process). `--http PORT` serves the same methods on localhost for browser
development and UI tests.

    request  {"id": 1, "method": "projects.open", "params": {"project_id": "..."}}
    response {"id": 1, "result": {...}}  or  {"id": 1, "error": "message"}
    event    {"event": "progress", "data": {...}}   (no id; sent while a build runs)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from importlib import resources
from typing import Callable, Optional

from medtimeline.bundle import make_bundle, update_notes
from medtimeline.extract import available_extractors, get_extractor
from medtimeline.ingest import load_folder
from medtimeline.pipeline import extract_folder
from medtimeline.schema import ExtractionRecord
from medtimeline.store import Store

Emit = Callable[[str, dict], None]
DEMO_NAME = "Meera Nair"


def demo_records() -> list[ExtractionRecord]:
    data = json.loads(resources.files("medtimeline.demo").joinpath("records.json").read_text())
    return [ExtractionRecord.model_validate(r) for r in data]


class Service:
    def __init__(self, home: Optional[str] = None, emit: Emit = lambda e, d: None):
        self.store = Store(home)
        self.emit = emit
        self.demo_resolutions: dict[str, dict] = {}  # the demo is not saved; its choices last for this session

    def info(self) -> dict:
        return {"extractors": available_extractors(), "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY"))}

    def demo(self) -> dict:
        return {"project": {"id": "demo", "name": DEMO_NAME + " (made-up demo patient)"},
                "bundle": make_bundle(demo_records(), resolutions=self.demo_resolutions, patient_name=DEMO_NAME)}

    def projects_list(self) -> list[dict]:
        return self.store.list()

    def projects_open(self, project_id: str) -> dict:
        return {"project": {"id": project_id, **self.store.meta(project_id)}, "bundle": self._bundle(project_id)}

    def _bundle(self, project_id: str, only: Optional[set[str]] = None) -> dict:
        records = [r for r in self.store.records(project_id) if only is None or r.page_id in only]
        return make_bundle(records, resolutions=self.store.resolutions(project_id), patient_name=self.store.meta(project_id)["name"])

    def review_resolve(self, project_id: str, key: str, choice: Optional[str] = None, clear: bool = False) -> dict:
        """Pick a label for a review item (choice), leave it unsure (choice None), or undo (clear). Returns the new bundle."""
        if project_id == "demo":
            if clear:
                self.demo_resolutions.pop(key, None)
            else:
                self.demo_resolutions[key] = {"choice": choice}
            return self.demo()
        self.store.resolve(project_id, key, choice, clear)
        return self.projects_open(project_id)

    def projects_create(self, name: str, folder: str, extractor: str = "claude", api_key: Optional[str] = None,
                        model: Optional[str] = None) -> dict:
        if not load_folder(folder):
            raise ValueError("No PDF, Word or image files found in that folder.")
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key  # this process only; never written to disk
        kwargs = {"model": model} if (extractor == "claude" and model) else {}
        ex = get_extractor(extractor, **kwargs)
        project_id = self.store.create(name, folder, extractor)
        return self._build(project_id, ex)

    def projects_add(self, project_id: str, folder: str, api_key: Optional[str] = None) -> dict:
        """Add pages from another folder, e.g. older reports found later. They slot into the history by date."""
        if not load_folder(folder):
            raise ValueError("No PDF, Word or image files found in that folder.")
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key  # this process only; never written to disk
        meta = self.store.meta(project_id)
        folders = self._folders(meta)
        if folder not in folders:
            self.store.touch(project_id, source_folders=folders + [folder])
        return self._build(project_id, get_extractor(meta["extractor"]))

    def projects_rebuild(self, project_id: str) -> dict:
        """Read the source folders again; pages already read are reused, new files are read and added."""
        return self._build(project_id, get_extractor(self.store.meta(project_id)["extractor"]))

    @staticmethod
    def _folders(meta: dict) -> list[str]:
        return meta.get("source_folders") or [meta["source_folder"]]

    def _build(self, project_id: str, ex) -> dict:
        meta = self.store.meta(project_id)
        before_ids = {r.page_id for r in self.store.records(project_id)}
        batch = meta.get("batches", 0)
        records, failures = [], []
        for folder in self._folders(meta):
            got, failed = extract_folder(folder, ex, self.store.records_dir(project_id),
                                         lambda p: self.emit("progress", {"project_id": project_id, **p}),
                                         batch=batch)
            records += got
            failures += failed
        new_ids = {r.page_id for r in records} - before_ids
        update = meta.get("last_update")
        if before_ids and new_ids:
            notes = update_notes(self._bundle(project_id, before_ids), self._bundle(project_id), new_ids)
            update = {"at": time.time(), "batch": batch, "pages_added": len(new_ids), "notes": notes}
        self.store.touch(project_id, pages=len(records), failures=failures, batches=batch + (1 if new_ids else 0),
                         last_update=update)
        return {**self.projects_open(project_id), "failures": failures}

    METHODS = {
        "info": "info", "demo": "demo", "projects.list": "projects_list", "projects.open": "projects_open",
        "projects.create": "projects_create", "projects.rebuild": "projects_rebuild", "review.resolve": "review_resolve", "projects.add": "projects_add",
    }

    def call(self, method: str, params: Optional[dict]) -> object:
        name = self.METHODS.get(method)
        if not name:
            raise ValueError(f"Unknown method {method!r}")
        return getattr(self, name)(**(params or {}))


def _respond(write: Callable[[dict], None], service: Service, req: dict) -> None:
    try:
        write({"id": req.get("id"), "result": service.call(req.get("method", ""), req.get("params"))})
    except Exception as e:  # report every failure to the caller instead of dying
        traceback.print_exc(file=sys.stderr)
        write({"id": req.get("id"), "error": str(e) or e.__class__.__name__})


def serve_stdio(home: Optional[str]) -> int:
    lock = threading.Lock()

    def write(obj: dict) -> None:
        with lock:
            sys.stdout.write(json.dumps(obj, default=str) + "\n")
            sys.stdout.flush()

    service = Service(home, emit=lambda e, d: write({"event": e, "data": d}))
    running: list[threading.Thread] = []
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            write({"id": None, "error": f"Bad request: {e}"})
            continue
        # Builds can take minutes; run each request on its own thread so quick calls still answer.
        t = threading.Thread(target=_respond, args=(write, service, req), daemon=True)
        t.start()
        running.append(t)
    for t in running:  # stdin closed: answer what is still in flight before exiting
        t.join()
    return 0


def serve_http(port: int, home: Optional[str]) -> int:
    """POST /rpc with a request body; GET /events streams progress as server-sent events."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import queue

    listeners: list[queue.Queue] = []

    def emit(event: str, data: dict) -> None:
        for q in list(listeners):
            q.put({"event": event, "data": data})

    service = Service(home, emit=emit)

    class Handler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "http://localhost:5173")
            self.send_header("Access-Control-Allow-Headers", "content-type")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
            out: dict = {}
            _respond(out.update, service, body)
            data = json.dumps(out, default=str).encode()
            self.send_response(200)
            self._cors()
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/events":
                self.send_response(404)
                self.end_headers()
                return
            q: queue.Queue = queue.Queue()
            listeners.append(q)
            self.send_response(200)
            self._cors()
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            try:
                while True:
                    self.wfile.write(f"data: {json.dumps(q.get(), default=str)}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                listeners.remove(q)

        def log_message(self, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"medtimeline serving on http://127.0.0.1:{port}", file=sys.stderr)
    server.serve_forever()
    return 0


def main(http: Optional[int] = None, home: Optional[str] = None) -> int:
    return serve_http(http, home) if http else serve_stdio(home)
