"""Score an extractor against hand-labelled gold pages.

Gold labels are PageExtraction JSON files named `<file stem>.p<page>.json`
next to (or in a folder separate from) the source documents. The same scores
decide when a local model is good enough to replace the cloud one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from medtimeline import normalize
from medtimeline.extract.base import ExtractionError, Extractor
from medtimeline.ingest import load_folder
from medtimeline.schema import PageExtraction

MATCH = 0.8


def _sim(a: str | None, b: str | None) -> float:
    if not a or not b:
        return float(a == b)
    a, b = " ".join(a.lower().split()), " ".join(b.lower().split())
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class Tally:
    correct: int = 0
    total: int = 0

    def add(self, ok: bool):
        self.total += 1
        self.correct += int(ok)

    @property
    def pct(self) -> float:
        return 100.0 * self.correct / self.total if self.total else 0.0


@dataclass
class Scores:
    fields: dict[str, Tally] = field(default_factory=dict)
    failed_pages: list[str] = field(default_factory=list)
    extra_items: int = 0  # predicted items with no gold counterpart (possible hallucinations)

    def t(self, name: str) -> Tally:
        return self.fields.setdefault(name, Tally())

    def report(self) -> str:
        lines = [f"{'field':<22}{'correct':>9}{'total':>7}{'score':>8}"]
        for name, t in sorted(self.fields.items()):
            lines.append(f"{name:<22}{t.correct:>9}{t.total:>7}{t.pct:>7.1f}%")
        lines.append(f"extra items (not in gold): {self.extra_items}")
        if self.failed_pages:
            lines.append(f"failed pages: {len(self.failed_pages)}")
        return "\n".join(lines)


def _best(item_name: str, candidates: list[str]) -> int | None:
    best, idx = 0.0, None
    for i, c in enumerate(candidates):
        s = _sim(item_name, c)
        if s > best:
            best, idx = s, i
    return idx if best >= MATCH else None


def score_page(gold: PageExtraction, pred: PageExtraction, s: Scores) -> None:
    s.t("doc_type").add(gold.doc_type == pred.doc_type)
    g_date = gold.encounter.date_iso or normalize.parse_date(gold.encounter.date_raw)[0]
    p_date = pred.encounter.date_iso or normalize.parse_date(pred.encounter.date_raw)[0]
    s.t("encounter_date").add(g_date == p_date)

    pred_meds = [m.generic_name or m.drug_as_written for m in pred.medications]
    used = set()
    for gm in gold.medications:
        idx = _best(gm.generic_name or gm.drug_as_written, pred_meds)
        s.t("med_name").add(idx is not None)
        if idx is None:
            continue
        used.add(idx)
        pm = pred.medications[idx]
        s.t("med_strength").add(_sim(gm.strength, pm.strength) >= MATCH)
        s.t("med_frequency").add(
            normalize.expand_frequency(gm.frequency) == normalize.expand_frequency(pm.frequency)
            or _sim(gm.frequency, pm.frequency) >= MATCH
        )
        s.t("med_duration").add(normalize.duration_days(gm.duration) == normalize.duration_days(pm.duration))
    s.extra_items += len(pred_meds) - len(used)

    pred_dx = [d.text for d in pred.diagnoses]
    for gd in gold.diagnoses:
        s.t("diagnosis").add(_best(gd.text, pred_dx) is not None)
    s.extra_items += max(0, len(pred_dx) - len(gold.diagnoses))

    pred_inv = [i.name for i in pred.investigations]
    for gi in gold.investigations:
        idx = _best(gi.name, pred_inv)
        s.t("investigation").add(idx is not None)
        if idx is not None and gi.value:
            s.t("lab_value").add(_sim(gi.value, pred.investigations[idx].value) >= 0.95)


def run_eval(extractor: Extractor, docs_folder: str, gold_folder: str) -> Scores:
    s = Scores()
    gold_dir = Path(gold_folder)
    for page in load_folder(docs_folder):
        gold_path = gold_dir / f"{Path(page.source_file).stem}.p{page.page_number}.json"
        if not gold_path.exists():
            continue
        gold = PageExtraction.model_validate_json(gold_path.read_text())
        try:
            pred = extractor.extract(page)
        except ExtractionError:
            s.failed_pages.append(page.page_id)
            continue
        score_page(gold, pred, s)
    return s
