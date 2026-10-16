// End-to-end smoke test: real engine over HTTP + the built UI in headless Chromium.
//   npm run build && npm run e2e
// Starts `medtimeline serve --http 8765` and `vite preview`, opens the demo patient,
// walks every view and the condition filter, and saves screenshots to e2e/screens/.
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const out = new URL("./screens/", import.meta.url).pathname;
mkdirSync(out, { recursive: true });
const home = mkdtempSync(join(tmpdir(), "medtimeline-e2e-"));
const engineCmd = (process.env.MEDTIMELINE_ENGINE ?? "medtimeline").split(/\s+/);
const procs = [
  spawn(engineCmd[0], [...engineCmd.slice(1), "serve", "--http", "8765", "--home", home], { stdio: "inherit" }),
  spawn("npx", ["vite", "preview", "--port", "5173", "--strictPort"], { stdio: "ignore" }),
];
const stop = () => procs.forEach((p) => p.kill());
process.on("exit", stop);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(url) {
  for (let i = 0; i < 60; i++) {
    try { await fetch(url, { method: url.endsWith("rpc") ? "OPTIONS" : "GET" }); return; } catch { await sleep(250); }
  }
  throw new Error(`timed out waiting for ${url}`);
}
await waitFor("http://127.0.0.1:8765/rpc");
await waitFor("http://localhost:5173/");

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM ?? "/opt/pw-browsers/chromium" });
const errors = [];
let failed = false;
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) failed = true; };

for (const theme of ["light", "dark"]) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: theme });
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  await page.goto("http://localhost:5173/");
  await page.getByText("Demo patient").click();
  await page.getByRole("heading", { level: 1 }).waitFor();
  const shot = (name) => page.screenshot({ path: `${out}${theme}-${name}.png`, fullPage: true });
  await shot("1-tree");
  check(await page.getByRole("button", { name: /items? need review/ }).isVisible(), `${theme}: review button shows`);

  if (theme === "light") {
    check((await page.locator(".lane").count()) === 5, "five condition lanes");
    await page.getByRole("button", { name: /UTI\s*acute · 3 episodes/ }).click();
    check(await page.getByRole("heading", { name: "Urinary tract infection" }).isVisible(), "condition detail opens from filter");
    await shot("2-uti-filter");
    await page.getByRole("button", { name: "All conditions" }).click();

    await page.getByRole("button", { name: /items? need review/ }).click();
    check(await page.getByText("quote not found on the page", { exact: false }).isVisible(), "held-out drug listed with reason");
    await shot("3-review");

    for (const [tab, name] of [["Symptoms", "4-symptoms"], ["Episodes", "5-episodes"], ["Medications", "6-meds"], ["Labs and scans", "7-tests"]]) {
      await page.getByRole("button", { name: tab, exact: true }).click();
      await page.locator("section[aria-label] .node").first().click();
      await shot(name);
    }
    await page.getByRole("button", { name: "Symptoms", exact: true }).click();
    await page.getByRole("button", { name: /Frequent urination/ }).click();
    check(await page.getByText("Not tied to a condition on the page").first().isVisible(), "unlinked occurrence shown honestly");

    await page.getByRole("button", { name: "Correlation", exact: true }).click();
    await shot("8-correlation-all");
    await page.getByRole("button", { name: /Epilepsy/ }).first().click();
    check(await page.getByText("Showing Epilepsy only.").isVisible(), "correlation narrows to one condition");
    await shot("9-correlation-epilepsy");

    await page.getByRole("button", { name: "Visit tree", exact: true }).click();
    await page.getByRole("button", { name: "All conditions" }).click();
    await page.getByRole("button", { name: /worst reported/ }).first().click();
    check(await page.getByText("Medication at the time").isVisible(), "worst episode detail");
    await shot("10-worst-episode");
  } else {
    await page.getByRole("button", { name: "Correlation", exact: true }).click();
    await shot("2-correlation");
  }
  await page.close();
}
check(errors.length === 0, `no page errors${errors.length ? `: ${errors.join(" | ")}` : ""}`);
await browser.close();
stop();
process.exit(failed ? 1 : 0);
