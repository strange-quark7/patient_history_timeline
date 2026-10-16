"""Pages in, verified extraction records out. Shared by the CLI and the app service."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from medtimeline.extract import ExtractionError
from medtimeline.ingest import load_folder
from medtimeline.schema import ExtractionRecord
from medtimeline.verify import verify_page

Progress = Callable[[dict], None]


def extract_folder(folder: str | Path, extractor, cache_dir: Optional[Path] = None,
                   on_progress: Optional[Progress] = None, batch: int = 0) -> tuple[list[ExtractionRecord], list[str]]:
    """Extract and verify every page. Cached pages are reused so nothing is paid for twice."""
    pages = load_folder(folder)
    records, failures = [], []
    for n, page in enumerate(pages, start=1):
        if on_progress:
            on_progress({"done": n - 1, "total": len(pages), "file": Path(page.source_file).name, "page": page.page_number})
        cached = cache_dir / f"{page.page_id}.json" if cache_dir else None
        if cached and cached.exists():
            records.append(ExtractionRecord.model_validate_json(cached.read_text()))
            continue
        try:
            extraction = extractor.extract(page)
        except ExtractionError as e:
            failures.append(str(e))
            continue
        issues, grounding = verify_page(extraction, page.text_layer)
        rec = ExtractionRecord(
            page_id=page.page_id, source_file=page.source_file, page_number=page.page_number,
            extractor=extractor.name, extraction=extraction,
            issues=[i.model_dump() for i in issues], grounding=grounding, batch=batch,
        )
        records.append(rec)
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(rec.model_dump_json(indent=2))
    if on_progress:
        on_progress({"done": len(pages), "total": len(pages), "file": None, "page": None})
    return records, failures
