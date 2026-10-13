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
  // The second part is rated cooler, so its margins can never pass for the first's.
  writeFileSync(file, made.replace(/^vendor:.*$/m, `vendor: ${vendor} ${rest.slice(0, -1).join(" ")}`).replace(/^part_number:.*$/m, `part_number: ${rest[rest.length - 1]}`).replace(/tj_max: .*/, `tj_max: ${k ? 125 : 150}`));
  return file;
});

/** Everything a user could press right now, as a description and a way to do it. */
async function moves(page) {
  const found = await page.evaluate(() => {
    const seen = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true, contentVisibilityAuto: true }); };
    const out = [];
    const add = (kind, selector, text) => out.push({ kind, selector, text });
    document.querySelectorAll("[data-tab],[data-compare],#rail [data-step],[data-zoom],[data-metric],[data-map-at],[data-add-motor],[data-drop-motor],[data-drop-load],[data-largest],[data-resize-load],#switcher [data-focus],[data-drop-value]").forEach((el, k) => {
      if (!seen(el) || el.disabled) return;
      const key = Object.keys(el.dataset)[0];
      el.dataset.walk = `w${k}`;
      add("click", `[data-walk="w${k}"]`, `${key}=${el.dataset[key] ?? ""}`);
    });
    document.querySelectorAll("[data-kind],[data-load]").forEach((el) => { if (seen(el.closest("label")) && !el.checked) add("check", `[${el.dataset.kind !== undefined ? "data-kind" : "data-load"}][value="${el.value}"]`, `pick ${el.value}`); });
    document.querySelectorAll("select[data-add-load]").forEach((el) => { if (seen(el) && el.options.length > 1) add("option", "select[data-add-load]", "add a load"); });
    document.querySelectorAll('select[data-bind="sweep.key"]').forEach((el) => { if (seen(el)) add("sweep", 'select[data-bind="sweep.key"]', "another setting"); });
    document.querySelectorAll("[data-sweep-add]").forEach((el) => { if (seen(el)) add("value", "[data-sweep-add]", "add a value"); });
    return out;
  });
  return found;
}

/** Every figure on show: the readouts, the table of things compared, the tab, the drawing. */
// What is worked out only when asked for (the largest load) is not kept across a reload.
const shown = (page) => page.evaluate(() => Object.fromEntries(["#readouts", "#compare-table", "#tab-body", "#plate", "#switcher"].map((s) => { const el = document.querySelector(s)?.cloneNode(true); el?.querySelectorAll("[data-asked]").forEach((x) => x.remove()); return [s, (el?.textContent ?? "").replace(/\s+/g, " ").trim()]; })));
const settle = (page) => page.waitForFunction(() => !document.body.dataset.busy && !document.querySelector(".waiting") && !document.querySelector("#readouts")?.textContent?.includes("Starting the engine") && ![...document.querySelectorAll("#compare-table td")].some((c) => c.textContent === "…"), null, { timeout: 150000 }).then(() => true, () => false);
/** The page reloaded from what it saved shows what it showed: anything else was left over
 *  from before the last change, or was never saved. */
async function sameAfterReload(page, where, trail) {
  await page.waitForLoadState("networkidle");
  const before = await shown(page);
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector("#panel h2");
  await page.waitForTimeout(1500);
  if (!(await settle(page))) { failures.push(`${where}: still waiting 150 s after a reload [${trail.slice(-4).join(" > ")}]`); return; }
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(300);
  const after = await shown(page);
  for (const [part, text] of Object.entries(before)) {
    if (text === after[part]) continue;
    let k = 0; while (k < text.length && text[k] === after[part][k]) k++;
    failures.push(`${where}: ${part} shows something else after a reload [${trail.slice(-6).join(" > ")}]: "${text.slice(Math.max(0, k - (process.env.WIDE ? 400 : 40)), k + (process.env.WIDE ? 500 : 60))}" became "${after[part].slice(Math.max(0, k - 40), k + (process.env.WIDE ? 500 : 60))}"`);
  }
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
      else if (move.kind === "value") { await page.fill(move.selector, String(pick([3, 7, 9, 15, 25, 35, 70])), { timeout: 8000 }); await page.keyboard.press("Enter"); }
      else if (move.kind === "option") await page.selectOption(move.selector, { index: 1 }, { timeout: 8000 });
      else await page.selectOption(move.selector, pick(["f_khz", "v_dc", "t_sink", "parallel"]), { timeout: 8000 });
    } catch (e) {
      // A control that went away between being listed and being pressed is the page moving
      // on, not a fault; anything else is.
      // So is a step the page has just closed because the configuration no longer runs.
      if (!/detached|not visible|not attached|intercepts|not enabled/.test(String(e))) failures.push(`walk ${walk}: could not ${move.text} after [${trail.slice(-4, -1).join(" > ")}]: ${String(e).split("\n")[0]}`);
      continue;
    }
    // The page works out a change a moment after it is made, so that typing does not ask
    // for a result at every key. The walk waits that moment out: otherwise it lists the
    // next control while the last press has not begun to redraw, and then presses a
    // control that is being replaced under it.
    await page.waitForTimeout(400);
    // Nothing may stay waiting: every result the press asked for has to arrive.
    const settled = await settle(page);
    if (!settled) { failures.push(`walk ${walk}: still waiting 150 s after [${trail.slice(-4).join(" > ")}]`); break; }
    await page.waitForLoadState("networkidle");
    const before = failures.length;
    await measure(page, `walk${walk}-${phone ? "phone" : "desk"}-${k}`);
    for (let f = before; f < failures.length; f++) failures[f] += ` (after ${trail.slice(-4).join(" > ")})`;
    if (failures.length > before && process.env.WALK_SHOTS) await page.screenshot({ path: `${process.env.WALK_SHOTS}/walk${walk}-${k}.png` }); if (failures.length > before && process.env.WALK_SHOTS) console.log(JSON.stringify(await page.evaluate(() => { const q = (el) => { const r = el.getBoundingClientRect(); return [el.tagName, el.textContent.trim().slice(0, 20), Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)]; }; return { y: scrollY, stage: document.querySelector("#stage")?.scrollTop, hits: [...document.querySelectorAll("th, svg text")].filter((e) => /^(Verdict|Motor: mag)/.test(e.textContent.trim())).map(q) }; })));
    if (await page.$(".refusal") && /engine stopped/.test(await page.$eval("#panel", (e) => e.textContent))) failures.push(`walk ${walk}: the engine stopped after [${trail.slice(-4).join(" > ")}]`);
    if (k % 5 === 4) await sameAfterReload(page, `walk ${walk} step ${k}`, trail);
  }
  await page.close();
}
await browser.close();
for (const e of errors) failures.push(`page error: ${e}`);
console.log(`${walks} walks, ${visited.length} surfaces checked`);
const distinct = [...new Set(failures.map((f) => f.replace(/^walk\d+-\w+-\d+: /, "")))];
if (distinct.length) { console.error(`\n${failures.length} failures, ${distinct.length} distinct:\n  ${distinct.slice(0, 40).join("\n  ")}`); process.exit(1); }
console.log("no failures");
