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
  check(await page.getByRole("button", { name: /items? to review/ }).isVisible(), `${theme}: review button shows`);

  if (theme === "light") {
    check((await page.locator(".lane").count()) === 5, "five condition lanes");
    await page.getByRole("button", { name: /UTI\s*acute · 3 episodes/ }).click();
    check(await page.getByRole("heading", { name: "Urinary tract infection" }).isVisible(), "condition detail opens from filter");
    await shot("2-uti-filter");
    await page.getByRole("button", { name: "All conditions" }).click();

    await page.getByRole("button", { name: /items? to review/ }).click();
    check(await page.getByText("quote not found on the page", { exact: false }).isVisible(), "held-out drug listed with reason");
    check((await page.getByText(/Needs a label/).count()) === 3, "three unnamed values offer labels");
    await shot("3-review");
    const reviewCount = async () => Number((await page.getByRole("button", { name: /items? to review/ }).textContent()).match(/\d+/)[0]);
    const before = await reviewCount();
    await page.getByRole("group", { name: "Label choices" }).filter({ hasText: "Haemoglobin" }).first().getByRole("button", { name: "Haemoglobin" }).click();
    await page.getByText('Labelled "Haemoglobin"').waitFor();
    check(await reviewCount() === before - 1, "picking a label settles the item");
    await page.getByRole("group", { name: "Label choices" }).filter({ hasText: "Leave unsure" }).first().getByRole("button", { name: "Leave unsure" }).click();
    await page.getByText("Left unlabelled").waitFor();
    await shot("3b-review-settled");
    await page.getByRole("button", { name: "Labs and scans", exact: true }).click();
    await page.getByRole("button", { name: /Haemoglobin/ }).first().click();
    check(await page.getByText("Label chosen by you").isVisible(), "labelled value is on the timeline, marked as chosen");
    await page.getByRole("button", { name: /items? to review/ }).click();
    await page.getByRole("group", { name: "Label choices" }).filter({ hasText: "Undo" }).last().getByRole("button", { name: "Undo" }).click();
    await page.getByText("Left unlabelled").waitFor({ state: "detached" });
    check(await reviewCount() === before - 1, "undo reopens the item");

    check(await page.getByText("Is this page for Meera Nair?").isVisible(), "page with a different age asks: same patient?");
    await page.getByRole("button", { name: "No, someone else" }).click();
    const settledNo = page.getByText("Marked as another patient's page, left out");
    await settledNo.waitFor();
    await settledNo.locator("..").getByRole("button", { name: "Undo" }).click();
    await settledNo.waitFor({ state: "detached" });
    await page.getByRole("button", { name: "Yes, same patient" }).click();
    await page.getByText("Confirmed: same patient").waitFor();
    await page.getByRole("button", { name: "Labs and scans", exact: true }).click();
    check(await page.getByRole("button", { name: /^TSH/ }).first().isVisible(), "confirmed page joins the history");
    await page.getByRole("button", { name: "Visit tree", exact: true }).click();
    await page.getByRole("button", { name: "Visit 22 Jan 2025", exact: true }).dispatchEvent("click"); // the worst-seizure dot sits on top of this tick
    check(await page.getByText("Held or stopped at this visit").isVisible(), "held drug listed at its visit");

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

    await page.getByRole("button", { name: "One-page summary" }).click();
    await page.getByRole("article", { name: "One-page summary" }).waitFor();
    check(await page.getByText("Held, stopped").isVisible(), "summary marks the metformin hold");
    await shot("11-summary");
    await page.emulateMedia({ media: "print" });
    await page.pdf({ path: `${out}summary.pdf`, format: "A4", printBackground: true });
    const pdfPages = (await import("node:fs")).readFileSync(`${out}summary.pdf`, "latin1").match(/\/Type\s*\/Page[^s]/g)?.length;
    check(pdfPages === 1, `summary prints on one A4 page (${pdfPages})`);
    await page.setViewportSize({ width: 703, height: 1031 }); // A4 less 12 mm margins, at 96 dpi
    await page.screenshot({ path: `${out}${theme}-12-summary-print.png`, fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.emulateMedia({ media: "screen" });
    await page.getByRole("button", { name: "← Back to the timeline" }).click();
    check(await page.getByText("Medication at the time").isVisible(), "back from the summary keeps the selection");
  } else {
    await page.getByRole("button", { name: "Correlation", exact: true }).click();
    await shot("2-correlation");
    await page.getByRole("button", { name: /items? to review/ }).click();
    await shot("3-review");
    await page.getByRole("button", { name: "One-page summary" }).click();
    await shot("4-summary");
  }
  await page.close();
}
// A saved patient (fixture reader), then older pages added later through the app.
{
  const { writeFileSync } = await import("node:fs");
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGP4DwABAQEAWk1v8QAAAABJRU5ErkJggg==", "base64");
  const page_ = (dir, stem, date, name, age, dx, drug) => {
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, `${stem}.png`), png);
    const rx = `Tab ${drug} 500 mg 1-0-1`;
    writeFileSync(join(dir, `${stem}.p1.json`), JSON.stringify({
      transcription: `${date}\n${name} ${age}/M\n${dx}\n${rx}`, doc_type: "prescription", script: "handwritten",
      encounter: { date_raw: date }, patient: { name, age, sex: "M" },
      diagnoses: [{ text: dx, confidence: 0.9, source_text: dx }],
      medications: [{ drug_as_written: drug, strength: "500 mg", frequency: "1-0-1", confidence: 0.9, source_text: rx }],
    }));
  };
  const first = join(home, "src-first"), later = join(home, "src-later");
  page_(first, "v1", "10/01/2024", "Ravi Kumar", "54", "Type 2 diabetes", "Metformin");
  page_(later, "old", "05/06/2019", "Ravi Kumar", "49", "Type 2 diabetes", "Metformin");
  page_(later, "other", "01/07/2019", "Ravi Shankar", "30", "Asthma", "Theophylline");
  await fetch("http://127.0.0.1:8765/rpc", { method: "POST", body: JSON.stringify({ id: 1, method: "projects.create", params: { name: "Ravi Kumar", folder: first, extractor: "fixture" } }) });

  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("dialog", (d) => d.accept(later));
  await page.goto("http://localhost:5173/");
  await page.getByRole("button", { name: /Ravi Kumar/ }).click();
  await page.getByRole("button", { name: "Add pages" }).click();
  await page.getByText("What changed with the pages you added").waitFor();
  check(await page.getByText("Type 2 diabetes is now first recorded on 5 Jun 2019 (was 10 Jan 2024)", { exact: false }).isVisible(), "added pages: note says the diagnosis moved earlier");
  check(await page.getByText("1 of them may be for a different patient", { exact: false }).isVisible(), "added pages: other patient's page held for yes/no");
  check(await page.getByText("1 page is left out", { exact: false }).isVisible(), "left-out page counted in the header");
  await page.screenshot({ path: `${out}light-13-added-pages.png`, fullPage: true });
  await page.close();
}

check(errors.length === 0, `no page errors${errors.length ? `: ${errors.join(" | ")}` : ""}`);
await browser.close();
stop();
process.exit(failed ? 1 : 0);
