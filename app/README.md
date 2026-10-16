# Desktop app

Tauri 2 shell (Rust) + React/Vite UI, built from the Patient History Explorer
design. The Python engine (`engine/`) runs as a sidecar and does all extraction,
checking and history assembly; the UI only renders the bundle it returns
(`engine/src/medtimeline/bundle.py`).

What it does:

- Home: open the built-in demo patient (several conditions: diabetes,
  hypertension, epilepsy, recurrent UTI), reopen saved patients, or build a new
  one from a folder of PDF/DOC/DOCX/JPEG/PNG pages.
- Explorer: visits, symptoms, medications, symptoms + medications, episodes and
  correlation views; condition filter and lanes; every visit, episode, symptom,
  drug, test and change opens a detail panel with its source quote and check
  result; a needs-review list of anything that failed the source check; dark mode.

Not done yet: patient data is stored unencrypted under `~/.medtimeline`
(SQLCipher is planned); the engine is not yet frozen into a sidecar binary for
release builds; live extraction has not been run on real pages.

## Running it

From the repo root:

```sh
pip install -e "engine[cloud]"     # puts `medtimeline` on PATH
cd app && npm install
npm run tauri dev                  # desktop window
```

Browser-only development (no Rust needed):

```sh
medtimeline serve --http 8765      # engine over HTTP
cd app && npm run dev              # http://localhost:5173
```

Tests: `npm test` (vitest), `npm run build` (type-check + bundle),
`npm run e2e` (starts the engine and a preview server, drives Chromium through
the demo patient in light and dark mode, writes screenshots to `e2e/screens/`).

The API key typed on the new-patient form is passed to the engine for that build
only and is never written to disk. `ANTHROPIC_API_KEY` in the environment also works.

## Desktop shell

The Tauri 2 shell lives in `src-tauri/` (Rust). It hosts the Vite/React UI and
runs the Python engine as a long-lived sidecar.

- Dev: `npm run tauri dev` from `app/` (runs `npm run dev`, loads
  `http://localhost:5173`). Linux needs `libwebkit2gtk-4.1-dev libgtk-3-dev
  libayatana-appindicator3-dev librsvg2-dev`.
- Release: `npm run tauri build -- --config src-tauri/tauri.bundle.conf.json`
  after placing the frozen engine at
  `src-tauri/binaries/medtimeline-engine-<target-triple>`. That extra config adds
  `bundle.externalBin`; it is kept out of `tauri.conf.json` because tauri-build
  refuses to compile when a declared sidecar file is missing.
- Rust unit tests (no window): `cd src-tauri && cargo test --lib`.

**Engine discovery** (first match wins): `medtimeline-engine` next to the app
executable (the bundled sidecar), then `$MEDTIMELINE_ENGINE` (split on whitespace,
so `python -m medtimeline` works), then `medtimeline` on `PATH`. It is launched as
`<engine> serve` with the parent environment (incl. `ANTHROPIC_API_KEY`), stdin and
stdout piped, stderr inherited. It starts on the first call, restarts on the next
call after a crash, and is killed when the app exits.

**Wire protocol** (one JSON object per line):

| Direction | Shape |
| --- | --- |
| shell → engine | `{"id": <u64>, "method": "<string>", "params": {…}}` |
| engine → shell | `{"id": <u64>, "result": <json>}` or `{"id": <u64>, "error": "<message>"}` |
| engine → shell (event) | `{"event": "<name>", "data": <json>}` |

**Frontend API:**

```ts
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";

const folder = await open({ directory: true });
const result = await invoke("engine_call", {
  method: "projects.create",
  params: { name: "A. Patient", folder, extractor: "claude" },
});
// rejects with the engine's error string (or "engine process exited")
const unlisten = await listen<{ event: string; data: unknown }>("engine-event", (e) => {
  console.log(e.payload.event, e.payload.data);
});
```

Calls run on a blocking worker thread, so a slow call such as `projects.create` does not
freeze the UI. Several calls can be in flight at once; they are matched by `id`.
Engine lines that are not valid JSON are logged to stderr and ignored.

**Engine methods:** `info`, `demo`, `projects.list`, `projects.open`
(`project_id`), `projects.create` (`name`, `folder`, `extractor`, `api_key?`),
`projects.rebuild` (`project_id`). Builds emit `progress` events.
