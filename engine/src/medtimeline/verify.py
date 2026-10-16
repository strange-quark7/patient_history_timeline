"""Deterministic checks that every extracted item is backed by the page.

The AI model only transcribes. Before anything reaches the history, these
rules check each item against what is actually written:

1. Its quote (`source_text`) must be found in the page's text.
2. Every number in its structured fields (doses, values, counts) must appear in that quote.
3. Its name (drug, diagnosis, test, symptom) must appear in the quote, directly or
   through a known abbreviation.
4. Dates are re-derived from the date as written; a model-supplied date that
   disagrees is rejected.

Items that fail are kept out of the history and listed for a person to review.
Nothing here calls a model, so the same input always gives the same result.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from pydantic import BaseModel

from medtimeline import normalize
from medtimeline.schema import PageExtraction

QUOTE_MATCH = 0.9  # share of the quote's characters found, in order, in the page text
MIN_TEXT_LAYER = 40  # characters; shorter text layers are treated as absent

# Common clinical abbreviations: abbreviation as written -> words it stands for.
ABBREVIATIONS = {
    "htn": "hypertension", "dm": "diabetes", "t2dm": "type 2 diabetes", "t1dm": "type 1 diabetes",
    "ckd": "chronic kidney disease", "cad": "coronary artery disease", "ihd": "ischaemic heart disease",
    "copd": "chronic obstructive pulmonary disease", "ba": "bronchial asthma", "tb": "tuberculosis",
    "gerd": "gastro-oesophageal reflux", "uti": "urinary tract infection", "urti": "upper respiratory tract infection",
    "lrti": "lower respiratory tract infection", "cva": "stroke", "mi": "myocardial infarction", "af": "atrial fibrillation",
    "chf": "heart failure", "hf": "heart failure", "ra": "rheumatoid arthritis", "oa": "osteoarthritis",
    "pcos": "polycystic ovary", "hypothyroid": "hypothyroidism", "sz": "seizure", "gtcs": "tonic clonic seizure",
    "hb": "haemoglobin", "hba1c": "glycated haemoglobin", "fbs": "fasting blood sugar", "ppbs": "post prandial blood sugar",
    "rbs": "random blood sugar", "grbs": "random blood sugar", "na": "sodium", "k": "potassium", "cr": "creatinine",
    "s.cr": "creatinine", "tsh": "thyroid stimulating hormone", "lft": "liver function", "rft": "renal function",
    "kft": "kidney function", "cbc": "complete blood count", "esr": "erythrocyte sedimentation rate",
    "crp": "c-reactive protein", "usg": "ultrasound", "cxr": "chest x-ray", "ecg": "electrocardiogram",
    "eeg": "electroencephalogram", "ct": "ct", "mri": "mri", "sob": "breathlessness", "c/o": "complaints of",
    "h/o": "history of", "k/c/o": "known case of", "bp": "blood pressure", "pr": "pulse", "rr": "respiratory rate",
    "spo2": "oxygen saturation", "wt": "weight", "temp": "temperature",
    "ida": "iron deficiency anaemia", "ccf": "heart failure",
}
NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
NEGATIONS = {"no", "not", "nil", "denies", "denied", "absent", "without", "neg", "negative"}
STOP = {"of", "the", "and", "with", "for", "tab", "cap", "syp", "inj", "left", "right", "on", "in", "to", "mg", "ml"}


class Issue(BaseModel):
    section: str  # e.g. "medications", "encounter"
    index: Optional[int]  # position in that list, None for single fields
    field: str
    reason: str
    blocking: bool = True  # False: shown with a caution but kept (e.g. an inferred date)


def _norm(text: str) -> str:
    text = text.lower().replace(" ", " ")
    text = re.sub(r"\s*([/:.,;()\-+])\s*", r"\1", text)
    return " ".join(text.split())


def quote_found(quote: str, page_text: str) -> bool:
    q, t = _norm(quote), _norm(page_text)
    if not q:
        return False
    if q in t:
        return True
    blocks = SequenceMatcher(None, q, t, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks) / len(q) >= QUOTE_MATCH


def _numbers(text: Optional[str]) -> set[str]:
    if not text:
        return set()
    return {n.lstrip("0") or "0" for n in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9.\-/]*", text.lower()) if len(w) >= 2 and w not in STOP}


def name_in_quote(name: str, quote: str) -> bool:
    """True if any meaningful word of `name` (or an abbreviation for it) is in the quote."""
    name_words, quote_words = _words(name), _words(quote)
    if not name_words:
        return True
    if name_words & quote_words:
        return True
    expanded = " ".join(ABBREVIATIONS.get(w.strip("."), "") for w in quote_words)
    if _words(expanded) & name_words:
        return True
    # Prefix match catches 'metformin' vs 'metform', 'hypothyroidism' vs 'hypothyroid'.
    return any(len(a) >= 5 and len(b) >= 5 and (a.startswith(b[:5]) or b.startswith(a[:5]))
               for a in name_words for b in quote_words)


def _all_words_on_page(text: str, page_text: str) -> bool:
    """Every word of a negative finding (apart from 'no', 'denies', ...) must be on the page."""
    words = _words(text) - NEGATIONS
    return bool(words) and all(name_in_quote(w, page_text) for w in words)


def _numbers_backed(values: list[Optional[str]], quote: str) -> list[str]:
    in_quote = _numbers(quote)
    return [n for v in values for n in _numbers(v) if n not in in_quote]


def verify_page(x: PageExtraction, text_layer: Optional[str]) -> tuple[list[Issue], str]:
    """Return (issues, what the quotes were checked against)."""
    if text_layer and len(text_layer.strip()) >= MIN_TEXT_LAYER:
        page_text, grounding = text_layer, "text_layer"
    elif x.transcription:
        page_text, grounding = x.transcription, "transcription"
    else:
        page_text, grounding = "", "none"

    issues: list[Issue] = []

    def check_item(section: str, i: int, quote: str, name: Optional[str], numeric: list[Optional[str]]):
        if not page_text:
            issues.append(Issue(section=section, index=i, field="source_text", reason="no page text to check against"))
            return
        if not quote_found(quote, page_text):
            issues.append(Issue(section=section, index=i, field="source_text", reason="quote not found on the page"))
            return
        if name and not name_in_quote(name, quote):
            issues.append(Issue(section=section, index=i, field="name", reason=f"'{name}' is not in the quoted text"))
        missing = _numbers_backed(numeric, quote)
        if missing:
            issues.append(Issue(section=section, index=i, field="numbers",
                                reason=f"number(s) {', '.join(sorted(missing))} not in the quoted text"))

    for i, m in enumerate(x.medications):
        check_item("medications", i, m.source_text, m.drug_as_written, [m.strength, m.dose])
        if m.duration and page_text and quote_found(m.source_text, page_text):
            # A duration can be written once for several drugs, so it may be backed by its own quote.
            # A failure drops only the duration (see gate), not the drug.
            backing = m.source_text
            if m.duration_source:
                if quote_found(m.duration_source, page_text):
                    backing += " " + m.duration_source
                else:
                    issues.append(Issue(section="medications", index=i, field="duration", blocking=False,
                                        reason="duration's quote not found on the page; duration dropped"))
                    continue
            missing = _numbers_backed([m.duration], backing)
            if missing:
                issues.append(Issue(section="medications", index=i, field="duration", blocking=False,
                                    reason=f"duration number(s) {', '.join(sorted(missing))} not in the quoted text; duration dropped"))
    for i, d in enumerate(x.diagnoses):
        check_item("diagnoses", i, d.source_text, d.text, [])
    for i, t in enumerate(x.investigations):
        check_item("investigations", i, t.source_text, t.name, [t.value])
    for i, v in enumerate(x.vitals):
        check_item("vitals", i, v.source_text, None, [v.value])
    for i, e in enumerate(x.episodes):
        check_item("episodes", i, e.source_text, e.symptom, [])
        if e.count > 1:
            q = e.source_text.lower()
            if str(e.count) not in _numbers(q) and not any(NUMBER_WORDS.get(w) == e.count for w in q.split()):
                issues.append(Issue(section="episodes", index=i, field="count", reason=f"count {e.count} not in the quoted text"))
        if e.date_iso:
            written, _ = normalize.parse_date(e.when_raw)
            if written and written != e.date_iso:
                issues.append(Issue(section="episodes", index=i, field="date_iso",
                                    reason=f"date {e.date_iso} does not match '{e.when_raw}'"))
            elif not written:
                issues.append(Issue(section="episodes", index=i, field="date_iso", blocking=False,
                                    reason=f"date inferred from '{e.when_raw or 'nothing written'}'"))

    for i, link in enumerate(x.links):
        check_item("links", i, link.source_text, link.item, [])
        if quote_found(link.source_text, page_text or "") and not name_in_quote(link.condition, link.source_text):
            issues.append(Issue(section="links", index=i, field="condition", reason=f"'{link.condition}' is not in the quoted text"))

    enc = x.encounter
    if enc.date_raw and page_text and not quote_found(enc.date_raw, page_text):
        issues.append(Issue(section="encounter", index=None, field="date_raw", reason="visit date not found on the page"))
    if enc.date_iso:
        written, _ = normalize.parse_date(enc.date_raw)
        if not enc.date_raw:
            issues.append(Issue(section="encounter", index=None, field="date_iso", reason="visit date given but nothing written"))
        elif written and written != enc.date_iso:
            issues.append(Issue(section="encounter", index=None, field="date_iso",
                                reason=f"visit date {enc.date_iso} does not match '{enc.date_raw}'"))
    for i, text in enumerate(x.negative_history):
        if page_text and not quote_found(text, page_text) and not _all_words_on_page(text, page_text):
            issues.append(Issue(section="negative_history", index=i, field="text", reason="not found on the page"))
    return issues, grounding


def gate(x: PageExtraction, issues: list[Issue]) -> PageExtraction:
    """A copy of the extraction without items that failed a blocking check."""
    blocked: dict[str, set[int]] = {}
    for issue in issues:
        if issue.blocking and issue.index is not None:
            blocked.setdefault(issue.section, set()).add(issue.index)
    data = x.model_copy(deep=True)
    for section, idxs in blocked.items():
        items = getattr(data, section)
        setattr(data, section, [item for i, item in enumerate(items) if i not in idxs])
    for issue in issues:
        if issue.section == "medications" and issue.field == "duration" and issue.index is not None \
                and issue.index not in blocked.get("medications", set()):
            kept = sum(1 for j in range(issue.index) if j not in blocked.get("medications", set()))
            data.medications[kept].duration = None
    if any(i.blocking and i.section == "encounter" and i.field == "date_iso" for i in issues):
        data.encounter.date_iso = None  # fall back to the date as written
    return data
