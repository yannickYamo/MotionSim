// One fixed journey through the page as it is hosted: the built files served as plain files,
// the engine running in the browser. A first visit, a made-up part, every step to a verdict,
// one setting changed, a reload, and the same at a phone's width. The tour (measure.mjs) and
// the walk (walk.mjs) are held against the local page; this is the check of the hosted one.
//   node scripts/journey.mjs [url]     with no url, the built page is served from here
import { chromium } from "playwright";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../src/motionsim/webui/", import.meta.url));
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".zip": "application/zip", ".json": "application/json", ".woff2": "font/woff2" };
let server = null;
let url = process.argv[2];
if (!url) {
  server = createServer(async (req, res) => {
    const path = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname)).replace(/^(\.\.[/\\])+/, "");
    try {
      const body = await readFile(join(root, path === "/" || path === "\\" ? "index.html" : path));
      res.writeHead(200, { "content-type": types[extname(path)] ?? (path.length <= 1 ? "text/html" : "application/octet-stream") });
      res.end(body);
    } catch { res.writeHead(404); res.end(); }
  });
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  url = `http://127.0.0.1:${server.address().port}/`;
}

const failed = [];
const hold = (ok, what) => { if (!ok) failed.push(what); console.log(`${ok ? "ok  " : "FAIL"} ${what}`); };
const browser = await chromium.launch();
// One context for both widths, so the browser's engine is fetched once and kept.
const context = await browser.newContext({ reducedMotion: "reduce" });

async function journey(width, height) {
  const at = `${width} px`;
  const page = await context.newPage();
  await page.setViewportSize({ width, height });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const text = (selector) => page.evaluate((s) => document.querySelector(s)?.textContent?.replace(/\s+/g, " ").trim() ?? "", selector);
  const settled = async () => {
    await page.waitForFunction(() => !document.querySelector("#readouts")?.textContent?.includes("Starting the engine"), null, { timeout: 240000 });
    await page.waitForFunction(() => /Power-stage loss/.test(document.querySelector("#readouts")?.textContent ?? ""), null, { timeout: 240000 });
    await page.waitForFunction(() => !document.body.dataset.busy && !document.querySelector(".waiting"), null, { timeout: 240000 });
  };
  const fits = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

  await page.goto(url, { waitUntil: "load" });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: "load" });
  await page.waitForSelector("#panel h2");
  // A first visit is offered what a newcomer can do at once, before any file is asked for.
  await page.waitForSelector("#panel [data-example]", { timeout: 240000 });
  const first = await page.evaluate(() => [...document.querySelectorAll("#panel .path > h3")].map((h) => h.textContent));
  hold(first.length === 3 && /See what it does/.test(first[0]), `${at}: a first visit is offered three ways to bring a part, the made-up one first`);
  hold(await text("#readouts").then((t) => /Start here/.test(t) && !/Power-stage loss/.test(t)), `${at}: nothing is worked out before a part is chosen`);
  hold(await fits(), `${at}: the first step fits the width`);

  await page.click('#panel [data-example*="mosfet"]');
  await page.waitForSelector("#panel .devices .device.is-on", { timeout: 240000 });
  for (const k of [1, 2, 3, 4]) {
    await page.click(`#panel .actions [data-step="${k}"]`);
    await page.waitForFunction((n) => document.querySelector("#rail [aria-current=step]")?.getAttribute("data-step") === String(n), k, { timeout: 60000 });
  }
  await settled();
  await page.waitForSelector("#panel .verdict", { timeout: 240000 });
  const verdict = await text("#panel .verdict");
  // The made-up part on its own starting design is one the tool passes: any other word is a change to look at.
  hold(/^Passes$/.test(verdict), `${at}: the made-up part passes on its starting design ("${verdict}")`);
  const loss = await text("#readouts");
  hold(/Power-stage loss\s*[\d.]+ ?W/.test(loss), `${at}: a loss is shown`);
  hold(await fits(), `${at}: the results fit the width`);
  // On a narrow screen the verdict's word is in the first screenful, not below the drawing.
  if (width <= 900) {
    const top = await page.evaluate(() => { window.scrollTo(0, 0); const r = document.querySelector("#verdict-strip .verdict")?.getBoundingClientRect(); return r && r.width > 0 ? r.bottom : null; });
    hold(top !== null && top < height, `${at}: the verdict is said in the first screenful`);
    await page.click("#verdict-strip a");
    const reached = await page.waitForFunction((half) => document.querySelector("#panel").getBoundingClientRect().top < half, height / 2, { timeout: 5000 }).then(() => true, () => false);
    hold(reached, `${at}: its link goes down to the reasons`);
  } else {
    hold(await page.evaluate(() => getComputedStyle(document.querySelector("#verdict-strip")).display === "none"), `${at}: the verdict is not said twice on a wide screen`);
  }

  // One setting changed: the answer follows it.
  await page.click('#rail [data-step="2"]');
  await page.fill('[data-bind="conditions.f_khz"]', "40");
  await page.dispatchEvent('[data-bind="conditions.f_khz"]', "change");
  await page.click('#rail [data-step="4"]');
  await page.waitForFunction((was) => { const now = document.querySelector("#readouts")?.textContent?.replace(/\s+/g, " ").trim(); return /Power-stage loss/.test(now ?? "") && now !== was; }, loss, { timeout: 240000 });
  await settled();
  const changed = await text("#readouts");
  const watts = (said) => Number(/Power-stage loss\s*([\d.]+) ?W/.exec(said)?.[1]);
  hold(watts(changed) > watts(loss), `${at}: a higher switching frequency loses more (${watts(loss)} W, then ${watts(changed)} W)`);

  // A reload brings back what was there, once the engine has started again.
  await page.reload({ waitUntil: "load" });
  await settled();
  hold((await text("#readouts")) === changed, `${at}: a reload shows the same result`);
  hold(errors.length === 0, `${at}: no page error${errors.length ? `: ${errors[0]}` : ""}`);
  await page.close();
}

try {
  await journey(1280, 900);
  await journey(390, 800);
} catch (e) {
  hold(false, `the journey stopped: ${String(e.message ?? e).split("\n")[0]}`);
} finally {
  await browser.close();
  server?.close();
}
if (failed.length) { console.error(`\n${failed.length} failed`); process.exit(1); }
console.log("\nthe hosted journey holds");
