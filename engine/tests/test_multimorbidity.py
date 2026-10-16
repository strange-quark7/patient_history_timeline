"""Several unrelated conditions: diabetes, known hypertension, epilepsy and recurrent UTIs.

Frequent urination appears at three visits: tied to diabetes by the first page,
to a UTI by the third, and to nothing by the last, so it stays unlinked there.
"""

import pytest

from medtimeline.correlation import correlate
from medtimeline.details import visit_flags
from medtimeline.schema import ExtractionRecord, PageExtraction
from medtimeline.timeline import build_history
from medtimeline.verify import verify_page
from medtimeline.views import build_view

DM, HTN, EPI, UTI = "Type 2 diabetes mellitus", "Hypertension", "Epilepsy", "Urinary tract infection"


def _item(**kw):
    return {"confidence": 0.9, "source_text": kw.pop("q", "x"), **kw}


def _page(n, date, facility, complaints=(), dx=(), meds=(), episodes=(), links=()):
    return ExtractionRecord(
        page_id=f"p{n}", source_file=f"visit{n}.pdf", page_number=1, extractor="test",
        extraction=PageExtraction.model_validate({
            "doc_type": "case_sheet", "script": "handwritten",
            "encounter": {"date_iso": date, "facility": facility}, "patient": {"name": "Demo"},
            "complaints": list(complaints),
            "diagnoses": [_item(text=t, known=k) for t, k in dx],
            "medications": [_item(drug_as_written=d, strength=st) for d, st in meds],
            "episodes": [_item(symptom="seizure", when_raw=w, count=c) for w, c in episodes],
            "links": [_item(item=i, condition=c) for i, c in links],
        }),
    )


@pytest.fixture
def history():
    return build_history([
        _page(1, "2024-01-10", "GP clinic", ["frequent urination", "thirst"], [(DM, False), (HTN, True)],
              [("Metformin", "500 mg"), ("Amlodipine", "5 mg")],
              links=[("frequent urination", "?DM"), ("thirst", "?DM")]),
        _page(2, "2024-03-05", "Neuro OPD", ["seizures"], [(EPI, False), (DM, True), (HTN, True)],
              [("Levetiracetam", "500 mg"), ("Metformin", "500 mg"), ("Amlodipine", "5 mg")], episodes=[("Feb", 2)]),
        _page(3, "2024-05-20", "GP clinic", ["burning micturition", "frequent urination", "fever"], [(UTI, False), (DM, True)],
              [("Nitrofurantoin", "100 mg"), ("Metformin", "500 mg")],
              links=[("burning micturition", "UTI"), ("frequent urination", "UTI")]),
        _page(4, "2024-05-28", "GP clinic", ["burning better"], [(UTI, False)]),
        _page(5, "2024-09-02", "GP clinic", ["burning micturition"], [(UTI, False)], [("Nitrofurantoin", "100 mg")],
              links=[("burning micturition", "UTI")]),
        _page(6, "2024-11-15", "Neuro OPD", ["seizures", "frequent urination"], [(EPI, False)],
              [("Levetiracetam", "750 mg")], episodes=[("since last visit", 3)]),
    ])


def test_every_condition_is_its_own_track(history):
    by_name = {c.name: c for c in history.conditions}
    assert (by_name[DM].course, by_name[DM].role) == ("long_term", "primary")
    assert (by_name[HTN].course, by_name[HTN].role) == ("long_term", "comorbidity")
    assert (by_name[EPI].course, by_name[EPI].role) == ("long_term", "comorbidity")
    uti = by_name[UTI]
    assert (uti.course, uti.role) == ("acute", "acute")
    # 20 May and 28 May are one UTI; 2 Sep is a second one.
    assert [(e.start, e.end) for e in uti.episodes] == [("2024-05-20", "2024-05-28"), ("2024-09-02", "2024-09-02")]


def test_acute_visits_are_flagged_per_recurrence(history):
    kinds = lambda i: {(f.kind, f.text) for f in visit_flags(history, history.encounters[i].id)}
    assert ("acute_illness", f"{UTI} (episode 1)") in kinds(2)
    assert not any(k == "acute_illness" for k, _ in kinds(3))  # the follow-up 8 days later is the same UTI
    assert ("acute_illness", f"{UTI} (episode 2)") in kinds(4)
    first = kinds(0)
    assert ("new_diagnosis", DM) in first and ("known_comorbidity", HTN) in first
    assert ("new_comorbidity", EPI) in kinds(1)


def test_overlapping_symptom_is_attributed_per_visit(history):
    freq = next(s for s in history.symptoms if s.name == "frequent urination")
    assert [(o.date, o.condition) for o in freq.occurrences] == [
        ("2024-01-10", DM), ("2024-05-20", UTI), ("2024-11-15", None)]
    fever = next(s for s in history.symptoms if s.name == "fever")
    assert fever.conditions == []  # the page did not say, so it stays unlinked


def test_drugs_link_only_when_one_condition_fits(history):
    courses = {c.drug: (c.condition, c.condition_basis) for c in history.medication_courses}
    assert courses["metformin"] == (DM, "drug_table")
    assert courses["amlodipine"] == (HTN, "drug_table")
    assert courses["levetiracetam"] == (EPI, "drug_table")
    assert courses["nitrofurantoin"] == (UTI, "drug_table")


def test_condition_filter(history):
    uti_symptoms = {r.label for r in build_view(history, "symptoms", condition=UTI).rows}
    assert uti_symptoms == {"burning micturition", "frequent urination"}
    epi_meds = [r.label for r in build_view(history, "medications", condition=EPI).rows]
    assert epi_meds == ["Levetiracetam"]
    epi_visits = [r.first_seen for r in build_view(history, "visits", condition=EPI).rows]
    assert epi_visits == ["2024-03-05", "2024-11-15"]


def test_correlation_one_condition_at_a_time(history):
    changes = correlate(history, symptom="seizure", condition=EPI)
    assert {c.drug for c in changes} == {"levetiracetam"}
    raise_750 = next(c for c in changes if c.kind == "dose change")
    assert raise_750.before.episodes == 3  # the 3 seizures reported on 15 Nov; UTIs are not counted


def test_link_must_be_written_on_the_page():
    page = "c/o frequent urination, thirst - ?DM. K/c/o HTN."
    x = PageExtraction.model_validate({
        "doc_type": "case_sheet", "script": "typed", "encounter": {}, "patient": {},
        "links": [{"item": "frequent urination", "condition": "UTI", "confidence": 0.9,
                   "source_text": "c/o frequent urination, thirst - ?DM"}],
    })
    issues, _ = verify_page(x, page * 2)
    assert [(i.section, i.field) for i in issues] == [("links", "condition")]
