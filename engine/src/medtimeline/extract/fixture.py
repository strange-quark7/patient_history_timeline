"""Offline stand-in extractor that reads pre-made JSON extractions.

Looks for `<source file stem>.p<page>.json` next to the source file or in a
given folder. Used by tests and the demo, and handy for re-running timeline
assembly without paying for extraction again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from medtimeline.extract.base import ExtractionError, register
from medtimeline.ingest import PageInput
from medtimeline.schema import PageExtraction


@register("fixture")
class FixtureExtractor:
    name = "fixture"

    def __init__(self, folder: Optional[str] = None):
        self.folder = Path(folder) if folder else None

    def extract(self, page: PageInput) -> PageExtraction:
        src = Path(page.source_file)
        filename = f"{src.stem}.p{page.page_number}.json"
        candidate = (self.folder or src.parent) / filename
        if not candidate.exists():
            raise ExtractionError(f"No fixture {candidate}")
        return PageExtraction.model_validate_json(candidate.read_text())
