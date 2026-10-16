"""Held drugs, and reviewers' label choices for unnamed values and unsure readings."""

from medtimeline.bundle import make_bundle
from medtimeline.schema import ExtractionRecord, PageExtraction
from medtimeline.serve import Service
from medtimeline.timeline import build_history
from medtimeline.verify import verify_page


def _record(page_id, date_raw, date_iso, text, **data):
    x = PageExtraction.model_validate({"transcription": text, "doc_type": "prescription", "script": "handwritten",
                                       "encounter": {"date_raw": date_raw, "date_iso": date_iso}, "patient": {}, **data})
    issues, grounding = verify_page(x, None)
    return ExtractionRecord(page_id=page_id, source_file=f"{page_id}.jpg", page_number=1, extractor="test",
                            extraction=x, issues=[i.model_dump() for i in issues], grounding=grounding)


def _med(name, quote, **kw):
    return {"drug_as_written": name, "confidence": 0.9, "source_text": quote, **kw}


def _records():
    return [
        _record("p1", "01/01/2025", "2025-01-01", "Tab Methotrexate 15 mg weekly",
                medications=[_med("Methotrexate", "Tab Methotrexate 15 mg weekly", strength="15 mg", frequency="weekly")]),
        _record("p2", "01/02/2025", "2025-02-01", "Hold Methotrexate\n9.4 ) 4500 ( 307000\nT. Pcm 650 SOS",
                medications=[_med("Methotrexate", "Hold Methotrexate", status="held"),
                             _med("Pcm", "T. Pcm 650 SOS", strength="650", frequency="SOS", confidence=0.5,
                                  alternatives=["Paracetamol"])],
                investigations=[{"name": "", "status": "resulted", "value": "9.4", "confidence": 0.8,
                                 "source_text": "9.4 ) 4500 ( 307000", "alternatives": ["Haemoglobin"]},
                                {"name": "", "status": "resulted", "value": "4500", "confidence": 0.8,
                                 "source_text": "9.4 ) 4500 ( 307000", "alternatives": ["Total leucocyte count"]}]),
        _record("p3", "01/03/2025", "2025-03-01", "Restart Tab Methotrexate 10 mg weekly",
                medications=[_med("Methotrexate", "Restart Tab Methotrexate 10 mg weekly", strength="10 mg", frequency="weekly")]),
    ]


def test_hold_ends_the_period_and_shows_as_a_change():
    b = make_bundle(_records())
    mtx = next(m for m in b["medications"] if m["id"] == "methotrexate")
    assert [(p["start"], p["end"]) for p in mtx["periods"]][0] == ("2025-01-01", "2025-02-01")
    assert [c["kind"] for c in b["changes"] if c["med_id"] == "methotrexate"] == ["first recorded", "held", "resumed"]
    visit = next(e for e in b["encounters"] if e["date"] == "2025-02-01")
    assert {m["label"]: m["status"] for m in visit["medications"]}["Methotrexate"] == "held"


def test_unnamed_values_are_held_out_with_label_options():
    h = build_history(_records())
    assert not [t for e in h.encounters for t in e.investigations]
    items = [r for r in h.review_items if r.field == "label"]
    assert [(r.key, r.options, r.value) for r in items] == [
        ("p2:investigations:0", ["Haemoglobin"], "9.4"), ("p2:investigations:1", ["Total leucocyte count"], "4500")]


def test_unsure_reading_is_kept_with_options():
    h = build_history(_records())
    item = next(r for r in h.review_items if r.field == "reading")
    assert (item.blocking, item.options) == (False, ["Pcm", "Paracetamol"])
    assert any(m.drug_as_written == "Pcm" for e in h.encounters for m in e.medications)


def test_choices_relabel_or_leave_unsure():
    res = {"p2:investigations:0": {"choice": "Haemoglobin"}, "p2:investigations:1": {"choice": None},
           "p2:medications:1": {"choice": "Paracetamol"}}
    b = make_bundle(_records(), resolutions=res)
    tests = {(t["name"], t["value"], t["labelled_by_user"]) for t in b["tests"]}
    assert tests == {("Haemoglobin", "9.4", True), ("Unlabelled value", "4500", False)}
    assert any(m["label"] == "Paracetamol" for e in b["encounters"] for m in e["medications"])
    assert all(r["resolved"] for r in b["review_items"] if r["key"])


def test_choices_are_saved_per_project_and_can_be_undone(tmp_path):
    service = Service(home=str(tmp_path))
    pid = service.store.create("Test", str(tmp_path), "fixture")
    for r in _records():
        (service.store.records_dir(pid) / f"{r.page_id}.json").write_text(r.model_dump_json())
    service.call("review.resolve", {"project_id": pid, "key": "p2:investigations:0", "choice": "Haemoglobin"})
    reopened = Service(home=str(tmp_path)).projects_open(pid)["bundle"]
    assert any(t["name"] == "Haemoglobin" for t in reopened["tests"])
    undone = service.call("review.resolve", {"project_id": pid, "key": "p2:investigations:0", "clear": True})["bundle"]
    assert not any(t["name"] == "Haemoglobin" for t in undone["tests"])


def test_demo_choices_last_for_the_session(tmp_path):
    service = Service(home=str(tmp_path))
    key = next(r["key"] for r in service.demo()["bundle"]["review_items"] if r["field"] == "label")
    after = service.call("review.resolve", {"project_id": "demo", "key": key, "choice": "Haemoglobin"})["bundle"]
    assert any(r["key"] == key and r["choice"] == "Haemoglobin" for r in after["review_items"])
