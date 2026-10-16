"""Assemble page extractions into a patient history.

The output is a view-neutral data model (encounters plus derived medication
courses, conditions and lab series). How it is drawn and interacted with is
decided in the app, not here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

from pydantic import BaseModel, Field

from medtimeline import normalize
from medtimeline.schema import Diagnosis, ExtractionRecord, Investigation, Medication, Vital

REVIEW_THRESHOLD = 0.7


class EncounterNode(BaseModel):
    id: str
    date: Optional[str]
    date_status: str = Field(description="'exact', 'ambiguous' or 'unknown'.")
    facility: Optional[str] = None
    clinician: Optional[str] = None
    encounter_type: Optional[str] = None
    doc_types: list[str] = Field(default_factory=list)
    page_ids: list[str] = Field(default_factory=list)
    complaints: list[str] = Field(default_factory=list)
    diagnoses: list[Diagnosis] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    investigations: list[Investigation] = Field(default_factory=list)
    vitals: list[Vital] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)
    needs_review: int = 0


class MedicationCourse(BaseModel):
    drug: str
    start: Optional[str]
    end: Optional[str]
    encounter_ids: list[str]
    entries: list[Medication]


class Episode(BaseModel):
    start: Optional[str]
    end: Optional[str]
    encounter_ids: list[str]


class Condition(BaseModel):
    name: str
    first_seen: Optional[str]
    last_seen: Optional[str]
    encounter_ids: list[str]
    episodes: list[Episode] = Field(default_factory=list)


class Symptom(BaseModel):
    name: str
    first_seen: Optional[str]
    last_seen: Optional[str]
    encounter_ids: list[str]
    episodes: list[Episode] = Field(default_factory=list)


class LabPoint(BaseModel):
    date: Optional[str]
    value: str
    unit: Optional[str]
    encounter_id: str


class LabSeries(BaseModel):
    test: str
    points: list[LabPoint]


class PatientHistory(BaseModel):
    patient_name: Optional[str]
    patient_conflicts: list[str] = Field(default_factory=list)
    encounters: list[EncounterNode]
    medication_courses: list[MedicationCourse]
    conditions: list[Condition]
    symptoms: list[Symptom] = Field(default_factory=list)
    lab_series: list[LabSeries]
    pages_needing_review: list[str]


def _encounter_key(rec: ExtractionRecord) -> tuple:
    e = rec.extraction.encounter
    date_iso = e.date_iso or normalize.parse_date(e.date_raw)[0]
    if date_iso is None:
        # Undated pages stay separate (per source file) until a person dates them.
        return ("undated", rec.source_file)
    return (date_iso, (e.facility or "").strip().lower())


def _review_count(items) -> int:
    return sum(1 for i in items if i.confidence < REVIEW_THRESHOLD)


def build_history(records: list[ExtractionRecord]) -> PatientHistory:
    groups: dict[tuple, list[ExtractionRecord]] = defaultdict(list)
    for rec in records:
        groups[_encounter_key(rec)].append(rec)

    encounters: list[EncounterNode] = []
    review_pages: list[str] = []
    names: list[str] = []
    for i, (key, recs) in enumerate(groups.items()):
        first = recs[0].extraction.encounter
        parsed, ambiguous = normalize.parse_date(first.date_raw)
        date_iso = key[0] if key[0] != "undated" else None
        if date_iso is None:
            status = "unknown"
        elif first.date_ambiguous or (parsed == date_iso and ambiguous):
            status = "ambiguous"
        else:
            status = "exact"
        node = EncounterNode(
            id=f"enc-{i + 1}",
            date=date_iso,
            date_status=status,
            facility=first.facility,
            clinician=first.clinician,
            encounter_type=first.encounter_type,
        )
        for rec in recs:
            x = rec.extraction
            node.page_ids.append(rec.page_id)
            node.doc_types.append(x.doc_type.value)
            node.complaints += x.complaints
            node.diagnoses += x.diagnoses
            node.medications += x.medications
            node.investigations += x.investigations
            node.vitals += x.vitals
            node.advice += x.advice
            node.clinician = node.clinician or x.encounter.clinician
            node.facility = node.facility or x.encounter.facility
            flagged = (
                _review_count(x.diagnoses)
                + _review_count(x.medications)
                + _review_count(x.investigations)
                + _review_count(x.vitals)
                + len(x.illegible_notes)
            )
            node.needs_review += flagged
            if flagged or status != "exact":
                review_pages.append(rec.page_id)
            if x.patient.name:
                names.append(x.patient.name.strip())
        encounters.append(node)

    encounters.sort(key=lambda n: (n.date is None, n.date or ""))
    for i, node in enumerate(encounters, start=1):
        node.id = f"enc-{i}"

    distinct = sorted({n.lower() for n in names})
    return PatientHistory(
        patient_name=names[0] if names else None,
        patient_conflicts=distinct if len(distinct) > 1 else [],
        encounters=encounters,
        medication_courses=_medication_courses(encounters),
        conditions=_conditions(encounters),
        symptoms=_symptoms(encounters),
        lab_series=_lab_series(encounters),
        pages_needing_review=review_pages,
    )


def _medication_courses(encounters: list[EncounterNode]) -> list[MedicationCourse]:
    by_drug: dict[str, list[tuple[EncounterNode, Medication]]] = defaultdict(list)
    for enc in encounters:
        for med in enc.medications:
            key = normalize.normalize_drug_key(med.generic_name or med.drug_as_written)
            if key:
                by_drug[key].append((enc, med))
    courses = []
    for drug, items in by_drug.items():
        dated = [(e, m) for e, m in items if e.date]
        start = dated[0][0].date if dated else None
        end = None
        if dated:
            last_enc, last_med = dated[-1]
            days = normalize.duration_days(last_med.duration)
            end = (date.fromisoformat(last_enc.date) + timedelta(days=days)).isoformat() if days else last_enc.date
        courses.append(
            MedicationCourse(
                drug=drug,
                start=start,
                end=end,
                encounter_ids=[e.id for e, _ in items],
                entries=[m for _, m in items],
            )
        )
    return sorted(courses, key=lambda c: (c.start is None, c.start or "", c.drug))


def _key(text: str) -> str:
    return " ".join(text.lower().split())


def episodes_from(mentions: list[tuple[Optional[str], str]]) -> list[Episode]:
    """One episode per doctor visit, in date order (undated visits last)."""
    ordered = sorted(mentions, key=lambda x: (x[0] is None, x[0] or ""))
    return [Episode(start=d, end=d, encounter_ids=[enc_id]) for d, enc_id in dict.fromkeys(ordered)]


def _mentions(encounters: list[EncounterNode], texts_of) -> dict[str, tuple[str, list[tuple[Optional[str], str]]]]:
    seen: dict[str, tuple[str, list[tuple[Optional[str], str]]]] = {}
    for enc in encounters:
        for text in dict.fromkeys(texts_of(enc)):  # once per encounter
            key = _key(text)
            if key:
                seen.setdefault(key, (text, []))[1].append((enc.date, enc.id))
    return seen


def _span(mentions: list[tuple[Optional[str], str]]) -> tuple[Optional[str], Optional[str]]:
    dates = sorted(d for d, _ in mentions if d)
    return (dates[0], dates[-1]) if dates else (None, None)


def _conditions(encounters: list[EncounterNode]) -> list[Condition]:
    out = []
    for name, mentions in _mentions(encounters, lambda e: [d.text for d in e.diagnoses]).values():
        first, last = _span(mentions)
        out.append(Condition(name=name, first_seen=first, last_seen=last,
                             encounter_ids=[i for _, i in mentions], episodes=episodes_from(mentions)))
    return out


def _symptoms(encounters: list[EncounterNode]) -> list[Symptom]:
    out = []
    for name, mentions in _mentions(encounters, lambda e: e.complaints).values():
        first, last = _span(mentions)
        out.append(Symptom(name=name, first_seen=first, last_seen=last,
                           encounter_ids=[i for _, i in mentions], episodes=episodes_from(mentions)))
    return out


def _lab_series(encounters: list[EncounterNode]) -> list[LabSeries]:
    series: dict[str, LabSeries] = {}
    for enc in encounters:
        for inv in enc.investigations:
            if inv.status != "resulted" or not inv.value:
                continue
            key = " ".join(inv.name.lower().split())
            s = series.setdefault(key, LabSeries(test=inv.name, points=[]))
            s.points.append(LabPoint(date=enc.date, value=inv.value, unit=inv.unit, encounter_id=enc.id))
    return list(series.values())
