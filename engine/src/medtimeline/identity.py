"""Is each page about the same patient? Deterministic checks, and a yes/no question when in doubt.

The reference is the name the user gave the patient (or, failing that, the name most pages carry).
Pages whose name matches it in full form the core; the core's sex, approximate birth year and any
hospital numbers or phone numbers are then compared with every page.

    match     the name matches in full (or an ID matches) and nothing conflicts
    doubt     only part of the name matches, no name is written, or the age or sex disagrees
    mismatch  the names differ

Pages in doubt or mismatched stay out of the history until a person answers yes. A "no" keeps the
page out for good (until undone). Nothing here guesses: every reason names what the pages say.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from statistics import median
from typing import Optional

from pydantic import BaseModel, Field

from medtimeline.schema import ExtractionRecord

TITLES = {"mr", "mrs", "ms", "miss", "smt", "shri", "sri", "sh", "dr", "master", "baby", "b/o", "late", "kum", "km"}
YES, NO = "yes", "no"


MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _day(d: str) -> str:
    y, m, dd = d.split("-")
    return f"{int(dd)} {MONTHS[int(m) - 1]} {y}"


def key(page_id: str) -> str:
    return f"identity:{page_id}"


def name_tokens(name: Optional[str]) -> list[str]:
    words = re.findall(r"[a-z]+(?:/[a-z]+)?", (name or "").lower())
    return [w for w in words if w not in TITLES]


def _same_word(a: str, b: str) -> bool:
    # One letter is an initial; otherwise allow small misreads (Srinivas / Shrinivas).
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]
    return a == b or SequenceMatcher(None, a, b).ratio() >= 0.85


def compare_names(page: list[str], ref: list[str]) -> str:
    """'same', 'partial' (one is part of the other) or 'different'."""
    if not page or not ref:
        return "unknown"
    unmatched_page = [w for w in page if not any(_same_word(w, r) for r in ref)]
    unmatched_ref = [r for r in ref if not any(_same_word(w, r) for w in page)]
    if not unmatched_page and not unmatched_ref:
        return "same"
    if len(unmatched_page) == len(page):
        return "different"
    if unmatched_page and unmatched_ref:
        return "different"  # e.g. Ashok Verma vs Ashok Kumar
    return "partial"


def age_years(age: Optional[str]) -> Optional[float]:
    if not age:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(m|mo|mon|month|months)\b", age.lower())
    if m:
        return float(m.group(1)) / 12
    m = re.search(r"\d+(?:\.\d+)?", age)
    return float(m.group(0)) if m else None


def sex_of(sex: Optional[str], age: Optional[str]) -> Optional[str]:
    for text in (sex, age):  # sex is often written with the age, as in "58y/M"
        t = (text or "").lower()
        if re.search(r"\b(f|female|fe)\b|/f\b", t):
            return "F"
        if re.search(r"\b(m|male)\b|/m\b", t):
            return "M"
    return None


def birth_year(rec: ExtractionRecord) -> Optional[float]:
    years = age_years(rec.extraction.patient.age)
    when = rec.extraction.encounter.date_iso
    if years is None or not when:
        return None
    return int(when[:4]) + (int(when[5:7]) - 1) / 12 - years


def _ids(rec: ExtractionRecord) -> set[str]:
    return {re.sub(r"\W", "", i).lower() for i in rec.extraction.patient.identifiers if len(re.sub(r"\W", "", i)) >= 4}


class PageIdentity(BaseModel):
    page_id: str
    verdict: str = Field(description="'match', 'doubt' or 'mismatch' from the checks alone.")
    name_on_page: Optional[str]
    age_on_page: Optional[str]
    sex_on_page: Optional[str]
    reasons: list[str] = Field(default_factory=list)
    answer: Optional[str] = Field(None, description="The reviewer's 'yes' or 'no', if given.")

    @property
    def included(self) -> bool:
        return self.answer == YES or (self.answer is None and self.verdict == "match")


class Profile(BaseModel):
    name: Optional[str]
    sex: Optional[str] = None
    born_about: Optional[int] = None
    identifiers: list[str] = Field(default_factory=list)


def check_pages(records: list[ExtractionRecord], patient_name: Optional[str] = None,
                answers: Optional[dict[str, dict]] = None) -> tuple[Profile, list[PageIdentity]]:
    answers = answers or {}
    names = [r.extraction.patient.name for r in records if name_tokens(r.extraction.patient.name)]
    ref_name = patient_name if patient_name and any(
        compare_names(name_tokens(n), name_tokens(patient_name)) in ("same", "partial") for n in names) else None
    if not ref_name and names:
        ref_name = Counter(" ".join(name_tokens(n)) for n in names).most_common(1)[0][0].title()
    ref = name_tokens(ref_name)

    def answer(rec):
        return (answers.get(key(rec.page_id)) or {}).get("choice")

    # The core sets the expected sex, age and IDs: full-name matches, or confirmed pages if there are none.
    core = [r for r in records if compare_names(name_tokens(r.extraction.patient.name), ref) == "same" and answer(r) != NO] \
        or [r for r in records if answer(r) == YES]
    sexes = Counter(s for r in core if (s := sex_of(r.extraction.patient.sex, r.extraction.patient.age)))
    sex = sexes.most_common(1)[0][0] if sexes and len(sexes) == 1 else None
    years = [y for r in core if (y := birth_year(r)) is not None]
    born = median(years) if years else None
    core_ids = set().union(*(_ids(r) for r in core)) if core else set()
    profile = Profile(name=ref_name, sex=sex, born_about=round(born) if born is not None else None,
                      identifiers=sorted(core_ids))

    out = []
    if not ref:  # no name anywhere to compare with: nothing to check
        return profile, [PageIdentity(page_id=r.page_id, verdict="match", name_on_page=None, age_on_page=r.extraction.patient.age,
                                      sex_on_page=sex_of(r.extraction.patient.sex, r.extraction.patient.age), answer=answer(r))
                         for r in records]
    for rec in records:
        p = rec.extraction.patient
        name_cmp = compare_names(name_tokens(p.name), ref)
        id_match = bool(_ids(rec) & core_ids)
        reasons = []
        if name_cmp == "unknown":
            reasons.append("No patient name is written on this page" if ref else "No patient name to compare with")
        elif name_cmp == "partial":
            reasons.append(f"Only part of the name matches: '{p.name}' and '{ref_name}'")
        elif name_cmp == "different":
            reasons.append(f"The name on the page, '{p.name}', differs from '{ref_name}'")
        page_sex = sex_of(p.sex, p.age)
        if sex and page_sex and page_sex != sex:
            reasons.append(f"Sex on the page is {page_sex}; other pages say {sex}")
        b = birth_year(rec)
        if born is not None and b is not None and abs(b - born) > 2:
            reasons.append(f"Age {p.age} on {_day(rec.extraction.encounter.date_iso)} puts birth around {round(b)}; other pages say around {round(born)}")
        if id_match:
            reasons.insert(0, "A hospital number or phone number matches other pages")

        conflicts = [r for r in reasons if r.startswith(("Sex", "Age"))]
        if name_cmp == "different" and not id_match:
            verdict = "mismatch"
        elif conflicts:
            verdict = "doubt"
        elif name_cmp == "same" or id_match:
            verdict = "match"
        else:
            verdict = "doubt"
        out.append(PageIdentity(page_id=rec.page_id, verdict=verdict, name_on_page=p.name, age_on_page=p.age,
                                sex_on_page=page_sex, reasons=reasons if verdict != "match" else [r for r in reasons if r.startswith("A hospital")],
                                answer=answer(rec)))
    return profile, out
