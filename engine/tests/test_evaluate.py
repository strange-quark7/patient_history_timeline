import shutil

from medtimeline.evaluate import run_eval
from medtimeline.extract import get_extractor


def test_perfect_extractor_scores_100(sample_folder):
    scores = run_eval(get_extractor("fixture"), sample_folder, sample_folder)
    assert scores.fields["med_name"].pct == 100.0
    assert scores.fields["encounter_date"].pct == 100.0
    assert scores.extra_items == 0


def test_wrong_prediction_lowers_score(sample_folder, tmp_path):
    preds = tmp_path / "preds"
    shutil.copytree(sample_folder, preds)
    p = preds / "visit_b.p1.json"
    p.write_text(p.read_text().replace("Metformin", "Glimepiride"))
    scores = run_eval(get_extractor("fixture", folder=str(preds)), sample_folder, sample_folder)
    assert scores.fields["med_name"].correct == scores.fields["med_name"].total - 1
    assert scores.extra_items == 1
