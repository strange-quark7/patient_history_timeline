"""Line medication starts and dose changes up against episodes.

For each change, compare episodes in the window since the previous change with
the window until the next one. This shows timing only, not cause.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel

from medtimeline.timeline import PatientHistory

DAYS_PER_MONTH = 30.44


class Window(BaseModel):
    start: str
    end: str
    episodes: int
    worst_episodes: int
    per_month: float


class MedicationChange(BaseModel):
    date: str
    drug: str
    kind: str  # "started" or "dose change"
    dose: Optional[str]
    previous_dose: Optional[str]
    encounter_id: str
    before: Optional[Window]
    after: Optional[Window]


def medication_changes(history: PatientHistory) -> list[tuple[str, str, str, Optional[str], Optional[str], str]]:
    """(date, drug, kind, dose, previous dose, encounter id) for each start or strength change."""
    dates = {e.id: e.date for e in history.encounters}
    out = []
    for course in history.medication_courses:
        previous = None
        for enc_id, entry in zip(course.encounter_ids, course.entries):
            day = dates[enc_id]
            if not day:
                continue
            dose = " ".join(x for x in [entry.strength, entry.frequency] if x) or None
            if previous is None:
                out.append((day, course.drug, "started", dose, None, enc_id))
            elif dose and dose != previous:
                out.append((day, course.drug, "dose change", dose, previous, enc_id))
            previous = dose or previous
    return sorted(out)


def _episode_dates(history: PatientHistory) -> list[tuple[str, int, bool]]:
    """(date, count, is_worst). Undated reports count just before the visit that recorded them."""
    dates = {e.id: e.date for e in history.encounters}
    out = []
    for ep in history.episodes:
        day = ep.date
        if not day:
            visit_day = dates.get(ep.reported_at)
            if not visit_day:
                continue
            day = date.fromordinal(date.fromisoformat(visit_day).toordinal() - 1).isoformat()
        out.append((day, ep.count, ep.is_worst))
    return out


def _window(eps: list[tuple[str, int, bool]], start: str, end: str) -> Optional[Window]:
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    if days <= 0:
        return None
    inside = [e for e in eps if start <= e[0] < end]
    n = sum(c for _, c, _ in inside)
    return Window(
        start=start, end=end, episodes=n,
        worst_episodes=sum(c for _, c, w in inside if w),
        per_month=round(n / (days / DAYS_PER_MONTH), 2),
    )


def correlate(history: PatientHistory, until: Optional[str] = None) -> list[MedicationChange]:
    eps = _episode_dates(history)
    changes = medication_changes(history)
    all_days = sorted([d for d, _, _ in eps] + [e.date for e in history.encounters if e.date])
    if not all_days or not changes:
        return []
    first, last = all_days[0], until or all_days[-1]
    change_days = sorted({c[0] for c in changes})
    out = []
    for day, drug, kind, dose, prev, enc_id in changes:
        i = change_days.index(day)
        before_start = change_days[i - 1] if i > 0 else first
        after_end = change_days[i + 1] if i + 1 < len(change_days) else last
        out.append(MedicationChange(
            date=day, drug=drug, kind=kind, dose=dose, previous_dose=prev, encounter_id=enc_id,
            before=_window(eps, before_start, day), after=_window(eps, day, after_end),
        ))
    return out
