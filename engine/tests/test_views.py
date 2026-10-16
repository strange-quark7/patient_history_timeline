import pytest

from medtimeline.extract import get_extractor
from medtimeline.ingest import load_folder
from medtimeline.schema import ExtractionRecord
from medtimeline.timeline import build_history, episodes_from
from medtimeline.views import build_view


@pytest.fixture
def history(sample_folder):
    ex = get_extractor("fixture")
    return build_history([
        ExtractionRecord(page_id=p.page_id, source_file=p.source_file, page_number=p.page_number,
                         extractor=ex.name, extraction=ex.extract(p))
        for p in load_folder(sample_folder)
    ])


def test_episodes_split_on_gap():
    eps = episodes_from([("2024-01-01", "a"), ("2024-01-20", "b"), ("2024-06-01", "c"), (None, "d")])
    assert [(e.start, e.end, e.encounter_ids) for e in eps] == [
        ("2024-01-01", "2024-01-20", ["a", "b"]),
        ("2024-06-01", "2024-06-01", ["c"]),
        (None, None, ["d"]),
    ]


def test_symptoms_sorted_by_episodes(history):
    rows = build_view(history, "symptoms", "episodes").rows
    assert [(r.label, r.episode_count, r.visit_count) for r in rows] == [
        ("epigastric pain", 2, 2),  # Jan and Mar visits are > 30 days apart
        ("constipation", 1, 1),
        ("fatigue", 1, 1),
    ]


def test_visits_chronological_and_recent(history):
    chron = [r.first_seen for r in build_view(history, "visits", "chronological").rows]
    recent = [r.first_seen for r in build_view(history, "visits", "recent").rows]
    assert chron == ["2024-01-12", "2024-03-20", None]
    assert recent == ["2024-03-20", "2024-01-12", None]


def test_medications_sorted_by_visits_and_duration(history):
    by_visits = build_view(history, "medications", "visits").rows
    assert by_visits[0].label == "Tab. Pan 40" and by_visits[0].visit_count == 2
    by_duration = build_view(history, "medications", "duration").rows
    assert by_duration[0].label == "Tab. Pan 40"  # 12 Jan to 19 Apr


def test_symptoms_and_medications_are_linked(history):
    rows = build_view(history, "symptoms_medications", "name").rows
    pain = next(r for r in rows if r.label == "epigastric pain")
    assert set(pain.related) == {"Tab. Pan 40", "Tab. Metformin"}
    cremaffin = next(r for r in rows if r.kind == "medication" and "Cremaffin" in r.label)
    assert cremaffin.related == ["constipation"]


def test_query_and_date_filters(history):
    rows = build_view(history, "symptoms_medications", "name", query="pain").rows
    assert {r.label for r in rows} == {"epigastric pain", "Tab. Pan 40", "Tab. Metformin"}
    rows = build_view(history, "visits", "chronological", start="2024-03-01").rows
    assert [r.first_seen for r in rows] == ["2024-03-20"]


def test_conditions_and_labs_lenses(history):
    conds = build_view(history, "conditions", "visits").rows
    assert conds[0].label == "GERD" and conds[0].visit_count == 2
    [lab] = build_view(history, "labs", "chronological").rows
    assert [e.detail for e in lab.events] == ["7.9 %", "7.1 %"]
