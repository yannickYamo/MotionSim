// Holds the page to its answers when things happen in an awkward order. Three families:
//  - a second device is added and the user jumps to the results before the page has
//    caught up; while it catches up no verdict of the inputs before is shown, the part
//    added moves nothing of the design, and what is then shown is what a reload shows and
//    what the same first part gives whenever the jump comes;
//  - the engine fails on a change: no figure worked out before the change may stay on
//    screen as if it answered, and the next answer that does arrive must be shown;
//  - another device is put on the drawing while a slow answer for the first is on its
//    way: an answer for the one must never be shown under the other;
//  - the comparison's + Add: a device, a load, the motor with a change and a setting at
//    several values, each a column with its own answer; a column taken out and put back.
//  - the search for the largest load is cancelled partway: the probes finished so far are
//    on the page as they come, Cancel gives the button back at once, and the search itself
//    stops (in the browser, the engine says it stopped and posts no probe after; on a local
//    server, the stream is closed) so that the engine is free for the next question;
//  - an IGBT is typed in with its knees and cold energies left empty, while the engine may
//    still be starting: it is built, the verdict holds at a caution naming each figure taken,
//    and the way back to a box brings the figures typed back with the keyboard in the box;
//  - a heatsink in air is chosen with its box left empty, and the offer taken at once: the
//    box holds the figure offered, marked sized, the verdict says so, and an edit undoes it.
//  - the switching event is opened from a spike of the loss chart: it is drawn with that edge
//    marked and the keyboard on it, zooms and moves from the wheel, a drag and the keys, a
//    figure typed while it is being worked out is in the answer shown, and the other device
//    put on the drawing while it is being worked out gets its own event, never the first's;
//    on a phone the two edges stand one above the other and the page does not scroll sideways;
//  - a plot of the event is pressed: it opens full screen at its zoom, zooms there, is saved
//    as a PDF named for it, and Escape gives the keyboard back to it at the zoom reached;
//  - the edge limit is raised from the event's line, which opens its fold on step 3: the event
//    and the figures follow it.
//  - the washing machine is chosen with the motor such products have: the Motion tab shows its
//    wash, rinses and spin in minutes, and marks the start-up's junction peak.
// Run against `motionsim serve` or the built page served as files:
//   node scripts/race.mjs [url]
import { chromium } from "playwright";
import { fresh, kept, settled, shown, toStep, twoParts, walkToResults } from "./lib.mjs";

const url = process.argv[2] ?? "http://127.0.0.1:4310/";
const { low, high } = twoParts();
const browser = await chromium.launch();
const failed = [];
const hold = (ok, what) => {
  if (!ok) failed.push(what);
  console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
};
const point = (state) => JSON.stringify([state.kind, state.conditions, state.motors?.[state.kind]]);
const type = async (page, path, text) => {
  await page.fill(`[data-bind="${path}"]`, text);
};
// The part is waited for by what the page shows, not by a clock: in the browser the engine
// builds it while it is still busy with what came before, which can take minutes on a slow
// machine. A refusal ends the wait at once, with its words.
const bring = async (page, part) => {
  // A first visit offers the file box behind "Your part".
  if (!(await page.locator("#part-file, [data-part-file]").count())) await page.click("#panel [data-your-part]");
  await page.setInputFiles("#part-file, [data-part-file]", part.path);
  const handle = await page.waitForFunction(
    (id) =>
      document.querySelector(`[data-device="${id}"], [data-drop-device="${id}"]`)
        ? "in"
        : (document.querySelector("#panel .refusal")?.textContent ?? ""),
    part.id,
    { timeout: 300000 },
  );
  const got = await handle.jsonValue();
  if (got !== "in") throw new Error(`${part.name} was not added: ${got}`);
};

/** No verdict and no figure of an answer stand on the page while the answer for the inputs
 *  as they are is on its way: either the page holds the answer for what it shows, or it
 *  says it is working one out. */
const noOldVerdict = (page) =>
  page.evaluate(() => {
    if (!document.body.hasAttribute("data-pending")) return true;
    const text = ["#verdict-strip", "#readouts", "#compare-table", "#switcher", "#tab-body", "#announce"]
      .map((s) => document.querySelector(s)?.textContent ?? "")
      .join(" ");
    return !/Passes|Fails|Cautions|Undecided|Ruled out|\d W\b|\d °C/.test(text);
  });

/** One part, a speed typed, then the other part brought on the first step and the results
 *  opened `gap` ms later, before the page has had the time to follow. While the page is
 *  catching up, at 100 and 300 ms after the jump, it shows no verdict of the inputs before. */
async function addThenJump(first, second, gap) {
  const page = await fresh(browser, url);
  await bring(page, first);
  await walkToResults(page);
  await toStep(page, 2);
  await type(page, "conditions.rpm", "1500");
  await settled(page);
  page.before = point(await kept(page));
  await toStep(page, 0);
  await page.setInputFiles("#part-file, [data-part-file]", second.path);
  await page.waitForTimeout(gap); // the race itself: how long after the file the jump comes
  await toStep(page, 4);
  const jumped = Date.now();
  for (const after of [100, 300]) {
    await page.waitForTimeout(Math.max(0, jumped + after - Date.now()));
    hold(
      await noOldVerdict(page),
      `${first.name} then ${second.name}, ${gap} ms: no earlier verdict ${after} ms after the jump`,
    );
  }
  await page.waitForFunction(
    (n) => document.querySelectorAll("#compare-table th[data-col], .candidate").length >= n,
    2,
    {
      timeout: 240000,
    },
  );
  await settled(page);
  return page;
}

async function addDeviceThenJump() {
  // The design follows the part it was started from; the one added is compared on it. So
  // for the same first part, whenever the jump comes, the inputs and the results are the same.
  const reference = new Map();
  for (const [first, second] of [
    [low, high],
    [high, low],
  ]) {
    for (const gap of [0, 40, 400]) {
      const how = `${first.name} then ${second.name}, results after ${gap} ms`;
      const page = await addThenJump(first, second, gap);
      const state = await kept(page);
      hold(state.conditions.rpm === 1500, `${how}: the speed that was typed is still 1500`);
      hold(point(state) === page.before, `${how}: the part added to compare moved nothing of the design`);
      const now = await shown(page);
      await page.reload();
      await page.waitForSelector("#panel h2");
      await settled(page);
      hold((await shown(page)) === now, `${how}: the results are what a reload shows`);
      hold(point(await kept(page)) === point(state), `${how}: the inputs are what a reload keeps`);
      const same = reference.get(first.name);
      if (!same) reference.set(first.name, { now, inputs: point(state), how });
      else {
        hold(point(state) === same.inputs, `${how}: the same inputs as ${same.how}`);
        hold(now === same.now, `${how}: the same results as ${same.how}`);
      }
      hold(page.faults.length === 0, `${how}: no page error${page.faults[0] ? `: ${page.faults[0]}` : ""}`);
      await page.close();
    }
  }
}

/** Every loss figure the page shows while the engine gives no answer: each block that holds
 *  one (the figures beside the drawing, the table of devices, the period drawing, the devices
 *  to put on the drawing) is dimmed, and the page says the figures are from before; the open
 *  tab holds none, and neither report can be written from them. */
const faultAudit = (page) =>
  page.evaluate(() => {
    const loss = /\d[\d.,\u202f\u00a0]*\s*k?W\b/;
    const blocks = ["readouts", "compare-table", "pwm", "switcher"].flatMap((id) => {
      const el = document.getElementById(id);
      const text = el?.textContent?.replace(/\s+/g, " ").trim() ?? "";
      if (!el || !text) return []; // absent
      return [{ id, dimmed: el.classList.contains("is-stale"), loss: loss.test(text) }];
    });
    const reports = [...document.querySelectorAll("[data-report], [data-report-md]")].map((b) => ({
      off: b.disabled,
      why: b.getAttribute("aria-describedby") === "fault" && !!document.getElementById("fault"),
    }));
    const said = document.querySelector("#fault")?.textContent ?? "";
    const readouts = document.getElementById("readouts")?.textContent ?? "";
    return {
      blocks,
      reports,
      tab: loss.test(document.getElementById("tab-body")?.textContent ?? ""),
      fromBefore: /from before/.test(said) && (!loss.test(readouts) || /from before/.test(readouts)),
    };
  });

/** The engine fails on a change. Only where the engine is behind a server: its answers can
 *  then be replaced on the way; the engine in the browser has no such way in. With one part
 *  the figures and the period drawing stand beside the drawing; with two, the table of
 *  devices and the devices to put on the drawing. */
async function failThenStale(parts) {
  const page = await fresh(browser, url);
  const server = await page.evaluate(() =>
    fetch("engine/mode.json")
      .then((r) => r.json())
      .then(
        (m) => m.server,
        () => true,
      ),
  );
  if (!server) return console.log("skip the engine failing on a change: the engine is in the browser here");
  const how = `${parts.length} ${parts.length === 1 ? "part" : "parts"}`;
  for (const part of parts) await bring(page, part);
  await walkToResults(page);
  const before = await shown(page);
  hold(/\d\s*k?W\b/.test(before), `${how}: a loss is shown before the engine fails`);
  let release;
  const slow = new Promise((done) => (release = done));
  await page.route("**/api/stage", async (route) => {
    await slow;
    await route.fulfill({ status: 500, contentType: "application/json", body: '{"error":"the engine fell over"}' });
  });
  await toStep(page, 2);
  await type(page, "conditions.f_khz", "35");
  await toStep(page, 4);
  await page.waitForSelector('#readouts[aria-busy="true"]', { state: "attached" });
  hold(true, `${how}: while the answer is on its way the figures are marked as waiting`);
  release();
  await settled(page);
  const audit = await faultAudit(page);
  const lossBlocks = audit.blocks.filter((b) => b.loss);
  for (const b of audit.blocks) hold(b.dimmed, `${how}: after the failure #${b.id} is shown only dimmed`);
  hold(!lossBlocks.length || audit.fromBefore, `${how}: the page says the figures shown are from before`);
  hold(!audit.tab, `${how}: the open tab shows no loss from before`);
  hold(audit.reports.length > 0 && audit.reports.every((r) => r.off), `${how}: neither report can be written`);
  hold(
    audit.reports.every((r) => r.why),
    `${how}: each report button points to the notice that says why`,
  );
  hold(
    (await page.locator("#panel .verdict, #verdict-strip .verdict").count()) === 0,
    `${how}: after the failure no verdict is shown`,
  );
  hold(/fell over/.test(await page.textContent("#panel")), `${how}: the failure is said, in the engine's words`);
  await page.unroute("**/api/stage");
  await toStep(page, 2);
  await type(page, "conditions.f_khz", "36");
  await toStep(page, 4);
  await settled(page);
  const after = await shown(page);
  hold(/\d\s*k?W\b/.test(after) && after !== before, `${how}: the next answer is shown, and is a new one`);
  const again = await faultAudit(page);
  hold(
    again.reports.every((r) => !r.off),
    `${how}: once it answers, the reports can be written again`,
  );
  await page.reload();
  await page.waitForSelector("#panel h2");
  await settled(page);
  hold((await shown(page)) === after, `${how}: and it is what a reload shows`);
  await page.close();
}

/** Another device on the drawing while a slow tab's answer for the first is on its way. */
async function swapWhileAsking() {
  for (const gap of (process.env.GAPS ?? "0,300").split(",").map(Number)) {
    for (const tab of ["limits", "motion"]) {
      const how = `the ${tab} tab, the other device ${gap} ms later`;
      const page = await fresh(browser, url);
      await bring(page, low);
      await bring(page, high);
      await walkToResults(page);
      await page.click(`#switcher [data-focus="${low.id}"]`);
      await settled(page);
      await page.click(`[data-tab="${tab}"]`);
      await page.waitForTimeout(gap); // the race itself
      await page.click(`#switcher [data-focus="${high.id}"]`);
      await settled(page);
      const body = await page.textContent("#tab-body");
      // The motions of both devices are drawn on one chart, each under its name: there the
      // other's name belongs. On the other tabs everything is of the device on the drawing.
      if (tab !== "motion") hold(!body.includes(low.name), `${how}: nothing of ${low.name} is left on the tab`);
      const now = await shown(page);
      await page.reload();
      await page.waitForSelector("#panel h2");
      await settled(page);
      hold((await shown(page)) === now, `${how}: the same after a reload`);
      await page.close();
    }
  }
}

/** The keys of the comparison's columns, once every column has its own answer. */
const columnsOnceWorked = async (page, n) => {
  await page.waitForFunction((k) => document.querySelectorAll("#compare-table th[data-col]").length === k, n, {
    timeout: 300000,
  });
  await settled(page);
  return page.$$eval("#compare-table th[data-col]", (h) => h.map((x) => x.dataset.col));
};

/** Every column of the table holds a loss figure of its own: none is left unworked. */
const everyColumnAnswered = (page) =>
  page.$$eval(
    "#compare-table tbody tr.loss td:not(.add-col)",
    (cells) => cells.length > 0 && cells.every((c) => /\d\s*k?W/.test(c.textContent)),
  );

/** An item of the + Add menu, chosen as a user does: the button, then the item. Where the
 *  item clears what is compared, the question is answered Yes. */
const fromAdd = async (page, item, clears) => {
  await page.click("#add-button");
  await page.click(`#add-menu ${item}`);
  if (!clears) return;
  await page.waitForSelector("#confirm");
  await page.click("[data-switch-yes]");
};

async function addEachKind() {
  const how = "the + Add menu";
  const page = await fresh(browser, url);
  await bring(page, low);
  await walkToResults(page);
  // Another device, through the dialog of the three ways to bring one.
  await fromAdd(page, '[data-adding="device"]', false);
  await page.waitForSelector("#device-dialog[open]");
  await bring(page, high);
  await page.click("#device-dialog .dialog-actions [data-dialog-close]");
  const devices = await columnsOnceWorked(page, 2);
  hold(devices.includes(high.id), `${how}: a device brought in the dialog is a column`);
  hold(await everyColumnAnswered(page), `${how}: each device has its own loss`);
  // Another load: a change of kind, asked first, and the devices but the design taken out.
  await fromAdd(page, '[data-adding="load"]:not([data-preset="own"])', true);
  const loads = await columnsOnceWorked(page, 2);
  hold((await kept(page)).compare === "loads", `${how}: a load is a column of loads`);
  hold(!loads.includes(high.id), `${how}: the device beside the design was taken out`);
  hold(await everyColumnAnswered(page), `${how}: each load has its own loss`);
  // Taken out, then put back.
  await page.click("#col-button-1");
  await page.click("#col-menu-1 [data-col-remove]");
  await page.waitForSelector("[data-undo-column]");
  hold((await kept(page)).loadSet.length === 0, `${how}: a load taken out is gone`);
  await page.click("[data-undo-column]");
  hold(JSON.stringify(await columnsOnceWorked(page, 2)) === JSON.stringify(loads), `${how}: Undo puts the load back`);
  // The motor with a change: the torque halved.
  await fromAdd(page, '[data-adding="motor"]', true);
  const torque = await page.inputValue('#variant-dialog [data-variant="point.torque"]');
  await page.fill('#variant-dialog [data-variant="point.torque"]', String(Number(torque) / 2));
  await page.click("#variant-dialog [data-variant-save]");
  await columnsOnceWorked(page, 2);
  const motors = await kept(page);
  hold(motors.compare === "motors" && motors.motorSet.length === 1, `${how}: the motor with a change is a column`);
  hold(motors.loadSet.length === 0, `${how}: the loads were taken out`);
  hold(await everyColumnAnswered(page), `${how}: the motor with a change has its own loss`);
  // A setting at several values.
  await fromAdd(page, '[data-adding="sweep"]', true);
  await page.fill('#variant-dialog [data-variant="sweep.values"]', "10; 20; 40");
  await page.click("#variant-dialog [data-variant-save]");
  await columnsOnceWorked(page, 3);
  hold((await kept(page)).compare === "sweep", `${how}: a setting at three values is three columns`);
  hold(await everyColumnAnswered(page), `${how}: each value has its own loss`);
  // The load margin is searched for after the figures are in: it is waited for both times.
  const marginFound = () =>
    page.waitForFunction(
      () => !/finding the load it carries/.test(document.querySelector("#tab-body")?.textContent ?? ""),
      null,
      {
        timeout: 300000,
      },
    );
  await marginFound();
  const now = await shown(page);
  await page.reload();
  await page.waitForSelector("#panel h2");
  await columnsOnceWorked(page, 3);
  await marginFound();
  hold((await shown(page)) === now, `${how}: the same after a reload`);
  hold(page.faults.length === 0, `${how}: no page error${page.faults[0] ? `: ${page.faults[0]}` : ""}`);
  await page.close();
}

/** Every message the engine in the browser posts to the page, as it arrives: recorded by the
 *  script, before the page loads, by listening on each worker the page starts. */
const RECORD_WORKER = () => {
  window.__fromEngine = [];
  const Real = window.Worker;
  window.Worker = class extends Real {
    constructor(...args) {
      super(...args);
      this.addEventListener("message", (e) => window.__fromEngine.push({ at: Date.now(), data: e.data }));
    }
  };
};

/** The largest load asked for, then cancelled after two probes. */
async function cancelLargest() {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
  await page.addInitScript(RECORD_WORKER);
  page.faults = [];
  page.on("pageerror", (e) => page.faults.push(e.message));
  await page.goto(url);
  await page.evaluate((keys) => keys.forEach((k) => localStorage.removeItem(k)), ["motionsim.bench.v11"]);
  await page.reload();
  await page.waitForSelector("#panel h2");
  await settled(page);
  await bring(page, low);
  await walkToResults(page);
  await page.click('[data-tab="limits"]');
  await settled(page);
  const inBrowser = await page.evaluate(() => window.__fromEngine.length > 0);
  await page.click("[data-largest]");
  const asked = Date.now();
  await page.waitForFunction(
    () => (document.querySelector("[data-largest-trail]")?.textContent?.match(/…/g) ?? []).length >= 2,
    null,
    { timeout: 300000 },
  );
  const twoProbes = Date.now() - asked;
  const trail = await page.textContent("[data-largest-trail]");
  hold(
    /^Tried 1× … /.test(trail.trim()),
    `the largest load: the first probe is on the page as it finishes (${trail.trim()})`,
  );
  hold(/(between|more than|under) [\d.]+×/.test(trail), "the largest load: the trail says where the answer lies");
  await page.click("[data-cancel-largest]");
  const cancelled = Date.now();
  await page.waitForSelector("[data-largest]", { timeout: 300 });
  hold(true, "the largest load: Cancel gives the button to ask back at once");
  hold(
    (await page.evaluate(() => document.activeElement?.hasAttribute("data-largest"))) === true,
    "the largest load: the focus is on the button to ask again",
  );
  hold(/Stopped looking/.test((await page.textContent("#announce")) ?? ""), "the largest load: the stop is said");
  if (inBrowser) {
    // The engine stops before its next probe: it says so within about a probe's time, and
    // posts no probe after that. A search left running would post a dozen more.
    await page.waitForTimeout(Math.min(4 * twoProbes, 120000));
    const after = await page.evaluate((t) => window.__fromEngine.filter((m) => m.at > t).map((m) => m.data), cancelled);
    const stop = after.findIndex((m) => m.status === 499);
    hold(stop >= 0, "the largest load: the engine in the browser says the search stopped");
    hold(
      stop >= 0 && after.slice(stop + 1).every((m) => !("probe" in m)) && after.filter((m) => "probe" in m).length <= 1,
      `the largest load: the engine posts no probe once it has stopped (${after.filter((m) => "probe" in m).length} after Cancel)`,
    );
  }
  // The engine is free: the next question is answered, and a search asked again runs to its end.
  await page.click("[data-largest]");
  await page.waitForSelector("[data-largest-trail] p", { timeout: 300000 });
  await page.waitForFunction(() => !document.querySelector(".largest-working"), null, { timeout: 600000 });
  hold(
    /times/.test((await page.textContent("#tab-body")) ?? ""),
    "the largest load: asked again, it runs to its answer",
  );
  hold(page.faults.length === 0, `the largest load: no page error${page.faults[0] ? `: ${page.faults[0]}` : ""}`);
  await page.close();
}

/** An IGBT typed in, from the hot figures of the made-up module, the knees and the cold
 *  energies left empty. Typed from the first moment, while the engine may be starting. */
async function typedIgbt() {
  const page = await fresh(browser, url);
  // A first visit types a part's figures under "Your part".
  await page.click("#panel [data-your-part]");
  await page.check('[data-typed-kind][value="igbt"]');
  await page.waitForSelector("#t-vce_sat");
  hold(
    (await page.evaluate(() => document.activeElement?.getAttribute("value"))) === "igbt",
    "a typed IGBT: the keyboard stays on the switch",
  );
  const figures = {
    v_rated: "600", i_rated: "30", rth_jc: "1.3", rth_jc_diode: "2.2", vce_sat: "2.15", vce_current: "30",
    vf: "1.75", vf_current: "30", e_on: "0.9", e_off: "0.75", e_rr: "0.36", e_current: "30", e_voltage: "300",
    tj_max: "150", hot_tj: "150",
  }; // prettier-ignore
  for (const [key, value] of Object.entries(figures)) await page.fill(`#t-${key}`, value);
  await page.click("[data-quick-add]");
  const handle = await page.waitForFunction(
    () =>
      document.querySelector('[data-device^="typed-igbt-"]')
        ? "in"
        : (document.querySelector("#panel .refusal, #panel .said-wrong")?.textContent ?? ""),
    null,
    { timeout: 300000 },
  );
  const got = await handle.jsonValue();
  hold(got === "in", `a typed IGBT: it is built and named by its kind (${got})`);
  if (got !== "in") return page.close();
  await walkToResults(page);
  const strip = (await page.textContent("#verdict-strip")) ?? "";
  hold(/caution|note/i.test(strip), `a typed IGBT: the verdict carries what was taken (${strip.trim().slice(0, 60)})`);
  const ways = await page.$$eval("[data-to-figure]", (b) => b.map((x) => x.getAttribute("data-to-figure")));
  hold(
    ["v_ce0", "v_f0", "e_cold"].every((k) => ways.includes(k)),
    `a typed IGBT: each figure taken has the way to its box (${ways.join(", ")})`,
  );
  // The way to a box stands with its finding, in a fold that starts shut.
  await page.evaluate(() => {
    let fold = document.querySelector('[data-to-figure="v_ce0"]')?.closest("details");
    for (; fold; fold = fold.parentElement?.closest("details") ?? null) fold.open = true;
  });
  await page.click('[data-to-figure="v_ce0"]');
  await page.waitForFunction(() => document.body.dataset.at === "0");
  hold(
    (await page.evaluate(() => document.activeElement?.id)) === "t-v_ce0",
    "a typed IGBT: the way back puts the keyboard in the knee's box",
  );
  hold((await page.inputValue("#t-vce_sat")) === "2.15", "a typed IGBT: the figures typed are back in their boxes");
  hold(page.faults.length === 0, `a typed IGBT: no page error${page.faults[0] ? `: ${page.faults[0]}` : ""}`);
  await page.close();
}

/** A heatsink in air chosen with its box left empty, and the figure offered taken. */
async function coolingOffer() {
  const page = await fresh(browser, url);
  await bring(page, low);
  await toStep(page, 2);
  await page.selectOption('[data-bind="conditions.cooling"]', "heatsink");
  await page.waitForSelector("[data-use-sized]", { timeout: 300000 });
  const said = (await page.textContent(".cooling-offer")) ?? "";
  hold(
    /To hold the heatsink at 60 °C at this design point, it needs [\d.]+ K\/W or less\./.test(said),
    `the cooling offer: the heatsink is offered from the loss (${said.trim().slice(0, 90)})`,
  );
  hold((await page.inputValue('[data-bind="conditions.rth_sink"]')) === "", "the cooling offer: the box is left empty");
  await page.click("[data-use-sized]");
  const value = await page.inputValue('[data-bind="conditions.rth_sink"]');
  hold(/^[\d.]+$/.test(value), `the cooling offer: taken, the figure is in its box (${value} K/W)`);
  hold(
    /Sized for you/.test((await page.textContent('label[for="f-conditions-rth_sink"]')) ?? ""),
    "the cooling offer: the box says it was sized for you",
  );
  await walkToResults(page);
  const tab = (await page.textContent("#tab-body")) ?? "";
  hold(/was sized by the tool/.test(tab), "the cooling offer: the verdict says the cooling was sized by the tool");
  hold(
    !/^\s*Passes\s*$/.test((await page.textContent("#verdict-strip")) ?? ""),
    "the cooling offer: never a clean pass",
  );
  await toStep(page, 2);
  await page.fill('[data-bind="conditions.rth_sink"]', "1.5");
  await page.waitForTimeout(300);
  hold(
    !/Sized for you/.test((await page.textContent('label[for="f-conditions-rth_sink"]')) ?? ""),
    "the cooling offer: an edit makes the figure the user's own",
  );
  hold((await kept(page)).conditions.sized === "", "the cooling offer: an edit is kept as the user's own");
  hold(page.faults.length === 0, `the cooling offer: no page error${page.faults[0] ? `: ${page.faults[0]}` : ""}`);
  await page.close();
}

/** What the event's plot of an edge says of itself: how many samples it shows, and its time ticks. */
const plotSaid = (page, which) =>
  page.evaluate((w) => {
    const plot = document.querySelector(`[data-edge-plot="${w}"]`);
    const label = plot?.querySelector("svg")?.getAttribute("aria-label") ?? "";
    const ticks = [...(plot?.querySelectorAll("text.tick") ?? [])].map((t) => t.textContent).join(" ");
    return { samples: Number(/(\d+) samples in view/.exec(label)?.[1] ?? 0), ticks };
  }, which);

const eventShown = (page) => page.waitForSelector("#pwm .ev-edges", { timeout: 300000 }).then(() => settled(page));

/** The switching event, opened from a spike of the loss chart and worked with. */
async function switchingEvent() {
  const page = await fresh(browser, url);
  await bring(page, low);
  await bring(page, high);
  await walkToResults(page);
  await page.click(`#switcher [data-focus="${low.id}"]`);
  await settled(page);
  hold((await page.$$("#pwm .ev-edge")).length === 0, "the event: nothing of it is drawn before it is asked for");
  await page.click('#pwm svg [data-event-show="off"] .spike-hit >> nth=1');
  await eventShown(page);
  hold(
    /is-marked/.test((await page.getAttribute('[data-key="ev-off"]', "class")) ?? ""),
    "the event: the turn-off pressed on the chart is marked",
  );
  hold(
    await page.evaluate(() => document.activeElement?.dataset?.edgePlot === "off"),
    "the event: the keyboard is on the turn-off's plot",
  );
  const said = (await page.textContent("#pwm .ev")) ?? "";
  hold(said.includes(low.name), `the event: of the device on the drawing (${low.name})`);
  hold(/Energy lost[\d.]+ µJ/.test(said) && /di\/dt/.test(said), "the event: its energy and di/dt are read out");
  await zoomAndMove(page);
  await fullScreen(page);
  await typedWhileAsked(page);
  await edgeLimit(page);
  // The other device on the drawing while its event is on its way.
  await page.click(`#switcher [data-focus="${high.id}"]`);
  await settled(page);
  await eventShown(page);
  const other = (await page.textContent("#pwm .ev")) ?? "";
  hold(other.includes(high.name) && !other.includes(low.name), `the event: the other device's own (${high.name})`);
  hold(/collector-emitter voltage/.test(other), "the event: an IGBT's traces are named as an IGBT's");
  hold(page.faults.length === 0, `the event: no page error${page.faults[0] ? `: ${page.faults[0]}` : ""}`);
  // Under 1784 px the two edges stand one above the other, held to the stage's measure.
  await page.setViewportSize({ width: 1700, height: 1080 });
  await page.waitForTimeout(300);
  const wrapped = await page.evaluate(() => {
    const box = document.querySelector("#pwm .ev").getBoundingClientRect();
    const prose = [...document.querySelectorAll("#pwm .ev > p, #pwm .ev-assumed li")];
    return prose
      .filter((p) => {
        const r = p.getBoundingClientRect();
        // As wide as the plots they stand with, and those are held to the stage's measure.
        return r.right > box.right + 1 || box.width > 962 || p.scrollWidth > p.clientWidth + 1;
      })
      .map((p) => p.textContent.slice(0, 40));
  });
  hold(
    !wrapped.length,
    `the event: on a wide desk its lines keep to the width of its plots, within the measure (${wrapped.join(" | ")})`,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(300);
  const stacked = await page.evaluate(() => {
    const [a, b] = [...document.querySelectorAll(".ev-edge")].map((e) => e.getBoundingClientRect());
    return b.top >= a.bottom - 1 && document.documentElement.scrollWidth <= innerWidth;
  });
  hold(stacked, "the event: on a phone the edges stand one above the other, with no sideways scroll");
  await page.close();
}

/** Zoom from the wheel, read by pointing, move by a drag, back with 0, in again with +. The
 *  page scrolled past a plot is not caught by it: the wheel zooms only once the pointer rests. */
async function zoomAndMove(page) {
  const first = await plotSaid(page, "on");
  await page.locator('[data-edge-plot="on"]').scrollIntoViewIfNeeded();
  let box = await page.locator('[data-edge-plot="on"]').boundingBox();
  // How far the page and every column round the plot have scrolled.
  const scrolled = () =>
    page.evaluate(() => {
      let total = scrollY;
      for (let el = document.querySelector('[data-edge-plot="on"]'); el; el = el.parentElement) total += el.scrollTop;
      return total;
    });
  const before = await scrolled();
  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.4);
  await page.mouse.wheel(0, 100);
  await page.waitForTimeout(100);
  hold(
    (await plotSaid(page, "on")).samples === first.samples,
    "the event: a wheel passing over a plot scrolls the page and does not zoom",
  );
  hold((await scrolled()) > before, "the event: the page scrolled on under the pointer");
  // A plot taller than the screen is brought to its top, so that the pointer rests on it.
  await page.evaluate(() => document.querySelector('[data-edge-plot="on"]').scrollIntoView({ block: "start" }));
  await page.waitForTimeout(400);
  box = await page.locator('[data-edge-plot="on"]').boundingBox();
  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.4);
  await page.waitForTimeout(800); // the pointer rests on the plot, the page still
  for (let k = 0; k < 4; k++) await page.mouse.wheel(0, -100);
  await page.waitForTimeout(100);
  const zoomed = await plotSaid(page, "on");
  hold(zoomed.samples < first.samples, `the event: the wheel zooms in (${first.samples} → ${zoomed.samples} samples)`);
  await page.mouse.move(box.x + box.width * 0.35, box.y + box.height * 0.4);
  const read = (await page.textContent("#ev-read-on")) ?? "";
  hold(/^At [\d.]+ ns: drain-source voltage/.test(read), `the event: pointing reads the traces (${read.slice(0, 50)})`);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.1, box.y + box.height * 0.4, { steps: 5 });
  await page.mouse.up();
  hold((await plotSaid(page, "on")).ticks !== zoomed.ticks, "the event: a drag moves along time");
  await page.waitForTimeout(400);
  hold(!(await page.$("dialog.ev-full[open]")), "the event: a drag does not open the plot full screen");
  await page.focus('[data-edge-plot="on"]');
  await page.keyboard.press("0");
  hold((await plotSaid(page, "on")).ticks === first.ticks, "the event: 0 goes back to the first span");
  await page.keyboard.press("+");
  hold((await plotSaid(page, "on")).samples < first.samples, "the event: + zooms in from the keyboard");
}

/** A press on a plot opens it full screen at the zoom it is at; the wheel zooms it there,
 *  Export PDF saves it as a PDF named for the plot and the device, and Escape closes it with
 *  the keyboard back on the plot, which keeps the zoom reached. */
async function fullScreen(page) {
  await page.locator('[data-edge-plot="on"]').scrollIntoViewIfNeeded();
  const inline = await plotSaid(page, "on");
  const box = await page.locator('[data-edge-plot="on"]').boundingBox();
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.25);
  await page.waitForSelector("dialog.ev-full[open]", { timeout: 5000 });
  const title = (await page.textContent("#ev-full-h")) ?? "";
  hold(/^Turn-on: drain-source voltage and drain current$/.test(title), `full screen: a press opens it (${title})`);
  const said = (await page.textContent("#ev-full-said")) ?? "";
  hold(said.includes(low.name) && / V and .* A, junction /.test(said), `full screen: the device and point (${said})`);
  const full = () =>
    page.evaluate(() => {
      const label = document.querySelector("[data-full-plot] svg")?.getAttribute("aria-label") ?? "";
      return Number(/(\d+) samples in view/.exec(label)?.[1] ?? 0);
    });
  hold((await full()) === inline.samples, "full screen: it opens at the zoom it was at");
  const fb = await page.locator("[data-full-plot]").boundingBox();
  hold(
    fb.width > 0.8 * (page.viewportSize()?.width ?? 0) - 100,
    `full screen: the plot fills the screen (${fb.width})`,
  );
  await page.mouse.move(fb.x + fb.width * 0.4, fb.y + fb.height * 0.5);
  for (let k = 0; k < 3; k++) await page.mouse.wheel(0, -100);
  await page.waitForTimeout(100);
  const zoomed = await full();
  hold(zoomed < inline.samples, `full screen: the wheel zooms (${inline.samples} → ${zoomed} samples)`);
  await page.mouse.move(fb.x + fb.width * 0.45, fb.y + fb.height * 0.5);
  const read = (await page.textContent("#ev-full-read")) ?? "";
  hold(/^At [\d.]+ ns: drain-source voltage .* power lost/.test(read), `full screen: pointing reads every trace`);
  const [download] = await Promise.all([page.waitForEvent("download"), page.click("[data-full-pdf]")]);
  const name = download.suggestedFilename();
  const device = low.name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  hold(name === `motionsim-turn-on-voltage-current-${device}.pdf`, `full screen: the PDF is named for it (${name})`);
  const path = await download.path();
  const { readFileSync } = await import("node:fs");
  const bytes = readFileSync(path).toString("latin1");
  hold(bytes.startsWith("%PDF"), "full screen: Export PDF saves a PDF");
  hold(
    bytes.includes("(Turn-on: drain-source voltage and drain current) Tj"),
    "full screen: the PDF carries the title",
  );
  hold(await savedPng(page, page.locator("[data-full-png]")), "full screen: Export PNG saves a sharp PNG image");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(200);
  hold(!(await page.$("dialog.ev-full[open]")), "full screen: Escape closes it");
  hold(
    await page.evaluate(() => document.activeElement?.dataset?.edgePlot === "on"),
    "full screen: the keyboard goes back to the plot it was opened from",
  );
  hold((await plotSaid(page, "on")).samples === zoomed, "full screen: closed, the plot keeps the zoom reached");
  // Every chart of the page is saved the same way: the loss chart and an edge stand for them.
  hold(
    await savedPng(page, page.locator("#pwm .plot-panel [data-save-png]").first()),
    "the loss chart is saved as a PNG",
  );
  hold(await savedPng(page, page.locator(".ev-edge [data-save-png]").first()), "an edge is saved as a PNG");
  hold(page.faults.length === 0, `full screen: no page error${page.faults[0] ? `: ${page.faults[0]}` : ""}`);
}

/** A press on a save button hands over a PNG image named for the chart, drawn at least
 *  1200 pixels across (its width is read from the file's own header). */
async function savedPng(page, button) {
  const [download] = await Promise.all([page.waitForEvent("download", { timeout: 20000 }), button.click()]);
  const { readFileSync } = await import("node:fs");
  const bytes = readFileSync(await download.path());
  const png = bytes.subarray(0, 8).toString("latin1") === "\x89PNG\r\n\x1a\n";
  return png && /^motionsim-[a-z0-9-]+\.png$/.test(download.suggestedFilename()) && bytes.readUInt32BE(16) >= 1200;
}

/** The edge limit raised from the event: the way to it on step 3, a press there, and the
 *  event and the figures worked out again for the faster edges. */
async function edgeLimit(page) {
  const held = (await page.textContent("#pwm .ev-held").catch(() => "")) ?? "";
  hold(
    /^(Edge speed is limited to 5 V\/ns|The edges here are .* well under the 5 V\/ns limit)/.test(held.trim()),
    `the edge limit: the event says what holds the edges (${held.trim()})`,
  );
  // The line quotes the event's own plotted slopes: each figure it gives is one the plot reads.
  const rates = [...held.matchAll(/([\d.]+) V\/ns at turn-(on|off)/g)].map((m) => Number(m[1]));
  const plotted = [...((await page.textContent("#pwm .ev-edges")) ?? "").matchAll(/dv\/dt(-?[\d.]+) V\/ns/g)].map((m) =>
    Math.abs(Number(m[1])),
  );
  hold(
    rates.every((r) => plotted.some((p) => Math.abs(p - r) <= 0.006 + 0.05 * r)),
    `the edge limit: the line agrees with the plotted dv/dt (${rates.join(", ")} against ${plotted.join(", ")})`,
  );
  const before = await shown(page);
  await page.click("[data-edge-limit-go]");
  await page.waitForFunction(() => document.body.dataset.at === "2");
  hold(
    await page.evaluate(() => document.activeElement?.matches?.('[data-edge-limit][value="cable"]')),
    "the edge limit: raise the limit takes the keyboard to it on step 3",
  );
  await page.check('[data-edge-limit][value="none"]');
  hold((await kept(page)).conditions?.edge_limit === "none", "the edge limit: the limit picked is kept");
  await toStep(page, 4);
  await settled(page);
  await eventShown(page);
  const after = (await page.textContent("#pwm .ev")) ?? "";
  hold(
    !(await page.$("#pwm .ev-held")) && !/hold the edges/.test(after),
    "the edge limit: the event no longer says it",
  );
  const now = await shown(page);
  hold(now !== before, "the edge limit: the figures are worked out again for the faster edges");
}

/** An assumption's way to its box, and a figure typed there while the event is being worked out. */
async function typedWhileAsked(page) {
  await page.click('[data-event-box="event.l_cs_nh"]');
  hold(
    await page.evaluate(() => document.activeElement?.id === "ev-f-event-l_cs_nh"),
    "the event: an assumption's way goes to its box",
  );
  // 10 nH of the loop's 30: a common-source inductance as large as the whole loop is one the
  // engine refuses for the IGBT, whose gate then never settles.
  await page.keyboard.type("1");
  await page.waitForSelector("#pwm .waiting", { timeout: 10000 }).catch(() => null);
  await page.keyboard.type("0"); // the race itself: typed again while the first is asked
  await eventShown(page);
  const after = (await page.textContent("#pwm .ev-assumed")) ?? "";
  hold(!/Common-source inductance left out/.test(after), "the event: the figure typed is in the answer shown");
  hold((await kept(page)).event?.l_cs_nh === "10", "the event: the figure typed is kept");
}

/** The washer on the motor it usually has, followed through its programme. */
async function washerDuty() {
  const page = await fresh(browser, url);
  await bring(page, high);
  await toStep(page, 3);
  await page.waitForSelector('[data-load][value="drum"]', { timeout: 300000 });
  await page.check('[data-load][value="drum"]');
  // The motor such products have is offered under "About this load", a fold that starts shut.
  await page.waitForSelector('[data-usual-motor="drum"]', { state: "attached", timeout: 300000 });
  await page.evaluate(() => {
    let fold = document.querySelector('[data-usual-motor="drum"]')?.closest("details");
    for (; fold; fold = fold.parentElement?.closest("details") ?? null) fold.open = true;
  });
  await page.click('[data-usual-motor="drum"]');
  await page.waitForFunction(() => document.querySelector("table.phases"), null, { timeout: 300000 });
  const state = await kept(page);
  hold(state.motors?.pmsm?.pole_pairs === 24, "the washer: its usual motor, 48 poles, is put in");
  await toStep(page, 4);
  await page.click('[data-tab="motion"]');
  await page.waitForSelector("#tab-body [data-motion-full]", { timeout: 600000 });
  await settled(page);
  const tab = (await page.textContent("#tab-body"))?.replace(/\s+/g, " ") ?? "";
  for (const name of ["wash", "rinse", "spin"]) hold(tab.includes(name), `the washer: the ${name} phase is named`);
  hold(tab.includes("time, min"), "the washer: the run is drawn in minutes");
  hold(/Start current [\d.]+ A for [\d.]+ s/.test(tab), "the washer: the start current and how long it held");
  const marks = await page.$$eval("#tab-body .mark-label", (els) => els.map((e) => e.textContent));
  hold(marks.includes("start"), "the washer: the start-up's junction peak is marked");
  hold(page.faults.length === 0, `the washer: no page error${page.faults[0] ? `: ${page.faults[0]}` : ""}`);
  await page.close();
}

try {
  await washerDuty();
  await switchingEvent();
  await addEachKind();
  await typedIgbt();
  await coolingOffer();
  await cancelLargest();
  await addDeviceThenJump();
  await failThenStale([low]);
  await failThenStale([low, high]);
  await swapWhileAsking();
} catch (e) {
  hold(false, `the script stopped: ${String(e.message ?? e).split("\n")[0]}`);
} finally {
  await browser.close();
}
if (failed.length) {
  console.error(`\n${failed.length} failed`);
  process.exit(1);
}
console.log("\nno failures");
