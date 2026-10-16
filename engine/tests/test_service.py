"""The service the desktop app talks to, and the demo patient it ships with."""

import json
import subprocess
import sys

import pytest

from medtimeline.serve import Service


@pytest.fixture
def demo():
    return Service(home=None).demo()["bundle"]


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDTIMELINE_HOME", str(tmp_path / "home"))


def test_demo_has_several_conditions_and_three_utis(demo):
    conds = {c["id"]: c for c in demo["conditions"]}
    assert conds["urinary-tract-infection"]["course"] == "acute"
    assert len(conds["urinary-tract-infection"]["episodes"]) == 3
    assert conds["type-2-diabetes-mellitus"]["role"] == "primary"
    assert conds["epilepsy"]["known"] and conds["hypertension"]["known"]


def test_demo_overlapping_symptom_and_held_out_items(demo):
    freq = next(s for s in demo["symptoms"] if s["id"] == "frequent-urination")
    assert [o["condition_id"] for o in freq["occurrences"]] == [
        "type-2-diabetes-mellitus", "urinary-tract-infection", "urinary-tract-infection", None]
    blocking = [r for r in demo["review_items"] if r["blocking"]]
    assert {(r["section"], r["field"]) for r in blocking} == {("links", "condition"), ("medications", "source_text"),
                                                              ("investigations", "label")}
    assert not any(m["id"] == "ciprofloxacin" for m in demo["medications"])


def test_demo_drug_courses_and_medication_at_time(demo):
    nitro = next(m for m in demo["medications"] if m["id"] == "nitrofurantoin")
    assert [(p["start"], p["end"]) for p in nitro["periods"]][:2] == [("2024-04-09", "2024-04-14"), ("2024-08-27", "2024-09-01")]
    worst = next(e for e in demo["episodes"] if e["is_worst"])
    # The seizure came before the emergency visit, so its antibiotics are not counted.
    assert [m["med_id"] for m in worst["medications_at_time"]] == ["levetiracetam", "metformin"]
    cef = next(m for m in demo["medications"] if m["id"] == "cefuroxime")
    assert (cef["condition_id"], cef["condition_basis"]) == ("urinary-tract-infection", "page")


def test_project_create_and_open(sample_folder):
    svc = Service()
    events = []
    svc.emit = lambda e, d: events.append((e, d))
    out = svc.call("projects.create", {"name": "Ravi Kumar", "folder": str(sample_folder), "extractor": "fixture"})
    assert out["project"]["id"] == "ravi-kumar" and out["failures"] == []
    assert len(out["bundle"]["encounters"]) == 3
    assert events[-1][1]["done"] == events[-1][1]["total"] == 3
    assert [p["id"] for p in svc.call("projects.list", {})] == ["ravi-kumar"]
    again = svc.call("projects.open", {"project_id": "ravi-kumar"})
    assert again["bundle"]["encounters"] == out["bundle"]["encounters"]


def test_bad_requests_are_errors_not_crashes():
    svc = Service()
    with pytest.raises(ValueError):
        svc.call("nope", {})
    with pytest.raises(ValueError):
        svc.call("projects.open", {"project_id": "../etc"})


def test_stdio_protocol(tmp_path):
    reqs = "\n".join(json.dumps(r) for r in [
        {"id": 1, "method": "info", "params": {}},
        {"id": 2, "method": "nope"},
        {"id": 3, "method": "demo", "params": {}},
    ]) + "\n"
    proc = subprocess.run([sys.executable, "-m", "medtimeline.cli", "serve", "--home", str(tmp_path)],
                          input=reqs, capture_output=True, text=True, timeout=60)
    replies = {r["id"]: r for r in map(json.loads, proc.stdout.splitlines())}
    assert "claude" in replies[1]["result"]["extractors"]
    assert "Unknown method" in replies[2]["error"]
    assert replies[3]["result"]["bundle"]["patient"]["name"] == "[Patient name]"
