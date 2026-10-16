"""Everything the app needs to draw one patient, as one JSON-ready dict.

The app only displays; every rule (flags, links, episodes, correlation) runs here,
so the desktop UI and the tests see the same answers.
"""

from __future__ import annotations

import re
from typing import Optional

from medtimeline import normalize
from medtimeline.correlation import correlate, medication_changes
from medtimeline.details import episode_detail, medications_on, visit_flags
from medtimeline.schema import ExtractionRecord
from medtimeline.timeline import PatientHistory, _linked_condition, build_history

SHORT = {"urinary tract infection": "UTI", "type 2 diabetes mellitus": "Type 2 diabetes", "chronic kidney disease": "CKD"}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def _dose(m) -> str:
    return " ".join(x for x in [m.strength, normalize.expand_frequency(m.frequency) or m.frequency] if x)


def make_bundle(records: list[ExtractionRecord], history: Optional[PatientHistory] = None,
                resolutions: Optional[dict[str, dict]] = None) -> dict:
    h = history or build_history(records, resolutions)
    cond_id = {c.name: slug(c.name) for c in h.conditions}
    names = list(cond_id)
    pages = {r.page_id: {"page_id": r.page_id, "file": r.source_file.rsplit("/", 1)[-1], "page": r.page_number,
                         "grounding": r.grounding, "script": r.extraction.script.value, "doc_type": r.extraction.doc_type.value}
             for r in records}
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
        "patient": {"name": h.patient_name, "conflicts": h.patient_conflicts},
        "span": {"start": min(dates, default=None), "end": max(dates, default=None)},
        "conditions": conditions, "encounters": encounters, "episodes": episodes, "symptoms": symptoms,
        "medications": meds, "changes": changes, "tests": tests,
        "correlation": {"all": corr(None), **{cond_id[c.name]: corr(c.name) for c in h.conditions}},
        "review_items": [{**r.model_dump(), "page": pages.get(r.page_id)} for r in h.review_items],
        "pages_needing_review": h.pages_needing_review,
    }
