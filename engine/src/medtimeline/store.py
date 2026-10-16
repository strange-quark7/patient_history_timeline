"""Patient projects on disk: one folder per patient with its verified page records.

    <home>/projects/<id>/meta.json      name, source folder, extractor, dates
    <home>/projects/<id>/records/*.json  one verified extraction per page (also the cache)

Not encrypted yet; the v1 plan moves this into SQLCipher before real patient data is used.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

from medtimeline.schema import ExtractionRecord


def default_home() -> Path:
    return Path(os.environ.get("MEDTIMELINE_HOME") or Path.home() / ".medtimeline")


class Store:
    def __init__(self, home: Optional[str | Path] = None):
        self.root = Path(home or default_home()) / "projects"
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, project_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9-]+", project_id):
            raise ValueError(f"Bad project id {project_id!r}")
        return self.root / project_id

    def list(self) -> list[dict]:
        out = []
        for d in sorted(self.root.iterdir()):
            meta = d / "meta.json"
            if meta.exists():
                out.append({"id": d.name, **json.loads(meta.read_text())})
        return sorted(out, key=lambda m: m.get("updated", 0), reverse=True)

    def create(self, name: str, source_folder: str, extractor: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "patient"
        project_id, n = base, 2
        while (self.root / project_id).exists():
            project_id, n = f"{base}-{n}", n + 1
        d = self._dir(project_id)
        (d / "records").mkdir(parents=True)
        now = time.time()
        (d / "meta.json").write_text(json.dumps({"name": name, "source_folder": source_folder, "extractor": extractor,
                                                 "created": now, "updated": now}, indent=2))
        return project_id

    def meta(self, project_id: str) -> dict:
        return json.loads((self._dir(project_id) / "meta.json").read_text())

    def touch(self, project_id: str, **fields) -> None:
        meta = {**self.meta(project_id), **fields, "updated": time.time()}
        (self._dir(project_id) / "meta.json").write_text(json.dumps(meta, indent=2))

    def records_dir(self, project_id: str) -> Path:
        return self._dir(project_id) / "records"

    def records(self, project_id: str) -> list[ExtractionRecord]:
        return [ExtractionRecord.model_validate_json(p.read_text()) for p in sorted(self.records_dir(project_id).glob("*.json"))]
