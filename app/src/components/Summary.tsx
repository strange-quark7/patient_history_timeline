// One-page summary of a patient's history, laid out for A4 print or "Save as PDF".
// Everything comes from the bundle; nothing here adds clinical meaning.
import { useMemo } from "react";
import { Index } from "../details";
import { cap, fmtDate, makeScale, openReview, roleText } from "../model";
import type { Bundle } from "../types";

const W = 1000, LABEL = 170, PLOT = W - LABEL - 8;
const MAX_MEDS = 9, MAX_ROWS = 5, MAX_VISITS = 3;
const NOTABLE = new Set(["emergency", "new_diagnosis", "new_comorbidity", "acute_illness", "new_symptom"]);
const clip = (s: string, n = 24) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

const more = (n: number, what: string) => (n > 0 ? <li className="muted">+{n} more {what} in the app</li> : null);

export function Summary({ bundle, title, onBack }: { bundle: Bundle; title: string; onBack: () => void }) {
  const ix = useMemo(() => new Index(bundle), [bundle]);
  const scale = useMemo(() => makeScale(bundle), [bundle]);
  const x = (d: string | null | undefined) => LABEL + scale.x(d) * PLOT;

  const name = bundle.patient.name ?? title;
  const visits = bundle.encounters.filter((v) => v.date);
  const pages = new Set(bundle.encounters.flatMap((v) => v.pages.map((p) => p.page_id))).size;
  const open = openReview(bundle.review_items).length;
  const labelled = bundle.tests.filter((t) => t.labelled_by_user).length + bundle.medications.filter((m) => m.steps.some((s) => s.labelled_by_user)).length;

  const meds = [...bundle.medications].sort((a, b) => Number(b.current) - Number(a.current) || (b.end ?? "").localeCompare(a.end ?? ""));
  const shownMeds = meds.slice(0, MAX_MEDS).sort((a, b) => (a.start ?? a.end ?? "").localeCompare(b.start ?? b.end ?? ""));
  const current = bundle.medications.filter((m) => m.current);
  const paused = bundle.medications.filter((m) => m.status !== "prescribed");
  const heldOn = (id: string) => bundle.changes.filter((c) => c.med_id === id && (c.kind === "held" || c.kind === "stopped"));
  const anyPause = bundle.changes.some((c) => c.kind === "held" || c.kind === "stopped");

  const symptoms = [...bundle.symptoms].sort((a, b) => b.episode_count - a.episode_count || (b.last_seen ?? "").localeCompare(a.last_seen ?? ""));
  const worst = bundle.episodes.filter((e) => e.is_worst);
  const latest = new Map<string, (typeof bundle.tests)[number]>();
  for (const t of bundle.tests) if (t.value && (!latest.has(t.name) || (t.date ?? "") > (latest.get(t.name)!.date ?? ""))) latest.set(t.name, t);
  const results = [...latest.values()].sort((a, b) => Number(!!b.abnormal) - Number(!!a.abnormal) || (b.date ?? "").localeCompare(a.date ?? ""));
  const recent = [...visits].reverse();

  // Figure rows: visits, episodes, one per condition, one per drug.
  const rows: { label: string; y: number }[] = [];
  let y = 28;
  const addRow = (label: string, h = 19) => { rows.push({ label: clip(label), y }); y += h; return y - h; };
  const yVisits = addRow("Visits");
  const yEps = bundle.episodes.length ? addRow("Episodes") : -1;
  const yConds = bundle.conditions.map((c) => addRow(c.short));
  y += 6;
  const yMeds = shownMeds.map((m) => addRow(m.label, 17));
  const H = y + 4;

  return (
    <div className="summary-wrap">
      <div className="summary-tools no-print">
        <button className="linkrow" style={{ fontSize: 14 }} onClick={onBack}>← Back to the timeline</button>
        <button className="btn primary" onClick={() => window.print()}>Print or save as PDF</button>
      </div>
      <article className="sheet" aria-label="One-page summary">
        <header className="sheet-head">
          <div>
            <h1>{name}</h1>
            <div className="muted">
              {[bundle.patient.sex === "F" ? "Female" : bundle.patient.sex === "M" ? "Male" : null,
                bundle.patient.born_about ? `born about ${bundle.patient.born_about}` : null,
                `${visits.length} visit${visits.length === 1 ? "" : "s"}`, bundle.span.start ? `${fmtDate(bundle.span.start)} to ${fmtDate(bundle.span.end)}` : null,
                `${pages} page${pages === 1 ? "" : "s"} read`].filter(Boolean).join(" · ")}
            </div>
          </div>
          <div className="muted" style={{ textAlign: "right" }}>Patient history summary<br />Made {fmtDate(new Date().toISOString().slice(0, 10))}</div>
        </header>

        <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Timeline of visits, episodes, conditions and medications" className="sheet-fig">
          {scale.ticks.map((t) => (
            <g key={t.label + t.at}>
              <line x1={LABEL + t.at * PLOT} x2={LABEL + t.at * PLOT} y1={16} y2={H} stroke="var(--line-soft)" />
              <text x={LABEL + t.at * PLOT + 3} y={11} fontSize="11" fill="var(--muted)">{t.label}</text>
            </g>
          ))}
          {rows.map((r) => <text key={r.label + r.y} x={0} y={r.y + 14} fontSize="12" fill="var(--ink-2)">{r.label}</text>)}
          {visits.map((v) => {
            const er = v.flags.some((f) => f.kind === "emergency");
            return <rect key={v.id} x={x(v.date) - 1.5} y={yVisits + 3} width={3} height={14} rx={1} fill={er ? "var(--f-er)" : "var(--ink-2)"} />;
          })}
          {yEps >= 0 && bundle.episodes.map((e) => {
            const day = e.date ?? ix.visit(e.reported_at).date;
            if (!day) return null;
            const r = e.is_worst ? 7 : 4 + Math.min(e.count - 1, 3);
            return <circle key={e.id} cx={x(day)} cy={yEps + 10} r={r} fill="var(--ep)" stroke="var(--ring)" strokeWidth={1.5} opacity={e.date ? 1 : 0.6} />;
          })}
          {bundle.conditions.map((c, i) => {
            const spans: [string, string][] = c.course === "acute" ? c.episodes.filter((e) => e.start).map((e) => [e.start!, e.end ?? e.start!]) : [[c.first_seen ?? scale.start, scale.end]];
            const fill = c.course === "acute" ? "var(--f-acute)" : c.known ? "none" : "var(--ink-2)";
            return spans.map(([a, b], j) => (
              <rect key={`${c.id}-${j}`} x={x(a)} y={yConds[i] + 6} width={Math.max(6, x(b) - x(a))} height={9} rx={2} fill={fill}
                stroke={c.known && c.course !== "acute" ? "var(--muted)" : "none"} strokeWidth={2} />
            ));
          })}
          {shownMeds.map((m, i) => (
            <g key={m.id}>
              {m.periods.map((p, j) => <rect key={j} x={x(p.start)} y={yMeds[i] + 5} width={Math.max(4, x(p.end) - x(p.start))} height={9} rx={2} fill="var(--s1)" />)}
              {heldOn(m.id).map((c) => <text key={c.id} x={x(c.date)} y={yMeds[i] + 14} fontSize="12" fontWeight="700" fill="var(--warn-ink)" textAnchor="middle">{c.kind === "held" ? "‖" : "×"}</text>)}
            </g>
          ))}
        </svg>
        <div className="sheet-legend muted">
          <span><i style={{ background: "var(--ink-2)" }} />Visit</span><span><i style={{ background: "var(--f-er)" }} />Emergency</span>
          {bundle.episodes.length > 0 && <span><i style={{ background: "var(--ep)", borderRadius: 99 }} />Reported episode (larger = worst)</span>}
          <span><i style={{ background: "var(--ink-2)" }} />Condition</span><span><i style={{ border: "2px solid var(--muted)" }} />Past history</span>
          <span><i style={{ background: "var(--f-acute)" }} />Acute episode</span><span><i style={{ background: "var(--s1)" }} />Drug in force</span>
          {anyPause && <span><b style={{ color: "var(--warn-ink)" }}>‖ ×</b> Held, stopped</span>}
          {meds.length > MAX_MEDS && <span>{meds.length - MAX_MEDS} older drugs not drawn</span>}
        </div>

        <div className="sheet-cols">
          <section>
            <h2>Conditions</h2>
            <ul>{bundle.conditions.map((c) => (
              <li key={c.id}><b>{c.name}</b> <span className="muted">· {roleText(c)} · first recorded {fmtDate(c.first_seen)}{c.known ? " as past history" : ""}{c.course === "acute" ? ` · ${c.episodes.length} episode${c.episodes.length === 1 ? "" : "s"}` : ""}</span></li>
            ))}{bundle.conditions.length === 0 && <li className="muted">No diagnosis written on these pages</li>}</ul>

            <h2>Current medication</h2>
            <ul>{current.slice(0, MAX_ROWS).map((m) => {
              const last = m.periods[m.periods.length - 1];
              return <li key={m.id}><b>{m.label}</b> {last?.dose} <span className="muted">· {m.condition_id ? `for ${ix.cond(m.condition_id)!.short} · ` : ""}since {fmtDate(m.start)}</span></li>;
            })}{current.length === 0 && <li className="muted">None in force at the last visit</li>}{more(current.length - MAX_ROWS, "drugs")}</ul>

            {paused.length > 0 && (<>
              <h2>Held or stopped</h2>
              <ul>{paused.map((m) => <li key={m.id}><b>{m.label}</b> <span className="muted">· {m.status} {fmtDate(m.end)}</span></li>)}</ul>
            </>)}
          </section>

          <section>
            {symptoms.length > 0 && (<>
              <h2>Symptoms and episodes</h2>
              <ul>{symptoms.slice(0, MAX_ROWS).map((s) => (
                <li key={s.id}><b>{cap(s.name)}</b> <span className="muted">· {s.episode_count} episode{s.episode_count === 1 ? "" : "s"} · {fmtDate(s.first_seen, "month")}{s.last_seen !== s.first_seen ? ` to ${fmtDate(s.last_seen, "month")}` : ""}</span></li>
              ))}{more(symptoms.length - MAX_ROWS, "symptoms")}</ul>
              {worst.map((e) => <p key={e.id} className="sheet-note">Worst {e.symptom} reported: {fmtDate(e.date)}{e.severity_note ? `, "${e.severity_note}"` : ""}{e.duration ? `, ${e.duration}` : ""}.</p>)}
            </>)}

            <h2>Latest results</h2>
            <ul>{results.slice(0, MAX_ROWS).map((t) => (
              <li key={t.id}><b>{t.name}</b> {t.value}{t.unit ? ` ${t.unit}` : ""}{t.abnormal ? <b style={{ color: "var(--severe-ink)" }}> · abnormal</b> : ""} <span className="muted">· {fmtDate(t.date)}{t.labelled_by_user ? " · label chosen by reviewer" : ""}</span></li>
            ))}{results.length === 0 && <li className="muted">No results on these pages</li>}{more(results.length - MAX_ROWS, "results")}</ul>

            <h2>Recent visits</h2>
            <ul>{recent.slice(0, MAX_VISITS).map((v) => {
              const notable = v.flags.filter((f) => NOTABLE.has(f.kind)).map((f) => f.text);
              const changes = v.flags.filter((f) => f.kind === "medication_change").length;
              const abnormal = v.flags.filter((f) => f.kind === "abnormal_result").length;
              const rest = [changes ? `${changes} medication change${changes === 1 ? "" : "s"}` : "", abnormal ? `${abnormal} abnormal result${abnormal === 1 ? "" : "s"}` : ""].filter(Boolean);
              return <li key={v.id}><b>{fmtDate(v.date)}</b> <span className="muted">· {[v.facility ?? v.encounter_type ?? "Visit", ...notable.map(cap), ...rest].join(" · ")}</span></li>;
            })}{more(recent.length - MAX_VISITS, "visits")}</ul>
          </section>
        </div>

        <footer className="sheet-foot muted">
          Every fact above was checked against the page it was read from.{" "}
          {open ? `${open} item${open === 1 ? "" : "s"} still waiting for review ${open === 1 ? "is" : "are"} left out. ` : "Nothing is waiting for review. "}
          {bundle.pages_left_out.length ? `${bundle.pages_left_out.length} page${bundle.pages_left_out.length === 1 ? " that may be another patient's is" : "s that may be another patient's are"} left out. ` : ""}
          {labelled ? `${labelled} label${labelled === 1 ? " was" : "s were"} chosen by a reviewer, not written on the page. ` : ""}
          Lining up medication and episodes shows timing only, not cause. This summary does not replace the source records.
        </footer>
      </article>
    </div>
  );
}
