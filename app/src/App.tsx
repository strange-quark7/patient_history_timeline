import { useEffect, useState } from "react";
import { Explorer } from "./components/Explorer";
import { Summary } from "./components/Summary";
import { call, isDesktop, onEngineEvent, pickFolder } from "./engine";
import type { Opened, Project } from "./types";

type Info = { extractors: string[]; has_api_key: boolean };
type Progress = { done: number; total: number; file: string | null; page: number | null };

function useTheme(): [boolean, () => void] {
  const initial = (() => {
    try {
      const saved = localStorage.getItem("theme");
      if (saved) return saved === "dark";
    } catch { /* storage unavailable */ }
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  })();
  const [dark, setDark] = useState(initial);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* ignore */ }
  }, [dark]);
  return [dark, () => setDark((d) => !d)];
}

export default function App() {
  const [dark, toggleTheme] = useTheme();
  const [opened, setOpened] = useState<Opened | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState(false);

  const open = async (method: string, params: Record<string, unknown> = {}) => {
    setBusy(true);
    setError(null);
    try {
      setOpened(await call<Opened>(method, params));
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  if (opened) {
    const resolve = async (key: string, choice: string | null | undefined) => {
      const params = choice === undefined ? { project_id: opened.project.id, key, clear: true } : { project_id: opened.project.id, key, choice };
      setOpened(await call<Opened>("review.resolve", params));
    };
    // The explorer stays mounted under the summary so its selection and view survive the round trip.
    return (<>
      {summary && <Summary bundle={opened.bundle} title={opened.project.name} onBack={() => setSummary(false)} />}
      <div hidden={summary}>
        <Explorer key={opened.project.id} bundle={opened.bundle} title={opened.project.name} onBack={() => { setSummary(false); setOpened(null); }}
          dark={dark} onTheme={toggleTheme} onResolve={resolve} onSummary={() => setSummary(true)} />
      </div>
    </>);
  }
  return <Home open={open} busy={busy} error={error} setError={setError} />;
}

function Home({ open, busy, error, setError }: { open: (m: string, p?: Record<string, unknown>) => Promise<void>; busy: boolean; error: string | null; setError: (e: string | null) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [info, setInfo] = useState<Info | null>(null);
  const [name, setName] = useState("");
  const [folder, setFolder] = useState("");
  const [extractor, setExtractor] = useState("claude");
  const [apiKey, setApiKey] = useState("");
  const [progress, setProgress] = useState<Progress | null>(null);

  useEffect(() => {
    call<Info>("info").then(setInfo).catch((e) => setError(`Could not start the engine: ${e instanceof Error ? e.message : e}`));
    call<Project[]>("projects.list").then(setProjects).catch(() => {});
    let stop: (() => void) | undefined;
    onEngineEvent((e) => { if (e.event === "progress") setProgress(e.data); }).then((s) => (stop = s));
    return () => stop?.();
  }, [setError]);

  const build = async () => {
    setProgress(null);
    await open("projects.create", { name: name.trim(), folder: folder.trim(), extractor, ...(apiKey ? { api_key: apiKey } : {}) });
  };
  const needsKey = extractor === "claude" && info && !info.has_api_key;

  return (
    <div className="page" style={{ maxWidth: 960 }}>
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div className="eyebrow">Patient History Timeline</div>
        <h1 style={{ margin: 0, fontSize: 30, fontWeight: 700 }}>Patients</h1>
        <div className="muted">Turn prescriptions and case sheets into a history you can explore. Every item is checked against the page it came from.</div>
      </header>
      {error && <div className="error" role="alert">{error}</div>}

      <section className="panel" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>Open a patient</h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <button className="node" disabled={busy} onClick={() => open("demo")}>
            <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{ fontWeight: 600 }}>Demo patient</span>
              <span className="muted" style={{ fontSize: 13 }}>Made-up data: diabetes, hypertension, epilepsy and three UTIs</span>
            </span>
          </button>
          {projects.map((p) => (
            <button key={p.id} className="node" disabled={busy} onClick={() => open("projects.open", { project_id: p.id })}>
              <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ fontWeight: 600 }}>{p.name}</span>
                <span className="muted" style={{ fontSize: 13 }}>{p.pages ?? 0} pages · {p.source_folder}</span>
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>New patient from a folder of documents</h2>
        <div className="muted" style={{ fontSize: 14 }}>PDF, Word (DOC, DOCX), JPEG and PNG. Each page is read once and saved, so rebuilding never pays twice.</div>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>Patient name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name or record number" />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>Folder</span>
          <span style={{ display: "flex", gap: 8 }}>
            <input style={{ flex: 1 }} value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="/path/to/patient/documents" />
            {isDesktop && <button className="btn" type="button" onClick={async () => { const f = await pickFolder(); if (f) setFolder(f); }}>Choose…</button>}
          </span>
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 14, fontWeight: 600 }}>Reader</span>
          <select value={extractor} onChange={(e) => setExtractor(e.target.value)}>
            {(info?.extractors ?? ["claude"]).map((x) => <option key={x} value={x}>{x === "claude" ? "Claude (cloud)" : x === "fixture" ? "Saved extractions (offline test)" : x}</option>)}
          </select>
        </label>
        {needsKey && (
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>Anthropic API key</span>
            <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-ant-…" autoComplete="off" />
            <span className="muted" style={{ fontSize: 13 }}>Kept in memory for this session only, never saved. Pages are sent to the cloud to be read.</span>
          </label>
        )}
        {busy && progress && progress.total > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }} aria-live="polite">
            <div className="progress"><span style={{ width: `${(progress.done / progress.total) * 100}%` }} /></div>
            <span className="muted" style={{ fontSize: 13 }}>{progress.file ? `Reading ${progress.file}, page ${progress.page} (${progress.done + 1} of ${progress.total})` : "Building the history…"}</span>
          </div>
        )}
        <div><button className="btn primary" disabled={busy || !name.trim() || !folder.trim() || (!!needsKey && !apiKey)} onClick={build}>{busy ? "Working…" : "Build history"}</button></div>
      </section>
      <div className="muted" style={{ fontSize: 13 }}>Patient data is stored on this computer. Encryption at rest is planned before real patient records are used.</div>
    </div>
  );
}
