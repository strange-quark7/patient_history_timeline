// Builds what the detail panel shows for the selected element. Everything comes from the bundle.
import { BASIS_TEXT, GROUNDING_TEXT, cap, episodeWhen, fmtDate, makeFilter, openReview, roleText, verdict, visitLabel, flagType } from "./model";
import type { Bundle, Encounter, Episode, ReviewItem, Test } from "./types";

export type Sel = { kind: "visit" | "episode" | "symptom" | "med" | "test" | "change" | "condition" | "review"; id: string };
export type Tone = "info" | "warn" | "severe" | "plain";
/** Label buttons for a review item: pick one of the options, leave it unsure, or undo a choice. */
export type Choices = { key: string; options: string[]; resolved: boolean; choice: string | null };
export type Row = { label?: string; value: string; link?: Sel; tone?: Tone; flagColor?: string; hollow?: boolean; choices?: Choices };
export type Section = { heading: string; rows: Row[] };
export type Detail = { kind: string; title: string; sub: string; badges: { text: string; tone: Tone }[]; sections: Section[] };

export class Index {
  enc = new Map<string, Encounter>();
  constructor(public b: Bundle) {
    b.encounters.forEach((e) => this.enc.set(e.id, e));
  }
  visit = (id: string) => this.enc.get(id)!;
  cond = (id: string | null) => this.b.conditions.find((c) => c.id === id);
  med = (id: string) => this.b.medications.find((m) => m.id === id);
  medLabel = (id: string) => this.med(id)?.label ?? id;
  test = (id: string) => this.b.tests.find((t) => t.id === id);
}

const text = (value: string, label?: string, tone?: Tone): Row => ({ value, label, tone });
const link = (value: string, to: Sel, label?: string): Row => ({ value, link: to, label });
const none = (what: string): Row[] => [text(what)];

function sourceCheck(ix: Index, enc: Encounter, quote?: string | null, approx?: string): Section {
  const groundings = Array.from(new Set(enc.pages.map((p) => p.grounding)));
  const rows: Row[] = [text(groundings.map((g) => GROUNDING_TEXT[g] ?? g).join("; "), "Checked against")];
  rows.push(quote ? text(`"${quote}"`, "Quote found on the page") : text("Names, numbers and dates match the quoted text", "Result"));
  if (approx) rows.push(text(approx, "Date", "warn"));
  rows.push(...enc.pages.map((p) => text(`${p.file}, page ${p.page} (${p.script})`, "Page")));
  void ix;
  return { heading: "Source check", rows };
}

function checkBadges(enc: Encounter, approx = false) {
  const out: { text: string; tone: Tone }[] = [{ text: "✓ Checked against source", tone: "info" }];
  if (approx) out.push({ text: "Approximate date", tone: "warn" });
  if (enc.pages.some((p) => p.script === "handwritten")) out.push({ text: "Handwritten page", tone: "plain" });
  return out;
}

const testRow = (t: Test): Row => link(`${t.labelled_by_user ? "(labelled by you) " : ""}${t.value ?? (t.status === "ordered" ? "Ordered" : "No result")}${t.unit ? ` ${t.unit}` : ""}${t.abnormal ? " · abnormal" : ""}`, { kind: "test", id: t.id }, t.name);

function testsSections(ix: Index, ids: string[]): Section[] {
  const tests = ids.map(ix.test).filter(Boolean) as Test[];
  const labs = tests.filter((t) => t.kind === "lab");
  const scans = tests.filter((t) => t.kind !== "lab");
  return [
    { heading: "Labs", rows: labs.length ? labs.map(testRow) : none("None at this visit") },
    { heading: "Scans and studies", rows: scans.length ? scans.map(testRow) : none("None at this visit") },
  ];
}

export function visitDetail(ix: Index, id: string): Detail {
  const v = ix.visit(id);
  const eps = ix.b.episodes.filter((e) => e.reported_at === id);
  const given = v.medications.filter((m) => m.status === "prescribed");
  const paused = v.medications.filter((m) => m.status !== "prescribed");
  return {
    kind: v.encounter_type ? `Visit · ${v.encounter_type}` : "Visit",
    title: fmtDate(v.date), sub: [v.facility, v.clinician].filter(Boolean).join(" · "),
    badges: [...(v.date_status === "ambiguous" ? [{ text: "Date could be read two ways", tone: "warn" as Tone }] : []), ...checkBadges(v)],
    sections: [
      { heading: "Conditions at this visit", rows: v.condition_ids.map((c) => link(ix.cond(c)!.name, { kind: "condition", id: c }, roleText(ix.cond(c)!))) },
      { heading: "What was new at this visit", rows: v.flags.length ? v.flags.map((f) => ({ ...text(cap(f.text), flagType(f.kind)?.label), flagColor: flagType(f.kind)?.color, hollow: "hollow" in (flagType(f.kind) ?? {}) })) : none("Nothing new recorded") },
      { heading: "Complaints", rows: v.complaints.length ? v.complaints.map((c) => text(cap(c))) : none("None recorded") },
      { heading: "Negative history", rows: v.negative_history.length ? v.negative_history.map((c) => text(c)) : none("None recorded") },
      { heading: "Episodes reported", rows: eps.length ? eps.map((e) => link(`${episodeWhen(e)} · ${e.symptom}${e.count > 1 ? ` ×${e.count}` : ""}${e.is_worst ? " · worst" : ""}`, { kind: "episode", id: e.id })) : none("None reported") },
      { heading: "Prescribed at this visit", rows: given.length ? given.map((m) => link(`${m.dose}${m.duration ? `, ${m.duration}` : ""}`, { kind: "med", id: m.med_id }, m.label)) : none("Nothing prescribed") },
      ...(paused.length ? [{ heading: "Held or stopped at this visit", rows: paused.map((m) => link(cap(m.status), { kind: "med", id: m.med_id }, m.label)) }] : []),
      ...testsSections(ix, v.test_ids),
      { heading: "Vitals", rows: v.vitals.length ? v.vitals.map((x) => text(`${x.value}${x.unit ? ` ${x.unit}` : ""}`, x.name)) : none("None recorded") },
      sourceCheck(ix, v),
    ],
  };
}

export function episodeDetail(ix: Index, id: string): Detail {
  const e = ix.b.episodes.find((x) => x.id === id)!;
  const v = ix.visit(e.reported_at);
  const approx = e.approx_date ? `Written as '${e.when_raw}'; the date is worked out from it` : undefined;
  const what: Row[] = [
    ...(e.description ? [text(cap(e.description), "What happened")] : []),
    ...(e.duration ? [text(e.duration, "Duration")] : []),
    ...(e.severity_note ? [text(e.severity_note, "Severity as written", e.is_worst ? "severe" : undefined)] : []),
    ...(e.triggers.length ? [text(e.triggers.join(", "), "Triggers")] : []),
    ...(e.when_raw ? [text(e.when_raw, "When, as written")] : []),
    ...(e.count > 1 ? [text(String(e.count), "Episodes in this report")] : []),
  ];
  const cond = ix.cond(e.condition_id);
  return {
    kind: `${cap(e.symptom)} episode`, title: episodeWhen(e), sub: [e.description, e.duration].filter(Boolean).join(" · "),
    badges: [...(e.is_worst ? [{ text: "Worst reported", tone: "severe" as Tone }] : []), ...checkBadges(v, e.approx_date)],
    sections: [
      { heading: "What happened", rows: what.length ? what : none("No further detail written") },
      { heading: "Negative history at that visit", rows: v.negative_history.length ? v.negative_history.map((n) => text(n)) : none("None recorded") },
      { heading: "Medication at the time", rows: e.medications_at_time.length ? e.medications_at_time.map((m) => link(m.dose, { kind: "med", id: m.med_id }, ix.medLabel(m.med_id))) : none("None recorded as active") },
      { heading: "Tied to", rows: cond ? [link(cond.name, { kind: "condition", id: cond.id }, "Written on the page")] : [text("The page does not tie it to a condition", undefined, "warn")] },
      ...testsSections(ix, v.test_ids),
      { heading: "Recorded at", rows: [link(visitLabel(v), { kind: "visit", id: v.id })] },
      sourceCheck(ix, v, e.source_text, approx),
    ],
  };
}

export function symptomDetail(ix: Index, id: string): Detail {
  const s = ix.b.symptoms.find((x) => x.id === id)!;
  const eps = ix.b.episodes.filter((e) => s.episode_ids.includes(e.id));
  return {
    kind: "Symptom", title: cap(s.name), sub: `${fmtDate(s.first_seen)} to ${fmtDate(s.last_seen)}`,
    badges: [{ text: `${s.encounter_ids.length} visit${s.encounter_ids.length === 1 ? "" : "s"}`, tone: "plain" },
             ...(eps.length ? [{ text: `${s.episode_count} episode${s.episode_count === 1 ? "" : "s"}`, tone: "info" as Tone }] : [])],
    sections: [
      { heading: "Tied to, visit by visit", rows: s.occurrences.map((o) => (o.condition_id
        ? link(`${ix.cond(o.condition_id)!.name} (written on the page)`, { kind: "condition", id: o.condition_id }, fmtDate(o.date))
        : text("Not tied to a condition on the page", fmtDate(o.date), "warn"))) },
      { heading: "Visits", rows: s.encounter_ids.map((v) => link(visitLabel(ix.visit(v)), { kind: "visit", id: v })) },
      ...(eps.length ? [{ heading: "Reported episodes", rows: eps.map((e) => link(`${episodeWhen(e)}${e.count > 1 ? ` ×${e.count}` : ""}${e.is_worst ? " · worst" : ""}`, { kind: "episode", id: e.id } as Sel)) }] : []),
    ],
  };
}

export function medDetail(ix: Index, id: string): Detail {
  const m = ix.med(id)!;
  const cond = ix.cond(m.condition_id);
  const during = ix.b.episodes.filter((e) => e.medications_at_time.some((x) => x.med_id === id));
  const changes = ix.b.changes.filter((c) => c.med_id === id);
  return {
    kind: "Medication", title: m.label, sub: m.periods.map((p) => p.dose).filter((d, i, a) => a.indexOf(d) === i).join(" → "),
    badges: [m.status !== "prescribed" ? { text: `${cap(m.status)} ${fmtDate(m.end)}`, tone: "warn" } : m.current ? { text: "Current", tone: "info" } : { text: `Last recorded ${fmtDate(m.end)}`, tone: "plain" },
             { text: "✓ Checked against source", tone: "info" }, ...(m.steps.some((s) => s.labelled_by_user) ? [{ text: "Name chosen by you", tone: "plain" as Tone }] : [])],
    sections: [
      { heading: "Treats", rows: cond ? [link(cond.name, { kind: "condition", id: cond.id }, BASIS_TEXT[m.condition_basis ?? ""] ?? "")] : [text("Neither the page nor the drug table settles it", "Not tied to a condition", "warn")] },
      { heading: "When it was in force", rows: m.periods.map((p) => link(`${p.dose}, ${fmtDate(p.start)}${p.end !== p.start ? ` to ${fmtDate(p.end)}` : " (that day, or as needed)"}`, { kind: "visit", id: p.encounter_id })) },
      { heading: "Changes", rows: changes.length ? changes.map((c) => link(`${cap(c.kind)}${c.kind === "dose change" ? `: ${c.previous_dose} to ${c.dose}` : c.dose ? `, ${c.dose}` : ""}`, { kind: "change", id: c.id }, fmtDate(c.date))) : none("None") },
      { heading: "Episodes while taking it", rows: during.length ? during.map((e) => link(`${episodeWhen(e)} · ${e.symptom}`, { kind: "episode", id: e.id })) : none("None recorded") },
      { heading: "As written", rows: m.steps.map((s) => text(`"${s.source_text}"`, fmtDate(s.date))) },
    ],
  };
}

export function testDetail(ix: Index, id: string): Detail {
  const t = ix.test(id)!;
  const v = ix.visit(t.encounter_id);
  const cond = ix.cond(t.condition_id);
  return {
    kind: t.kind === "lab" ? "Lab" : "Scan or study", title: t.name, sub: fmtDate(t.date),
    badges: [...(t.abnormal ? [{ text: "Abnormal", tone: "severe" as Tone }] : t.abnormal === false ? [{ text: "Normal", tone: "plain" as Tone }] : []), ...checkBadges(v),
             ...(t.labelled_by_user ? [{ text: "Label chosen by you", tone: "warn" as Tone }] : [])],
    sections: [
      { heading: "Result", rows: [text(t.value ? `${t.value}${t.unit ? ` ${t.unit}` : ""}` : t.status === "ordered" ? "Ordered; no result in these pages" : "No result", undefined, t.abnormal ? "severe" : undefined),
                                   ...(t.reference_range ? [text(t.reference_range, "Range as written")] : [])] },
      { heading: "Ordered at", rows: [link(visitLabel(v), { kind: "visit", id: v.id })] },
      { heading: "For", rows: cond ? [link(cond.name, { kind: "condition", id: cond.id })] : none("Not tied to a condition on the page") },
      ...(t.labelled_by_user ? [{ heading: "Label", rows: [text("The page gives this value without naming it. You chose this label in Needs review.", undefined, "warn")] }] : []),
      sourceCheck(ix, v, t.source_text),
    ],
  };
}

export function conditionDetail(ix: Index, id: string): Detail {
  const c = ix.cond(id)!;
  const f = makeFilter(id);
  const meds = ix.b.medications.filter(f.med);
  const syms = ix.b.symptoms.filter(f.symptom);
  const eps = ix.b.episodes.filter(f.episode);
  const sections: Section[] = [{ heading: "Course", rows: [text(roleText(c)), text(`First recorded ${fmtDate(c.first_seen)}${c.known ? " as past history" : ""}`)] }];
  if (c.course === "acute") sections.push({ heading: "Episodes", rows: c.episodes.map((e, i) => link(`${fmtDate(e.start)}${e.end && e.end !== e.start ? ` to ${fmtDate(e.end)}` : ""}`, { kind: "visit", id: e.encounter_ids[0] }, `Episode ${i + 1}`)) });
  sections.push(
    { heading: "Visits that recorded it", rows: c.encounter_ids.map((v) => link(visitLabel(ix.visit(v)), { kind: "visit", id: v })) },
    { heading: "Drugs tied to it", rows: meds.length ? meds.map((m) => link(m.label, { kind: "med", id: m.id }, BASIS_TEXT[m.condition_basis ?? ""])) : none("None tied to it") },
    { heading: "Symptoms tied to it on the page", rows: syms.length ? syms.map((s) => link(cap(s.name), { kind: "symptom", id: s.id })) : none("None tied to it") },
  );
  if (eps.length) sections.push({ heading: "Reported episodes", rows: eps.map((e) => link(`${episodeWhen(e)} · ${e.symptom}${e.is_worst ? " · worst" : ""}`, { kind: "episode", id: e.id })) });
  return {
    kind: "Condition", title: c.name, sub: `${c.encounter_ids.length} visit${c.encounter_ids.length === 1 ? "" : "s"} · ${meds.length} drug${meds.length === 1 ? "" : "s"} tied to it`,
    badges: [{ text: roleText(c), tone: c.course === "acute" ? "warn" : "info" }, ...(c.course === "acute" ? [{ text: `${c.episodes.length} episode${c.episodes.length === 1 ? "" : "s"}`, tone: "plain" as Tone }] : [])],
    sections,
  };
}

export function changeDetail(ix: Index, id: string, cond: string | null): Detail {
  const ch = ix.b.changes.find((c) => c.id === id)!;
  const corr = (ix.b.correlation[cond ?? "all"] ?? []).find((c) => c.date === ch.date && c.drug === ch.drug);
  const fmt = (w: { episodes: number; per_month: number; start: string; end: string }) =>
    `${w.episodes} episode${w.episodes === 1 ? "" : "s"} from ${fmtDate(w.start)} to ${fmtDate(w.end)} (${w.per_month.toFixed(1)} a month)`;
  const v = corr ? verdict(corr) : { text: "Not in this view", tone: "plain" as Tone };
  const f = makeFilter(cond);
  const after = corr?.after ? ix.b.episodes.filter((e) => f.episode(e) && e.date && e.date >= corr.after!.start && e.date < corr.after!.end) : [];
  return {
    kind: "Medication change", title: `${ix.medLabel(ch.med_id)} ${ch.kind}`, sub: `${fmtDate(ch.date)}${ch.kind === "dose change" ? ` · ${ch.previous_dose} to ${ch.dose}` : ch.dose ? ` · ${ch.dose}` : ""}`,
    badges: [{ text: v.text, tone: v.tone }],
    sections: [
      { heading: "Before (since the previous change)", rows: [text(corr?.before ? fmt(corr.before) : "Nothing recorded before")] },
      { heading: "After (until the next change)", rows: [text(corr?.after ? fmt(corr.after) : "Too soon to tell")] },
      { heading: "Episodes after", rows: after.length ? after.map((e) => link(`${episodeWhen(e)} · ${e.symptom}`, { kind: "episode", id: e.id })) : none("None recorded") },
      { heading: "Medication", rows: [link(ix.medLabel(ch.med_id), { kind: "med", id: ch.med_id })] },
      { heading: "Recorded at", rows: [link(visitLabel(ix.visit(ch.encounter_id)), { kind: "visit", id: ch.encounter_id })] },
      { heading: "Note", rows: [text("This lines up timing only. It does not show that the change caused what followed.")] },
    ],
  };
}

const SECTION_NAMES: Record<string, string> = { medications: "Medication", diagnoses: "Diagnosis", investigations: "Lab or scan", vitals: "Vital sign", episodes: "Episode", links: "Link to a condition", negative_history: "Negative history", encounter: "Visit date" };

const where = (r: ReviewItem) => text(r.page ? `${r.page.file}, page ${r.page.page} (${r.page.script})` : r.page_id, "Page");
const choicesOf = (r: ReviewItem): Choices => ({ key: r.key!, options: r.options, resolved: r.resolved, choice: r.choice });

export function reviewDetail(ix: Index): Detail {
  const open = openReview(ix.b.review_items);
  const toLabel = open.filter((r) => r.key);
  const failed = open.filter((r) => !r.key);
  const settled = ix.b.review_items.filter((r) => r.resolved);
  const notes = ix.b.review_items.filter((r) => !r.blocking && !r.key);
  return {
    kind: "Needs review", title: open.length ? `${open.length} item${open.length === 1 ? "" : "s"} to check` : "Nothing left to check",
    sub: "The reader picked these up, but a check failed or the reading is unsure. Pick the right label, or leave it unsure. Nothing here is shown as a fact until you do.",
    badges: [{ text: "Not shown as facts", tone: "warn" }, ...(settled.length ? [{ text: `${settled.length} settled by you`, tone: "plain" as Tone }] : []),
             ...(notes.length ? [{ text: `${notes.length} caution${notes.length === 1 ? "" : "s"} shown on the timeline`, tone: "plain" as Tone }] : [])],
    sections: [
      ...toLabel.map((r) => ({ heading: r.field === "reading" ? `Unsure reading · ${SECTION_NAMES[r.section] ?? r.section}` : `Needs a label · ${SECTION_NAMES[r.section] ?? r.section}`, rows: [
        ...(r.source_text ? [text(`"${r.source_text}"`, "Written on the page")] : []),
        ...(r.value ? [text(r.value, "Value")] : []),
        ...(r.reading && r.field === "reading" ? [text(r.reading, "Read as (kept on the timeline for now)")] : []),
        where(r),
        { label: r.field === "label" ? "Most likely labels" : "Most likely readings", value: "", choices: choicesOf(r) },
      ] })),
      ...failed.map((r) => ({ heading: SECTION_NAMES[r.section] ?? r.section, rows: [
        ...(r.source_text ? [text(`"${r.source_text}"`, "Read as")] : []),
        where(r),
        text(cap(r.reason), "Why it was held out", "warn"),
      ] })),
      ...(settled.length ? [{ heading: "Settled by you", rows: settled.map((r) => ({
        label: `${SECTION_NAMES[r.section] ?? r.section}${r.value ? ` · ${r.value}` : ""}`,
        value: r.choice ? `Labelled "${r.choice}"` : r.field === "label" ? "Left unlabelled" : "Left unsure",
        choices: choicesOf(r),
      })) }] : []),
      ...(notes.length ? [{ heading: "Cautions kept on the timeline", rows: notes.map((r) => text(cap(r.reason), SECTION_NAMES[r.section] ?? r.section)) }] : []),
    ],
  };
}

export function detailFor(ix: Index, sel: Sel, cond: string | null): Detail {
  switch (sel.kind) {
    case "visit": return visitDetail(ix, sel.id);
    case "episode": return episodeDetail(ix, sel.id);
    case "symptom": return symptomDetail(ix, sel.id);
    case "med": return medDetail(ix, sel.id);
    case "test": return testDetail(ix, sel.id);
    case "condition": return conditionDetail(ix, sel.id);
    case "change": return changeDetail(ix, sel.id, cond);
    case "review": return reviewDetail(ix);
  }
}

export type { Episode };
