// Pure display helpers: time scale, labels, filters. No clinical rules live here.
import type { Bundle, Condition, Correlated, Encounter, Episode, Medication, Symptom, Test, ReviewItem } from "./types";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY = 86_400_000;

const toTime = (d: string) => Date.parse(d + "T00:00:00Z");

export function fmtDate(d: string | null | undefined, precision = "day"): string {
  if (!d) return "Undated";
  const [y, m, day] = d.split("-").map(Number);
  if (precision === "year") return String(y);
  if (precision === "month") return `${MONTHS[m - 1]} ${y}`;
  return `${day} ${MONTHS[m - 1]} ${y}`;
}

export type Scale = {
  x: (d: string | null | undefined) => number; // 0..1 across the axis
  ticks: { label: string; at: number }[];
  start: string;
  end: string;
  monthBuckets: { label: string; from: string; to: string }[];
};

/** Monthly axis from the first to the last date, padded to whole months. */
export function makeScale(b: Bundle): Scale {
  const s = b.span.start ?? new Date().toISOString().slice(0, 10);
  const e = b.span.end ?? s;
  const [sy, sm] = s.split("-").map(Number);
  const [ey, em] = e.split("-").map(Number);
  const months: { y: number; m: number }[] = [];
  for (let y = sy, m = sm; y < ey || (y === ey && m <= em); m === 12 ? ((m = 1), y++) : m++) months.push({ y, m });
  const iso = (y: number, m: number) => `${y}-${String(m).padStart(2, "0")}-01`;
  const start = iso(months[0].y, months[0].m);
  const last = months[months.length - 1];
  const end = last.m === 12 ? iso(last.y + 1, 1) : iso(last.y, last.m + 1);
  const t0 = toTime(start), t1 = toTime(end);
  const x = (d: string | null | undefined) => (d ? Math.min(1, Math.max(0, (toTime(d) - t0) / (t1 - t0))) : 0);
  const step = months.length > 36 ? 12 : months.length > 18 ? 3 : 1;
  const ticks = months
    .map((mo, i) => ({ mo, i }))
    .filter(({ mo, i }) => i === 0 || step === 1 || (mo.m - 1) % step === 0)
    .map(({ mo, i }) => ({ label: mo.m === 1 || i === 0 ? `${MONTHS[mo.m - 1]} ${String(mo.y).slice(2)}` : MONTHS[mo.m - 1], at: x(iso(mo.y, mo.m)) }));
  const monthBuckets = months.map((mo) => ({ label: `${MONTHS[mo.m - 1]} ${mo.y}`, from: iso(mo.y, mo.m), to: mo.m === 12 ? iso(mo.y + 1, 1) : iso(mo.y, mo.m + 1) }));
  return { x, ticks, start, end, monthBuckets };
}

export const pct = (v: number) => `${(v * 100).toFixed(3)}%`;
export const days = (a: string, b: string) => Math.round((toTime(b) - toTime(a)) / DAY);

export const FLAG_TYPES = [
  { kind: "new_symptom", id: "sym", label: "New symptom", color: "var(--f-sym)" },
  { kind: "new_diagnosis", id: "dx", label: "New diagnosis", color: "var(--f-dx)" },
  { kind: "new_comorbidity", id: "como", label: "New comorbidity", color: "var(--f-dx)", hollow: true },
  { kind: "known_comorbidity", id: "known", label: "Known comorbidity", color: "var(--muted)", hollow: true },
  { kind: "medication_change", id: "med", label: "Medication change", color: "var(--f-med)" },
  { kind: "acute_illness", id: "acute", label: "Acute illness", color: "var(--f-acute)" },
  { kind: "abnormal_result", id: "abn", label: "Abnormal result", color: "var(--f-abn)" },
  { kind: "emergency", id: "er", label: "Emergency or admission", color: "var(--f-er)" },
] as const;
export type FlagType = (typeof FLAG_TYPES)[number];
export const flagType = (kind: string) => FLAG_TYPES.find((f) => f.kind === kind);

export const ROLE_TEXT: Record<string, string> = {
  primary: "Long-term, diagnosed in these records",
  comorbidity: "Long-term, found later or past history",
  acute: "Acute, comes and goes",
};
export function roleText(c: Condition): string {
  if (c.course === "acute") return ROLE_TEXT.acute;
  if (c.known) return "Long-term, past history";
  if (c.course === "unclassified") return "Not classified (seen once)";
  return c.role === "primary" ? ROLE_TEXT.primary : "Long-term, found later";
}
export const BASIS_TEXT: Record<string, string> = {
  page: "Written on the page",
  drug_table: "Drug table: the only one of this patient's conditions it is used for",
};
export const GROUNDING_TEXT: Record<string, string> = {
  text_layer: "The PDF's own text (typed page)",
  transcription: "The AI transcription of a handwritten page; a second reader is planned",
  none: "Nothing to check against",
  unchecked: "Not checked",
};

export const visitLabel = (e: Encounter) => `${fmtDate(e.date)}${e.facility ? ` · ${e.facility}` : ""}`;
export const episodeWhen = (e: Episode) => (e.date ? fmtDate(e.date, e.date_precision) : e.when_raw ?? "Undated");

/** What the condition filter keeps. `null` keeps everything. */
export function makeFilter(cond: string | null) {
  return {
    visit: (v: Encounter) => !cond || v.condition_ids.includes(cond),
    episode: (e: Episode) => !cond || e.condition_id === cond,
    med: (m: Medication) => !cond || m.condition_id === cond,
    symptom: (s: Symptom) => !cond || s.condition_ids.includes(cond),
    test: (t: Test) => !cond || t.condition_id === cond,
  };
}

/** Plain-language summary of a before/after window pair. Timing only; never cause. */
export function verdict(c: Correlated): { text: string; tone: "info" | "warn" | "plain" } {
  if (!c.after) return { text: "Too soon to tell", tone: "plain" };
  if (!c.before) return { text: "Nothing recorded before", tone: "plain" };
  const a = c.after.per_month, b = c.before.per_month;
  if (a === 0 && b === 0) return { text: "No episodes either side", tone: "plain" };
  if (a < b * 0.85) return { text: "Fewer episodes after", tone: "info" };
  if (a > b * 1.15) return { text: "More episodes after", tone: "warn" };
  return { text: "Similar frequency", tone: "plain" };
}

/** Review items still waiting on a person: failed checks, and label choices not yet settled. */
export const openReview = (items: ReviewItem[]) => items.filter((r) => !r.resolved && (r.blocking || r.key));

export const CHANGE_MARK: Record<string, string> = { "first recorded": "+", "dose change": "↕", held: "‖", stopped: "×", resumed: "↺" };

export const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
