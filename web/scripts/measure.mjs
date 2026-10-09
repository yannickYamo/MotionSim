// Measures the built page against the design laws that can be measured, on every step and
// tab, at desktop, laptop and phone widths. Needs `motionsim serve` running.
//   node scripts/measure.mjs [url] [screenshot-folder]
// Exits 1 on any failure. A surface that did not render is a failure, not a pass.
import { chromium } from "playwright";

const url = process.argv[2] ?? "http://127.0.0.1:4310/";
const shots = process.argv[3];
const failures = [];
const visited = [];

function luminance([r, g, b]) {
  const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

async function measure(page, name) {
  // Everything is measured from the top: the page and every pane that scrolls inside it.
  await page.evaluate(() => { scrollTo(0, 0); for (const el of document.querySelectorAll("*")) if (el.scrollTop) el.scrollTop = 0; });
  const report = await page.evaluate(() => {
    // Shown to the user: not hidden, not transparent, not inside a closed disclosure.
    // With a dialog open over the page, only the dialog is in front of the user.
    const modal = document.querySelector("dialog[open]");
    const visible = (el) => { if (modal && !modal.contains(el)) return false; const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true, contentVisibilityAuto: true }); };
    // The bar that holds Back and Next stays put while the form scrolls under it, by design.
    // So does the bar across the top once the page has scrolled.
    const pinned = (node) => !!(node.nodeType === 1 ? node : node.parentElement).closest(".actions, .skip, header.top");
    const rgb = (text) => (text.match(/[\d.]+/g) ?? []).map(Number);
    const ground = (el) => { for (let n = el; n; n = n.parentElement) { const c = rgb(getComputedStyle(n).backgroundColor); if (c.length >= 3 && (c[3] ?? 1) > 0.5) return c.slice(0, 3); } return [20, 19, 16]; };
    // The skip link is one pixel until it takes focus, by design; it is sized when shown.
    const targets = [...document.querySelectorAll("button, a[href]:not(.skip), input, select, summary, label.kind, label.drop, label.add-part, .device label")].filter(visible);
    const small = targets
      .map((el) => { const r = el.getBoundingClientRect(); return { tag: el.tagName, text: (el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 30), w: Math.round(r.width), h: Math.round(r.height), type: el.type }; })
      // A radio or checkbox is pressed through its label, which is measured in its own right.
      .filter((t) => (t.w < 24 || t.h < 24) && !(t.tag === "INPUT" && ["radio", "checkbox", "file"].includes(t.type)));
    const texts = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const el = n.parentElement;
      if (!n.textContent.trim() || !visible(el) || el.closest("svg, .sr, option")) continue;
      const style = getComputedStyle(el);
      if (el.closest("button:disabled")) continue;
      texts.push({ text: n.textContent.trim().slice(0, 40), color: rgb(style.color).slice(0, 3), ground: ground(el), size: parseFloat(style.fontSize), weight: Number(style.fontWeight) });
    }
    // Text inside a drawing scales with the drawing, so its size on screen has to be measured.
    const drawn = [...document.querySelectorAll("svg text")].filter(visible)
      .map((el) => ({ text: el.textContent.trim().slice(0, 30), px: parseFloat(getComputedStyle(el).fontSize) * (el.ownerSVGElement.getBoundingClientRect().width / el.ownerSVGElement.viewBox.baseVal.width) }))
      .filter((t) => t.text && t.px < 9.5);
    const unnamed = [...document.querySelectorAll("button")].filter(visible)
      .filter((el) => !(el.getAttribute("aria-label") || el.textContent).trim()).length;
    const doc = document.documentElement;
    // Placement: no two pieces of text on top of each other, no text cut off by its box,
    // no two controls sharing ground, nothing above the top of the page.
    const boxes = [];
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      const el = n.parentElement;
      if (!n.textContent.trim() || !visible(el) || el.closest(".sr, option, svg, .skip")) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      for (const r of range.getClientRects()) if (r.width > 1 && r.height > 1) boxes.push({ id: boxes.length, node: n, text: n.textContent.trim().slice(0, 28), l: r.left, t: r.top, r: r.right, b: r.bottom });
    }
    for (const el of document.querySelectorAll("svg text")) {
      // A drawing that cannot run is dimmed under its notice; the notice is what is read.
      if (!visible(el) || !el.textContent.trim() || (el.closest(".is-blocked") && !el.closest(".blocked"))) continue;
      const r = el.getBoundingClientRect();
      boxes.push({ node: el, text: el.textContent.trim().slice(0, 28), l: r.left, t: r.top, r: r.right, b: r.bottom });
    }
    // A pill or chip is one box: it must not wrap over a line or sit on other text.
    for (const el of document.querySelectorAll(".tag, .chip")) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      boxes.push({ node: el, own: el, text: `[${el.textContent.trim().slice(0, 24)}]`, l: r.left, t: r.top, r: r.right, b: r.bottom });
    }
    // Text stays inside the box drawn round it: a pill, a chip, a button.
    const spilled = [];
    for (const el of document.querySelectorAll(".tag, .chip, button")) {
      if (!visible(el)) continue;
      const box = el.getBoundingClientRect();
      const range = document.createRange();
      range.selectNodeContents(el);
      for (const r of range.getClientRects()) {
        // Inside it, and for a bordered pill not hard against its sides either.
        const edge = el.matches(".tag, .chip") ? 3 : -1;
        if (r.width > 1 && (r.left < box.left + edge || r.right > box.right - edge || r.top < box.top - 1 || r.bottom > box.bottom + 1)) { spilled.push(el.textContent.trim().slice(0, 28)); break; }
      }
    }
    const overlaps = [];
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      if (a.node === b.node || pinned(a.node) !== pinned(b.node)) continue;
      if ((a.own && a.own.contains(b.node)) || (b.own && b.own.contains(a.node))) continue;
      const w = Math.min(a.r, b.r) - Math.max(a.l, b.l), h = Math.min(a.b, b.b) - Math.max(a.t, b.t);
      if (w > 3 && h > 5) overlaps.push(`"${a.text}" over "${b.text}"`);
    }
    const clipped = [...document.querySelectorAll("#app *")].filter(visible)
      .filter((el) => el.children.length === 0 && !el.closest(".sr") && el.textContent.trim() && getComputedStyle(el).overflowX !== "visible" && el.scrollWidth > el.clientWidth + 1)
      .map((el) => el.textContent.trim().slice(0, 28));
    const hit = targets.filter((el) => !(el.tagName === "INPUT" && ["radio", "checkbox", "file"].includes(el.type))).map((el) => ({ el, r: el.getBoundingClientRect() }));
    const stacked = [];
    for (let i = 0; i < hit.length; i++) for (let j = i + 1; j < hit.length; j++) {
      const a = hit[i], b = hit[j];
      if (a.el.contains(b.el) || b.el.contains(a.el) || pinned(a.el) !== pinned(b.el)) continue;
      const w = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left), h = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
      if (w > 2 && h > 2) stacked.push(`${a.el.tagName} "${(a.el.textContent || "").trim().slice(0, 20)}" and ${b.el.tagName} "${(b.el.textContent || "").trim().slice(0, 20)}"`);
    }
    const above = [...document.querySelectorAll("#app *")].filter(visible).filter((el) => scrollY === 0 && el.getBoundingClientRect().bottom < 0 && !el.closest(".skip")).length;
    return { small, texts, drawn, unnamed, targets: targets.length, overflow: doc.scrollWidth - innerWidth, overlaps: [...new Set(overlaps)], spilled: [...new Set(spilled)], clipped: [...new Set(clipped)], stacked: [...new Set(stacked)], above };
  });
  visited.push(`${name} (${report.targets} targets, ${report.texts.length} texts)`);
  if (report.targets === 0 || report.texts.length < 5) failures.push(`${name}: the page did not render (${report.targets} targets)`);
  if (report.overflow > 0) failures.push(`${name}: horizontal overflow of ${report.overflow}px`);
  if (report.unnamed) failures.push(`${name}: ${report.unnamed} buttons with no accessible name`);
  if (report.drawn.length) failures.push(`${name}: ${report.drawn.length} drawing labels under 9.5px, smallest ${Math.min(...report.drawn.map((t) => t.px)).toFixed(1)}px ("${report.drawn[0].text}")`);
  for (const o of report.overlaps.slice(0, 6)) failures.push(`${name}: text on top of text: ${o}`);
  for (const c of report.spilled.slice(0, 6)) failures.push(`${name}: text spills out of its box or touches its sides: "${c}"`);
  for (const c of report.clipped.slice(0, 6)) failures.push(`${name}: text cut off by its box: "${c}"`);
  for (const o of report.stacked.slice(0, 6)) failures.push(`${name}: two controls share ground: ${o}`);
  if (report.above) failures.push(`${name}: ${report.above} elements above the top of the page, out of reach`);
  for (const t of report.small) failures.push(`${name}: target under 24px: ${t.tag} "${t.text}" ${t.w}x${t.h}`);
  const seen = new Set();
  for (const t of report.texts) {
    const a = luminance(t.color);
    const b = luminance(t.ground);
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const need = t.size >= 24 || (t.size >= 18.66 && t.weight >= 700) ? 3 : 4.5;
    const key = `${t.color}|${t.ground}`;
    if (ratio < need && !seen.has(key)) {
      seen.add(key);
      failures.push(`${name}: contrast ${ratio.toFixed(2)} (needs ${need}) "${t.text}" rgb(${t.color}) on rgb(${t.ground})`);
    }
  }
  await page.evaluate(() => scrollTo(0, 0));
  if (shots) await page.screenshot({ path: `${shots}/${name}.png`, fullPage: page.viewportSize().width < 900 });
}

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
const browser = await chromium.launch();
const errors = [];
for (const [label, width, height] of [["desktop", 1440, 900], ["laptop", 1100, 760], ["mobile", 390, 844]]) {
  const page = await browser.newPage({ viewport: { width, height }, reducedMotion: "reduce" });
  page.on("pageerror", (e) => errors.push(`${label}: ${e.message}`));
  await page.goto(url, { waitUntil: "networkidle" });
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
  await page.click('#panel .actions [data-step="2"]');
  await page.waitForTimeout(800);
  await measure(page, `${label}-3-supply`);
  await page.fill('[data-bind="conditions.rpm"]', "30000");
  await page.waitForSelector(".refusal");
  await measure(page, `${label}-3-refused`);
  await page.fill('[data-bind="conditions.rpm"]', "2000");
  await page.waitForSelector(".schematic.is-live");
  await page.click('#panel .actions [data-step="3"]');
  await page.waitForTimeout(1500);
  await measure(page, `${label}-4-load`);
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
    await page.waitForFunction(() => /3,000 rpm/.test(document.querySelector("#motion-preview .fact")?.textContent ?? ""), null, { timeout: 30000 }).catch(() => {});
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
  for (const tab of ["losses", "motion", "map", "settings"]) {
    await page.click(`[data-tab="${tab}"]`);
    await page.waitForFunction(() => !document.querySelector(".waiting"), null, { timeout: 90000 });
    await page.waitForTimeout(300);
    await measure(page, `${label}-5-${tab}`);
  }
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
  if ((await page.$$("#compare-table td.best")).length !== 1) failures.push(`${label}: exactly one device should be marked lowest loss`);
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
  await page.waitForFunction(() => { const cells = [...document.querySelectorAll("#compare-table tbody tr:first-child td")]; return cells.length === 2 && cells.every((c) => /W/.test(c.textContent)); }, null, { timeout: 120000 });
  await page.click('[data-tab="motion"]');
  await page.waitForFunction(() => !document.querySelector(".waiting"), null, { timeout: 120000 });
  await measure(page, `${label}-7-loads`);
  if (!(await page.$(".series.s1"))) failures.push(`${label}: the two loads are not drawn on one chart`);
  await page.click("[data-drop-load]");
  await page.click('[data-compare="devices"]');
  await page.click('[data-tab="proposal"]');
  await page.waitForSelector(".candidate", { timeout: 60000 });
  if (label === "desktop") {
    for (const kind of ["dc", "dc_series", "stepper", "bldc", "synrm", "induction"]) {
      await page.click('#rail [data-step="1"]');
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
