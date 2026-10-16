"""Assemble page extractions into a patient history.

The output is a view-neutral data model (encounters plus derived medication
courses, conditions and lab series). How it is drawn and interacted with is
decided in the app, not here.
"""

from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
from datetime import date, timedelta
from typing import Optional

from pydantic import BaseModel, Field

from medtimeline import normalize
from medtimeline import attribution
from medtimeline.schema import Diagnosis, ExtractionRecord, Investigation, Link, Medication, ReportedEpisode, Vital

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
    negative_history: list[str] = Field(default_factory=list)
    reported_episodes: list[ReportedEpisode] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    needs_review: int = 0


class MedicationCourse(BaseModel):
    drug: str
    start: Optional[str]
    end: Optional[str]
    encounter_ids: list[str]
    entries: list[Medication]
    condition: Optional[str] = Field(None, description="The condition it treats, only if the page or the drug table settles it.")
    condition_basis: Optional[str] = Field(None, description="'page' (written on the page) or 'drug_table' (only one of the patient's conditions fits).")


class Episode(BaseModel):
    """One episode on a lane: a reported event, or a visit where the item appeared."""

    start: Optional[str]
    end: Optional[str]
    encounter_ids: list[str]
    id: Optional[str] = Field(None, description="EpisodeRecord id when this is a reported event.")
    count: int = 1
    is_worst: bool = False


class EpisodeRecord(BaseModel):
    """A patient-reported event, linked to the visit where it was recorded."""

    id: str
    symptom: str
    date: Optional[str]
    date_precision: str
    when_raw: Optional[str]
    count: int
    description: Optional[str]
    duration: Optional[str]
    severity_note: Optional[str]
    is_worst: bool
    triggers: list[str]
    reported_at: str = Field(description="Encounter id of the visit that recorded it.")
    condition: Optional[str] = Field(None, description="Set only when the page ties this event to a diagnosis.")
    confidence: float
    source_text: str


class Condition(BaseModel):
    name: str
    first_seen: Optional[str]
    last_seen: Optional[str]
    encounter_ids: list[str]
    episodes: list[Episode] = Field(default_factory=list)
    course: str = Field("unclassified", description="'long_term', 'acute' (each recurrence is its own episode) or 'unclassified'.")
    role: str = Field("primary", description="'primary' (long-term, recorded at the first visit that recorded any), "
                                             "'comorbidity' (long-term, recorded later or as past history) or 'acute'.")
    known_at_first_mention: bool = Field(False, description="First recorded as past history, so it predates the records.")


class Occurrence(BaseModel):
    """A symptom at one visit, and the condition the page tied it to there, if any."""

    encounter_id: str
    date: Optional[str]
    condition: Optional[str] = None


class Symptom(BaseModel):
    name: str
    first_seen: Optional[str]
    last_seen: Optional[str]
    encounter_ids: list[str]
    episodes: list[Episode] = Field(default_factory=list)
    occurrences: list[Occurrence] = Field(
        default_factory=list,
        description="Per visit, because the same symptom can belong to different conditions at different visits.",
    )

    @property
    def conditions(self) -> list[str]:
        return list(dict.fromkeys(o.condition for o in self.occurrences if o.condition))


class LabPoint(BaseModel):
    date: Optional[str]
    value: str
    unit: Optional[str]
    encounter_id: str


class LabSeries(BaseModel):
    test: str
    points: list[LabPoint]


class ReviewItem(BaseModel):
    """An extracted item held out of the history because a check failed."""

    page_id: str
    section: str
    field: str
    reason: str
    source_text: Optional[str]
    blocking: bool


class PatientHistory(BaseModel):
    patient_name: Optional[str]
    patient_conflicts: list[str] = Field(default_factory=list)
    encounters: list[EncounterNode]
    medication_courses: list[MedicationCourse]
    conditions: list[Condition]
    symptoms: list[Symptom] = Field(default_factory=list)
    episodes: list[EpisodeRecord] = Field(default_factory=list)
    lab_series: list[LabSeries]
    pages_needing_review: list[str]
    review_items: list[ReviewItem] = Field(default_factory=list)


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
    """Assemble verified items into a history; failed items go to review_items instead."""
    from medtimeline.verify import Issue, gate

    review: list[ReviewItem] = []
    gated = []
    for rec in records:
        issues = [Issue.model_validate(i) for i in rec.issues]
        for issue in issues:
            items = getattr(rec.extraction, issue.section, None)
            item = items[issue.index] if isinstance(items, list) and issue.index is not None else None
            quote = getattr(item, "source_text", None) or (item if isinstance(item, str) else None)
            review.append(ReviewItem(page_id=rec.page_id, section=issue.section, field=issue.field,
                                     reason=issue.reason, source_text=quote, blocking=issue.blocking))
        gated.append(rec.model_copy(update={"extraction": gate(rec.extraction, issues)}) if issues else rec)
    records = gated

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
            node.negative_history += x.negative_history
            node.reported_episodes += x.episodes
            node.links += x.links
            node.clinician = node.clinician or x.encounter.clinician
            node.facility = node.facility or x.encounter.facility
            flagged = (
                _review_count(x.diagnoses)
                + _review_count(x.medications)
                + _review_count(x.investigations)
                + _review_count(x.vitals)
                + _review_count(x.episodes)
                + len(x.illegible_notes)
            )
            node.needs_review += flagged
            flagged += len(rec.issues)
            if flagged or status != "exact":
                review_pages.append(rec.page_id)
            if x.patient.name:
                names.append(x.patient.name.strip())
        encounters.append(node)

    encounters.sort(key=lambda n: (n.date is None, n.date or ""))
    for i, node in enumerate(encounters, start=1):
        node.id = f"enc-{i}"

    distinct = sorted({n.lower() for n in names})
    conditions = _conditions(encounters)
    condition_names = [c.name for c in conditions]
    episodes = _episode_records(encounters, condition_names)
    return PatientHistory(
        patient_name=names[0] if names else None,
        patient_conflicts=distinct if len(distinct) > 1 else [],
        encounters=encounters,
        medication_courses=_medication_courses(encounters, condition_names),
        conditions=conditions,
        symptoms=_symptoms(encounters, episodes, condition_names),
        episodes=episodes,
        lab_series=_lab_series(encounters),
        pages_needing_review=review_pages,
        review_items=review,
    )


def _linked_condition(enc: EncounterNode, item: str, conditions: list[str]) -> Optional[str]:
    """The condition a link on this visit's pages ties `item` to, if any."""
    for link in enc.links:
        if _same_symptom(link.item, item) or attribution.matches(item, link.item):
            hit = attribution.resolve(link.condition, conditions)
            if hit:
                return hit
    return None


def _medication_courses(encounters: list[EncounterNode], conditions: list[str] = ()) -> list[MedicationCourse]:
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
        course = courses[-1]
        on_page = next((c for e, m in items if (c := _linked_condition(e, m.drug_as_written, list(conditions)))), None)
        if on_page:
            course.condition, course.condition_basis = on_page, "page"
        elif (by_table := attribution.condition_for_drug(drug, list(conditions))):
            course.condition, course.condition_basis = by_table, "drug_table"
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
    """Each condition is its own track; a patient can have several unrelated ones."""
    out = []
    for name, mentions in _mentions(encounters, lambda e: [d.text for d in e.diagnoses]).values():
        first, last = _span(mentions)
        enc_ids = [i for _, i in mentions]
        first_enc = next((e for e in encounters if e.id == enc_ids[0]), None)
        known = bool(first_enc) and any(d.known and _key(d.text) == _key(name) for d in first_enc.diagnoses)
        course = attribution.course_of(name, known, [d for d, _ in mentions if d])
        if course == "acute":
            # Each recurrence (e.g. each UTI) is its own episode.
            episodes = [Episode(start=run[0][0], end=run[-1][0], encounter_ids=[e for _, e in run])
                        for run in attribution.acute_runs(mentions)]
        else:
            episodes = episodes_from(mentions)
        out.append(Condition(name=name, first_seen=first, last_seen=last, encounter_ids=enc_ids, episodes=episodes,
                             course=course, known_at_first_mention=known))
    # Long-term conditions diagnosed at the first visit that diagnosed any are primary; later or
    # past-history ones are comorbidities. There can be several primaries.
    new_long = [c for c in out if c.course != "acute" and not c.known_at_first_mention and c.first_seen]
    earliest = min((c.first_seen for c in new_long), default=None)
    for c in out:
        if c.course == "acute":
            c.role = "acute"
        else:
            c.role = "primary" if earliest and c.first_seen == earliest and not c.known_at_first_mention else "comorbidity"
    return out


def _episode_records(encounters: list[EncounterNode], conditions: list[str] = ()) -> list[EpisodeRecord]:
    records = []
    for enc in encounters:
        for ep in enc.reported_episodes:
            records.append(EpisodeRecord(
                id="",
                symptom=ep.symptom,
                date=ep.date_iso,
                date_precision=ep.date_precision if ep.date_iso else "unknown",
                when_raw=ep.when_raw,
                count=max(1, ep.count),
                description=ep.description,
                duration=ep.duration,
                severity_note=ep.severity_note,
                is_worst=ep.is_worst,
                triggers=ep.triggers,
                reported_at=enc.id,
                condition=_linked_condition(enc, ep.symptom, list(conditions)),
                confidence=ep.confidence,
                source_text=ep.source_text,
            ))
    # Undated reports sit at the visit that recorded them.
    dates = {e.id: e.date for e in encounters}
    records.sort(key=lambda r: (r.date or dates[r.reported_at] or "9999", r.reported_at))
    for i, r in enumerate(records, start=1):
        r.id = f"ep-{i}"
    return records


def _same_symptom(a: str, b: str) -> bool:
    a, b = _key(a), _key(b)
    return a == b or (len(a) > 3 and a in b) or (len(b) > 3 and b in a) or SequenceMatcher(None, a, b).ratio() >= 0.8


def _symptoms(encounters: list[EncounterNode], records: list[EpisodeRecord], conditions: list[str] = ()) -> list[Symptom]:
    """Reported events are the episodes when a symptom has any; otherwise each visit is one."""
    dates = {e.id: e.date for e in encounters}
    names = {_key(n): n for n, _ in _mentions(encounters, lambda e: e.complaints).values()}
    for r in records:
        if not any(_same_symptom(r.symptom, n) for n in names.values()):
            names[_key(r.symptom)] = r.symptom
    out = []
    mentions_by_key = _mentions(encounters, lambda e: e.complaints)
    for key, name in names.items():
        mentions = mentions_by_key.get(key, (name, []))[1]
        reported = [r for r in records if _same_symptom(r.symptom, name)]
        enc_ids = list(dict.fromkeys([i for _, i in mentions] + [r.reported_at for r in reported]))
        if reported:
            episodes = [
                Episode(start=r.date, end=r.date, encounter_ids=[r.reported_at], id=r.id, count=r.count, is_worst=r.is_worst)
                for r in reported
            ]
        else:
            episodes = episodes_from(mentions)
        by_id = {e.id: e for e in encounters}
        occurrences = [Occurrence(encounter_id=i, date=dates[i], condition=_linked_condition(by_id[i], name, list(conditions)))
                       for i in enc_ids]
        all_dates = sorted([d for d, _ in mentions if d] + [r.date or dates[r.reported_at] for r in reported if r.date or dates[r.reported_at]])
        out.append(Symptom(
            name=name,
            first_seen=all_dates[0] if all_dates else None,
            last_seen=all_dates[-1] if all_dates else None,
            encounter_ids=enc_ids,
            episodes=episodes,
            occurrences=occurrences,
        ))
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
