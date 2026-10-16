"""Everything the detail panel shows when one element of the history is selected."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from medtimeline.schema import Investigation, Medication
from medtimeline.timeline import EncounterNode, EpisodeRecord, MedicationCourse, PatientHistory


class ActiveMedication(BaseModel):
    drug: str
    dose: Medication = Field(description="The prescription in force at that date.")
    course_start: Optional[str]


class EpisodeDetail(BaseModel):
    episode: EpisodeRecord
    reported_at: EncounterNode
    negative_history: list[str]
    medications_at_time: list[ActiveMedication]
    labs: list[Investigation]
    imaging: list[Investigation]
    other_tests: list[Investigation]
    episodes_at_same_visit: list[str] = Field(description="Ids of the other episodes recorded at that visit.")
    source_pages: list[str]


class VisitDetail(BaseModel):
    visit: EncounterNode
    episodes: list[EpisodeRecord]
    medications_at_time: list[ActiveMedication]
    labs: list[Investigation]
    imaging: list[Investigation]
    other_tests: list[Investigation]


def _encounter(history: PatientHistory, enc_id: str) -> EncounterNode:
    for e in history.encounters:
        if e.id == enc_id:
            return e
    raise KeyError(enc_id)


def medications_on(history: PatientHistory, day: Optional[str]) -> list[ActiveMedication]:
    """Drugs prescribed on or before `day` whose course had not ended by then."""
    if not day:
        return []
    dates = {e.id: e.date for e in history.encounters}
    active = []
    for course in history.medication_courses:
        course: MedicationCourse
        if not course.start or course.start > day or (course.end and course.end < day):
            continue
        current = None
        for enc_id, entry in zip(course.encounter_ids, course.entries):
            if dates[enc_id] and dates[enc_id] <= day:
                current = entry
        if current:
            active.append(ActiveMedication(drug=course.drug, dose=current, course_start=course.start))
    return active


def _split_tests(tests: list[Investigation]) -> tuple[list[Investigation], list[Investigation], list[Investigation]]:
    labs = [t for t in tests if t.kind == "lab"]
    imaging = [t for t in tests if t.kind == "imaging"]
    other = [t for t in tests if t.kind not in ("lab", "imaging")]
    return labs, imaging, other


def episode_detail(history: PatientHistory, episode_id: str) -> EpisodeDetail:
    ep = next(e for e in history.episodes if e.id == episode_id)
    visit = _encounter(history, ep.reported_at)
    # Medication the patient was on when it happened, not what the visit then changed.
    meds = medications_on(history, ep.date or visit.date)
    if not ep.date:
        # Undated: assume it happened before the visit, so drop drugs that visit started.
        meds = [m for m in meds if m.course_start != visit.date]
    labs, imaging, other = _split_tests(visit.investigations)
    return EpisodeDetail(
        episode=ep,
        reported_at=visit,
        negative_history=visit.negative_history,
        medications_at_time=meds,
        labs=labs,
        imaging=imaging,
        other_tests=other,
        episodes_at_same_visit=[e.id for e in history.episodes if e.reported_at == visit.id and e.id != ep.id],
        source_pages=visit.page_ids,
    )


def visit_detail(history: PatientHistory, encounter_id: str) -> VisitDetail:
    visit = _encounter(history, encounter_id)
    labs, imaging, other = _split_tests(visit.investigations)
    return VisitDetail(
        visit=visit,
        episodes=[e for e in history.episodes if e.reported_at == visit.id],
        medications_at_time=medications_on(history, visit.date),
        labs=labs,
        imaging=imaging,
        other_tests=other,
    )
