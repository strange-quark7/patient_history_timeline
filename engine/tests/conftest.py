import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


def _rx(date_raw, meds, dx, facility="City Clinic", labs=(), confidence=0.95, complaints=("epigastric pain",)):
    return {
        "doc_type": "prescription",
        "script": "handwritten",
        "encounter": {"date_raw": date_raw, "facility": facility, "clinician": "Dr. Rao"},
        "patient": {"name": "Ravi Kumar", "age": "54", "sex": "M"},
        "complaints": list(complaints),
        "diagnoses": [{"text": d, "confidence": confidence, "source_text": d} for d in dx],
        "medications": [
            {
                "drug_as_written": name,
                "strength": strength,
                "frequency": freq,
                "duration": dur,
                "confidence": confidence,
                "source_text": f"{name} {strength} {freq} x {dur}",
            }
            for name, strength, freq, dur in meds
        ],
        "investigations": [
            {"name": n, "status": "resulted", "value": v, "unit": u, "confidence": confidence, "source_text": f"{n} {v}"}
            for n, v, u in labs
        ],
    }


@pytest.fixture
def sample_folder(tmp_path: Path) -> Path:
    """Three fake documents (PNG, PDF, PNG) with matching fixture extractions."""
    docs = tmp_path / "docs"
    docs.mkdir()
    for stem in ("visit_b", "visit_a", "visit_c"):
        img = Image.new("RGB", (800, 1000), "white")
        ImageDraw.Draw(img).text((40, 40), f"Rx {stem}", fill="black")
        if stem == "visit_a":
            img.save(docs / f"{stem}.pdf")
        else:
            img.save(docs / f"{stem}.png")

    fixtures = {
        "visit_a": _rx("12/01/2024", [("Tab. Pan 40", "40 mg", "1-0-0", "14 days")], ["GERD"], labs=[("HbA1c", "7.9", "%")]),
        "visit_b": _rx("20/03/2024", [("Tab. Pan 40", "40 mg", "1-0-0", "30 days"), ("Tab. Metformin", "500 mg", "BD", "1 month")], ["GERD", "Type 2 diabetes"], labs=[("HbA1c", "7.1", "%")], complaints=("epigastric pain", "fatigue")),
        "visit_c": _rx(None, [("Syp. Cremaffin", "", "HS", "5 days")], ["Constipation"], confidence=0.4, complaints=("constipation",)),
    }
    for stem, data in fixtures.items():
        (docs / f"{stem}.p1.json").write_text(json.dumps(data))
    return docs
