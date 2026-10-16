import { useMemo, useState, type CSSProperties } from "react";
import { Index, detailFor, type Choices, type Detail, type Sel } from "../details";
import { CHANGE_MARK, FLAG_TYPES, cap, episodeWhen, fmtDate, makeFilter, makeScale, openReview, pct, roleText, verdict, type FlagType } from "../model";
import type { Bundle, Encounter, Project } from "../types";

type Lens = "tree" | "symptoms" | "episodes" | "meds" | "tests" | "corr";
const LENSES: [Lens, string][] = [["tree", "Visit tree"], ["symptoms", "Symptoms"], ["episodes", "Episodes"], ["meds", "Medications"], ["tests", "Labs and scans"], ["corr", "Correlation"]];
const SORTS: Record<Lens, [string, string][]> = {
  tree: [["asc", "Oldest first"], ["desc", "Newest first"]],
  symptoms: [["episodes", "Most episodes"], ["visits", "Most visits"], ["recent", "Most recent"], ["name", "Name"]],
  episodes: [["asc", "By date"], ["worst", "Worst first"], ["count", "Largest reports"]],
  meds: [["asc", "Oldest first"], ["cond", "By condition"], ["name", "Name"]],
  tests: [["asc", "Oldest first"], ["desc", "Newest first"], ["abn", "Abnormal first"]],
  corr: [],
};

const swatch = (f: FlagType | undefined, w: number, h: number): CSSProperties => ({
  display: "block", flex: "0 0 auto", width: w, height: h, borderRadius: 2, boxSizing: "border-box",
  ...(f && "hollow" in f ? { background: "transparent", border: `2px solid ${f.color}` } : { background: f?.color }),
});

/** Save a review choice: a label, null to leave it unsure, or undefined to undo. */
export type Resolve = (key: string, choice: string | null | undefined) => Promise<void>;

export function Explorer({ bundle, title, onBack, dark, onTheme, onResolve, onSummary, update, onAddPages }: {
  bundle: Bundle; title: string; onBack: () => void; dark: boolean; onTheme: () => void; onResolve: Resolve; onSummary: () => void;
  update?: Project["last_update"];
  /** Absent for the demo patient, which has no folder to add to. */
  onAddPages?: () => Promise<void>;
}) {
  const [seenUpdate, setSeenUpdate] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  const addPages = async () => {
    setAdding(true); setAddError(null);
    try { await onAddPages!(); } catch (e) { setAddError(String((e as Error).message ?? e)); } finally { setAdding(false); }
  };
  const ix = useMemo(() => new Index(bundle), [bundle]);
  const scale = useMemo(() => makeScale(bundle), [bundle]);
  const firstSel: Sel = bundle.episodes.find((e) => e.is_worst) ? { kind: "episode", id: bundle.episodes.find((e) => e.is_worst)!.id }
    : bundle.encounters.length ? { kind: "visit", id: bundle.encounters[bundle.encounters.length - 1].id } : { kind: "review", id: "all" };
  const [lens, setLens] = useState<Lens>("tree");
  const [sort, setSort] = useState("asc");
  const [sel, setSel] = useState<Sel>(firstSel);
  const [cond, setCond] = useState<string | null>(null);
  const [flag, setFlag] = useState<string | null>(null);
  const f = makeFilter(cond);
  const pick = (s: Sel) => () => setSel(s);
  const isSel = (k: Sel["kind"], id: string) => sel.kind === k && sel.id === id;
  const detail: Detail = useMemo(() => detailFor(ix, sel, cond), [ix, sel, cond]);

  const blocking = openReview(bundle.review_items).length;
  const name = bundle.patient.name ?? title;
  const epCount = bundle.episodes.reduce((a, e) => a + e.count, 0);
  const summary = [
    bundle.conditions.map((c) => c.short).join(", "),
    `${bundle.encounters.length} visit${bundle.encounters.length === 1 ? "" : "s"}`,
    epCount ? `${epCount} reported episode${epCount === 1 ? "" : "s"}` : null,
    bundle.span.start ? `${fmtDate(bundle.span.start, "month")} to ${fmtDate(bundle.span.end, "month")}` : null,
  ].filter(Boolean).join(" · ");

  const visitFlagTypes = (v: Encounter) => FLAG_TYPES.filter((t) => v.flags.some((x) => x.kind === t.kind));
  const months = scale.ticks;

  return (
    <div className="page">
      <header style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", justifyContent: "space-between", gap: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <button className="linkrow" style={{ fontSize: 14 }} onClick={onBack}>← All patients</button>
          <h1 style={{ margin: 0, fontSize: 30, fontWeight: 700, letterSpacing: "-0.01em" }}>{name}</h1>
          <div className="muted" style={{ fontSize: 15 }}>{summary}</div>
          {bundle.pages_left_out.length > 0 && (
            <div className="muted" style={{ fontSize: 14 }}>
              {bundle.pages_left_out.length} page{bundle.pages_left_out.length === 1 ? " is" : "s are"} left out because {bundle.pages_left_out.length === 1 ? "it" : "they"} may be another patient's.
            </div>
          )}
          {update && seenUpdate !== update.at && (
            <div className="notice" role="status">
              <strong>What changed with the pages you added</strong>
              <ul>{update.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
              <div><button className="btn" onClick={() => setSeenUpdate(update.at)}>Got it</button></div>
            </div>
          )}
          {addError && <div className="error">{addError}</div>}
          {blocking > 0 && (
            <div><button className={`review${sel.kind === "review" ? " on" : ""}`} onClick={pick({ kind: "review", id: "all" })}>
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4M12 17.5v.5" /></svg>
              {blocking} item{blocking === 1 ? "" : "s"} to review
            </button></div>
          )}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <nav aria-label="History views" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {LENSES.map(([id, label]) => (
              <button key={id} className={`tab${lens === id ? " on" : ""}`} onClick={() => { setLens(id); setSort(SORTS[id][0]?.[0] ?? "asc"); if (id === "corr" && sel.kind !== "change") { const first = bundle.changes.find((c) => f.med(ix.med(c.med_id)!)); if (first) setSel({ kind: "change", id: first.id }); } }}>{label}</button>
            ))}
          </nav>
          {onAddPages && <button className="btn" disabled={adding} onClick={addPages}>{adding ? "Reading pages…" : "Add pages"}</button>}
          <button className="btn" onClick={onSummary}>One-page summary</button>
          <button className="theme" aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} aria-pressed={dark} onClick={onTheme}>
            {dark ? <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
              : <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" /></svg>}
            <span style={{ fontSize: 14, fontWeight: 500 }}>{dark ? "Light" : "Dark"}</span>
          </button>
        </div>
      </header>

      <nav aria-label="Filter by condition" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
        <span className="eyebrow" style={{ marginRight: 4 }}>Conditions</span>
        {[null, ...bundle.conditions.map((c) => c.id)].map((id) => {
          const c = id ? ix.cond(id)! : null;
          const sub = c ? (c.course === "acute" ? `acute · ${c.episodes.length} episode${c.episodes.length === 1 ? "" : "s"}` : c.known ? "past history" : c.course === "unclassified" ? "seen once" : "long-term") : "";
          return (
            <button key={id ?? "all"} className={`condbtn${cond === id ? " on" : ""}`} aria-pressed={cond === id}
              onClick={() => { setCond(id); if (id) setSel({ kind: "condition", id }); }}>
              <span style={{ fontSize: 14, fontWeight: 600 }}>{c ? c.short : "All conditions"}</span>
              {sub && <span className="muted" style={{ fontSize: 12 }}>{sub}</span>}
            </button>
          );
        })}
      </nav>

      {lens !== "corr" && (
        <section aria-label="Episode and condition timeline" className="panel" style={{ padding: "16px 20px 12px", display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 8, fontSize: 14 }} className="muted">
            <span style={{ fontWeight: 600, color: "var(--ink)" }}>Episodes and conditions over time</span>
            <span style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: "50%", background: "var(--ep)" }} />Episode (bigger = more in one report)</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 2, height: 14, background: "var(--ink)" }} />Visit</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 16, height: 8, borderRadius: 2, background: "var(--ink-2)" }} />Long-term condition</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 16, height: 8, borderRadius: 2, border: "2px solid var(--muted)" }} />Past history</span>
              <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 8, height: 8, borderRadius: 2, background: "var(--f-acute)" }} />Acute episode</span>
            </span>
          </div>
          <div role="group" aria-label="Highlight visits with" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
            <span className="muted" style={{ fontSize: 13 }}>Visit markers, click to highlight:</span>
            {FLAG_TYPES.map((t) => (
              <button key={t.kind} className={`flagbtn${flag === t.kind ? " on" : ""}`} aria-pressed={flag === t.kind} onClick={() => setFlag(flag === t.kind ? null : t.kind)}>
                <span style={swatch(t, 10, 10)} />{t.label}
              </button>
            ))}
          </div>
          <div style={{ overflowX: "auto" }}>
            <div style={{ minWidth: 720, position: "relative" }}>
              <div style={{ position: "relative", height: 64 }}>
                <div style={{ position: "absolute", left: 0, right: 0, top: "50%", height: 2, background: "var(--line)" }} />
                {bundle.encounters.filter((v) => v.date).map((v) => (
                  <button key={v.id} className={`tick${isSel("visit", v.id) ? " sel" : ""}${f.visit(v) ? "" : " dim"}`} aria-label={`Visit ${fmtDate(v.date)}`} title={`Visit ${fmtDate(v.date)}`} onClick={pick({ kind: "visit", id: v.id })} style={{ left: pct(scale.x(v.date)) }} />
                ))}
                {bundle.episodes.map((e) => {
                  const day = e.date ?? ix.visit(e.reported_at).date;
                  if (!day) return null;
                  const size = e.is_worst ? 22 : 10 + Math.min(e.count - 1, 4) * 3;
                  const label = `${cap(e.symptom)}, ${episodeWhen(e)}${e.count > 1 ? `, ${e.count} episodes` : ""}${e.is_worst ? ", worst reported" : ""}${e.date ? "" : " (undated, shown at the visit)"}`;
                  return <button key={e.id} className={`dot${isSel("episode", e.id) ? " sel" : ""}${f.episode(e) ? "" : " dim"}`} aria-label={label} title={label} onClick={pick({ kind: "episode", id: e.id })} style={{ top: "50%", left: pct(scale.x(day)), width: size, height: size, opacity: e.date ? undefined : 0.6 }} />;
                })}
              </div>
              <div style={{ position: "relative", height: 64, borderTop: "1px dashed var(--line-soft)" }}>
                {bundle.encounters.filter((v) => v.date).map((v) => {
                  const types = visitFlagTypes(v);
                  const dimmed = (flag && !types.some((t) => t.kind === flag)) || !f.visit(v);
                  const aria = `Visit ${fmtDate(v.date)}: ${types.map((t) => t.label.toLowerCase()).join(", ") || "nothing new"}`;
                  return (
                    <button key={v.id} className={`vflag${dimmed ? " dim" : ""}`} style={{ left: pct(scale.x(v.date)), top: 6 }} aria-label={aria} title={aria} onClick={pick({ kind: "visit", id: v.id })}>
                      {types.map((t) => <span key={t.kind} style={{ ...swatch(t, 12, 8), outline: flag === t.kind ? "2px solid var(--ink)" : "none", outlineOffset: 1 }} />)}
                    </button>
                  );
                })}
              </div>
              <div style={{ borderTop: "1px dashed var(--line-soft)", padding: "6px 0" }}>
                {bundle.conditions.filter((c) => !cond || c.id === cond).map((c) => {
                  const spans: [string, string][] = c.course === "acute" ? c.episodes.filter((e) => e.start).map((e) => [e.start!, e.end ?? e.start!])
                    : [[c.first_seen ?? scale.start, scale.end]];
                  const fill = c.course === "acute" ? "var(--f-acute)" : c.known ? "transparent" : "var(--ink-2)";
                  const left0 = scale.x(spans[0]?.[0]);
                  return (
                    <button key={c.id} className="lane" aria-label={`${c.name}: ${roleText(c)}`} title={`${c.name}: ${roleText(c)}`} onClick={pick({ kind: "condition", id: c.id })}>
                      <span style={{ position: "absolute", top: 0, ...(left0 > 0.8 ? { right: 0 } : { left: pct(left0) }), fontSize: 12, fontWeight: 600, color: "var(--ink-2)", whiteSpace: "nowrap" }}>
                        {c.short}{c.course === "acute" ? ` · ${c.episodes.length} episode${c.episodes.length === 1 ? "" : "s"}` : c.known ? " · past history" : ""}
                      </span>
                      {spans.map(([a, b], i) => (
                        <span key={i} style={{ position: "absolute", top: 18, height: 10, left: pct(scale.x(a)), width: `max(8px, ${pct(scale.x(b) - scale.x(a))})`, borderRadius: 3, background: fill, border: c.known && c.course !== "acute" ? "2px solid var(--muted)" : undefined, boxSizing: "border-box", outline: isSel("condition", c.id) ? "2px solid var(--accent)" : "none", outlineOffset: 2 }} />
                      ))}
                    </button>
                  );
                })}
              </div>
              <div style={{ position: "relative", height: 18 }} className="mono muted">
                {months.map((t) => <span key={t.label + t.at} style={{ position: "absolute", left: pct(t.at), fontSize: 12, borderLeft: "1px solid var(--line-soft)", paddingLeft: 4 }}>{t.label}</span>)}
              </div>
            </div>
          </div>
        </section>
      )}

      {lens === "corr" && <Correlation bundle={bundle} ix={ix} scale={scale} cond={cond} sel={sel} setSel={setSel} />}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 20, alignItems: "flex-start" }}>
        {lens !== "corr" && (
          <ListPanel bundle={bundle} ix={ix} lens={lens} sort={sort} setSort={setSort} cond={cond} flag={flag} isSel={isSel} pick={pick} />
        )}
        <DetailPanel detail={detail} setSel={setSel} onResolve={onResolve} />
      </div>
    </div>
  );
}

function ListPanel({ bundle, ix, lens, sort, setSort, cond, flag, isSel, pick }: {
  bundle: Bundle; ix: Index; lens: Lens; sort: string; setSort: (s: string) => void; cond: string | null; flag: string | null;
  isSel: (k: Sel["kind"], id: string) => boolean; pick: (s: Sel) => () => void;
}) {
  const f = makeFilter(cond);
  const desc = sort === "desc";
  const title = { tree: "Visits and what each recorded", symptoms: "Symptoms", episodes: "Reported episodes", meds: "Medications", tests: "Labs and scans", corr: "" }[lens];
  const row = (key: string, kind: Sel["kind"], id: string, main: string, sub: string, meta = "", mark?: CSSProperties) => (
    <button key={key} className={`node${isSel(kind, id) ? " sel" : ""}`} onClick={pick({ kind, id })}>
      {mark && <span style={mark} />}
      <span style={{ display: "flex", flexDirection: "column", gap: 2, flex: "1 1 auto", minWidth: 0 }}>
        <span style={{ fontSize: 15, fontWeight: 600 }}>{main}</span>
        <span className="muted" style={{ fontSize: 13 }}>{sub}</span>
      </span>
      {meta && <span className="mono muted" style={{ fontSize: 13 }}>{meta}</span>}
    </button>
  );
  const epMark = (worst: boolean): CSSProperties => ({ flex: "0 0 auto", width: worst ? 14 : 10, height: worst ? 14 : 10, borderRadius: "50%", background: "var(--ep)" });

  let body: JSX.Element;
  if (lens === "tree") {
    const visits = (desc ? [...bundle.encounters].reverse() : bundle.encounters).filter(f.visit);
    const years = new Map<string, Encounter[]>();
    visits.forEach((v) => { const y = v.date?.slice(0, 4) ?? "Undated"; years.set(y, [...(years.get(y) ?? []), v]); });
    body = (
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {[...years].map(([year, vs]) => (
          <div key={year} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div className="mono muted" style={{ fontSize: 13, fontWeight: 500, padding: "0 12px" }}>{year}</div>
            {vs.map((v) => {
              const eps = bundle.episodes.filter((e) => e.reported_at === v.id && f.episode(e));
              const flags = v.flags.filter((x) => !flag || x.kind === flag);
              return (
                <div key={v.id} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <button className={`node${isSel("visit", v.id) ? " sel" : ""}${flag && !v.flags.some((x) => x.kind === flag) ? " dim" : ""}`} onClick={pick({ kind: "visit", id: v.id })}>
                    <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ flex: "0 0 auto" }}><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M9 8h6M12 5v6M8 15h8M8 18h5" /></svg>
                    <span style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      <span style={{ fontWeight: 600 }}>{fmtDate(v.date)}</span>
                      <span className="muted" style={{ fontSize: 13 }}>{[v.facility, v.condition_ids.map((c) => ix.cond(c)!.short).join(", "), v.added_later ? "added later" : ""].filter(Boolean).join(" · ")}</span>
                      <span style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                        {flags.map((x, i) => { const t = FLAG_TYPES.find((ft) => ft.kind === x.kind); return <span key={i} className="flagchip"><span style={swatch(t, 9, 9)} />{cap(x.text)}</span>; })}
                      </span>
                    </span>
                  </button>
                  {eps.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 2, marginLeft: 20, paddingLeft: 12, borderLeft: "2px solid var(--line-soft)" }}>
                      {eps.map((e) => row(e.id, "episode", e.id, episodeWhen(e), `${cap(e.symptom)}${e.count > 1 ? ` ×${e.count}` : ""}${e.is_worst ? " · worst reported" : ""}`, "", epMark(e.is_worst)))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    );
  } else if (lens === "symptoms") {
    const order: Record<string, (a: any, b: any) => number> = {
      episodes: (a, b) => b.episode_count - a.episode_count || b.encounter_ids.length - a.encounter_ids.length,
      visits: (a, b) => b.encounter_ids.length - a.encounter_ids.length,
      recent: (a, b) => (b.last_seen ?? "").localeCompare(a.last_seen ?? ""),
      name: (a, b) => a.name.localeCompare(b.name),
    };
    const list = bundle.symptoms.filter(f.symptom).sort(order[sort] ?? order.episodes);
    body = <div>{list.map((s) => row(s.id, "symptom", s.id, cap(s.name),
      `${fmtDate(s.first_seen)} to ${fmtDate(s.last_seen)} · ${s.condition_ids.map((c) => ix.cond(c)!.short).join(", ") || "not tied to a condition"}`,
      `${s.episode_count}×`))}</div>;
  } else if (lens === "episodes") {
    const list = bundle.episodes.filter(f.episode);
    const sorted = sort === "worst" ? [...list].sort((a, b) => Number(b.is_worst) - Number(a.is_worst)) : sort === "count" ? [...list].sort((a, b) => b.count - a.count) : list;
    body = <div>{sorted.map((e) => row(e.id, "episode", e.id, episodeWhen(e), `${cap(e.symptom)}${e.description ? ` · ${e.description}` : ""}${e.is_worst ? " · worst reported" : ""}`, e.count > 1 ? `×${e.count}` : "", epMark(e.is_worst)))}</div>;
  } else if (lens === "meds") {
    const list = bundle.medications.filter(f.med);
    const condOrder = (id: string | null) => (id ? bundle.conditions.findIndex((c) => c.id === id) : 99);
    const sorted = sort === "name" ? [...list].sort((a, b) => a.label.localeCompare(b.label)) : sort === "cond" ? [...list].sort((a, b) => condOrder(a.condition_id) - condOrder(b.condition_id)) : list;
    body = <div>{sorted.map((m) => row(m.id, "med", m.id, m.label, `${m.condition_id ? `For ${ix.cond(m.condition_id)!.short}` : "Not tied to a condition"} · ${m.periods.map((p) => p.dose).filter((d, i, a) => a.indexOf(d) === i).join(" → ")}`, m.current ? "Current" : "Past"))}</div>;
  } else {
    const list = bundle.tests.filter(f.test);
    const sorted = sort === "abn" ? [...list].sort((a, b) => Number(!!b.abnormal) - Number(!!a.abnormal)) : desc ? [...list].reverse() : list;
    body = <div>{sorted.map((t) => row(t.id, "test", t.id, t.name, `${fmtDate(t.date)} · ${t.value ?? (t.status === "ordered" ? "ordered" : "no result")}${t.unit ? ` ${t.unit}` : ""}`, t.abnormal ? "Abnormal" : t.abnormal === false ? "Normal" : "",
      { flex: "0 0 auto", width: 10, height: 10, borderRadius: 2, background: t.abnormal ? "var(--severe-ink)" : "var(--muted)" }))}</div>;
  }

  const empty = (lens === "tree" ? bundle.encounters.filter(f.visit) : lens === "symptoms" ? bundle.symptoms.filter(f.symptom) : lens === "episodes" ? bundle.episodes.filter(f.episode) : lens === "meds" ? bundle.medications.filter(f.med) : bundle.tests.filter(f.test)).length === 0;
  return (
    <section aria-label={title} className="panel" style={{ flex: "1 1 360px", maxWidth: 480, minWidth: 0, padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>{title}</h2>
        <div role="group" aria-label="Sort" className="segs">
          {SORTS[lens].map(([id, label]) => <button key={id} className={`seg${sort === id ? " on" : ""}`} onClick={() => setSort(id)}>{label}</button>)}
        </div>
      </div>
      {empty ? <div className="muted">Nothing here for this condition.</div> : body}
    </section>
  );
}

function Correlation({ bundle, ix, scale, cond, sel, setSel }: { bundle: Bundle; ix: Index; scale: ReturnType<typeof makeScale>; cond: string | null; sel: Sel; setSel: (s: Sel) => void }) {
  const f = makeFilter(cond);
  const rows = bundle.correlation[cond ?? "all"] ?? [];
  const changeId = (d: string, drug: string) => bundle.changes.find((c) => c.date === d && c.drug === drug)?.id;
  const eps = bundle.episodes.filter(f.episode);
  const counts = scale.monthBuckets.map((m) => eps.filter((e) => { const d = e.date ?? ix.visit(e.reported_at).date; return d && d >= m.from && d < m.to; }).reduce((a, e) => a + e.count, 0));
  const max = Math.max(1, ...counts);
  const condOrder = (id: string | null) => (id ? bundle.conditions.findIndex((c) => c.id === id) : 99);
  const meds = bundle.medications.filter(f.med).sort((a, b) => condOrder(a.condition_id) - condOrder(b.condition_id));
  const symptoms = bundle.symptoms.filter((s) => f.symptom(s) && s.episode_ids.length === 0);
  const cols = `repeat(${scale.monthBuckets.length}, minmax(0, 1fr))`;
  const guides = rows.map((r) => <span key={r.date + r.drug} style={{ position: "absolute", top: 0, bottom: 0, left: pct(scale.x(r.date)), borderLeft: "2px dashed var(--muted)", opacity: sel.kind === "change" && sel.id === changeId(r.date, r.drug) ? 1 : 0.5, pointerEvents: "none" }} />);
  const label = (main: string, sub: string, onClick?: () => void) => (
    <div style={{ flex: "0 0 180px", padding: "10px 12px 10px 0", display: "flex", flexDirection: "column", justifyContent: "center", gap: 2 }}>
      {onClick ? <button className="linkrow" style={{ fontWeight: 600, fontSize: 14 }} onClick={onClick}>{main}</button> : <span style={{ fontSize: 14, fontWeight: 600 }}>{main}</span>}
      <span className="muted" style={{ fontSize: 12 }}>{sub}</span>
    </div>
  );
  const chips = new Map<string, Correlated[]>();
  rows.forEach((r) => chips.set(r.date, [...(chips.get(r.date) ?? []), r]));

  return (
    <section aria-label="Correlation" className="panel" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", gap: 12, alignItems: "flex-end" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>Medication changes against episodes and symptoms</h2>
          <div className="muted" style={{ fontSize: 14 }}>Dashed lines mark each first record or dose change. Click a change, a bar or a row for detail.</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink-2)" }}>
            {cond ? `Showing ${ix.cond(cond)!.name} only.` : bundle.conditions.length > 1 ? "Showing every condition. Pick one above to compare only its drugs with its episodes." : ""}
          </div>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 16, fontSize: 13 }} className="muted">
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 14, height: 10, borderRadius: 2, background: "var(--s1)" }} />Medication in force</span>
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 10, height: 10, borderRadius: "50%", background: "var(--ep)" }} />Episodes</span>
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}><span style={{ width: 8, height: 14, borderRadius: 2, background: "var(--heat)" }} />Symptom recorded at a visit</span>
        </div>
      </div>
      <div style={{ overflowX: "auto" }}>
        <div style={{ minWidth: 900, display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex" }}>
            <div style={{ flex: "0 0 180px" }} />
            <div style={{ position: "relative", flex: "1 1 auto", height: 36 }}>
              {[...chips].map(([d, rs]) => {
                const id = changeId(d, rs[0].drug)!;
                const text = rs.map((r) => `${ix.medLabel(rs.length > 2 ? r.drug : r.drug).slice(0, rs.length > 1 ? 4 : 12)} ${CHANGE_MARK[r.kind] ?? "•"}`).join(" ");
                return <button key={d} className={`chip${sel.kind === "change" && rs.some((r) => sel.id === changeId(d, r.drug)) ? " sel" : ""}`} style={scale.x(d) > 0.9 ? { left: "auto", right: 0, transform: "none" } : scale.x(d) < 0.06 ? { left: 0, transform: "none" } : { left: pct(scale.x(d)) }} title={rs.map((r) => `${ix.medLabel(r.drug)} ${r.kind}${r.dose ? `, ${r.dose}` : ""}`).join("; ")} onClick={() => setSel({ kind: "change", id })}>{text}</button>;
              })}
            </div>
          </div>
          {meds.map((m) => (
            <div key={m.id} style={{ display: "flex", borderTop: "1px solid var(--line-soft)" }}>
              {label(m.label, m.condition_id ? `For ${ix.cond(m.condition_id)!.short}` : "Not tied to a condition", () => setSel({ kind: "med", id: m.id }))}
              <div style={{ position: "relative", flex: "1 1 auto", height: 44 }}>
                {guides}
                {m.periods.map((p, i) => {
                  const doses = Array.from(new Set(m.periods.map((x) => x.dose)));
                  return <button key={i} className="seg-bar" title={`${m.label} ${p.dose} from ${fmtDate(p.start)}`} onClick={() => setSel({ kind: "med", id: m.id })}
                    style={{ left: `calc(${pct(scale.x(p.start))} + 1px)`, width: `max(6px, calc(${pct(scale.x(p.end) - scale.x(p.start))} - 2px))`, opacity: 0.55 + 0.45 * ((doses.indexOf(p.dose) + 1) / doses.length), outline: sel.kind === "med" && sel.id === m.id ? "2px solid var(--ink)" : "none" }}>{p.dose}</button>;
                })}
              </div>
            </div>
          ))}
          <div style={{ display: "flex", borderTop: "1px solid var(--line-soft)" }}>
            {label("Episodes per month", "Count, all reported")}
            <div style={{ position: "relative", flex: "1 1 auto", height: 70 }}>
              {guides}
              <div style={{ position: "absolute", inset: 0, display: "grid", gridTemplateColumns: cols, alignItems: "end", paddingBottom: 2 }}>
                {counts.map((n, i) => (
                  <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", height: "100%", gap: 2 }}>
                    <span className="mono muted" style={{ fontSize: 11 }}>{n || ""}</span>
                    <span title={`${scale.monthBuckets[i].label}: ${n} episode${n === 1 ? "" : "s"}`} style={{ display: "block", width: "56%", height: n ? Math.max(6, (n / max) * 44) : 0, background: "var(--ep)", borderRadius: "4px 4px 0 0" }} />
                  </div>
                ))}
              </div>
              {eps.filter((e) => e.is_worst && e.date).map((e) => <button key={e.id} className={`dot${sel.kind === "episode" && sel.id === e.id ? " sel" : ""}`} aria-label={`Worst reported, ${episodeWhen(e)}`} title={`Worst reported, ${episodeWhen(e)}`} onClick={() => setSel({ kind: "episode", id: e.id })} style={{ left: pct(scale.x(e.date)), top: 10, width: 16, height: 16 }} />)}
            </div>
          </div>
          {symptoms.map((s) => (
            <div key={s.id} style={{ display: "flex", borderTop: "1px solid var(--line-soft)" }}>
              {label(cap(s.name), "Recorded at visits", () => setSel({ kind: "symptom", id: s.id }))}
              <div style={{ position: "relative", flex: "1 1 auto", height: 36 }}>
                {guides}
                {s.occurrences.filter((o) => o.date).map((o) => (
                  <button key={o.encounter_id} title={`${cap(s.name)}, ${fmtDate(o.date)}`} aria-label={`${cap(s.name)}, ${fmtDate(o.date)}`} onClick={() => setSel({ kind: "visit", id: o.encounter_id })}
                    style={{ position: "absolute", top: 8, bottom: 8, width: 10, transform: "translateX(-50%)", left: pct(scale.x(o.date)), border: "none", borderRadius: 2, background: "var(--heat)", opacity: 0.75, padding: 0 }} />
                ))}
              </div>
            </div>
          ))}
          <div style={{ display: "flex", borderTop: "1px solid var(--line)" }}>
            <div style={{ flex: "0 0 180px" }} />
            <div style={{ position: "relative", flex: "1 1 auto", height: 22 }} className="mono muted">
              {scale.ticks.map((t) => <span key={t.label + t.at} style={{ position: "absolute", left: pct(t.at), fontSize: 12, paddingLeft: 4, paddingTop: 6 }}>{t.label}</span>)}
            </div>
          </div>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>Before and after each change</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
          {rows.map((r) => {
            const id = changeId(r.date, r.drug)!;
            const v = verdict(r);
            return (
              <button key={id} className={`card${sel.kind === "change" && sel.id === id ? " sel" : ""}`} onClick={() => setSel({ kind: "change", id })}>
                <span className="mono muted" style={{ fontSize: 12 }}>{fmtDate(r.date)}</span>
                <span style={{ fontSize: 15, fontWeight: 600 }}>{ix.medLabel(r.drug)} {r.kind}{r.kind === "dose change" ? `: ${r.previous_dose} to ${r.dose}` : r.dose ? `, ${r.dose}` : ""}</span>
                <span style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "4px 12px", fontSize: 14 }}>
                  <span className="muted">Episodes / month</span>
                  <span className="mono">{r.before ? r.before.per_month.toFixed(1) : "–"} → {r.after ? r.after.per_month.toFixed(1) : "?"}</span>
                </span>
                <span style={{ fontSize: 14, fontWeight: 600, color: v.tone === "info" ? "var(--accent-ink)" : v.tone === "warn" ? "var(--warn-ink)" : "var(--ink-2)" }}>{v.text}</span>
              </button>
            );
          })}
        </div>
        {rows.length === 0 && <div className="muted">No medication changes for this condition.</div>}
        <div className="muted" style={{ fontSize: 13 }}>Windows run from one change to the next. This shows timing only; it does not show that a change caused what followed.</div>
      </div>
    </section>
  );
}

function ChoiceButtons({ c, onResolve }: { c: Choices; onResolve: Resolve }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = (choice: string | null | undefined) => async () => {
    setBusy(true); setErr(null);
    try { await onResolve(c.key, choice); } catch (e) { setErr(String((e as Error).message ?? e)); } finally { setBusy(false); }
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div role="group" aria-label="Label choices" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {c.resolved ? <button className="btn" disabled={busy} onClick={run(undefined)}>Undo</button> : (<>
          {c.yesNo ? (<>
            <button className="btn" disabled={busy} onClick={run("yes")}>Yes, same patient</button>
            <button className="btn" disabled={busy} onClick={run("no")}>No, someone else</button>
          </>) : (<>
            {c.options.map((o) => <button key={o} className="btn" disabled={busy} onClick={run(o)}>{o}</button>)}
            <button className="btn quiet" disabled={busy} onClick={run(null)}>Leave unsure</button>
          </>)}
        </>)}
      </div>
      {err && <div className="error">{err}</div>}
    </div>
  );
}

function DetailPanel({ detail, setSel, onResolve }: { detail: Detail; setSel: (s: Sel) => void; onResolve: Resolve }) {
  const color = (tone?: string) => (tone === "severe" ? "var(--severe-ink)" : tone === "warn" ? "var(--warn-ink)" : "var(--ink)");
  return (
    <section aria-label="Details" className="panel" style={{ flex: "999 1 560px", minWidth: 0, padding: 24, display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div className="eyebrow">{detail.kind}</div>
        <h2 style={{ margin: 0, fontSize: 26, fontWeight: 700, letterSpacing: "-0.01em" }}>{detail.title}</h2>
        {detail.sub && <div style={{ fontSize: 15, color: "var(--ink-2)" }}>{detail.sub}</div>}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {detail.badges.map((b, i) => <span key={i} className={`badge ${b.tone}`}>{b.text}</span>)}
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
        {detail.sections.map((sec, i) => (
          <div key={i} style={{ border: "1px solid var(--line-soft)", borderRadius: 10, padding: 16, display: "flex", flexDirection: "column", gap: 10 }}>
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--ink-2)" }}>{sec.heading}</h3>
            {sec.rows.map((r, j) => (
              <div key={j} style={{ display: "flex", flexDirection: "column", gap: 2, ...(r.flagColor ? { borderLeft: `4px ${r.hollow ? "double" : "solid"} ${r.flagColor}`, paddingLeft: 8 } : {}) }}>
                {r.label && <span className="muted" style={{ fontSize: 13 }}>{r.label}</span>}
                {r.link ? <button className="linkrow" onClick={() => setSel(r.link!)}>{r.value}</button>
                  : r.value ? <span style={{ fontSize: 15, lineHeight: 1.45, color: color(r.tone) }}>{r.value}</span> : null}
                {r.choices && <ChoiceButtons c={r.choices} onResolve={onResolve} />}
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="muted" style={{ fontSize: 13, borderTop: "1px solid var(--line-soft)", paddingTop: 12 }}>
        Every item passed rule-based checks against the page it was read from: its quote is on the page, and its names, numbers, counts and dates match what is written. Items that failed are held out under "needs review".
      </div>
    </section>
  );
}

type Correlated = Bundle["correlation"][string][number];
