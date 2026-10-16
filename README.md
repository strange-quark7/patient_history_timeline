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
    correlation.py   medication starts/dose changes vs episodes before and after
    details.py       what the detail panel shows for one selected episode or visit
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

Episodes the patient reports (e.g. "13 seizures, the worst in Dec 2024") are
their own records, linked to the visit that recorded them, with a count when the
page only gives a number. A symptom with no reported episodes falls back to one
episode per visit where it appears. In `symptoms_medications`, each row
lists the items of the other kind seen at the same visits.

## Scoring an extractor

Put sample documents in `eval/docs/` and hand-checked extractions in
`eval/gold/` as `<file stem>.p<page>.json` (same shape as `schema.PageExtraction`).
Both folders are git-ignored so patient data never lands in the repo.

```bash
medtimeline eval eval/docs eval/gold --extractor claude
```

## Detail for a selected element

`details.episode_detail(history, episode_id)` returns the episode with the visit
that recorded it, the negative history, the medication in force when it happened,
and the labs, imaging and other tests from that visit. `details.visit_detail`
does the same for a visit.

## Correlation

`correlation.correlate(history)` lists every medication start and dose change,
with episodes per month (and worst episodes) in the window since the previous
change and until the next one. It shows timing only, not cause.

A local extractor replaces the cloud one only once its scores are close enough.

## Keeping out invented facts

The model only reads the page. Everything after that is plain rules in `engine/src/medtimeline/verify.py`, so the same pages always give the same history. Each extracted item must pass these checks before it enters the history:

- Its quote must appear on the page. Typed PDFs are checked against the PDF's own text; scans are checked against the model's verbatim transcription.
- Every number in a dose, strength, duration, lab value or vital must appear in that quote.
- The drug, diagnosis, test or symptom name must appear in the quote, directly or as a known abbreviation (HTN, FBS, k/c/o and so on).
- An episode count above one must be written on the page.
- Dates are re-derived from the date as written. A model date that disagrees is dropped; a date the model inferred from words like "last week" is kept but marked as inferred.
- Every word of a negative finding ("no fever") must be on the page.

Items that fail are not shown as facts. They are listed in `review_items` with the reason, for a person to accept or correct. Nothing in the timeline logic is specific to one disease.

Limitation: on handwritten scans, the quote is checked against the same model's transcription. A local OCR pass as an independent second reader is planned for the offline version.

## Adding an extractor (e.g. a local model)

Implement `extract(page: PageInput) -> PageExtraction`, decorate the class with
`@register("name")`, and select it with `--extractor name`. Nothing downstream changes.

## Privacy

The `claude` extractor sends page images to Anthropic's API. Don't use it on real
patient documents without consent. Never commit patient documents or outputs.
