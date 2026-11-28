// Your own part, typed: from a cold first visit, "Your part", the figures a verdict needs typed
// into the compact table from the keyboard alone (Tab between boxes, the unit typed after the
// figure where the datasheet prints another prefix), Enter, and the final verdict. Times the
// path and counts every press, and holds it to the product's target: a person types it in
// three minutes or less. Needs `motionsim serve` running.
//   node scripts/typedpath.mjs [url]
/* global DataTransfer, ClipboardEvent */
// Exits 1 when the verdict is not reached, a box is refused, or the path is over its budget.
import { chromium } from "playwright";
import { KEYS, settled } from "./lib.mjs";

const url = process.argv[2] ?? "http://127.0.0.1:4310/";

/** A made-up 100 V MOSFET as its datasheet prints it, one figure a box, in the table's order.
 *  Two are written with a unit of their own: what a datasheet prints is copied, not converted. */
const FIGURES = [
  ["v_rated", "100"],
  ["i_rated", "60"],
  ["tj_max", "175"],
  ["rth_jc", "0.9"],
  ["rds_on", "0.0045 Ω"], // the box is in mΩ: the unit typed is read
  ["v_th", "3"],
  ["v_plateau", "5.2"],
  ["q_gs", "18"],
  ["q_gd", "12 nC"],
];

/** A person's pace, by the keystroke-level model (Card, Moran and Newell): a key 0.28 s, a
 *  mental step 1.35 s, and a look along the datasheet for each figure, 6 s. */
const KEY_S = 0.28;
const THINK_S = 1.35;
const LOOK_S = 6;
const HUMAN_BUDGET_S = 180;

const failed = [];
const hold = (ok, what) => {
  if (!ok) failed.push(what);
  console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
const faults = [];
page.on("pageerror", (e) => faults.push(e.message));
await page.goto(url);
await page.evaluate((keys) => keys.forEach((k) => localStorage.removeItem(k)), KEYS);
await page.reload();
await page.waitForSelector(".choice");
await settled(page);

// Paste across cells: a column copied from a spreadsheet, into the first box, fills the table
// down from it, one figure a box. Then the page is opened afresh for the typed path.
await page.locator("[data-your-part]").click();
await page.locator(".quick [data-typed]").first().focus();
await page.evaluate(
  (column) => {
    const data = new DataTransfer();
    data.setData("text/plain", column);
    document.activeElement.dispatchEvent(new ClipboardEvent("paste", { clipboardData: data, bubbles: true }));
  },
  FIGURES.map(([, text]) => text).join("\n"),
);
const filled = await page.$$eval(".quick [data-typed]", (els) => els.map((e) => e.value));
hold(
  FIGURES.every(([, text], k) => filled[k] === text),
  `a pasted column fills the ${FIGURES.length} boxes in turn (${filled.join(" | ")})`,
);
// The boxes are emptied as a person would, so the timed path starts from an empty table: the
// page keeps what was typed across a reload.
for (const box of await page.$$(".quick [data-typed]")) await box.fill("");
await page.evaluate((keys) => keys.forEach((k) => localStorage.removeItem(k)), KEYS);
await page.reload();
await page.waitForSelector(".choice");
await settled(page);

let presses = 0;
let keys = 0;
const t0 = Date.now();
await page.locator("[data-your-part]").click();
presses++;
// One press into the first box; from there the keyboard alone.
await page.locator(".quick [data-typed]").first().click();
presses++;
const order = await page.$$eval(".quick [data-typed]", (els) => els.map((e) => e.dataset.typed));
hold(order.length === FIGURES.length, `the table asks for ${order.length} figures (expected ${FIGURES.length})`);
for (const [i, [key, text]] of FIGURES.entries()) {
  const at = await page.evaluate(() => document.activeElement?.dataset?.typed ?? "");
  hold(at === key, `Tab reaches ${key} in turn (at ${at || "nothing"})`);
  await page.keyboard.type(text);
  keys += text.length;
  if (i < FIGURES.length - 1) {
    await page.keyboard.press("Tab");
    keys++;
  }
}
await page.keyboard.press("Enter");
keys++;
await page.waitForFunction(
  () => {
    const v = document.querySelector("#panel .verdict-line");
    return v && !v.classList.contains("working") && !document.body.hasAttribute("data-pending");
  },
  null,
  { timeout: 120000, polling: 50 },
);
const scripted = (Date.now() - t0) / 1000;
const verdict = await page.evaluate(() => document.querySelector("#panel .verdict-line")?.textContent?.trim() ?? "");
const wrong = await page.$$eval("[aria-invalid=true]", (els) => els.length);
hold(!wrong, "no box refused");
hold(!!verdict, `a final verdict: ${verdict}`);

// A person: a look and a thought per figure, every key, every press, plus the wait the script saw.
const human = FIGURES.length * (LOOK_S + THINK_S) + (keys + presses) * KEY_S + scripted;
hold(human <= HUMAN_BUDGET_S, `a person in about ${Math.round(human)} s (budget ${HUMAN_BUDGET_S} s)`);
hold(!faults.length, `no page errors${faults.length ? `: ${faults.join("; ")}` : ""}`);
console.log(
  JSON.stringify({ fields: FIGURES.length, presses, keys, scriptedSeconds: scripted, humanSeconds: Math.round(human) }),
);
await browser.close();
process.exit(failed.length ? 1 : 0);
