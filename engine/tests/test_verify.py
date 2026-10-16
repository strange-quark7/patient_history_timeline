"""Deterministic grounding checks, on a typed diabetes / hypertension page."""

from medtimeline.schema import ExtractionRecord, PageExtraction
from medtimeline.timeline import build_history
from medtimeline.verify import gate, name_in_quote, quote_found, verify_page

PAGE = """Date: 12/03/2025  Medicine OPD
C/o increased thirst, 2 episodes of giddiness this week.
K/c/o HTN on treatment. No chest pain. No vomiting.
FBS 182 mg/dl  HbA1c 8.4 %  BP 150/94
Rx: Tab Metformin 500 mg 1-0-1 x 30 days
    Tab Amlodipine 5 mg 0-0-1
"""


def _x(**over):
    data = {
        "transcription": None, "doc_type": "case_sheet", "script": "typed",
        "encounter": {"date_raw": "12/03/2025", "date_iso": "2025-03-12"}, "patient": {},
        "complaints": ["increased thirst"],
        "episodes": [{"symptom": "giddiness", "when_raw": "this week", "count": 2,
                      "confidence": 0.9, "source_text": "2 episodes of giddiness this week"}],
        "negative_history": ["No chest pain", "No vomiting"],
        "diagnoses": [{"text": "Hypertension", "known": True, "confidence": 0.9, "source_text": "K/c/o HTN"}],
        "medications": [
            {"drug_as_written": "Metformin", "strength": "500 mg", "frequency": "1-0-1", "duration": "30 days",
             "confidence": 0.9, "source_text": "Tab Metformin 500 mg 1-0-1 x 30 days"},
            {"drug_as_written": "Amlodipine", "strength": "5 mg", "frequency": "0-0-1",
             "confidence": 0.9, "source_text": "Tab Amlodipine 5 mg 0-0-1"},
        ],
        "investigations": [
            {"name": "Fasting blood sugar", "status": "resulted", "value": "182", "unit": "mg/dl",
             "confidence": 0.9, "source_text": "FBS 182 mg/dl"},
            {"name": "HbA1c", "status": "resulted", "value": "8.4", "unit": "%",
             "confidence": 0.9, "source_text": "HbA1c 8.4 %"},
        ],
        "vitals": [{"name": "BP", "value": "150/94", "confidence": 0.9, "source_text": "BP 150/94"}],
    }
    data.update(over)
    return PageExtraction.model_validate(data)


def _kinds(issues):
    return {(i.section, i.index, i.field) for i in issues}


def test_faithful_page_passes():
    issues, grounding = verify_page(_x(), PAGE)
    assert grounding == "text_layer"
    assert issues == []


def test_quote_matching_tolerates_spacing_but_not_invention():
    assert quote_found("Tab  Metformin 500mg 1 - 0 - 1", PAGE)
    assert not quote_found("Tab Glimepiride 2 mg", PAGE)


def test_abbreviations_and_prefixes_back_names():
    assert name_in_quote("Hypertension", "K/c/o HTN")
    assert name_in_quote("Fasting blood sugar", "FBS 182 mg/dl")
    assert not name_in_quote("Diabetes", "K/c/o HTN")


def test_invented_drug_is_caught():
    meds = _x().model_dump()["medications"] + [
        {"drug_as_written": "Atorvastatin", "strength": "10 mg", "confidence": 0.95, "source_text": "Tab Atorvastatin 10 mg"}]
    issues, _ = verify_page(_x(medications=meds), PAGE)
    assert ("medications", 2, "source_text") in _kinds(issues)


def test_wrong_dose_and_wrong_value_are_caught():
    meds = _x().model_dump()["medications"]
    meds[0]["strength"] = "1000 mg"
    tests = _x().model_dump()["investigations"]
    tests[1]["value"] = "6.4"
    issues, _ = verify_page(_x(medications=meds, investigations=tests), PAGE)
    assert {("medications", 0, "numbers"), ("investigations", 1, "numbers")} <= _kinds(issues)


def test_name_not_in_its_own_quote_is_caught():
    dx = [{"text": "Type 2 diabetes", "confidence": 0.9, "source_text": "K/c/o HTN"}]
    issues, _ = verify_page(_x(diagnoses=dx), PAGE)
    assert ("diagnoses", 0, "name") in _kinds(issues)


def test_episode_count_must_be_written():
    eps = _x().model_dump()["episodes"]
    eps[0]["count"] = 5
    issues, _ = verify_page(_x(episodes=eps), PAGE)
    assert ("episodes", 0, "count") in _kinds(issues)


def test_dates_are_rederived_from_what_is_written():
    issues, _ = verify_page(_x(encounter={"date_raw": "12/03/2025", "date_iso": "2025-12-03"}), PAGE)
    assert ("encounter", None, "date_iso") in _kinds(issues)
    eps = _x().model_dump()["episodes"]
    eps[0]["date_iso"] = "2025-03-10"  # 'this week' can't be parsed, so the date is a guess
    issues, _ = verify_page(_x(episodes=eps), PAGE)
    [inferred] = [i for i in issues if i.field == "date_iso"]
    assert not inferred.blocking


def test_invented_negative_history_is_caught():
    issues, _ = verify_page(_x(negative_history=["No fever"]), PAGE)
    assert ("negative_history", 0, "text") in _kinds(issues)


def test_handwritten_page_falls_back_to_transcription():
    issues, grounding = verify_page(_x(transcription=PAGE), text_layer="")
    assert grounding == "transcription" and issues == []
    issues, grounding = verify_page(_x(), text_layer=None)
    assert grounding == "none" and issues  # nothing to check against, so nothing passes


def test_gate_removes_failed_items_and_history_lists_them():
    meds = _x().model_dump()["medications"]
    meds[1]["strength"] = "10 mg"
    x = _x(medications=meds, encounter={"date_raw": "12/03/2025", "date_iso": "2025-12-03"})
    issues, grounding = verify_page(x, PAGE)
    kept = gate(x, issues)
    assert [m.drug_as_written for m in kept.medications] == ["Metformin"]
    assert kept.encounter.date_iso is None

    rec = ExtractionRecord(page_id="p1", source_file="opd.pdf", page_number=1, extractor="test",
                           extraction=x, issues=[i.model_dump() for i in issues], grounding=grounding)
    h = build_history([rec])
    assert [c.drug for c in h.medication_courses] == ["metformin"]
    assert h.encounters[0].date == "2025-03-12"  # from the date as written
    assert {(r.section, r.field) for r in h.review_items} >= {("medications", "numbers"), ("encounter", "date_iso")}
