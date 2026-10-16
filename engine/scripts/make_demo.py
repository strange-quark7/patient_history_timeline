"""Write the demo patient (made-up data) as verified extraction records.

The page text below stands in for what the reader transcribes; the extractions
are what a good reader would return, an unlabelled blood count and an unsure reading
with label choices for the reviewer, plus two deliberate mistakes (a drug not on
the page, and a symptom link the page does not make) and a page that is probably
another patient's, so the review list has something in it. Every item goes through the same verify checks as real pages.

    python scripts/make_demo.py   # writes src/medtimeline/demo/records.json
"""

import json
from pathlib import Path

from medtimeline.schema import ExtractionRecord, PageExtraction
from medtimeline.verify import verify_page

DM, HTN, EPI, UTI, RUTI = "Type 2 diabetes mellitus", "Hypertension", "Epilepsy", "Urinary tract infection", "Recurrent urinary tract infection"


def src(**kw):
    return {"confidence": kw.pop("confidence", 0.93), **kw}


def med(name, strength, freq, quote, duration=None):
    return src(drug_as_written=name, strength=strength, frequency=freq, duration=duration, source_text=quote)


def dx(text, quote, known=False):
    return src(text=text, known=known, source_text=quote)


def test(name, quote, value=None, unit=None, abnormal=None, kind="lab", status="resulted", ref=None, alternatives=()):
    return src(name=name, kind=kind, status=status, value=value, unit=unit, abnormal=abnormal, reference_range=ref,
               source_text=quote, alternatives=list(alternatives))


def link(item, condition, quote):
    return src(item=item, condition=condition, source_text=quote)


PAGES = [
    ("gp-2024-01-18.pdf", "typed", """GREENFIELD FAMILY CLINIC
Date: 18/01/2024    OPD
Name: Meera Nair   Age/Sex: 46/F
C/o increased frequency of urination and thirst x 2 months - ?DM. Tiredness.
K/c/o HTN on Tab Amlodipine 5 mg OD.
K/c/o epilepsy (seizure disorder) since age 12, on Tab Levetiracetam 500 mg BD.
O/E: BP 136/84 mmHg. BMI 31.
Inv: HbA1c 8.6 %  FBS 172 mg/dl
Diagnosis: Type 2 diabetes mellitus (new). Hypertension. Epilepsy.
Rx:
1. Tab Metformin 500 mg 1-0-1 x 30 days
2. Tab Amlodipine 5 mg 1-0-0 x 30 days
3. Tab Levetiracetam 500 mg 1-0-1 x 30 days
Review in 3 months.""", {
        "doc_type": "case_sheet", "encounter": {"date_raw": "18/01/2024", "date_iso": "2024-01-18", "facility": "Greenfield Family Clinic", "encounter_type": "OPD"},
        "complaints": ["frequent urination", "thirst", "tiredness"],
        "links": [link("frequent urination", "DM", "C/o increased frequency of urination and thirst x 2 months - ?DM"),
                  link("thirst", "DM", "C/o increased frequency of urination and thirst x 2 months - ?DM")],
        "diagnoses": [dx(DM, "Type 2 diabetes mellitus (new)"), dx(HTN, "K/c/o HTN on Tab Amlodipine 5 mg OD", True),
                      dx(EPI, "K/c/o epilepsy (seizure disorder) since age 12", True)],
        "medications": [med("Metformin", "500 mg", "1-0-1", "Tab Metformin 500 mg 1-0-1 x 30 days", "30 days"),
                        med("Amlodipine", "5 mg", "1-0-0", "Tab Amlodipine 5 mg 1-0-0 x 30 days", "30 days"),
                        med("Levetiracetam", "500 mg", "1-0-1", "Tab Levetiracetam 500 mg 1-0-1 x 30 days", "30 days")],
        "investigations": [test("HbA1c", "HbA1c 8.6 %", "8.6", "%", True), test("Fasting blood sugar", "FBS 172 mg/dl", "172", "mg/dl", True)],
        "vitals": [src(name="BP", value="136/84", unit="mmHg", source_text="BP 136/84 mmHg")],
        "follow_up_date_iso": "2024-04-18",
    }),
    ("gp-2024-04-09.jpg", "handwritten", """9/4/24
c/o burning micturition x 3 days, increased frequency, fever 38.4 C
Burning micturition, frequency, fever - ? UTI
O/E: T 38.4 C. Suprapubic tenderness +. No renal angle tenderness.
k/c/o DM, HTN, epilepsy - on Rx
Urine routine: pus cells 20-25/hpf. Urine C/S sent.
Imp: Urinary tract infection
Rx: T. Nitrofurantoin 100 mg 1-0-1 x 5 days
    T. Metformin 500 mg 1-0-1 - continue
    T. Paracetamol 650 mg SOS
Adv: plenty of oral fluids""", {
        "doc_type": "case_sheet", "encounter": {"date_raw": "9/4/24", "date_iso": "2024-04-09", "facility": "Greenfield Family Clinic"},
        "complaints": ["burning micturition", "frequent urination", "fever"],
        "links": [link("burning micturition", "UTI", "Burning micturition, frequency, fever - ? UTI"),
                  link("frequent urination", "UTI", "Burning micturition, frequency, fever - ? UTI"),
                  link("fever", "UTI", "Burning micturition, frequency, fever - ? UTI")],
        "negative_history": ["No renal angle tenderness"],
        "diagnoses": [dx(UTI, "Imp: Urinary tract infection"), dx(DM, "k/c/o DM, HTN, epilepsy - on Rx", True),
                      dx(HTN, "k/c/o DM, HTN, epilepsy - on Rx", True), dx(EPI, "k/c/o DM, HTN, epilepsy - on Rx", True)],
        "medications": [med("Nitrofurantoin", "100 mg", "1-0-1", "T. Nitrofurantoin 100 mg 1-0-1 x 5 days", "5 days"),
                        med("Metformin", "500 mg", "1-0-1", "T. Metformin 500 mg 1-0-1 - continue"),
                        med("Paracetamol", "650 mg", "SOS", "T. Paracetamol 650 mg SOS")],
        "investigations": [test("Urine routine", "Urine routine: pus cells 20-25/hpf", "pus cells 20-25/hpf", None, True),
                           test("Urine culture", "Urine C/S sent", status="ordered")],
        "vitals": [src(name="Temperature", value="38.4", unit="C", source_text="T 38.4 C")],
        "advice": ["Plenty of oral fluids"],
    }),
    ("neuro-2024-06-12.jpg", "handwritten", """Neurology OPD   12.06.2024
k/c/o epilepsy on LEV 500 BD
2 seizures since last visit - 1 GTCS during fever in April (~2 min), 1 brief focal aware episode in May
No missed doses. No head injury.
k/c/o DM, HTN
CNS: NAD
Imp: Epilepsy - breakthrough seizures
Rx: T. Levetiracetam 750 mg 1-0-1 x 3 months
Review 6 months / SOS""", {
        "doc_type": "case_sheet", "encounter": {"date_raw": "12.06.2024", "date_iso": "2024-06-12", "facility": "Neurology OPD", "department": "Neurology"},
        "complaints": ["seizures"],
        "episodes": [
            src(symptom="seizure", when_raw="April", date_iso="2024-04-01", date_precision="month", count=1,
                description="Generalised tonic-clonic seizure during fever", duration="about 2 minutes", triggers=["fever"],
                source_text="2 seizures since last visit - 1 GTCS during fever in April (~2 min), 1 brief focal aware episode in May"),
            src(symptom="seizure", when_raw="May", date_iso="2024-05-01", date_precision="month", count=1,
                description="Brief focal aware seizure",
                source_text="2 seizures since last visit - 1 GTCS during fever in April (~2 min), 1 brief focal aware episode in May"),
        ],
        "links": [link("seizure", "Epilepsy", "Imp: Epilepsy - breakthrough seizures")],
        "negative_history": ["No missed doses", "No head injury"],
        "diagnoses": [dx(EPI, "Imp: Epilepsy - breakthrough seizures"), dx(DM, "k/c/o DM, HTN", True), dx(HTN, "k/c/o DM, HTN", True)],
        "medications": [med("Levetiracetam", "750 mg", "1-0-1", "T. Levetiracetam 750 mg 1-0-1 x 3 months", "3 months")],
    }),
    ("gp-2024-08-27.jpg", "handwritten", """27/08/24
c/o burning micturition again x 2 days, frequency. No fever.
Burning micturition, frequency - UTI (2nd episode)
BP 152/96
k/c/o DM, HTN, epilepsy
Imp: Urinary tract infection. HTN - not controlled.
Rx: T. Nitrofurantoin 100 mg 1-0-1 x 5 days
    T. Amlodipine 10 mg 1-0-0 x 30 days (increased)
    Continue other meds
Urine C/S: E. coli, sensitive to nitrofurantoin""", {
        "doc_type": "case_sheet", "encounter": {"date_raw": "27/08/24", "date_iso": "2024-08-27", "facility": "Greenfield Family Clinic"},
        "complaints": ["burning micturition", "frequent urination"],
        "links": [link("burning micturition", "UTI", "Burning micturition, frequency - UTI (2nd episode)"),
                  link("frequent urination", "UTI", "Burning micturition, frequency - UTI (2nd episode)")],
        "negative_history": ["No fever"],
        "diagnoses": [dx(UTI, "Imp: Urinary tract infection. HTN - not controlled."), dx(HTN, "Imp: Urinary tract infection. HTN - not controlled."),
                      dx(DM, "k/c/o DM, HTN, epilepsy", True), dx(EPI, "k/c/o DM, HTN, epilepsy", True)],
        "medications": [med("Nitrofurantoin", "100 mg", "1-0-1", "T. Nitrofurantoin 100 mg 1-0-1 x 5 days", "5 days"),
                        med("Amlodipine", "10 mg", "1-0-0", "T. Amlodipine 10 mg 1-0-0 x 30 days (increased)", "30 days")],
        "investigations": [test("Urine culture", "Urine C/S: E. coli, sensitive to nitrofurantoin", "E. coli, sensitive to nitrofurantoin", None, True)],
        "vitals": [src(name="BP", value="152/96", source_text="BP 152/96")],
    }),
    ("diabetes-2024-11-05.pdf", "typed", """CITY DIABETES CENTRE - OPD
Date: 05/11/2024
Complaints: Passing urine frequently at night.
History: Known type 2 diabetes since Jan 2024. Known hypertension, epilepsy.
Examination: Foot examination normal. BP 134/82.
Investigations: HbA1c 7.6 %. Urine ACR 18 mg/g.
Diagnosis: Type 2 diabetes mellitus - suboptimal control
Plan: Tab Metformin 1000 mg 1-0-1 x 90 days""", {
        "doc_type": "case_sheet", "encounter": {"date_raw": "05/11/2024", "date_iso": "2024-11-05", "facility": "City Diabetes Centre", "encounter_type": "OPD"},
        "complaints": ["frequent urination"],
        # Deliberate mistake: the page does not say what the urination is due to.
        "links": [link("frequent urination", "Type 2 diabetes mellitus", "Complaints: Passing urine frequently at night.")],
        "diagnoses": [dx(DM, "Diagnosis: Type 2 diabetes mellitus - suboptimal control"),
                      dx(HTN, "Known hypertension, epilepsy.", True), dx(EPI, "Known hypertension, epilepsy.", True)],
        "medications": [med("Metformin", "1000 mg", "1-0-1", "Tab Metformin 1000 mg 1-0-1 x 90 days", "90 days")],
        "investigations": [test("HbA1c", "HbA1c 7.6 %", "7.6", "%", True),
                           test("Urine albumin to creatinine ratio", "Urine ACR 18 mg/g", "18", "mg/g", False)],
        "vitals": [src(name="BP", value="134/82", source_text="BP 134/82")],
        "negative_history": ["Foot examination normal"],
    }),
    ("emergency-2025-01-22.pdf", "typed", """CITY HOSPITAL - EMERGENCY DEPARTMENT
Date: 22/01/2025  Time: 09:40
Presenting complaint: Fever 39 C with chills since yesterday. Burning micturition. Generalised seizure at home this morning, approx 3 minutes, witnessed by husband. Worst seizure so far.
Fever with chills, burning micturition - UTI
Seizure provoked by fever - epilepsy
PMH: Type 2 DM, HTN, epilepsy.
No head injury. No missed doses. No neck stiffness.
O/E: T 39.0 C, BP 128/80, drowsy, oriented after 1 hour. Right renal angle tenderness.
Labs: RBS 248 mg/dl. Levetiracetam level 9 ug/ml (12-46). Urine C/S sent.
Diagnosis: Urinary tract infection with fever. Breakthrough seizure.""", {
        "doc_type": "discharge_summary", "encounter": {"date_raw": "22/01/2025", "date_iso": "2025-01-22", "facility": "City Hospital Emergency", "encounter_type": "Emergency"},
        "complaints": ["fever", "burning micturition", "seizures"],
        "episodes": [src(symptom="seizure", when_raw="this morning", date_iso="2025-01-22", date_precision="day", count=1,
                         description="Generalised seizure at home", duration="about 3 minutes", severity_note="Worst seizure so far",
                         is_worst=True, triggers=["fever"],
                         source_text="Generalised seizure at home this morning, approx 3 minutes, witnessed by husband. Worst seizure so far.")],
        "links": [link("fever", "UTI", "Fever with chills, burning micturition - UTI"),
                  link("burning micturition", "UTI", "Fever with chills, burning micturition - UTI"),
                  link("seizure", "epilepsy", "Seizure provoked by fever - epilepsy")],
        "negative_history": ["No head injury", "No missed doses", "No neck stiffness"],
        "diagnoses": [dx(UTI, "Diagnosis: Urinary tract infection with fever. Breakthrough seizure."),
                      dx(DM, "PMH: Type 2 DM, HTN, epilepsy.", True), dx(HTN, "PMH: Type 2 DM, HTN, epilepsy.", True),
                      dx(EPI, "PMH: Type 2 DM, HTN, epilepsy.", True)],
        "investigations": [test("Random blood sugar", "RBS 248 mg/dl", "248", "mg/dl", True),
                           test("Levetiracetam level", "Levetiracetam level 9 ug/ml (12-46)", "9", "ug/ml", True, ref="12-46"),
                           test("Urine culture", "Urine C/S sent", status="ordered")],
        "vitals": [src(name="Temperature", value="39.0", unit="C", source_text="T 39.0 C"), src(name="BP", value="128/80", source_text="BP 128/80")],
    }),
    ("emergency-2025-01-22-rx.jpg", "handwritten", """22/1/25 ER
CBC 11.2 ) 14800 ( 210000
Rx: T. Cefuroxime 500 mg 1-0-1 x 7 days - for UTI
    T. Levetiracetam 750 mg 1-0-1 - continue
    T. Paracetamol 650 mg SOS
    T. Emeset 4 mg SOS
    Hold Metformin till sugars reviewed
Discharged after 8 hrs. Review with GP in 1 week.""", {
        "doc_type": "prescription", "encounter": {"date_raw": "22/1/25", "date_iso": "2025-01-22", "facility": "City Hospital Emergency", "encounter_type": "Emergency"},
        "links": [link("Cefuroxime", "UTI", "T. Cefuroxime 500 mg 1-0-1 x 7 days - for UTI")],
        "medications": [med("Cefuroxime", "500 mg", "1-0-1", "T. Cefuroxime 500 mg 1-0-1 x 7 days - for UTI", "7 days"),
                        med("Levetiracetam", "750 mg", "1-0-1", "T. Levetiracetam 750 mg 1-0-1 - continue"),
                        med("Paracetamol", "650 mg", "SOS", "T. Paracetamol 650 mg SOS"),
                        src(drug_as_written="Emeset", strength="4 mg", frequency="SOS", source_text="T. Emeset 4 mg SOS",
                            confidence=0.55, alternatives=["Emset"]),
                        src(drug_as_written="Metformin", status="held", source_text="Hold Metformin till sugars reviewed"),
                        # Deliberate mistake: not on the page.
                        med("Ciprofloxacin", "500 mg", "1-0-1", "T. Ciprofloxacin 500 mg 1-0-1 x 5 days", "5 days")],
        # The shorthand blood count names none of its values, so the reader only offers likely labels.
        "investigations": [test("", "CBC 11.2 ) 14800 ( 210000", "11.2", None, alternatives=["Haemoglobin"]),
                           test("", "CBC 11.2 ) 14800 ( 210000", "14800", None, alternatives=["Total leucocyte count", "Platelet count"]),
                           test("", "CBC 11.2 ) 14800 ( 210000", "210000", None, alternatives=["Platelet count", "Total leucocyte count"])],
        "advice": ["Review with GP in 1 week"],
    }),
    ("gp-2025-03-18.pdf", "typed", """GREENFIELD FAMILY CLINIC
Date: 18/03/2025
Review after UTI. No urinary symptoms now.
3 UTIs in the last 12 months.
USG KUB (15/03/2025): Both kidneys normal in size and echotexture. No calculi. Post-void residual negligible.
Diagnosis: Recurrent urinary tract infection. Type 2 diabetes mellitus.
Rx: Tab Nitrofurantoin 50 mg 0-0-1 x 3 months - prophylaxis for recurrent UTI
    Continue Metformin 1000 mg 1-0-1""", {
        "doc_type": "case_sheet", "encounter": {"date_raw": "18/03/2025", "date_iso": "2025-03-18", "facility": "Greenfield Family Clinic"},
        "links": [link("Nitrofurantoin", "recurrent UTI", "Tab Nitrofurantoin 50 mg 0-0-1 x 3 months - prophylaxis for recurrent UTI")],
        "negative_history": ["No urinary symptoms now"],
        "diagnoses": [dx(RUTI, "Diagnosis: Recurrent urinary tract infection. Type 2 diabetes mellitus."),
                      dx(DM, "Diagnosis: Recurrent urinary tract infection. Type 2 diabetes mellitus.")],
        "medications": [med("Nitrofurantoin", "50 mg", "0-0-1", "Tab Nitrofurantoin 50 mg 0-0-1 x 3 months - prophylaxis for recurrent UTI", "3 months"),
                        med("Metformin", "1000 mg", "1-0-1", "Continue Metformin 1000 mg 1-0-1")],
        "investigations": [test("Ultrasound kidneys and bladder", "USG KUB (15/03/2025): Both kidneys normal in size and echotexture.",
                                "Both kidneys normal in size and echotexture", None, False, kind="imaging")],
    }),
    # A report filed with this patient's papers but probably someone else's: similar name, different age.
    ("lab-2025-02-10.pdf", "typed", """SUNRISE DIAGNOSTICS
Name: Meera N.    Age/Sex: 64/F    Date: 10/02/2025
Thyroid profile: TSH 8.9 mIU/L (0.4-4.0)
Impression: Raised TSH. Suggest clinical correlation.""", {
        "doc_type": "lab_report", "encounter": {"date_raw": "10/02/2025", "date_iso": "2025-02-10", "facility": "Sunrise Diagnostics"},
        "patient": {"name": "Meera N.", "age": "64", "sex": "F"},
        "investigations": [test("TSH", "TSH 8.9 mIU/L (0.4-4.0)", "8.9", "mIU/L", True, ref="0.4-4.0")],
    }),
]


def main() -> None:
    records = []
    for n, (filename, script, text, data) in enumerate(PAGES, start=1):
        x = PageExtraction.model_validate({"transcription": text, "script": script, "patient": {"name": "Meera Nair", "age": "46", "sex": "F"}, **data})
        issues, grounding = verify_page(x, text if script == "typed" else None)
        records.append(ExtractionRecord(page_id=f"demo-{n:02d}", source_file=f"demo/{filename}", page_number=1, extractor="demo",
                                        extraction=x, issues=[i.model_dump() for i in issues], grounding=grounding))
        for i in issues:
            print(f"{filename}: {i.section}[{i.index}].{i.field} {'BLOCK' if i.blocking else 'note'}: {i.reason}")
    out = Path(__file__).resolve().parents[1] / "src/medtimeline/demo/records.json"
    out.write_text(json.dumps([r.model_dump(mode="json") for r in records], indent=1))
    print(f"wrote {len(records)} pages to {out}")


if __name__ == "__main__":
    main()
