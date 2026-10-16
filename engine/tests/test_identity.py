"""Same-patient checks, yes/no answers, and pages added later."""

import json
from pathlib import Path

from PIL import Image

from conftest import _rx
from medtimeline.identity import check_pages, compare_names, name_tokens
from medtimeline.schema import ExtractionRecord, PageExtraction
from medtimeline.serve import Service


def _rec(page_id, name, age, sex, date):
    x = PageExtraction.model_validate({"doc_type": "prescription", "script": "handwritten",
                                       "encounter": {"date_raw": date, "date_iso": date}, "patient": {"name": name, "age": age, "sex": sex}})
    return ExtractionRecord(page_id=page_id, source_file=f"{page_id}.jpg", page_number=1, extractor="test", extraction=x)


def test_name_comparison():
    assert compare_names(name_tokens("Mr. SRINIVAS"), name_tokens("Shrinivas")) == "same"
    assert compare_names(name_tokens("Ashok"), name_tokens("Ashok Verma")) == "partial"
    assert compare_names(name_tokens("A. Verma"), name_tokens("Ashok Verma")) == "same"
    assert compare_names(name_tokens("Ashok Kumar"), name_tokens("Ashok Verma")) == "different"
    assert compare_names(name_tokens("Suman Maham"), name_tokens("Ashok Verma")) == "different"


def test_pages_are_checked_against_the_patient():
    recs = [_rec("a", "Ashok Verma", "58y", "M", "2025-12-29"), _rec("b", "Mr Ashok Verma", "57", "M", "2024-11-02"),
            _rec("c", "Ashok", "39 yrs", "M", "2022-09-28"), _rec("d", "Suman Maham", None, "F", "2025-01-10"),
            _rec("e", None, None, None, "2017-08-08"), _rec("f", "Ashok", "55", "M", "2023-02-01")]
    profile, checks = check_pages(recs, "Ashok Verma")
    by = {c.page_id: c for c in checks}
    assert (profile.sex, profile.born_about) == ("M", 1968)
    assert [by[p].verdict for p in "abcdef"] == ["match", "match", "doubt", "mismatch", "doubt", "doubt"]
    assert any("birth around 1984" in r for r in by["c"].reasons)
    assert not any(r.startswith("Age") for r in by["f"].reasons)  # first name only, but the age fits


def test_answers_let_pages_in_or_keep_them_out():
    recs = [_rec("a", "Ashok Verma", "58", "M", "2025-12-29"), _rec("c", "Ashok", "39", "M", "2022-09-28")]
    _, checks = check_pages(recs, "Ashok Verma", {"identity:c": {"choice": "yes"}})
    assert all(c.included for c in checks)
    _, checks = check_pages(recs, "Ashok Verma", {"identity:a": {"choice": "no"}})
    assert not next(c for c in checks if c.page_id == "a").included


def _page(folder: Path, stem: str, data: dict) -> None:
    folder.mkdir(exist_ok=True)
    quotes = [i["source_text"] for k in ("diagnoses", "medications", "investigations") for i in data.get(k, [])]
    data["transcription"] = "\n".join([data["encounter"]["date_raw"] or "", *quotes])
    Image.new("RGB", (400, 500), "white").save(folder / f"{stem}.png")
    (folder / f"{stem}.p1.json").write_text(json.dumps(data))


def test_older_pages_added_later_slot_in_and_say_what_changed(tmp_path):
    svc = Service(home=str(tmp_path / "home"))
    first = tmp_path / "first"
    _page(first, "visit_a", _rx("12/01/2024", [("Tab. Pan 40", "40 mg", "1-0-0", "14 days")], ["GERD"]))
    _page(first, "visit_b", _rx("20/03/2024", [("Tab. Metformin", "500 mg", "BD", "1 month")], ["GERD", "Type 2 diabetes"]))
    pid = svc.call("projects.create", {"name": "Ravi Kumar", "folder": str(first), "extractor": "fixture"})["project"]["id"]
    older = tmp_path / "found_later"
    gerd_2019 = _rx("05/06/2019", [("Tab. Pan 40", "40 mg", "1-0-0", "14 days")], ["GERD"])
    gerd_2019["patient"]["age"] = "49"
    _page(older, "old_visit", gerd_2019)
    other = _rx("01/07/2019", [], ["Asthma"])
    other["patient"] = {"name": "Ravi Shankar", "age": "30", "sex": "M"}
    _page(older, "someone_else", other)

    out = svc.call("projects.add", {"project_id": pid, "folder": str(older)})
    b, update = out["bundle"], out["project"]["last_update"]
    assert b["span"]["start"] == "2019-06-05"
    assert next(e for e in b["encounters"] if e["date"] == "2019-06-05")["added_later"]
    gerd = next(c for c in b["conditions"] if c["name"] == "GERD")
    assert gerd["first_seen"] == "2019-06-05"
    notes = " ".join(update["notes"])
    assert "2 pages added" in notes and "GERD is now first recorded on 5 Jun 2019 (was 12 Jan 2024)" in notes
    assert "1 of them may be for a different patient" in notes
    assert "Asthma" not in [c["name"] for c in b["conditions"]]
    item = next(r for r in b["review_items"] if r["field"] == "identity")
    assert item["verdict"] == "mismatch" and item["options"] == ["yes", "no"]

    after_yes = svc.call("review.resolve", {"project_id": pid, "key": item["key"], "choice": "yes"})["bundle"]
    assert "Asthma" in [c["name"] for c in after_yes["conditions"]]
    # Reading the folders again changes nothing and keeps the last update's notes.
    again = svc.call("projects.rebuild", {"project_id": pid})
    assert again["project"]["last_update"]["notes"] == update["notes"]
