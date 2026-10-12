// Measures the built page against the design laws that can be measured, on every step and
// tab, at desktop, laptop and phone widths. Needs `motionsim serve` running.
//   node scripts/measure.mjs [url] [screenshot-folder]
// Exits 1 on any failure. A surface that did not render is a failure, not a pass.
import { chromium } from "playwright";

const url = process.argv[2] ?? "http://127.0.0.1:4310/";
import { failures, keepShotsIn, measure, visited } from "./checks.mjs";
keepShotsIn(process.argv[3]);


// The part dropped in is the made-up one under a long name, as a module with its drivers
// inside: real names are long, and that is what breaks a layout.
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const made = readFileSync(new URL("../../examples/synthetic_igbt_600v_30a.yaml", import.meta.url), "utf8");
const part = join(mkdtempSync(join(tmpdir(), "motionsim-")), "long-name-module.device.yaml");
writeFileSync(part, made.replace(/^vendor:.*$/m, "vendor: Longname Semiconductor (Formerly Another Company)").replace(/^part_number:.*$/m, "part_number: ABC41560-XYZ / ABC41560B2-XYZ"));
// A mission profile: a ramp up, a hold and a ramp down, as a logger would write it.
const mission = join(mkdtempSync(join(tmpdir(), "motionsim-")), "mission.csv");
writeFileSync(mission, "time_s;speed_rpm;torque_Nm\n" + Array.from({ length: 40 }, (_, k) => { const t = k * 0.25; const up = Math.min(t / 3, 1, (9.75 - t) / 3); return `${t};${(1500 * Math.max(up, 0)).toFixed(1)};${(0.2 + 0.6 * Math.max(up, 0)).toFixed(3)}`; }).join("\n"));
// A second part, to compare with the first.
const second = join(mkdtempSync(join(tmpdir(), "motionsim-")), "second-part.device.yaml");
writeFileSync(second, made.replace(/^vendor:.*$/m, "vendor: Second Maker").replace(/^part_number:.*$/m, "part_number: SM-600-30"));
// What the tool assumes is said on the face of a fold; the means of changing it is inside.
// The tour opens the folds of the step it is on before it reaches in.
const unfold = (page) => page.evaluate(() => document.querySelectorAll("#panel details[data-fold]").forEach((d) => { d.open = true; }));
const browser = await chromium.launch();
const errors = [];
for (const [label, width, height] of [["desktop", 1440, 900], ["laptop", 1100, 760], ["mobile", 390, 844]]) {
  const page = await browser.newPage({ viewport: { width, height }, reducedMotion: "reduce" });
  page.on("pageerror", (e) => errors.push(`${label}: ${e.message}`));
  // Nothing on the page may be pushed about while it loads, and no request may fail.
  await page.addInitScript(() => {
    window.__shift = 0;
    new PerformanceObserver((list) => { for (const e of list.getEntries()) if (!e.hadRecentInput) window.__shift += e.value; }).observe({ type: "layout-shift", buffered: true });
  });
  const failed = [];
  page.on("response", (r) => { if (r.status() >= 400 && !/\/api\//.test(r.url())) failed.push(`${r.status()} ${r.url()}`); });
  await page.goto(url, { waitUntil: "networkidle" });
  await page.waitForSelector("#panel h2");
  await page.waitForTimeout(1500);
  const shift = await page.evaluate(() => window.__shift);
  if (shift > 0.02) failures.push(`${label}: the page shifts as it loads (cumulative layout shift ${shift.toFixed(3)})`);
  if (failed.length) failures.push(`${label}: a request failed while the page loaded: ${failed.join(", ")}`);
  const unnamed = await page.$$eval("button, a[href], summary", (els) => els.filter((e) => e.offsetParent !== null && !(e.getAttribute("aria-label") || e.textContent || e.getAttribute("title") || "").trim()).map((e) => e.outerHTML.slice(0, 80)));
  if (unnamed.length) failures.push(`${label}: a control has no name for a screen reader: ${unnamed.join(" | ")}`);
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "networkidle" });
  // Without a server the engine loads into the page first, which takes a while.
  await page.waitForSelector("#panel h2");
  // To prove a check can fail: BREAK holds CSS that puts a fault back, and the run must then fail.
  if (process.env.BREAK) await page.addStyleTag({ content: process.env.BREAK });
  // Without a server the engine loads into the page first, which takes a while.
  await page.waitForFunction(() => !document.querySelector("#readouts")?.textContent?.includes("Starting the engine"), null, { timeout: 240000 });
  await measure(page, `${label}-1-device-empty`);
  // The equations, opened from the top of the page.
  await page.click("[data-equations]");
  await page.waitForSelector("#equations[open] .eq");
  await measure(page, `${label}-0-equations`);
  await page.click("[data-close-equations]");
  await page.waitForSelector("#equations:not([open])", { state: "attached" }); // a closed dialog is in the page but not shown
  // A part can be typed in from its datasheet: the form opens, and a slip is refused at
  // the figure it sits in, with nothing added.
  await page.click("details.typed summary");
  await page.waitForSelector('details.typed[open] [data-typed="rds_on"]');
  await measure(page, `${label}-1-typed`);
  for (const [key, value] of Object.entries({ part_number: "TYPED-1", v_rated: 100, i_rated: 100, tj_max: 175, rth_jc: 0.6, rds_on: 4000, v_th: 3, v_plateau: 4.6, q_gs: 20, q_gd: 14 })) await page.fill(`[data-typed="${key}"]`, String(value));
  await page.click("[data-add-typed]");
  await page.waitForSelector("details.typed .said-wrong");
  // The reason is said at the figure, in view, with the figure in focus; and it goes when the figure is corrected.
  const said = await page.evaluate(() => { const m = document.querySelector(".said-wrong")?.getBoundingClientRect(); return !!m && m.top >= 0 && m.bottom <= innerHeight && document.activeElement?.getAttribute("data-typed") === "rds_on"; });
  if (!said) failures.push(`${label}: the reason a figure is refused is not shown at that figure, in view and in focus`);
  await measure(page, `${label}-1-typed-slip`);
  if (!(await page.$('.field.is-wrong [data-typed="rds_on"]'))) failures.push(`${label}: the mistyped figure is not the one marked`);
  await page.fill('[data-typed="rds_on"]', "4");
  if (await page.$("details.typed .said-wrong, details.typed .field.is-wrong")) failures.push(`${label}: a corrected figure keeps its mark`);
  await page.fill('[data-typed="rds_on"]', "4000");
  await page.click("[data-add-typed]");
  await page.waitForSelector("details.typed .said-wrong");
  if ((await page.$$("[data-device]")).length) failures.push(`${label}: a part with a mistyped figure was added`);
  if ((await page.$$("[data-example]")).length !== 2) failures.push(`${label}: both made-up parts should be offered, a transistor and an IGBT`);
  await page.click("details.typed summary");
  // Nothing is listed that the user did not bring, whatever the served folder holds.
  if ((await page.$$("[data-device]")).length) failures.push(`${label}: parts are listed before the user has added any`);
  // No figure is shown that the user has not given: the supply voltage comes at step 3.
  if (await page.$(".schematic .source .reading")) failures.push(`${label}: a supply voltage is drawn before the user has given one`);
  if (await page.$(".schematic .motor .rotor")) failures.push(`${label}: a kind of motor is drawn before the user has chosen one`);
  // The user brings the part: a device file is dropped here, as they would drop their own.
  await page.setInputFiles("#part-file", part);
  await page.waitForSelector(".read-result");
  await measure(page, `${label}-1-device`);
  if ((await page.$$("[data-device]:checked")).length !== 1) failures.push(`${label}: the part just added is not the part under test`);
  // The model laid open for checking against the datasheet.
  await page.click(".review-link[data-review]");
  await page.waitForSelector("#review .read-chart");
  await measure(page, `${label}-1-review`);
  await page.click(".review-link[data-review]");
  await page.click('#panel .actions [data-step="1"]');
  await page.waitForSelector(".kind.is-rec");
  await measure(page, `${label}-2-motor`);
  if ((await page.$$(".tag.recommended")).length !== 1) failures.push(`${label}: exactly one kind of motor should be recommended for the device`);
  if (!(await page.$(".kind.is-rec input:checked"))) failures.push(`${label}: the recommended motor is not the one the user starts on`);
  // A motor that asks more than the part is rated for is said here, where it was typed,
  // with why; and the alert goes when the figure is put back.
  {
    const box = '[data-bind$=".i_max"]';
    await page.waitForSelector("#motor-fit .fact");
    if (await page.$("#motor-fit .fit-raised")) failures.push(`${label}: the example motor is said not to fit the part it was wound for`);
    const was = await page.$eval(box, (e) => e.value);
    await page.fill(box, "4000");
    await page.waitForSelector("#motor-fit .fit-raised", { timeout: 15000 }).catch(() => failures.push(`${label}: a motor drawing far more than the part's rating raises nothing at the motor step`));
    if (!/A peak, and the part is rated/.test(await page.$eval("#motor-fit", (e) => e.textContent))) failures.push(`${label}: the alert does not say what the motor draws against what the part is rated for`);
    await measure(page, `${label}-2-motor-misfit`);
    await page.fill(box, was);
    await page.waitForFunction(() => !document.querySelector("#motor-fit .fit-raised"), null, { timeout: 15000 }).catch(() => failures.push(`${label}: the alert stays after the motor is put right`));
  }
  // A figure in a base unit is said the way it is spoken, and follows what is typed.
  {
    const box = '[data-bind$=".l"], [data-bind$=".ld"], [data-bind$=".lm"]';
    const was = await page.$eval(box, (e) => e.value);
    const said = () => page.$eval(box, (e) => e.closest(".field").querySelector("[data-said]").textContent.trim());
    await page.fill(box, "0.00833");
    if ((await said()) !== "That is 8.33 mH.") failures.push(`${label}: an inductance of 0.00833 H is not said as 8.33 mH: "${await said()}"`);
    await page.fill(box, "0.0002");
    if ((await said()) !== "That is 200 µH.") failures.push(`${label}: the spoken inductance does not follow what is typed: "${await said()}"`);
    await page.fill(box, was);
  }
  await page.click('#panel .actions [data-step="2"]');
  await page.waitForTimeout(800);
  await measure(page, `${label}-3-supply`);
  // The step asks for three figures and the cooling; the rest is assumed, said, and one press away.
  const asked = await page.$$eval("#panel input:not(.sr), #panel select", (els) => els.filter((e) => e.offsetParent && !e.closest("details:not([open])")).length);
  // In view: the bus, the point, the switching frequency, devices in parallel, the modulation
  // and the cooling. Folded, and said on the fold: the kind of supply and the motor's temperature.
  for (const bind of ["conditions.v_dc", "conditions.rpm", "conditions.torque", "conditions.f_khz", "conditions.parallel", "conditions.cooling"]) {
    if (!(await page.$eval(`[data-bind="${bind}"]`, (e) => !!e.offsetParent && !e.closest("details:not([open])")).catch(() => false))) failures.push(`${label}: ${bind} is not in view on the supply step`);
  }
  if (asked > 9) failures.push(`${label}: the supply step asks for ${asked} things before anything is unfolded`);
  if (!/power supply, which does not take braking energy back; motor at 25 °C/.test(await page.$eval('[data-fold="more-settings"] summary', (e) => e.textContent))) failures.push(`${label}: the settings left folded are not said on the fold's face`);
  await unfold(page);
  await measure(page, `${label}-3-supply-unfolded`);
  // Cooling: each choice asks only for what it needs, and the one that needs a figure says so.
  await page.selectOption('[data-bind="conditions.cooling"]', "heatsink");
  await page.waitForSelector(".refusal");
  await measure(page, `${label}-3-cooling-heatsink`);
  if (!(await page.$('[data-bind="conditions.rth_sink"]')) || (await page.$('[data-bind="conditions.t_sink"]'))) failures.push(`${label}: a heatsink in air should ask for its K/W and the air, not its temperature`);
  await page.fill('[data-bind="conditions.rth_sink"]', "2");
  await page.waitForFunction(() => !document.querySelector(".refusal"), null, { timeout: 30000 });
  await page.selectOption('[data-bind="conditions.cooling"]', "none");
  await page.waitForSelector('[data-bind="conditions.rth_ja"]');
  await page.fill('[data-bind="conditions.rth_ja"]', "40");
  await page.waitForTimeout(800);
  await measure(page, `${label}-3-cooling-none`);
  // Soldered to one board: the board's area is asked for, and refused without.
  await page.selectOption('[data-bind="conditions.cooling"]', "board");
  await page.waitForSelector(".refusal");
  if (!(await page.$('.field.is-wrong [data-bind="conditions.board_area"]'))) failures.push(`${label}: the missing board area is not the field marked`);
  await page.fill('[data-bind="conditions.board_area"]', "150");
  await page.waitForFunction(() => !document.querySelector(".refusal"), null, { timeout: 30000 });
  await measure(page, `${label}-3-cooling-board`);
  await page.selectOption('[data-bind="conditions.cooling"]', "held");
  await page.waitForSelector('[data-bind="conditions.t_sink"]');
  await page.fill('[data-bind="conditions.rpm"]', "30000");
  await page.waitForSelector(".refusal");
  await measure(page, `${label}-3-refused`);
  await page.fill('[data-bind="conditions.rpm"]', "2000");
  await page.waitForSelector(".schematic.is-live");
  await page.click('#panel .actions [data-step="3"]');
  await page.waitForTimeout(1500);
  await measure(page, `${label}-4-load`);
  // The load step is a choice and a picture; its figures and its motion are one press away.
  const typed = await page.$$eval("#panel input:not(.sr):not([type=radio]):not([type=file]), #panel select", (els) => els.filter((e) => e.offsetParent && !e.closest("details:not([open])")).length);
  if (typed > 0) failures.push(`${label}: the load step shows ${typed} figures to fill before anything is unfolded`);
  await unfold(page);
  await measure(page, `${label}-4-load-unfolded`);
  if (!(await page.$("[data-load]:checked"))) failures.push(`${label}: no kind of load is chosen for the motor on the load step`);
  // Every kind of load offered for this motor, on the widest screen: each has to draw and run.
  if (label === "desktop") {
    for (const id of await page.$$eval("[data-load]", (els) => els.map((e) => e.value))) {
      await page.check(`[data-load][value="${id}"]`);
      await page.waitForTimeout(700);
      await measure(page, `${label}-4-load-${id}`);
    }
  }
  // The steps have to agree: with a load picked, a new design speed sizes that load again.
  {
    const kindOf = await page.$eval("[data-load]:checked", (e) => e.value);
    const reach = async () => Number((await page.$eval("#motion-preview .fact", (e) => e.textContent)).match(/reaches ([\d,]+) rpm/)[1].replace(/,/g, ""));
    await page.click('#rail [data-step="2"]');
    await page.fill('[data-bind="conditions.rpm"]', "3000");
    await page.click('#rail [data-step="3"]');
    // The load is sized again by the engine a moment after the new speed shows: wait for the
    // motion itself to follow, not only for the sentence that quotes the design speed.
    await page.waitForFunction(() => { const text = document.querySelector("#motion-preview .fact")?.textContent ?? ""; const at = Number((text.match(/reaches ([\d,]+) rpm/)?.[1] ?? "0").replace(/,/g, "")); return /3,000 rpm/.test(text) && at >= 1200; }, null, { timeout: 30000 }).catch(() => {});
    const now = await reach();
    if (now > 3000 * 1.01 || now < 3000 * 0.4) failures.push(`${label}: after the design speed became 3000 rpm the motion still reaches ${now} rpm at the motor`);
    if ((await page.$eval("[data-load]:checked", (e) => e.value)) !== kindOf) failures.push(`${label}: changing the design speed changed the kind of load picked`);
    if (await page.$("#motion-preview .fact.warn")) failures.push(`${label}: a load sized by the tool asks for more than the design speed`);
    // Figures of the user's own are kept, and the page says when they pass the design speed.
    await page.fill('[data-bind="segments.1.speed_start"]', "9000");
    await page.fill('[data-bind="segments.1.speed_end"]', "9000");
    await page.waitForSelector("#motion-preview .fact.warn");
    await measure(page, `${label}-4-load-over`);
    await page.click('#rail [data-step="2"]');
    await page.fill('[data-bind="conditions.rpm"]', "2000");
    await page.click('#rail [data-step="3"]');
    await page.click("[data-resize-load]"); // the tool's sizing can be taken back
    await page.waitForFunction(() => !document.querySelector("#motion-preview .fact.warn"), null, { timeout: 30000 });
  }
  await page.click('#panel .actions [data-step="4"]');
  await page.waitForSelector(".candidate", { timeout: 60000 });
  await measure(page, `${label}-5-verdict`);
  await page.evaluate(() => document.querySelectorAll("details.pwm-fold").forEach((d) => { d.open = true; }));
  if (!(await page.$("#pwm svg.pwm .area.switching"))) failures.push(`${label}: the switching periods are not drawn under the result`);
  // Zoom the switching periods in and out: the drawing follows.
  await page.evaluate(() => document.querySelectorAll("details.pwm-fold").forEach((d) => { d.open = true; }));
  await page.click('[data-zoom="in"]');
  if (!(await page.$eval("#pwm h3", (e) => e.textContent)).startsWith("2 ")) failures.push(`${label}: zooming in did not show two switching periods`);
  await page.click('[data-zoom="out"]');
  for (const tab of ["losses", "motion", "map", "settings", "capability"]) {
    await page.click(`[data-tab="${tab}"]`);
    await page.waitForFunction(() => !document.querySelector(".waiting"), null, { timeout: 90000 });
    await page.waitForTimeout(300);
    await measure(page, `${label}-5-${tab}`);
  }
  // What it can drive: the limit line, and how much heavier the load could be.
  await page.click('[data-tab="capability"]');
  await page.waitForSelector("[data-largest]", { timeout: 120000 });
  await page.click("[data-largest]");
  await page.waitForFunction(() => /times|already too much/.test(document.querySelector("#tab-body")?.textContent ?? ""), null, { timeout: 180000 });
  await measure(page, `${label}-5-largest`);
  await page.click('[data-tab="proposal"]');
  // Two devices in parallel lose less in each, and the result says so; then back to one.
  const alone = await page.$eval("#readouts .figure", (e) => e.textContent);
  await page.click('#rail [data-step="2"]');
  await page.fill('[data-bind="conditions.parallel"]', "2");
  await page.click('#rail [data-step="4"]');
  await page.waitForFunction((was) => { const f = document.querySelector("#readouts .figure"); return f && f.textContent !== was; }, alone, { timeout: 60000 });
  await measure(page, `${label}-5-parallel`);
  if (!(await page.$eval(".schematic .plate-title", (e) => e.textContent)).includes("2 in parallel at each switch")) failures.push(`${label}: the drawing does not say the devices are in parallel`);
  await page.click('#rail [data-step="2"]');
  await page.fill('[data-bind="conditions.parallel"]', "1");
  // A mission profile from a file takes the place of the load and the motion.
  await page.click('#rail [data-step="3"]');
  await page.setInputFiles("[data-mission-file]", mission);
  await page.waitForSelector("[data-drop-mission]");
  await measure(page, `${label}-4-mission`);
  await page.click('#rail [data-step="4"]');
  await page.click('[data-tab="motion"]');
  await page.waitForFunction(() => /Life under thermal cycling/.test(document.querySelector("#panel")?.textContent ?? ""), null, { timeout: 120000 });
  await measure(page, `${label}-5-mission-motion`);
  await page.click('#rail [data-step="3"]');
  await page.click("[data-drop-mission]");
  await page.click('#rail [data-step="4"]');
  // The motion is four drawings of one size, each with its axes named and its unit said.
  {
    await page.click('[data-tab="motion"]');
    await page.waitForFunction(() => !document.querySelector(".waiting") && document.querySelectorAll("#tab-body svg.chart").length >= 4, null, { timeout: 120000 });
    const charts = await page.$$eval("#tab-body svg.chart", (els) => els.map((e) => { const b = e.getBoundingClientRect(); return { size: `${Math.round(b.width)}x${Math.round(b.height)}`, axes: [...e.querySelectorAll("text.axis")].map((t) => t.textContent), ticks: e.querySelectorAll("text.tick").length }; }));
    if (new Set(charts.map((c) => c.size)).size !== 1) failures.push(`${label}: the motion's charts are not one size: ${charts.map((c) => c.size).join(", ")}`);
    for (const c of charts) if (c.axes.length < 2 || !c.axes.includes("time, s") || !c.axes.some((a) => /, (°C|rpm|N·m|A peak)$/.test(a)) || c.ticks < 4) failures.push(`${label}: a motion chart has no named axes with units, or no scale: ${JSON.stringify(c)}`);
    await page.click('[data-tab="proposal"]');
    await page.waitForSelector(".candidate", { timeout: 60000 });
  }
  // The result can be kept as a Markdown file, the same report the command line writes.
  {
    const [file] = await Promise.all([page.waitForEvent("download", { timeout: 120000 }), page.click("[data-report-md]")]);
    const text = readFileSync(await file.path(), "utf8");
    if (!file.suggestedFilename().endsWith("-report.md")) failures.push(`${label}: the Markdown report is saved under "${file.suggestedFilename()}"`);
    for (const part of ["power-stage estimate", "## What was tested", "## Verdict at the design point", "## What to build", "## What this rests on"]) if (!text.includes(part)) failures.push(`${label}: the Markdown report has no "${part}"`);
    await page.waitForSelector("[data-report-md]:not([disabled])");
  }
  // The report is built for paper: with print styles on, only it is on the page.
  await page.click('[data-tab="proposal"]');
  await page.waitForSelector(".candidate", { timeout: 60000 });
  await page.evaluate(() => { window.print = () => { window.__printed = true; }; });
  await page.click("[data-report]");
  await page.waitForFunction(() => window.__printed === true, null, { timeout: 120000 });
  await page.emulateMedia({ media: "print" });
  const paper = await page.evaluate(() => ({ app: getComputedStyle(document.querySelector("#app")).display, text: document.querySelector("#report").innerText }));
  await page.emulateMedia({ media: "screen", reducedMotion: "reduce" });
  for (const part of ["What was tested", "Result at the design point", "Through the motion", "What this rests on", "The equations", "Conduction loss"]) {
    if (!paper.text.includes(part)) failures.push(`${label}: the report has no section "${part}"`);
  }
  if (paper.app !== "none") failures.push(`${label}: the page itself would print along with the report`);
  // Compare devices: a second part is added at the results, and every tab shows both.
  await page.click('[data-tab="proposal"]');
  await page.setInputFiles("[data-part-file]", second);
  await page.waitForSelector("#compare-table table", { timeout: 60000 });
  await measure(page, `${label}-6-devices`);
  if ((await page.$$("#compare-table thead th")).length !== 3) failures.push(`${label}: the table does not have a column for each of the two devices`);
  // The second part is the first under another name: the same loss, so neither is the winner.
  if ((await page.$$("#compare-table td.best")).length !== 2) failures.push(`${label}: two parts with the same loss should be marked together`);
  if (!/marked together/.test(await page.$eval("#compare-table", (e) => e.textContent))) failures.push(`${label}: the table does not say the two losses are level`);
  for (const row of ["Verdict", "Held at standstill", "Switching data"]) {
    if (!(await page.$$eval("#compare-table tbody th", (cells, name) => cells.some((c) => c.textContent === name), row))) failures.push(`${label}: the device comparison has no row "${row}"`);
  }
  if (!(await page.$$eval("#compare-table .room", (cells) => cells.length >= 4 && cells.every((c) => /°C to the limit/.test(c.textContent))))) failures.push(`${label}: the margins to the junction limit are not shown for both devices`);
  for (const tab of ["losses", "motion", "map"]) {
    await page.click(`[data-tab="${tab}"]`);
    await page.waitForFunction(() => !document.querySelector(".waiting"), null, { timeout: 120000 });
    await page.waitForTimeout(300);
    await measure(page, `${label}-6-devices-${tab}`);
    const seen = { losses: ".bar-row", motion: ".series.s1", map: ".map-one svg" }[tab];
    if ((await page.$$(seen)).length < (tab === "motion" ? 1 : 2)) failures.push(`${label}: the ${tab} tab does not show both devices`);
  }
  // Compare loads: the second device is taken out, and a second load is set beside the first.
  await page.click("[data-drop-device]:last-of-type");
  await page.waitForSelector("#readouts .readout", { timeout: 60000 });
  await page.click('[data-compare="loads"]');
  await page.selectOption("[data-add-load]", { index: 1 });
  await page.waitForFunction(() => { const cells = [...document.querySelectorAll("#compare-table tbody tr.loss td")]; return cells.length === 2 && cells.every((c) => /W/.test(c.textContent)); }, null, { timeout: 120000 });
  await page.click('[data-tab="motion"]');
  await page.waitForFunction(() => !document.querySelector(".waiting"), null, { timeout: 120000 });
  await measure(page, `${label}-7-loads`);
  if (!(await page.$(".series.s1"))) failures.push(`${label}: the two loads are not drawn on one chart`);
  await page.click("[data-drop-load]");
  // Compare motors: the motor of step 2 is kept, and stands beside the one on the page.
  await page.click('[data-compare="motors"]');
  await page.click("[data-add-motor]");
  await page.waitForFunction(() => { const cells = [...document.querySelectorAll("#compare-table tbody tr.loss td")]; return cells.length === 2 && cells.every((c) => /W/.test(c.textContent)); }, null, { timeout: 120000 });
  await measure(page, `${label}-8-motors`);
  await page.click("[data-drop-motor]");
  // Try a setting: the switching frequency at half, as set, and double.
  await page.click('[data-compare="sweep"]');
  await page.waitForFunction(() => { const cells = [...document.querySelectorAll("#compare-table tbody tr.loss td")]; return cells.length === 3 && cells.every((c) => /W/.test(c.textContent)); }, null, { timeout: 120000 });
  await page.click('[data-tab="losses"]');
  await measure(page, `${label}-9-sweep`);
  const swept = await page.$$eval("#compare-table tbody tr.loss td", (cells) => cells.map((c) => parseFloat(c.textContent)));
  if ((await page.$$("#compare-table td.best")).length !== 1) failures.push(`${label}: with losses well apart exactly one value should be marked lowest`);
  if (!(swept[0] < swept[1] && swept[1] < swept[2])) failures.push(`${label}: loss does not rise with switching frequency across the values tried (${swept.join(", ")})`);
  await page.click('[data-compare="devices"]');
  await page.click('[data-tab="proposal"]');
  await page.waitForSelector(".candidate", { timeout: 60000 });
  if (label === "desktop") {
    for (const kind of ["dc", "dc_series", "stepper", "bldc", "synrm", "induction"]) {
      await page.click('#rail [data-step="1"]');
      await page.waitForLoadState("networkidle");
      // Kinds that are unusual with the device sit one press away.
      await page.evaluate(() => document.querySelectorAll("details.other-kinds").forEach((d) => { d.open = true; }));
      await page.check(`[data-kind][value="${kind}"]`);
      await page.waitForTimeout(1800);
      await measure(page, `${label}-motor-${kind}`);
    }
  }
  await page.close();
}
await browser.close();
console.log(`measured ${visited.length} surfaces:\n  ${visited.join("\n  ")}`);
for (const e of errors) failures.push(`page error: ${e}`);
if (failures.length) {
  console.error(`\n${failures.length} failures:\n  ${failures.join("\n  ")}`);
  process.exit(1);
}
console.log("\nno failures");
