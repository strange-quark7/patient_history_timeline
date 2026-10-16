"""Everything the app needs to draw one patient, as one JSON-ready dict.

The app only displays; every rule (flags, links, episodes, correlation) runs here,
so the desktop UI and the tests see the same answers.
"""

from __future__ import annotations

import re
from typing import Optional

from medtimeline import identity, normalize
from medtimeline.correlation import correlate, medication_changes
from medtimeline.details import episode_detail, medications_on, visit_flags
from medtimeline.schema import ExtractionRecord
from medtimeline.timeline import PatientHistory, _linked_condition, build_history

SHORT = {"urinary tract infection": "UTI", "type 2 diabetes mellitus": "Type 2 diabetes", "chronic kidney disease": "CKD"}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def _dose(m) -> str:
    return " ".join(x for x in [m.strength, normalize.expand_frequency(m.frequency) or m.frequency] if x)


def _identity_review(p: identity.PageIdentity, profile: identity.Profile, page: dict) -> dict:
    said = ", ".join(x for x in [p.name_on_page or "no name", p.age_on_page and f"age {p.age_on_page}", p.sex_on_page] if x)
    return {"page_id": p.page_id, "section": "patient", "field": "identity", "blocking": True,
            "reason": "; ".join(p.reasons) or "Not checked", "source_text": None, "page": page,
            "key": identity.key(p.page_id), "reading": said, "value": None, "options": [identity.YES, identity.NO],
            "resolved": p.answer is not None, "choice": p.answer, "verdict": p.verdict, "question": f"Is this page for {profile.name}?"}


def make_bundle(records: list[ExtractionRecord], history: Optional[PatientHistory] = None,
                resolutions: Optional[dict[str, dict]] = None, patient_name: Optional[str] = None) -> dict:
    """`patient_name` is what the user called the patient; pages are checked against it (see identity.py)
    and only pages that match, or that a reviewer confirmed, go into the history."""
    all_pages = {r.page_id: {"page_id": r.page_id, "file": r.source_file.rsplit("/", 1)[-1], "page": r.page_number,
                             "grounding": r.grounding, "script": r.extraction.script.value, "doc_type": r.extraction.doc_type.value,
                             "batch": r.batch} for r in records}
    profile, checks = identity.check_pages(records, patient_name, resolutions)
    for c in checks:
        all_pages[c.page_id]["identity"] = c.verdict if c.answer is None else ("confirmed" if c.answer == identity.YES else "not this patient")
    keep = {c.page_id for c in checks if c.included}
    identity_items = [_identity_review(c, profile, all_pages[c.page_id]) for c in checks if c.verdict != "match" or c.answer]
    records = [r for r in records if r.page_id in keep]
    h = history or build_history(records, resolutions)
    cond_id = {c.name: slug(c.name) for c in h.conditions}
    names = list(cond_id)
    pages = {p: all_pages[p] for p in keep}
    dates = [e.date for e in h.encounters if e.date] + [ep.date for ep in h.episodes if ep.date]
    enc_by_id = {e.id: e for e in h.encounters}
    last_visit = max((e.date for e in h.encounters if e.date), default=None)

    conditions = [{
        "id": cond_id[c.name], "name": c.name, "short": SHORT.get(c.name.lower(), c.name),
        "course": c.course, "role": c.role, "known": c.known_at_first_mention,
        "first_seen": c.first_seen, "last_seen": c.last_seen, "encounter_ids": c.encounter_ids,
        "episodes": [{"start": e.start, "end": e.end, "encounter_ids": e.encounter_ids} for e in c.episodes],
    } for c in h.conditions]

    tests, test_ids_by_enc = [], {}
    for e in h.encounters:
        for i, t in enumerate(e.investigations):
            tid = f"{e.id}-t{i + 1}"
            linked = _linked_condition(e, t.name, names)
            tests.append({"id": tid, "name": t.name, "kind": t.kind, "status": t.status, "value": t.value, "unit": t.unit,
                          "reference_range": t.reference_range, "abnormal": t.abnormal, "encounter_id": e.id, "date": e.date,
                          "condition_id": cond_id.get(linked), "source_text": t.source_text,
                          "labelled_by_user": t.labelled_by_user})
            test_ids_by_enc.setdefault(e.id, []).append(tid)

    episodes = []
    for ep in h.episodes:
        written, _ = normalize.parse_date(ep.when_raw)
        detail = episode_detail(h, ep.id)
        episodes.append({
            **ep.model_dump(), "condition_id": cond_id.get(ep.condition),
            "approx_date": bool(ep.date) and not written and ep.date_precision != "day",
            "medications_at_time": [{"med_id": slug(m.drug), "dose": _dose(m.dose)} for m in detail.medications_at_time],
        })

    meds = []
    for c in h.medication_courses:
        mid = slug(c.drug)
        steps = [{"encounter_id": i, "date": enc_by_id[i].date, "dose": _dose(m), "duration": m.duration,
                  "status": m.status, "as_written": m.drug_as_written, "source_text": m.source_text,
                  "labelled_by_user": m.labelled_by_user} for i, m in zip(c.encounter_ids, c.entries)]
        meds.append({"id": mid, "drug": c.drug, "label": c.entries[0].generic_name or c.entries[0].drug_as_written,
                     "start": c.start, "end": c.end, "status": c.entries[-1].status,
                     "current": bool(c.end and last_visit and c.end >= last_visit) and c.entries[-1].status == "prescribed",
                     "condition_id": cond_id.get(c.condition), "condition_basis": c.condition_basis, "steps": steps,
                     "periods": [{"start": p.start, "end": p.end, "encounter_id": p.encounter_id, "dose": _dose(p.entry)} for p in c.periods]})

    changes = [{"id": f"chg-{n}", "date": d, "med_id": slug(drug), "drug": drug, "kind": kind, "dose": dose,
                "previous_dose": prev, "encounter_id": enc}
               for n, (d, drug, kind, dose, prev, enc) in enumerate(medication_changes(h), start=1)]

    def corr(condition: Optional[str]) -> list[dict]:
        return [c.model_dump() for c in correlate(h, condition=condition)]

    encounters = []
    for e in h.encounters:
        encounters.append({
            "id": e.id, "date": e.date, "date_status": e.date_status, "facility": e.facility, "clinician": e.clinician,
            "encounter_type": e.encounter_type, "complaints": e.complaints, "negative_history": e.negative_history,
            "advice": e.advice, "diagnoses": [{"text": d.text, "known": d.known} for d in e.diagnoses],
            "vitals": [{"name": v.name, "value": v.value, "unit": v.unit} for v in e.vitals],
            "medications": [{"med_id": slug(normalize.normalize_drug_key(m.generic_name or m.drug_as_written) or m.drug_as_written),
                             "label": m.generic_name or m.drug_as_written, "dose": _dose(m), "duration": m.duration,
                             "status": m.status} for m in e.medications],
            "condition_ids": [cond_id[c.name] for c in h.conditions if e.id in c.encounter_ids],
            "flags": [f.model_dump() for f in visit_flags(h, e.id)],
            "test_ids": test_ids_by_enc.get(e.id, []),
            "episode_ids": [ep.id for ep in h.episodes if ep.reported_at == e.id],
            "medications_at_time": [{"med_id": slug(m.drug), "dose": _dose(m.dose)} for m in medications_on(h, e.date)],
            "pages": [pages[p] for p in e.page_ids if p in pages],
            "added_later": all(pages[p]["batch"] > 0 for p in e.page_ids if p in pages),
            "needs_review": e.needs_review,
        })

    symptoms = [{
        "id": slug(s.name), "name": s.name, "first_seen": s.first_seen, "last_seen": s.last_seen,
        "encounter_ids": s.encounter_ids, "episode_ids": [x.id for x in s.episodes if x.id],
        "episode_count": sum(x.count for x in s.episodes),
        "occurrences": [{"encounter_id": o.encounter_id, "date": o.date, "condition_id": cond_id.get(o.condition)} for o in s.occurrences],
        "condition_ids": [cond_id[c] for c in s.conditions],
    } for s in h.symptoms]

    return {
        "patient": {"name": profile.name or h.patient_name, "sex": profile.sex, "born_about": profile.born_about,
                    "identifiers": profile.identifiers},
        "pages_left_out": [all_pages[c.page_id] for c in checks if not c.included],
        "span": {"start": min(dates, default=None), "end": max(dates, default=None)},
        "conditions": conditions, "encounters": encounters, "episodes": episodes, "symptoms": symptoms,
        "medications": meds, "changes": changes, "tests": tests,
        "correlation": {"all": corr(None), **{cond_id[c.name]: corr(c.name) for c in h.conditions}},
        "review_items": identity_items + [{**r.model_dump(), "page": pages.get(r.page_id)} for r in h.review_items],
        "pages_needing_review": h.pages_needing_review,
    }


MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _day(d: Optional[str]) -> str:
    if not d:
        return "an undated visit"
    y, m, dd = d.split("-")
    return f"{int(dd)} {MONTHS[int(m) - 1]} {y}"


def update_notes(before: dict, after: dict, new_page_ids: set[str]) -> list[str]:
    """What a later upload changed, in plain words, by comparing the bundle before and after."""
    n = len(new_page_ids)
    notes = [f"{n} page{'s' if n != 1 else ''} added."]
    doubts = [r for r in after["review_items"] if r["field"] == "identity" and not r["resolved"] and r["page_id"] in new_page_ids]
    if doubts:
        notes.append(f"{len(doubts)} of them may be for a different patient and {'is' if len(doubts) == 1 else 'are'} "
                     f"left out until you answer yes or no in Needs review.")
    old_dates = {e["date"] for e in before["encounters"]}
    new_visits = sorted((e["date"] or "") for e in after["encounters"]
                        if any(p["page_id"] in new_page_ids for p in e["pages"]) and e["date"] not in old_dates)
    if new_visits:
        earliest, first_before = new_visits[0] or None, before["span"]["start"]
        older = " (earlier than anything recorded before)" if earliest and first_before and earliest < first_before else ""
        notes.append(f"{len(new_visits)} visit{'s' if len(new_visits) != 1 else ''} added"
                     f"{f', the earliest on {_day(earliest)}' if earliest else ''}{older}.")
    was = {c["name"]: c for c in before["conditions"]}
    for c in after["conditions"]:
        old = was.get(c["name"])
        if not old:
            notes.append(f"{c['name']} appears for the first time, first recorded on {_day(c['first_seen'])}.")
        elif c["first_seen"] and old["first_seen"] and c["first_seen"] < old["first_seen"]:
            notes.append(f"{c['name']} is now first recorded on {_day(c['first_seen'])} (was {_day(old['first_seen'])}), "
                         f"so its 'new diagnosis' marker moves to that visit.")
    was_meds = {m["id"]: m for m in before["medications"]}
    for m in after["medications"]:
        old = was_meds.get(m["id"])
        if not old:
            notes.append(f"{m['label']} appears for the first time, on {_day(m['start'] or m['end'])}.")
        elif m["start"] and old["start"] and m["start"] < old["start"]:
            notes.append(f"{m['label']} is now first recorded on {_day(m['start'])} (was {_day(old['start'])}).")
    return notes
