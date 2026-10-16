# Patient History Timeline: v1 plan

**Status:** proposal, 2026-10-16. Nothing built yet; no repository exists.

## What we're building

A desktop app where a clinician (or patient) drops in a pile of prescriptions and case sheets (PDF, DOC/DOCX, JPEG/PNG), and gets back a chronological, browsable patient history: encounters, diagnoses, medications, investigations and vitals, each linked back to the exact page it came from.

Fixed by the user's answers:
- Desktop app.
- Inputs are roughly 50% handwritten, 50% typed.
- Cloud AI is fine for v1. The end goal is fully offline, so the AI/OCR layer must be swappable.

## Recommended stack

| Layer | Choice | Why |
|---|---|---|
| App shell | **Tauri 2** (Rust) | Small installers (~10 MB vs ~150 MB for Electron), native on Windows/macOS/Linux, can launch and supervise a bundled sidecar process. |
| UI | **React + TypeScript** (Vite), a timeline component built on plain SVG/CSS | The UI is mostly lists, a document viewer, and a timeline; nothing exotic. |
| Processing engine | **Python 3.12 sidecar**, packaged with PyInstaller, talking to the UI over local HTTP (FastAPI on 127.0.0.1, random port + token) | Every useful document, OCR and local-model library is Python-first. Keeping it in one process makes the cloud-to-local swap a config change, not a rewrite. |
| Storage | **SQLite** (encrypted with SQLCipher) + a local folder of original files | Single-file, offline, easy backup. Patient data is encrypted at rest from day one. |
| v1 extraction | **Claude vision API** with a JSON-schema structured output | Handles handwriting far better than classic OCR; one call per page returns structured fields directly. |
| Offline extraction (later) | **Local vision-language model** via llama.cpp/Ollama (e.g. Qwen2.5-VL 7B class, or whatever leads at that time) + **PaddleOCR/docTR** for typed text | Same input/output contract as the cloud extractor. |

Alternative considered: Electron (heavier, but more familiar to many devs) or a pure-Python UI (PySide6). Tauri + Python sidecar is the best balance of install size and access to the ML ecosystem.

## Architecture

```
┌────────────── Desktop app (Tauri + React) ──────────────┐
│  Import  →  Review queue  →  Timeline / History tree    │
└───────────────┬─────────────────────────────────────────┘
                │ localhost API
┌───────────────▼──── Python engine ──────────────────────┐
│ 1. Ingest      file → pages (image + optional text)     │
│ 2. Classify    page: typed / handwritten / mixed, doc type│
│ 3. Extract     ── Extractor interface (swappable) ──    │
│                 ├ CloudExtractor (Claude vision)         │
│                 ├ LocalVLMExtractor (llama.cpp/Ollama)   │
│                 └ HybridExtractor (local OCR + local LLM)│
│ 4. Normalize   dates, drug names, units, patient match  │
│ 5. Assemble    encounters → timeline, dedupe            │
└───────────────┬─────────────────────────────────────────┘
                │
        SQLite (SQLCipher) + original files
```

### 1. Ingest
- **PDF:** PyMuPDF. If a page has a real text layer, keep the text *and* render the page image (layout still matters). Scanned PDFs are just images.
- **DOCX:** python-docx for text and tables; render to PDF/image via LibreOffice headless only if layout is needed.
- **DOC (legacy):** convert to DOCX with LibreOffice headless (bundled or detected). This is the one awkward dependency; acceptable for v1.
- **JPEG/PNG:** OpenCV preprocessing: EXIF rotation, deskew, crop to page, contrast normalize, downscale to ~2000 px long edge.
- Every page gets a stable ID and a content hash so re-imports are detected.

### 2. Classify
Cheap first pass per page: document type (prescription, case sheet, lab report, discharge summary, other) and script type (typed/handwritten/mixed). In v1 the cloud model does this inside the same call. In the offline path it decides routing: typed pages go to fast OCR, handwritten pages go to the VLM.

### 3. Extract: the swappable contract
The single most important design decision. Every extractor implements:

```python
class Extractor(Protocol):
    name: str
    def extract(self, page: PageInput) -> PageExtraction: ...
```

`PageInput` = page image + optional text layer + doc-type hint.
`PageExtraction` = the schema below, where **every field carries `value`, `confidence` (0–1), and `source` (page ID + bounding box or quoted text span)**.

Core schema (per page, merged per encounter later):
- `encounter`: date (raw string + parsed ISO date + certainty), facility, clinician, department, encounter type (OPD, admission, follow-up)
- `patient`: name, age/DOB, sex, IDs (hospital number, phone)
- `complaints`, `history`, `examination` (free text)
- `vitals`: BP, pulse, temp, SpO2, weight, etc. with units
- `diagnoses`: text + optional ICD-10 code (code is a suggestion, never authoritative)
- `medications`: drug (as written + normalized generic), strength, form, dose, frequency (e.g. 1-0-1, BD, TDS), duration, route, instructions
- `investigations`: test name, ordered vs resulted, value, unit, reference range
- `procedures`, `advice`, `follow_up_date`

Extractor choice lives in settings and is recorded on every extraction row, so results from different extractors can be compared side by side.

### 4. Normalize
- **Dates:** default to DD/MM/YYYY (setting), keep the raw string, flag ambiguous dates (e.g. 03/04) and undated pages. Undated pages are placed using file metadata or neighbouring pages, shown with a "date inferred" badge.
- **Drugs:** map brand names to generics with a local drug dictionary (start with a CSV; later RxNorm or a regional brand list). Expand frequency shorthand (BD, TDS, 1-0-1, SOS, HS).
- **Patient matching:** documents are imported into a chosen patient profile in v1 (no automatic cross-patient matching). A warning appears when an extracted name/ID conflicts with the profile.

### 5. Assemble the timeline / history tree
- Encounters are the backbone: each encounter has a date and the pages that belong to it. Pages with the same date + facility merge into one encounter.
- **Tree view:** Patient → Year → Encounter → (Diagnoses, Medications, Investigations, Vitals, Notes).
- **Timeline view:** horizontal chronology with lanes: encounters, medication courses (start/stop bars, so you can see when a drug was started, changed or stopped), conditions (first seen → last seen), and lab trends (sparklines for repeated tests).
- Every item is clickable back to its source page with the region highlighted.

## Human review is part of the product
With 50% handwriting, no model will be right every time, and this is medical data. So:
- Fields below a confidence threshold, ambiguous dates and unrecognized drugs land in a **review queue**.
- Review screen: source image on the left, extracted fields on the right, one keystroke to accept, edit or reject.
- Edits are stored as corrections (original value kept), which also become evaluation data.
- The timeline marks unreviewed items visually. The app is a record-organizing aid, not a clinical decision tool, and says so.

## Privacy and security (v1, cloud mode)
- Explicit opt-in screen before any page leaves the device, naming the provider.
- Use the API under a zero-data-retention / no-training arrangement; store the API key in the OS keychain, never in the database.
- Only page images and the minimum prompt go to the cloud; the database never leaves the machine.
- Encrypted SQLite and an app-level passphrase from day one, so the offline version inherits nothing insecure.
- Audit log of which pages were sent to which extractor and when.

## Path to fully offline

Gate each step on the **evaluation harness**, not on intuition.

**Evaluation harness (build first, in phase 0):** a gold set of ~50–100 real (de-identified or consented) pages, half handwritten, with hand-labelled expected output. A script scores any extractor on field-level accuracy: date, drug name, dose, frequency, diagnosis, lab value. Reviewer corrections from the app feed this set over time.

| Phase | Extraction | Goal |
|---|---|---|
| **0. Spike** | Python script only, Claude vision | Gold set, schema, eval script; prove extraction quality on real samples. |
| **1. MVP (cloud)** | CloudExtractor | Full desktop app: import, review queue, tree + timeline, encrypted storage. |
| **2. Hybrid** | Typed pages → local OCR (PaddleOCR/docTR) + local text LLM; handwritten → cloud | Cuts cloud use roughly in half; proves the local pipeline on the easier half. |
| **3. Offline** | LocalVLMExtractor for everything | Switch default to local once eval scores are within an agreed margin of cloud (e.g. ≤5 points on drug/dose/date). Cloud becomes optional or removed. |
| **4. Polish** | Any | Export (PDF summary, FHIR bundle), multi-patient matching, drug interaction hints. |

Offline practicalities:
- **Hardware:** a 7B-class vision model in 4-bit needs ~6–8 GB of GPU VRAM or an Apple Silicon Mac with 16 GB+. CPU-only works but is slow (tens of seconds to minutes per page); acceptable for batch import overnight, poor for interactive use.
- **Model delivery:** models are a separate download (several GB) managed by the app, not bundled in the installer.
- **Handwriting is the hard part.** If local VLMs lag on handwriting, a fine-tune (LoRA) on the corrections collected in phases 1–2 is the planned lever. This is why storing corrections from day one matters.

## Repository layout (when we create it)
```
app/            Tauri + React UI
engine/         Python package
  ingest/       pdf, docx, doc, image
  extract/      base.py (Extractor), cloud_claude.py, local_vlm.py, hybrid.py
  normalize/    dates, drugs, units
  timeline/     encounter merge, tree/timeline assembly
  storage/      SQLCipher models, migrations
eval/           gold set manifest (no PHI in git), scorer
docs/
```

## Defaults I picked (say if any are wrong)
- **Target OS:** Windows and macOS first, Linux builds as a bonus.
- **Language:** English documents, including Indian-style prescription conventions (DD/MM dates, 1-0-1 dosing, brand names). Other scripts later.
- **One patient at a time:** user picks the patient, then imports their documents.
- **Who uses it:** a single user on their own machine; no accounts or sync in v1.

## Next steps
1. Gather 20–50 sample pages (mix of handwritten and typed) to seed the gold set.
2. Create the repository and run the phase 0 spike: schema + CloudExtractor + eval script.
3. Scaffold the Tauri app and wire import → extract → review → timeline.
