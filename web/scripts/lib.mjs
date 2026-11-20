// What the scripts that drive the page share: opening it afresh, waiting until it has
// settled, and two parts that differ enough to be told apart at a glance.
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** The keys the page keeps in the browser. Only these are cleared, as the page itself does. */
export const KEYS = ["motionsim.bench.v11", "motionsim.devices.v1"];

/**
 * Two device files of different kinds: a 100 V part and a 600 V part, under names that
 * cannot be taken for each other. A result shown under the wrong one cannot pass for right.
 */
export function twoParts() {
  const folder = mkdtempSync(join(tmpdir(), "motionsim-parts-"));
  const made = (file, vendor, part) => {
    const text = readFileSync(new URL(`../../examples/${file}`, import.meta.url), "utf8")
      .replace(/^vendor:.*$/m, `vendor: ${vendor}`)
      .replace(/^part_number:.*$/m, `part_number: ${part}`);
    const path = join(folder, `${part.toLowerCase()}.device.yaml`);
    writeFileSync(path, text);
    return { path, name: `${vendor} ${part}`, id: part.toLowerCase() };
  };
  return {
    low: made("synthetic_mosfet_100v_100a.yaml", "Alfa", "LV-100"),
    high: made("synthetic_igbt_600v_30a.yaml", "Bravo", "HV-600"),
  };
}

/** The page has nothing on its way: no answer awaited, no figure marked as waiting for one. */
export const settled = (page, timeout = 240000) =>
  page.waitForFunction(
    () =>
      !document.body.dataset.busy &&
      !document.body.hasAttribute("data-stale") &&
      !document.querySelector(".waiting") &&
      !document.querySelector("#readouts")?.textContent?.includes("Starting the engine"),
    null,
    { timeout },
  );

/** Open the page as on a first visit, and wait for its engine. */
export async function fresh(browser, url, viewport = { width: 1280, height: 900 }) {
  const page = await browser.newPage({ viewport, reducedMotion: "reduce" });
  page.faults = [];
  page.on("pageerror", (e) => page.faults.push(e.message));
  await page.goto(url);
  await page.evaluate((keys) => keys.forEach((k) => localStorage.removeItem(k)), KEYS);
  await page.reload();
  await page.waitForSelector("#panel h2");
  await settled(page);
  return page;
}

/** What the page holds for the inputs, as it keeps it. */
export const kept = (page) => page.evaluate((key) => JSON.parse(localStorage.getItem(key) ?? "{}"), KEYS[0]);

/** Go to a step by the rail, and wait until it is the open one. */
export async function toStep(page, k) {
  await page.click(`#rail [data-step="${k}"]`);
  await page.waitForFunction((n) => document.body.dataset.at === String(n), k);
}

/** Walk the steps in order by the button at the foot of each, to the results. */
export async function walkToResults(page) {
  for (const k of [1, 2, 3, 4]) {
    await page.click(`#panel .actions [data-step="${k}"]`);
    await page.waitForFunction((n) => document.body.dataset.at === String(n), k);
  }
  await settled(page);
}

/** Everything the results say, as text: the figures, the table and the open tab. */
export const shown = (page) =>
  page.evaluate(() =>
    ["#readouts", "#compare-table", "#tab-body"]
      .map((s) => document.querySelector(s)?.textContent?.replace(/\s+/g, " ").trim() ?? "")
      .join(" | "),
  );
