"""Ways to slice and sort a PatientHistory for display.

A view is a list of rows (lanes on a timeline). Each lens decides what a row
is: one visit, one symptom, one medication, and so on. Each sort decides the
row order. The app picks a lens and a sort; the engine does the work so every
screen sorts the same way.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from medtimeline.timeline import Episode, PatientHistory


class Lens(str, Enum):
    visits = "visits"
    symptoms = "symptoms"
    medications = "medications"
    symptoms_medications = "symptoms_medications"
    conditions = "conditions"
    labs = "labs"


class SortBy(str, Enum):
    chronological = "chronological"  # earliest first
    recent = "recent"  # most recently seen first
    episodes = "episodes"  # most episodes first
    visits = "visits"  # seen at the most visits first
    duration = "duration"  # longest span first
    name = "name"


class Event(BaseModel):
    date: Optional[str]
    encounter_id: str
    detail: Optional[str] = None


class Row(BaseModel):
    kind: str = Field(description="visit, symptom, medication, condition or lab.")
    label: str
    first_seen: Optional[str]
    last_seen: Optional[str]
    visit_count: int
    episode_count: int
    episodes: list[Episode] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    related: list[str] = Field(
        default_factory=list,
        description="For symptoms+medications: items of the other kind seen at the same visits.",
    )


class View(BaseModel):
    lens: Lens
    sort: SortBy
    rows: list[Row]


def _span_days(row: Row) -> int:
    if not (row.first_seen and row.last_seen):
        return -1
    return (date.fromisoformat(row.last_seen) - date.fromisoformat(row.first_seen)).days


_SORTS = {
    # Undated rows always go last for date-based sorts.
    SortBy.chronological: lambda r: (r.first_seen is None, r.first_seen or "", r.label.lower()),
    SortBy.recent: lambda r: (r.last_seen is None, _neg_date(r.last_seen), r.label.lower()),
    SortBy.episodes: lambda r: (-r.episode_count, -r.visit_count, r.label.lower()),
    SortBy.visits: lambda r: (-r.visit_count, -r.episode_count, r.label.lower()),
    SortBy.duration: lambda r: (-_span_days(r), r.label.lower()),
    SortBy.name: lambda r: r.label.lower(),
}


def _neg_date(d: Optional[str]) -> int:
    return -date.fromisoformat(d).toordinal() if d else 0


def _dates(history: PatientHistory) -> dict[str, Optional[str]]:
    return {e.id: e.date for e in history.encounters}


def _visit_rows(h: PatientHistory) -> list[Row]:
    rows = []
    for e in h.encounters:
        summary = ", ".join(d.text for d in e.diagnoses) or ", ".join(e.complaints) or None
        rows.append(Row(
            kind="visit",
            label=" · ".join(x for x in [e.date or "Undated", e.facility, e.clinician] if x),
            first_seen=e.date, last_seen=e.date, visit_count=1, episode_count=1,
            events=[Event(date=e.date, encounter_id=e.id, detail=summary)],
        ))
    return rows


def _symptom_rows(h: PatientHistory) -> list[Row]:
    dates = _dates(h)
    return [
        Row(kind="symptom", label=s.name, first_seen=s.first_seen, last_seen=s.last_seen,
            visit_count=len(s.encounter_ids), episode_count=sum(e.count for e in s.episodes), episodes=s.episodes,
            events=[Event(date=dates[i], encounter_id=i) for i in s.encounter_ids])
        for s in h.symptoms
    ]


def _condition_rows(h: PatientHistory) -> list[Row]:
    dates = _dates(h)
    return [
        Row(kind="condition", label=c.name, first_seen=c.first_seen, last_seen=c.last_seen,
            visit_count=len(c.encounter_ids), episode_count=len(c.episodes), episodes=c.episodes,
            events=[Event(date=dates[i], encounter_id=i) for i in c.encounter_ids])
        for c in h.conditions
    ]


def _medication_rows(h: PatientHistory) -> list[Row]:
    from medtimeline.timeline import episodes_from

    dates = _dates(h)
    rows = []
    for c in h.medication_courses:
        mentions = [(dates[i], i) for i in dict.fromkeys(c.encounter_ids)]
        episodes = episodes_from(mentions)
        events = [
            Event(date=dates[i], encounter_id=i,
                  detail=" ".join(x for x in [m.strength, m.frequency, m.duration] if x) or None)
            for i, m in zip(c.encounter_ids, c.entries)
        ]
        label = c.entries[0].generic_name or c.entries[0].drug_as_written
        rows.append(Row(kind="medication", label=label, first_seen=c.start, last_seen=c.end,
                        visit_count=len(set(c.encounter_ids)), episode_count=len(episodes),
                        episodes=episodes, events=events))
    return rows


def _lab_rows(h: PatientHistory) -> list[Row]:
    rows = []
    for s in h.lab_series:
        dated = sorted(p.date for p in s.points if p.date)
        rows.append(Row(
            kind="lab", label=s.test,
            first_seen=dated[0] if dated else None, last_seen=dated[-1] if dated else None,
            visit_count=len({p.encounter_id for p in s.points}), episode_count=len(s.points),
            events=[Event(date=p.date, encounter_id=p.encounter_id,
                          detail=f"{p.value} {p.unit or ''}".strip()) for p in s.points],
        ))
    return rows


def _link(rows_a: list[Row], rows_b: list[Row]) -> None:
    """Fill `related` on both sides with items seen at the same visits."""
    for a in rows_a:
        enc_a = {e.encounter_id for e in a.events}
        for b in rows_b:
            if enc_a & {e.encounter_id for e in b.events}:
                a.related.append(b.label)
                b.related.append(a.label)


def build_view(
    history: PatientHistory,
    lens: Lens | str = Lens.visits,
    sort: SortBy | str = SortBy.chronological,
    query: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> View:
    """Rows for one lens, filtered by text and date range, in the chosen order."""
    lens, sort = Lens(lens), SortBy(sort)
    if lens is Lens.visits:
        rows = _visit_rows(history)
    elif lens is Lens.symptoms:
        rows = _symptom_rows(history)
    elif lens is Lens.medications:
        rows = _medication_rows(history)
    elif lens is Lens.conditions:
        rows = _condition_rows(history)
    elif lens is Lens.labs:
        rows = _lab_rows(history)
    else:
        symptoms, meds = _symptom_rows(history), _medication_rows(history)
        _link(symptoms, meds)
        rows = symptoms + meds

    if query:
        q = query.lower()
        rows = [r for r in rows if q in r.label.lower() or any(q in x.lower() for x in r.related)]
    if start or end:
        def in_range(r: Row) -> bool:
            return any(e.date and (not start or e.date >= start) and (not end or e.date <= end) for e in r.events)
        rows = [r for r in rows if in_range(r)]

    rows.sort(key=_SORTS[sort])
    return View(lens=lens, sort=sort, rows=rows)
