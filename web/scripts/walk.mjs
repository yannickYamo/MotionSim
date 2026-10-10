// A random walk through the page. The fixed tour (measure.mjs) visits what its author
// thought of; this presses what a user might, in an order nobody planned, and after every
// press asks the same questions: did the page throw, is anything still waiting, and does
// every check of checks.mjs still pass. Seeded, so a failing walk can be run again.
//   node scripts/walk.mjs [url] [walks] [steps] [seed]
import { chromium } from "playwright";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { failures, keepShotsIn, measure, visited } from "./checks.mjs";
if (process.env.SHOTS) keepShotsIn(process.env.SHOTS);

const url = process.argv[2] ?? "http://127.0.0.1:4310/";
const walks = Number(process.argv[3] ?? 6);
const steps = Number(process.argv[4] ?? 25);
let seed = Number(process.argv[5] ?? 20261010);
const random = () => { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296; };
const pick = (list) => list[Math.floor(random() * list.length)];

const made = readFileSync(new URL("../../examples/synthetic_igbt_600v_30a.yaml", import.meta.url), "utf8");
const folder = mkdtempSync(join(tmpdir(), "motionsim-walk-"));
const parts = ["First Maker FM-600-30", "Second Maker With A Longer Name SM-600-30B"].map((name, k) => {
  const file = join(folder, `part-${k}.device.yaml`);
  const [vendor, ...rest] = name.split(" ");
  writeFileSync(file, made.replace(/^vendor:.*$/m, `vendor: ${vendor} ${rest.slice(0, -1).join(" ")}`).replace(/^part_number:.*$/m, `part_number: ${rest[rest.length - 1]}`));
  return file;
});

/** Everything a user could press right now, as a description and a way to do it. */
async function moves(page) {
  const found = await page.evaluate(() => {
    const seen = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true, contentVisibilityAuto: true }); };
    const out = [];
    const add = (kind, selector, text) => out.push({ kind, selector, text });
    document.querySelectorAll("[data-tab],[data-compare],#rail [data-step],[data-zoom],[data-metric],[data-map-at],[data-add-motor],[data-drop-motor],[data-drop-load],[data-largest],[data-resize-load]").forEach((el, k) => {
      if (!seen(el) || el.disabled) return;
      const key = Object.keys(el.dataset)[0];
      el.dataset.walk = `w${k}`;
      add("click", `[data-walk="w${k}"]`, `${key}=${el.dataset[key] ?? ""}`);
    });
    document.querySelectorAll("[data-kind],[data-load]").forEach((el) => { if (seen(el.closest("label")) && !el.checked) add("check", `[${el.dataset.kind !== undefined ? "data-kind" : "data-load"}][value="${el.value}"]`, `pick ${el.value}`); });
    document.querySelectorAll("select[data-add-load]").forEach((el) => { if (seen(el) && el.options.length > 1) add("option", "select[data-add-load]", "add a load"); });
    document.querySelectorAll('select[data-bind="sweep.key"]').forEach((el) => { if (seen(el)) add("sweep", 'select[data-bind="sweep.key"]', "another setting"); });
    return out;
  });
  return found;
}

const browser = await chromium.launch();
const errors = [];
for (let walk = 0; walk < walks; walk++) {
  const phone = walk % 2 === 1;
  const page = await browser.newPage({ viewport: phone ? { width: 390, height: 844 } : { width: 1280, height: 860 }, reducedMotion: "reduce" });
  const trail = [];
  page.on("pageerror", (e) => errors.push(`walk ${walk} after [${trail.slice(-4).join(" > ")}]: ${e.message}`));
  await page.goto(url, { waitUntil: "networkidle" });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector("#panel h2");
  await page.setInputFiles("#part-file", parts[0]);
  await page.waitForSelector(".read-result");
  for (const step of [1, 2, 3, 4]) { await page.click(`#panel .actions [data-step="${step}"]`); await page.waitForTimeout(500); }
  await page.waitForSelector(".candidate", { timeout: 60000 });
  if (random() < 0.5) { await page.setInputFiles("[data-part-file]", parts[1]); await page.waitForSelector("#compare-table table", { timeout: 60000 }); trail.push("second device"); }
  for (let k = 0; k < steps; k++) {
    const open = await moves(page);
    if (!open.length) { failures.push(`walk ${walk}: nothing to press after [${trail.slice(-4).join(" > ")}]`); break; }
    const move = pick(open);
    trail.push(move.text);
    try {
      if (move.kind === "click") await page.click(move.selector, { timeout: 8000 });
      else if (move.kind === "check") await page.check(move.selector, { timeout: 8000 });
      else if (move.kind === "option") await page.selectOption(move.selector, { index: 1 }, { timeout: 8000 });
      else await page.selectOption(move.selector, pick(["f_khz", "v_dc", "t_sink", "parallel"]), { timeout: 8000 });
    } catch (e) {
      // A control that went away between being listed and being pressed is the page moving
      // on, not a fault; anything else is.
      // So is a step the page has just closed because the configuration no longer runs.
      if (!/detached|not visible|not attached|intercepts|not enabled/.test(String(e))) failures.push(`walk ${walk}: could not ${move.text} after [${trail.slice(-4, -1).join(" > ")}]: ${String(e).split("\n")[0]}`);
      continue;
    }
    // Nothing may stay waiting: every result the press asked for has to arrive.
    const settled = await page.waitForFunction(() => !document.querySelector(".waiting") && ![...document.querySelectorAll("#compare-table td")].some((c) => c.textContent === "…"), null, { timeout: 150000 }).then(() => true, () => false);
    if (!settled) { failures.push(`walk ${walk}: still waiting 150 s after [${trail.slice(-4).join(" > ")}]`); break; }
    await page.waitForLoadState("networkidle");
    const before = failures.length;
    await measure(page, `walk${walk}-${phone ? "phone" : "desk"}-${k}`);
    for (let f = before; f < failures.length; f++) failures[f] += ` (after ${trail.slice(-4).join(" > ")})`;
    if (await page.$(".refusal") && /engine stopped/.test(await page.$eval("#panel", (e) => e.textContent))) failures.push(`walk ${walk}: the engine stopped after [${trail.slice(-4).join(" > ")}]`);
  }
  await page.close();
}
await browser.close();
for (const e of errors) failures.push(`page error: ${e}`);
console.log(`${walks} walks, ${visited.length} surfaces checked`);
const distinct = [...new Set(failures.map((f) => f.replace(/^walk\d+-\w+-\d+: /, "")))];
if (distinct.length) { console.error(`\n${failures.length} failures, ${distinct.length} distinct:\n  ${distinct.slice(0, 40).join("\n  ")}`); process.exit(1); }
console.log("no failures");
