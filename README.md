# patient_history_timeline

Patient History Collation and Visualisation Tool.

Desktop tool that turns prescriptions and case sheets (PDF, DOC/DOCX, JPEG/PNG;
typed or handwritten) into a chronological patient history.

Status: **phase 0 spike**. The Python engine works end to end from the command
line; the desktop app is not started. See [docs/v1-plan.md](docs/v1-plan.md).

## Layout

```
engine/   Python engine: ingest -> extract -> normalize -> assemble history
  src/medtimeline/
    ingest.py        PDF, DOC/DOCX, images -> page images + text layers
    schema.py        the structured record every extractor returns
    extract/         swappable extractors (claude = cloud; fixture = offline stand-in)
    normalize.py     DD/MM dates, 1-0-1 / BD frequencies, durations, drug keys
    timeline.py      encounters, medication courses, conditions, symptoms, episodes, lab series
    views.py         lenses (visits, symptoms, medications, both, conditions, labs) and sort orders
    evaluate.py      field-level scoring against hand-labelled gold pages
app/      desktop app (Tauri + React), not started
docs/     plan and design notes
```

## Quick start

```bash
cd engine
pip install -e ".[cloud,dev]"
pytest

export ANTHROPIC_API_KEY=...
medtimeline build path/to/patient-docs --out patient.history.json --cache cache/
```

`--cache` stores each page's extraction so re-runs don't pay for extraction again.

## Sorting and slicing the timeline

```bash
medtimeline view patient.history.json --lens symptoms_medications --sort episodes
```

Lenses: `visits`, `symptoms`, `medications`, `symptoms_medications`, `conditions`, `labs`.
Sorts: `chronological`, `recent`, `episodes`, `visits`, `duration`, `name`.
Filters: `--query <text>`, `--from YYYY-MM-DD`, `--to YYYY-MM-DD`.

Each doctor visit where a symptom, condition or drug appears counts as one
episode of it. In `symptoms_medications`, each row
lists the items of the other kind seen at the same visits.

## Scoring an extractor

Put sample documents in `eval/docs/` and hand-checked extractions in
`eval/gold/` as `<file stem>.p<page>.json` (same shape as `schema.PageExtraction`).
Both folders are git-ignored so patient data never lands in the repo.

```bash
medtimeline eval eval/docs eval/gold --extractor claude
```

A local extractor replaces the cloud one only once its scores are close enough.

## Adding an extractor (e.g. a local model)

Implement `extract(page: PageInput) -> PageExtraction`, decorate the class with
`@register("name")`, and select it with `--extractor name`. Nothing downstream changes.

## Privacy

The `claude` extractor sends page images to Anthropic's API. Don't use it on real
patient documents without consent. Never commit patient documents or outputs.
