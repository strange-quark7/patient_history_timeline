// Shapes returned by the engine (engine/src/medtimeline/bundle.py). The app only displays them.

export type Flag = { kind: string; text: string };
export type Page = { page_id: string; file: string; page: number; grounding: string; script: string; doc_type: string };
export type Dose = { med_id: string; dose: string };

export type Condition = {
  id: string; name: string; short: string;
  course: "long_term" | "acute" | "unclassified"; role: "primary" | "comorbidity" | "acute"; known: boolean;
  first_seen: string | null; last_seen: string | null; encounter_ids: string[];
  episodes: { start: string | null; end: string | null; encounter_ids: string[] }[];
};

export type Encounter = {
  id: string; date: string | null; date_status: string; facility: string | null; clinician: string | null;
  encounter_type: string | null; complaints: string[]; negative_history: string[]; advice: string[];
  diagnoses: { text: string; known: boolean }[]; vitals: { name: string; value: string; unit: string | null }[];
  medications: { med_id: string; label: string; dose: string; duration: string | null }[];
  condition_ids: string[]; flags: Flag[]; test_ids: string[]; episode_ids: string[];
  medications_at_time: Dose[]; pages: Page[]; needs_review: number;
};

export type Episode = {
  id: string; symptom: string; date: string | null; date_precision: string; when_raw: string | null; count: number;
  description: string | null; duration: string | null; severity_note: string | null; is_worst: boolean; triggers: string[];
  reported_at: string; condition_id: string | null; confidence: number; source_text: string; approx_date: boolean;
  medications_at_time: Dose[];
};

export type Symptom = {
  id: string; name: string; first_seen: string | null; last_seen: string | null; encounter_ids: string[];
  episode_ids: string[]; episode_count: number;
  occurrences: { encounter_id: string; date: string | null; condition_id: string | null }[]; condition_ids: string[];
};

export type Medication = {
  id: string; drug: string; label: string; start: string | null; end: string | null; current: boolean;
  condition_id: string | null; condition_basis: "page" | "drug_table" | null;
  steps: { encounter_id: string; date: string | null; dose: string; duration: string | null; as_written: string; source_text: string }[];
  periods: { start: string; end: string; encounter_id: string; dose: string }[];
};

export type Change = { id: string; date: string; med_id: string; drug: string; kind: string; dose: string | null; previous_dose: string | null; encounter_id: string };

export type Test = {
  id: string; name: string; kind: string; status: string; value: string | null; unit: string | null; reference_range: string | null;
  abnormal: boolean | null; encounter_id: string; date: string | null; condition_id: string | null; source_text: string;
};

export type Window = { start: string; end: string; episodes: number; worst_episodes: number; per_month: number };
export type Correlated = { date: string; drug: string; kind: string; dose: string | null; previous_dose: string | null; encounter_id: string; before: Window | null; after: Window | null };

export type ReviewItem = { page_id: string; section: string; field: string; reason: string; source_text: string | null; blocking: boolean; page: Page | null };

export type Bundle = {
  patient: { name: string | null; conflicts: string[] };
  span: { start: string | null; end: string | null };
  conditions: Condition[]; encounters: Encounter[]; episodes: Episode[]; symptoms: Symptom[];
  medications: Medication[]; changes: Change[]; tests: Test[];
  correlation: Record<string, Correlated[]>;
  review_items: ReviewItem[]; pages_needing_review: string[];
};

export type Project = { id: string; name: string; source_folder?: string; extractor?: string; updated?: number; pages?: number; failures?: string[] };
export type Opened = { project: Project; bundle: Bundle; failures?: string[] };
