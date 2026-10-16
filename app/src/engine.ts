// Talks to the Python engine: through the Tauri shell in the desktop app, or over HTTP
// (`medtimeline serve --http 8765`) when the UI runs in a plain browser for development.

type EngineEvent = { event: string; data: any };

const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
const httpBase = (import.meta.env.VITE_ENGINE_URL as string | undefined) ?? "http://127.0.0.1:8765";
let nextId = 1;

export const isDesktop = inTauri;

export async function call<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  if (inTauri) {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<T>("engine_call", { method, params });
  }
  const res = await fetch(`${httpBase}/rpc`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ id: nextId++, method, params }),
  });
  const body = await res.json();
  if ("error" in body && body.error != null) throw new Error(body.error);
  return body.result as T;
}

export async function onEngineEvent(handler: (e: EngineEvent) => void): Promise<() => void> {
  if (inTauri) {
    const { listen } = await import("@tauri-apps/api/event");
    return listen<EngineEvent>("engine-event", (e) => handler(e.payload));
  }
  const source = new EventSource(`${httpBase}/events`);
  source.onmessage = (m) => handler(JSON.parse(m.data));
  return () => source.close();
}

export async function pickFolder(): Promise<string | null> {
  if (!inTauri) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const picked = await open({ directory: true, multiple: false });
  return typeof picked === "string" ? picked : null;
}
