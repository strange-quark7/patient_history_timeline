"""Rules for patients with several conditions at once.

Nothing here uses a model. A condition's course comes from fixed term lists
and the dates it was recorded. A complaint or drug is tied to a condition only
when the page itself says so, or, for drugs, when a fixed table allows exactly
one of the patient's conditions. Anything else stays unlinked rather than guessed.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable, Optional

# Usually self-limiting illnesses that can recur. Each recurrence is its own episode.
ACUTE_TERMS = [
    "urinary tract infection", "uti", "cystitis", "pyelonephritis", "upper respiratory tract infection", "urti",
    "lower respiratory tract infection", "lrti", "pneumonia", "bronchitis", "pharyngitis", "tonsillitis",
    "sinusitis", "otitis", "conjunctivitis", "gastroenteritis", "age", "acute gastroenteritis", "diarrhoea",
    "dysentery", "cellulitis", "abscess", "viral fever", "dengue", "malaria", "typhoid", "influenza", "covid",
    "sprain", "fracture", "migraine attack", "renal colic", "acute pancreatitis", "dka", "hypoglycaemia",
]
# Conditions that, once recorded, are carried forward.
LONG_TERM_TERMS = [
    "diabetes", "dm", "t2dm", "t1dm", "hypertension", "htn", "epilepsy", "seizure disorder", "asthma", "copd",
    "chronic kidney disease", "ckd", "hypothyroidism", "hyperthyroidism", "coronary artery disease", "cad",
    "heart failure", "atrial fibrillation", "rheumatoid arthritis", "osteoarthritis", "parkinson", "dementia",
    "depression", "anxiety", "schizophrenia", "bipolar", "neuropathy", "retinopathy", "nephropathy",
    "dyslipidaemia", "hyperlipidaemia", "gout", "psoriasis", "hiv", "hepatitis b", "hepatitis c", "cirrhosis",
    "pcos", "migraine", "stroke", "cva", "tuberculosis", "tb",
]
# Generic drug -> conditions it is commonly used for. A drug links only if exactly one matches.
INDICATIONS = {
    "metformin": ["diabetes"], "glimepiride": ["diabetes"], "gliclazide": ["diabetes"], "sitagliptin": ["diabetes"],
    "linagliptin": ["diabetes"], "vildagliptin": ["diabetes"], "insulin": ["diabetes"], "dapagliflozin": ["diabetes", "heart failure", "chronic kidney disease"],
    "empagliflozin": ["diabetes", "heart failure", "chronic kidney disease"],
    "amlodipine": ["hypertension", "angina"], "telmisartan": ["hypertension", "chronic kidney disease"],
    "losartan": ["hypertension", "chronic kidney disease"], "enalapril": ["hypertension", "heart failure"],
    "ramipril": ["hypertension", "heart failure", "chronic kidney disease"], "metoprolol": ["hypertension", "heart failure", "angina", "atrial fibrillation"],
    "atenolol": ["hypertension", "angina"], "hydrochlorothiazide": ["hypertension"], "chlorthalidone": ["hypertension"],
    "levetiracetam": ["epilepsy", "seizure"], "phenytoin": ["epilepsy", "seizure"], "carbamazepine": ["epilepsy", "seizure", "neuralgia"],
    "valproate": ["epilepsy", "seizure", "bipolar", "migraine"], "sodium valproate": ["epilepsy", "seizure", "bipolar", "migraine"],
    "lamotrigine": ["epilepsy", "seizure", "bipolar"], "clobazam": ["epilepsy", "seizure", "anxiety"],
    "pregabalin": ["neuropathy", "epilepsy", "seizure", "anxiety"], "gabapentin": ["neuropathy", "epilepsy", "seizure"],
    "nitrofurantoin": ["urinary tract infection", "uti", "cystitis"], "fosfomycin": ["urinary tract infection", "uti", "cystitis"],
    "levothyroxine": ["hypothyroidism"], "thyroxine": ["hypothyroidism"], "atorvastatin": ["dyslipidaemia", "hyperlipidaemia", "coronary artery disease", "stroke"],
    "salbutamol": ["asthma", "copd"], "budesonide": ["asthma", "copd"],
}
ABBREV = {"uti": "urinary tract infection", "htn": "hypertension", "dm": "diabetes", "t2dm": "diabetes",
          "t1dm": "diabetes", "ckd": "chronic kidney disease", "cad": "coronary artery disease", "copd": "copd",
          "urti": "upper respiratory tract infection", "lrti": "lower respiratory tract infection",
          "age": "acute gastroenteritis", "cva": "stroke", "tb": "tuberculosis", "sz": "seizure"}
ACUTE_GAP_DAYS = 28  # an acute condition recorded again after this many days is a new episode


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _expanded(text: str) -> set[str]:
    words = _words(text)
    out = set(words)
    for w in words:
        out |= set(_words(ABBREV.get(w, "")))
    # 'diabetic', 'epileptic', 'hypertensive' count as the condition word
    out |= {w[:-2] + "es" for w in words if w.endswith("ic")} | {w[:-1] for w in words if w.endswith("ic")}
    out |= {"hypertension" for w in words if w.startswith("hypertensi")}
    out |= {"epilepsy" for w in words if w.startswith("epilep")}
    out |= {"seizure" for w in words if w.startswith("seizure")}
    return out


def matches(term: str, text: str) -> bool:
    """Every word of `term` (or its abbreviation's expansion) appears in `text`."""
    have = _expanded(text)
    want = _words(ABBREV.get(term.lower(), term))
    return bool(want) and all(w in have for w in want)


def _any(terms: Iterable[str], text: str) -> bool:
    return any(matches(t, text) for t in terms)


def course_of(name: str, known: bool, dates: list[str]) -> str:
    """'long_term', 'acute' or 'unclassified', from the name and the recorded dates only."""
    if _any(ACUTE_TERMS, name) and not _any(["chronic", "recurrent"], name):
        return "acute"
    if known or _any(LONG_TERM_TERMS, name) or _any(["chronic", "recurrent"], name):
        return "long_term"
    if len(dates) >= 2 and (date.fromisoformat(max(dates)) - date.fromisoformat(min(dates))).days >= 90:
        return "long_term"
    return "unclassified"


def acute_runs(mentions: list[tuple[Optional[str], str]]) -> list[list[tuple[Optional[str], str]]]:
    """Split dated mentions into episodes wherever the gap exceeds ACUTE_GAP_DAYS."""
    dated = sorted((d, e) for d, e in mentions if d)
    runs: list[list[tuple[Optional[str], str]]] = []
    for d, e in dated:
        if runs and (date.fromisoformat(d) - date.fromisoformat(runs[-1][-1][0])).days <= ACUTE_GAP_DAYS:
            runs[-1].append((d, e))
        else:
            runs.append([(d, e)])
    runs += [[(None, e)] for d, e in mentions if not d]
    return runs


def condition_for_drug(drug: str, conditions: list[str]) -> Optional[str]:
    """The patient's one condition this drug's table entry allows, or None if none or several."""
    uses = INDICATIONS.get(drug.lower().strip())
    if not uses:
        return None
    hits = [c for c in conditions if _any(uses, c)]
    return hits[0] if len(hits) == 1 else None


def resolve(name: str, conditions: list[str]) -> Optional[str]:
    """Map a diagnosis as written in a link ('?UTI') to one of the history's condition names."""
    hits = [c for c in conditions if matches(name.strip("?! ."), c) or matches(c, name)]
    if len(hits) <= 1:
        return hits[0] if hits else None
    # Several fit ('recurrent UTI' fits 'UTI' and 'recurrent UTI'): take the one sharing most words, if unique.
    # Score = shared words minus words the condition has that the link does not, so 'UTI' prefers plain UTI.
    want = _expanded(name.strip("?! ."))
    scored = sorted(((len(want & _expanded(c)) - len(_expanded(c) - want), c) for c in hits), reverse=True)
    return scored[0][1] if scored[0][0] > scored[1][0] else None
