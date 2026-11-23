// @vitest-environment happy-dom
// What is taken back of a kept state or a setup file whose values are of the right kind and
// still not ones the page could have kept: a name every object answers to, a text far longer
// than a box holds, a stretch of no time, a profile whose time goes back. And the page drawn
// from what comes back, on every step and tab.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { fromSetupFile, restore } from "../src/restore";
import { initial, KEY, request, sizedEarlier, sizingKey } from "../src/state";
import type { Tab } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { renderRail } from "../src/views/rail";
import { renderStage } from "../src/views/stage";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;
const TABS: Tab[] = ["proposal", "losses", "motion", "limits"];

const store = new Map<string, string>();
beforeEach(() => {
  store.clear();
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
});
const keep = (s: unknown) => store.set(KEY, JSON.stringify(s));
/** A state as the page keeps it: plain data, to be changed by hand. */
const kept = () => JSON.parse(JSON.stringify(initial(setup))) as Record<string, Record<string, unknown>>;

/** Every step and every tab of the results, drawn from the state with answers on hand. */
function drawEverything(): void {
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  Object.assign(app.state, { devices: ["example-mosfet"], added: ["example-mosfet"], focus: "example-mosfet" });
  app.state.reached = 4;
  Object.assign(res, { stage: answers.stage.stage, advice: answers.stage.advice });
  Object.assign(res, { proposal: answers.proposal, cycle: answers.cycle });
  res.presets = { key: "k", list: answers.loads.loads as never };
  ui.notes.clear();
  for (const step of [0, 1, 2, 3, 4]) {
    app.state.step = step;
    for (const tab of step === 4 ? TABS : TABS.slice(0, 1)) {
      app.state.tab = tab;
      renderRail();
      renderPanel();
      renderStage();
    }
  }
}

describe("a kind of motor named after something every object has", () => {
  // The kinds are the names of a record: "constructor" is in every record, and is no kind.
  const names = ["constructor", "toString", "__proto__", "hasOwnProperty"];
  it("is not a state in a setup file", () => {
    for (const kind of names) {
      const file = JSON.parse(`{"app":"MotionSim","setup":3,"state":{"kind":"${kind}","devices":[]},"parts":[]}`);
      expect(fromSetupFile(file, setup), kind).toBeNull();
    }
  });
  it("is a fresh start in what the browser kept", () => {
    for (const kind of names) {
      keep({ kind, devices: [] });
      expect(restore(setup), kind).toEqual(initial(setup));
    }
  });
});

describe("a text longer than a box holds", () => {
  it("comes back whole where it is what a cooling was sized for", () => {
    const state = initial(setup);
    state.devices = ["example"];
    state.lead = "example";
    Object.assign(state.conditions, { cooling: "heatsink", rth_sink: "1.5", sized: "rth_sink" });
    state.conditions.sizedFor = sizingKey(state, "rth_sink", "example");
    // Every input of the sizing written out: longer than the 400 characters of any typed text.
    expect(state.conditions.sizedFor.length).toBeGreaterThan(400);
    // The design point moves after the sizing: the page says it was sized for an earlier point.
    state.conditions.rpm += 500;
    keep(state);
    const back = restore(setup);
    expect(back.conditions.sizedFor).toBe(state.conditions.sizedFor);
    expect(back.conditions.sized).toBe("rth_sink");
    expect(sizedEarlier(back)).toBe(true);
    expect(request(back).conditions.sized_earlier).toBe(true);
  });
  it("comes back whole at 547 characters, and empty past the 8000 a sizing is held to", () => {
    const state = kept();
    state.conditions.sizedFor = "s".repeat(547);
    keep(state);
    expect(restore(setup).conditions.sizedFor).toBe("s".repeat(547));
    state.conditions.sizedFor = "s".repeat(8001);
    keep(state);
    expect(restore(setup).conditions.sizedFor).toBe("");
  });
  it("comes back whole where it is a board's layout file, with its name", () => {
    const state = kept();
    const layout = "(kicad_pcb ".padEnd(5000, "x");
    Object.assign(state.event, { layout, layout_name: "board.kicad_pcb" });
    keep(state);
    const back = restore(setup);
    expect(back.event.layout).toBe(layout);
    expect(back.event.layout).toHaveLength(5000);
    expect(back.event.layout_name).toBe("board.kicad_pcb");
  });
  it("comes back empty, its name with it, where the layout is longer than two million characters", () => {
    const state = kept();
    Object.assign(state.event, { layout: "x".repeat(2_000_001), layout_name: "board.kicad_pcb" });
    keep(state);
    const back = restore(setup);
    expect(back.event.layout).toBe("");
    expect(back.event.layout_name).toBe("");
  });
});

describe("a profile that no motion runs through", () => {
  it("leaves the fresh stretches standing where a stretch lasts no time, or less", () => {
    for (const duration of [0, -5]) {
      keep({ ...kept(), segments: [{ duration, speed_start: 0, speed_end: 100 }] });
      expect(restore(setup).segments, `a stretch of ${duration} s`).toEqual(initial(setup).segments);
    }
  });
  it("drops a mission whose time goes back, or stands still", () => {
    for (const time of [
      [5, 1, 3],
      [0, 1, 1],
    ]) {
      keep({ ...kept(), mission: { name: "m", time, rpm: [1, 2, 3], torque: [1, 2, 3] } });
      expect(restore(setup).mission, `time ${time.join(", ")}`).toBeNull();
    }
    keep({ ...kept(), mission: { name: "m", time: [0, 1, 3], rpm: [1, 2, 3], torque: [1, 2, 3] } });
    expect(restore(setup).mission).toEqual({ name: "m", time: [0, 1, 3], rpm: [1, 2, 3], torque: [1, 2, 3] });
  });
});

describe("the page drawn from a kept state of an odd shape", () => {
  const base = kept();
  const shapes: Record<string, unknown> = {
    "a stretch of no time": { ...base, segments: [{ duration: 0, speed_start: 0, speed_end: 0 }] },
    "a stretch of less than no time": { ...base, segments: [{ duration: -5, speed_start: 0, speed_end: 100 }] },
    "a thousand million repeats": { ...base, sink: { ...base.sink, repeats: 1e9 } },
    "repeats below nought, and not whole": { ...base, sink: { ...base.sink, repeats: -3.5 } },
    "no part in parallel": { ...base, conditions: { ...base.conditions, parallel: 0 } },
    "a mission whose time goes back": {
      ...base,
      mission: { name: "m", time: [5, 1, 3], rpm: [1, 2, 3], torque: [1, 2, 3] },
    },
    "a sweep of a setting every object has": { ...base, compare: "sweep", sweep: { key: "__proto__", values: "1, 2" } },
    "a way of starting the page has not": { ...base, start: { ...base.start, method: "<x>" } },
    "a modulation the page has not": { ...base, conditions: { ...base.conditions, pwm: "nope" } },
  };
  // Each shape is drawn on every step and tab: slow where the machine is busy.
  it.each(Object.keys(shapes))(
    "draws every step and tab with %s, and no figure that is not one",
    (what) => {
      keep(shapes[what]);
      app.state = restore(setup);
      expect(drawEverything).not.toThrow();
      expect(document.querySelector("#tab-body")!.textContent.length).toBeGreaterThan(50);
      expect(document.body.innerHTML).not.toMatch(/\bNaN\b|undefined|Infinity|\[object Object\]/);
    },
    30_000,
  );
});
