"""Small, deterministic clean-ups applied after extraction."""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

_DATE_RE = re.compile(r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})")

FREQUENCY = {
    "OD": "once daily",
    "QD": "once daily",
    "BD": "twice daily",
    "BID": "twice daily",
    "TDS": "three times daily",
    "TID": "three times daily",
    "QID": "four times daily",
    "QDS": "four times daily",
    "HS": "at bedtime",
    "SOS": "as needed",
    "PRN": "as needed",
    "STAT": "immediately",
}


def parse_date(raw: Optional[str], day_first: bool = True) -> tuple[Optional[str], bool]:
    """Return (YYYY-MM-DD or None, ambiguous)."""
    if not raw:
        return None, False
    m = _DATE_RE.search(raw)
    if not m:
        return None, False
    a, b, y = (int(x) for x in m.groups())
    if y < 100:
        y += 2000 if y < 70 else 1900
    day, month = (a, b) if day_first else (b, a)
    ambiguous = a <= 12 and b <= 12 and a != b
    try:
        return date(y, month, day).isoformat(), ambiguous
    except ValueError:
        # Swapped order might be valid (e.g. 04/25/2024 written US-style).
        try:
            return date(y, day, month).isoformat(), True
        except ValueError:
            return None, False


def expand_frequency(freq: Optional[str]) -> Optional[str]:
    """'1-0-1' -> 'morning and night'; 'BD' -> 'twice daily'."""
    if not freq:
        return None
    s = freq.strip().upper().replace(" ", "")
    if s in FREQUENCY:
        return FREQUENCY[s]
    m = re.fullmatch(r"(\d+(?:/\d)?)-(\d+(?:/\d)?)-(\d+(?:/\d)?)(?:-(\d+(?:/\d)?))?", s)
    if m:
        slots = ["morning", "afternoon", "night"] if m.group(4) is None else ["morning", "afternoon", "evening", "night"]
        parts = [g for g in m.groups() if g is not None]
        taken = [f"{slot}" if q == "1" else f"{slot} ({q})" for slot, q in zip(slots, parts) if q != "0"]
        return " and ".join(taken) if taken else None
    return None


_DURATION_RE = re.compile(r"(\d+)\s*(d|day|days|w|wk|week|weeks|m|mo|month|months)\b", re.I)


def duration_days(duration: Optional[str]) -> Optional[int]:
    if not duration:
        return None
    m = _DURATION_RE.search(duration)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith("w"):
        return n * 7
    if unit.startswith("m"):
        return n * 30
    return n


def normalize_drug_key(name: str) -> str:
    """Key used to link the same drug across encounters ('Tab. PAN-40' -> 'pan')."""
    s = name.lower()
    s = re.sub(r"^(tab|t|cap|c|syp|syr|inj|oint)\.?\s+", "", s)
    s = re.sub(r"[\d.]+\s*(mg|mcg|g|ml|iu|%)?", " ", s)
    s = re.sub(r"[^a-z ]", " ", s)
    return " ".join(s.split())
