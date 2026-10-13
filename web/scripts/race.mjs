// Chooses another device while a slow answer for the first is still on its way, at several
// delays, on the tabs that take longest, and holds the page to what it shows after a reload:
// an answer for the device that was on the drawing must never be shown under the other.
//   node scripts/race.mjs [url]
const url = process.argv[2] ?? "http://127.0.0.1:4310/";
import { chromium } from "playwright";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os"; import { join } from "node:path";
const made = readFileSync(new URL("../../examples/synthetic_igbt_600v_30a.yaml", import.meta.url), "utf8");
const dir = mkdtempSync(join(tmpdir(), "ms-"));
const files = [["Alfa", "A-150", 150], ["Bravo", "B-125", 125]].map(([v, n, t]) => { const f = join(dir, `${n.toLowerCase()}.device.yaml`); writeFileSync(f, made.replace(/^vendor:.*$/m, `vendor: ${v}`).replace(/^part_number:.*$/m, `part_number: ${n}`).replace(/tj_max: .*/, `tj_max: ${t}`)); return f; });
const b = await chromium.launch();
let bad = 0;
for (const gap of (process.env.GAPS ?? "0,60,300,900").split(",").map(Number)) for (const tab of ["settings", "motion", "capability"]) {
  const page = await b.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  await page.goto(url); await page.evaluate(() => localStorage.clear()); await page.reload(); await page.waitForSelector("#panel h2");
  // Where the engine runs in the page it has to start first, which takes a while.
  await page.waitForFunction(() => !document.querySelector("#readouts")?.textContent?.includes("Starting the engine"), null, { timeout: 240000 });
  await page.setInputFiles("#part-file", files[0]); await page.waitForFunction(() => JSON.parse(localStorage.getItem("motionsim.bench.v10") ?? "{}").devices?.length === 1, null, { timeout: 120000 });
  for (const k of [1, 2, 3, 4]) { await page.click(`#panel .actions [data-step="${k}"]`); await page.waitForTimeout(400); }
  await page.waitForSelector(".candidate", { timeout: 240000 });
  await page.setInputFiles("[data-part-file]", files[1]); await page.waitForSelector("#compare-table table", { timeout: 240000 });
  const settle = async () => { await page.waitForTimeout(400); await page.waitForFunction(() => !document.body.dataset.busy && !document.querySelector(".waiting") && ![...document.querySelectorAll("#compare-table td")].some((c) => c.textContent === "…"), null, { timeout: 120000 }); };
  await page.click('[data-compare="sweep"]'); await settle();
  await page.click('#switcher [data-focus="a-150"]'); await settle();
  await page.click(`[data-tab="${tab}"]`); await page.waitForTimeout(gap);
  await page.click('#switcher [data-focus="b-125"]'); await settle(); await page.waitForTimeout(600); await settle();
  const text = await page.evaluate(() => document.querySelector("#tab-body").textContent + document.querySelector("#compare-table").textContent);
  const wrong = /150 °C rating|Alfa A-150/.test(text.replace(/Alfa A-150(?= through| can|,)/g, "X"));
  const before = await page.evaluate(() => ["#compare-table", "#tab-body"].map((s) => document.querySelector(s).textContent.replace(/\s+/g, " ")).join("|"));
  await page.reload(); await page.waitForSelector("#panel h2"); await page.waitForFunction(() => !document.querySelector("#readouts")?.textContent?.includes("Starting the engine"), null, { timeout: 240000 }); await page.waitForTimeout(1500); await settle();
  const after = await page.evaluate(() => ["#compare-table", "#tab-body"].map((s) => document.querySelector(s).textContent.replace(/\s+/g, " ")).join("|"));
  if (before !== after) { bad++; let k = 0; while (before[k] === after[k]) k++; console.log(`gap ${gap} tab ${tab}: DIFFERS after reload: "${before.slice(k - 50, k + 70)}" -> "${after.slice(k - 50, k + 70)}"`); } else console.log(`gap ${gap} tab ${tab}: same after reload${wrong ? " (mentions 150)" : ""}`);
  await page.close();
}
await b.close();
if (bad) { console.error(`${bad} differences`); process.exit(1); }
console.log("no failures");
