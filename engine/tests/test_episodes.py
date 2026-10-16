"""The seizure example: 4 visits, 13 reported episodes, one (Dec 2024) the worst."""

import pytest

from medtimeline.details import episode_detail, visit_detail
from medtimeline.schema import ExtractionRecord, PageExtraction
from medtimeline.timeline import build_history
from medtimeline.views import build_view


def _ep(when, date, count=1, worst=False, precision="month", **kw):
    return {"symptom": "seizure", "when_raw": when, "date_iso": date, "date_precision": precision,
            "count": count, "is_worst": worst, "confidence": 0.9, "source_text": when, **kw}


def _med(name, strength, freq="BD"):
    return {"drug_as_written": name, "strength": strength, "frequency": freq, "confidence": 0.9, "source_text": name}


def _page(n, date, episodes, meds, tests=(), negatives=(), complaints=("seizures",), dx=()):
    return ExtractionRecord(
        page_id=f"p{n}", source_file=f"visit{n}.pdf", page_number=1, extractor="test",
        extraction=PageExtraction.model_validate({
            "doc_type": "case_sheet", "script": "handwritten",
            "encounter": {"date_iso": date, "facility": "Neuro OPD"}, "patient": {"name": "Demo"},
            "complaints": list(complaints), "episodes": episodes, "medications": meds,
            "investigations": list(tests), "negative_history": list(negatives),
            "diagnoses": [{"text": t, "known": known, "confidence": 0.9, "source_text": t} for t, known in dx],
        }),
    )


@pytest.fixture
def history():
    return build_history([
        _page(1, "2024-03-14", [_ep("Jan 2024", "2024-01-15"), _ep("Feb 2024", "2024-02-20")],
              [_med("Levetiracetam", "500 mg")], dx=[("Focal epilepsy", False), ("Hypothyroidism", True)]),
        _page(2, "2024-07-02", [_ep("3 since last visit", None, count=3, precision="unknown")],
              [_med("Levetiracetam", "750 mg")], dx=[("Focal epilepsy", False), ("Hypothyroidism", True)]),
        _page(3, "2024-12-23", [
            _ep("Sep-Nov 2024", None, count=3, precision="unknown"),
            _ep("last night", "2024-12-22", worst=True, precision="day",
                description="Focal to bilateral tonic-clonic, 4 min", triggers=["missed doses"]),
        ], [_med("Levetiracetam", "750 mg"), _med("Clobazam", "10 mg", "HS")],
            tests=[
                {"name": "MRI brain", "kind": "imaging", "status": "resulted", "value": "L hippocampal sclerosis", "confidence": 0.9, "source_text": "MRI"},
                {"name": "Serum sodium", "kind": "lab", "status": "resulted", "value": "131", "unit": "mmol/L", "abnormal": True, "confidence": 0.9, "source_text": "Na 131"},
                {"name": "EEG", "kind": "study", "status": "ordered", "confidence": 0.9, "source_text": "EEG"},
            ],
            negatives=["no fever", "no head injury"], dx=[("Focal epilepsy", False), ("Hyponatraemia", False)]),
        _page(4, "2025-04-10", [_ep("4 brief ones", None, count=4, precision="unknown")],
              [_med("Levetiracetam", "1000 mg")], dx=[("Focal epilepsy", False), ("Anxiety", False)]),
    ])


def test_reported_episodes_outnumber_visits(history):
    [seizures] = [s for s in history.symptoms if s.name == "seizures"]
    assert len(seizures.encounter_ids) == 4
    assert sum(e.count for e in seizures.episodes) == 13
    [row] = build_view(history, "symptoms", "episodes").rows
    assert (row.visit_count, row.episode_count) == (4, 13)


def test_worst_episode_detail(history):
    worst = next(e for e in history.episodes if e.is_worst)
    d = episode_detail(history, worst.id)
    assert d.episode.date == "2024-12-22"
    assert d.reported_at.date == "2024-12-23"
    assert d.negative_history == ["no fever", "no head injury"]
    # On the night it happened only levetiracetam 750 mg had been prescribed; clobazam came after.
    assert [(m.drug, m.dose.strength) for m in d.medications_at_time] == [("levetiracetam", "750 mg")]
    assert [t.name for t in d.imaging] == ["MRI brain"]
    assert [t.name for t in d.labs] == ["Serum sodium"]
    assert [t.name for t in d.other_tests] == ["EEG"]
    assert len(d.episodes_at_same_visit) == 1


def test_undated_episodes_exclude_drugs_started_at_that_visit(history):
    undated = next(e for e in history.episodes if e.reported_at == history.encounters[2].id and not e.is_worst)
    d = episode_detail(history, undated.id)
    assert [m.drug for m in d.medications_at_time] == ["levetiracetam"]


def test_visit_detail_lists_its_episodes(history):
    d = visit_detail(history, history.encounters[2].id)
    assert sum(e.count for e in d.episodes) == 4
    assert {m.drug for m in d.medications_at_time} == {"levetiracetam", "clobazam"}


def test_symptom_without_reports_falls_back_to_visits(sample_folder):
    from medtimeline.extract import get_extractor
    from medtimeline.ingest import load_folder

    ex = get_extractor("fixture")
    h = build_history([
        ExtractionRecord(page_id=p.page_id, source_file=p.source_file, page_number=p.page_number,
                         extractor=ex.name, extraction=ex.extract(p))
        for p in load_folder(sample_folder)
    ])
    pain = next(s for s in h.symptoms if s.name == "epigastric pain")
    assert len(pain.episodes) == 2 and all(e.id is None for e in pain.episodes)


def test_correlation_windows(history):
    from medtimeline.correlation import correlate

    changes = correlate(history)
    assert [(c.date, c.drug, c.kind) for c in changes] == [
        ("2024-03-14", "levetiracetam", "started"),
        ("2024-07-02", "levetiracetam", "dose change"),
        ("2024-12-23", "clobazam", "started"),
        ("2025-04-10", "levetiracetam", "dose change"),
    ]
    start, raise_750, clobazam, raise_1000 = changes
    assert start.before.episodes == 2 and start.after.episodes == 3
    # The worst seizure (22 Dec) falls just before clobazam was added.
    assert raise_750.after.episodes == 4 and raise_750.after.worst_episodes == 1
    assert clobazam.after.episodes == 4 and clobazam.after.worst_episodes == 0
    assert raise_1000.after is None  # nothing recorded after the last visit yet
    assert raise_750.previous_dose == "500 mg BD" and raise_750.dose == "750 mg BD"


def test_visit_flags_mark_what_was_new(history):
    from medtimeline.details import visit_flags

    first = {(f.kind, f.text) for f in visit_flags(history, history.encounters[0].id)}
    assert ("new_symptom", "seizures") in first
    assert ("medication_change", "levetiracetam started, 500 mg BD") in first
    assert ("new_diagnosis", "Focal epilepsy") in first
    assert ("known_comorbidity", "Hypothyroidism") in first
    third = {(f.kind, f.text) for f in visit_flags(history, history.encounters[2].id)}
    assert ("new_comorbidity", "Hyponatraemia") in third
    assert not any(t == "Focal epilepsy" for _, t in third)  # already recorded at earlier visits
    # Visit 2 repeats epilepsy and hypothyroidism, so only the dose change is new.
    second = [f.kind for f in visit_flags(history, history.encounters[1].id)]
    assert second == ["medication_change"]
    fourth = {(f.kind, f.text) for f in visit_flags(history, history.encounters[3].id)}
    assert ("new_comorbidity", "Anxiety") in fourth
