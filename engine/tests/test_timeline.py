from medtimeline.extract import get_extractor
from medtimeline.ingest import load_folder
from medtimeline.schema import ExtractionRecord
from medtimeline.timeline import build_history


def _records(folder):
    ex = get_extractor("fixture")
    return [
        ExtractionRecord(page_id=p.page_id, source_file=p.source_file, page_number=p.page_number,
                         extractor=ex.name, extraction=ex.extract(p))
        for p in load_folder(folder)
    ]


def test_encounters_are_chronological_with_undated_last(sample_folder):
    h = build_history(_records(sample_folder))
    assert [e.date for e in h.encounters] == ["2024-01-12", "2024-03-20", None]
    assert [e.date_status for e in h.encounters] == ["ambiguous", "exact", "unknown"]


def test_medication_course_spans_visits(sample_folder):
    h = build_history(_records(sample_folder))
    pan = next(c for c in h.medication_courses if c.drug == "pan")
    assert pan.start == "2024-01-12"
    assert pan.end == "2024-04-19"  # last visit + 30 days
    assert len(pan.encounter_ids) == 2


def test_conditions_and_lab_trend(sample_folder):
    h = build_history(_records(sample_folder))
    gerd = next(c for c in h.conditions if c.name == "GERD")
    assert (gerd.first_seen, gerd.last_seen) == ("2024-01-12", "2024-03-20")
    [hba1c] = h.lab_series
    assert [p.value for p in hba1c.points] == ["7.9", "7.1"]


def test_low_confidence_and_undated_pages_need_review(sample_folder):
    h = build_history(_records(sample_folder))
    assert h.encounters[2].needs_review == 2
    assert len(h.pages_needing_review) == 2  # ambiguous date page + low-confidence undated page
