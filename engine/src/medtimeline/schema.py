"""Data model shared by every extractor.

Extractors (cloud or local) must return a PageExtraction. Everything downstream
(normalization, timeline assembly, the UI) only ever sees these types, which is
what lets the AI layer be swapped without touching the rest of the app.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DocType(str, Enum):
    prescription = "prescription"
    case_sheet = "case_sheet"
    lab_report = "lab_report"
    discharge_summary = "discharge_summary"
    other = "other"


class Script(str, Enum):
    typed = "typed"
    handwritten = "handwritten"
    mixed = "mixed"


class Sourced(BaseModel):
    """Common provenance fields: how sure the extractor is, and where it read it."""

    confidence: float = Field(description="0 to 1. Below 0.7 means a human should check it.")
    source_text: str = Field(description="The text exactly as written on the page, including abbreviations.")


class Encounter(BaseModel):
    date_raw: Optional[str] = Field(None, description="Date exactly as written, e.g. '3/4/24'.")
    date_iso: Optional[str] = Field(None, description="Best reading as YYYY-MM-DD, assuming DD/MM order.")
    date_ambiguous: bool = Field(False, description="True if day and month could be swapped or the year is unclear.")
    facility: Optional[str] = None
    clinician: Optional[str] = None
    department: Optional[str] = None
    encounter_type: Optional[str] = Field(None, description="e.g. OPD, admission, follow-up, emergency.")


class Patient(BaseModel):
    name: Optional[str] = None
    age: Optional[str] = None
    sex: Optional[str] = None
    identifiers: list[str] = Field(default_factory=list, description="Hospital numbers, phone numbers, etc.")


class Diagnosis(Sourced):
    text: str
    known: bool = Field(False, description="True if listed as past history or a known case (k/c/o), not diagnosed at this visit.")
    icd10_suggestion: Optional[str] = Field(None, description="A suggestion only, never authoritative.")


class Medication(Sourced):
    drug_as_written: str
    generic_name: Optional[str] = None
    strength: Optional[str] = None
    form: Optional[str] = Field(None, description="tablet, syrup, injection, ...")
    dose: Optional[str] = None
    frequency: Optional[str] = Field(None, description="As written, e.g. '1-0-1', 'BD', 'TDS'.")
    duration: Optional[str] = None
    route: Optional[str] = None
    instructions: Optional[str] = None


class Investigation(Sourced):
    name: str
    kind: str = Field("lab", description="'lab', 'imaging' (X-ray, CT, MRI, ultrasound) or 'study' (EEG, ECG, ...).")
    status: str = Field(description="'ordered' or 'resulted'.")
    value: Optional[str] = None
    unit: Optional[str] = None
    reference_range: Optional[str] = None
    abnormal: Optional[bool] = Field(None, description="True if flagged high/low/abnormal on the page or outside its range.")


class Vital(Sourced):
    name: str = Field(description="e.g. BP, pulse, temperature, SpO2, weight.")
    value: str
    unit: Optional[str] = None


class ReportedEpisode(Sourced):
    """One event the history describes, e.g. a seizure that happened between visits."""

    symptom: str = Field(description="What happened, e.g. 'seizure', 'chest pain'.")
    when_raw: Optional[str] = Field(None, description="As written, e.g. 'last night', 'Dec 2024', 'since last visit'.")
    date_iso: Optional[str] = Field(None, description="Best date as YYYY-MM-DD; first of the month/year if only that is known.")
    date_precision: str = Field("unknown", description="'day', 'month', 'year' or 'unknown'.")
    count: int = Field(1, description="Episodes this entry covers, e.g. 3 for 'three episodes since last visit'.")
    description: Optional[str] = None
    duration: Optional[str] = None
    severity_note: Optional[str] = Field(None, description="Severity as described, e.g. 'worst so far'.")
    is_worst: bool = Field(False, description="True only if the page says this was the worst or most severe one.")
    triggers: list[str] = Field(default_factory=list)


class PageExtraction(BaseModel):
    transcription: Optional[str] = Field(
        None,
        description="Verbatim transcription of the whole page, line by line, as written; no corrections or expansions.",
    )
    doc_type: DocType
    script: Script
    encounter: Encounter
    patient: Patient
    complaints: list[str] = Field(default_factory=list)
    history: Optional[str] = None
    episodes: list[ReportedEpisode] = Field(
        default_factory=list,
        description="Individual events the history describes (dated or counted), separate from the visit itself.",
    )
    negative_history: list[str] = Field(
        default_factory=list,
        description="Things the page says were absent or denied, e.g. 'no fever', 'no head injury'.",
    )
    examination: Optional[str] = None
    diagnoses: list[Diagnosis] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    investigations: list[Investigation] = Field(default_factory=list)
    vitals: list[Vital] = Field(default_factory=list)
    procedures: list[str] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)
    follow_up_date_iso: Optional[str] = None
    illegible_notes: list[str] = Field(
        default_factory=list,
        description="Parts of the page that could not be read; never guess these.",
    )


class ExtractionRecord(BaseModel):
    """One page's extraction plus bookkeeping, as stored and passed to assembly."""

    page_id: str
    source_file: str
    page_number: int
    extractor: str
    extraction: PageExtraction
    issues: list = Field(default_factory=list, description="verify.Issue entries from the deterministic checks.")
    grounding: str = Field("unchecked", description="What quotes were checked against: text_layer, transcription, none or unchecked.")
