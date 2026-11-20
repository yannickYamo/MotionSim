// @vitest-environment happy-dom
// The page drawn from real answers of the engine, and from the same answers with every
// piece of text in them turned hostile: whatever the engine, a device file or a saved
// state says, it is shown as text and never becomes markup.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { Refused } from "../src/api";
import { initial } from "../src/state";
import type { Tab } from "../src/state";
import { setPath } from "../src/boxes";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { renderRail } from "../src/views/rail";
import { renderStage } from "../src/views/stage";

// Read from the working directory: under a DOM this file's own address is the page's.
const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;
const HOSTILE = `x"'><img src=x onerror=alert(1)><script>alert(2)</script>`;
const TABS: Tab[] = ["proposal", "losses", "motion", "limits"];

/** The same answer with every text in it replaced, keys left alone. */
function hostile<T>(value: T): T {
  if (typeof value === "string") return HOSTILE as unknown as T;
  if (Array.isArray(value)) return value.map(hostile) as unknown as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, hostile(v)])) as T;
  }
  return value;
}

function fill(a: typeof answers): void {
  Object.assign(res, { stage: a.stage.stage, advice: a.stage.advice, proposal: a.proposal, cycle: a.cycle });
  Object.assign(res, {
    grid: a.map,
    advised: (a.recommend as { items: unknown }).items,
    capable: a.capability,
    fit: a.fit,
  });
  res.presets = { key: "k", list: a.loads.loads as never };
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
}

function drawEverything(): void {
  for (const step of [0, 1, 2, 3]) {
    app.state.step = step;
    renderRail();
    renderPanel();
    renderStage();
  }
  app.state.step = 4;
  for (const tab of TABS) {
    app.state.tab = tab;
    renderPanel();
    renderStage();
  }
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example-mosfet", "example"], added: ["example-mosfet", "example"] });
  Object.assign(app.state, { reached: 4, focus: "example-mosfet", loadKind: "joint" });
  ui.notes.clear();
  ui.followed = null;
  fill(answers);
});

describe("the page drawn from the engine's answers", () => {
  it("draws every step and every tab", () => {
    drawEverything();
    expect(document.querySelector("#tab-body")!.textContent.length).toBeGreaterThan(50);
    expect(document.body.innerHTML).not.toMatch(/\bNaN\b|undefined|\[object Object\]/);
  });
  it("has one heading of the page, and no id twice", () => {
    for (const tab of TABS) {
      app.state.step = 4;
      app.state.tab = tab;
      renderPanel();
      renderStage();
      expect(document.querySelectorAll("h1")).toHaveLength(1);
      const ids = [...document.querySelectorAll("[id]")].map((e) => e.id);
      const twice = ids.filter((id, k) => ids.indexOf(id) !== k);
      expect(twice, `on the ${tab} tab`).toEqual([]);
    }
  });
  it("shows hostile text as text, wherever it comes from", () => {
    fill(hostile(answers));
    app.setup.devices = app.setup.devices.map((d) => ({ ...hostile(d), id: d.id, example: d.example }));
    app.state.mission = { name: HOSTILE, time: [0, 1], rpm: [0, 5], torque: [1, 1] };
    app.state.typed = { part_number: HOSTILE, vendor: HOSTILE };
    app.state.conditions.rth_case_sink = HOSTILE;
    app.state.sink.rth = HOSTILE;
    app.state.loadSet = [{ id: HOSTILE, label: HOSTILE, loadKind: HOSTILE, load: app.state.load, segments: [] }];
    app.state.motorSet = [{ id: HOSTILE, label: HOSTILE, motor: {}, conditions: {} }];
    ui.missionFault = new Refused(HOSTILE, HOSTILE, "mission");
    ui.notes.set("conditions.rpm", { raw: HOSTILE, why: HOSTILE });
    res.blocked = null;
    drawEverything();
    res.blocked = new Refused(HOSTILE, HOSTILE, "rpm");
    res.fault = HOSTILE;
    drawEverything();
    expect(document.querySelectorAll("img, script, iframe, object")).toHaveLength(0);
    const handlers = [...document.querySelectorAll("*")].flatMap((e) =>
      [...e.attributes].filter((a) => a.name.startsWith("on") || a.name === "src" || a.name === "srcdoc"),
    );
    expect(handlers).toEqual([]);
    expect(document.body.textContent).toContain("<img src=x onerror=alert(1)>");
  });
});

describe("a box as it is drawn", () => {
  const box = (path: string) => document.querySelector<HTMLInputElement>(`[data-bind="${path}"]`)!;
  it("says under itself that it could not be read, and is marked for a screen reader", () => {
    app.state.step = 2;
    renderPanel();
    setPath("conditions.rpm", "1,500");
    renderPanel(true);
    const input = box("conditions.rpm");
    expect(input.value).toBe("1,500"); // what was typed stays in the box
    expect(input.getAttribute("aria-invalid")).toBe("true");
    const said = input
      .getAttribute("aria-describedby")!
      .split(" ")
      .map((id) => document.getElementById(id)!.textContent);
    expect(said.join(" ")).toMatch(/can be read two ways.*2000 is still in use/);
  });
  it("keeps the very node, the typed text and its note through any number of redraws", () => {
    app.state.step = 2;
    renderPanel();
    const input = box("conditions.torque");
    input.focus();
    input.value = "abc";
    setPath("conditions.torque", "abc");
    for (let k = 0; k < 3; k++) renderPanel(true);
    expect(box("conditions.torque")).toBe(input);
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("abc");
    expect(input.closest(".field")!.querySelectorAll(".unread")).toHaveLength(1);
  });
  it("marks a load figure that cannot be, at the box, before the engine is asked", () => {
    app.state.step = 3;
    ui.folds.set("load-figures", true);
    renderPanel();
    const path = [...document.querySelectorAll<HTMLInputElement>("[data-bind^='load.']")][0].dataset.bind!;
    setPath(path, "-5");
    setPath("segments.0.duration", "0");
    renderPanel(true);
    expect(box("segments.0.duration").getAttribute("aria-invalid")).toBe("true");
    expect(box("segments.0.duration").closest("td")!.textContent).toContain("A stretch has to be above 0 s.");
  });
  it("asks for the figure the chosen cooling needs, at its box, without calling anything wrong", () => {
    app.state.step = 2;
    app.state.conditions.cooling = "heatsink";
    res.waiting = new Refused("the heatsink's thermal resistance is needed", "give it under Cooling", "rth_sink");
    res.proposal = null;
    renderPanel();
    renderStage();
    const input = box("conditions.rth_sink");
    expect(input.getAttribute("aria-invalid")).toBeNull();
    expect(document.getElementById(input.getAttribute("aria-describedby")!.split(" ").pop()!)!.textContent).toBe(
      "Needed: the heatsink's thermal resistance is needed.",
    );
    expect(document.body.textContent).not.toContain("This cannot work");
    expect(document.querySelector("#readouts")!.textContent).toContain("One figure needed");
  });
});

describe("a fold", () => {
  it("stays as the user left it through redraws and when they come back to the step", () => {
    app.state.step = 2;
    renderPanel();
    const folds = [...document.querySelectorAll<HTMLDetailsElement>("#panel details")];
    expect(folds.length).toBeGreaterThan(1);
    expect(folds.every((f) => f.dataset.fold)).toBe(true);
    const fold = folds.find((f) => !f.open)!;
    ui.folds.set(fold.dataset.fold!, true); // what the toggle handler records on a press
    renderPanel(true);
    expect(fold.open).toBe(true);
    app.state.step = 1;
    renderPanel();
    app.state.step = 2;
    renderPanel();
    expect(document.querySelector<HTMLDetailsElement>(`[data-fold="${fold.dataset.fold}"]`)!.open).toBe(true);
  });
});

describe("the verdict where the motion cannot be followed", () => {
  it("is not Passes, on the strip, in the table and in the sentence", () => {
    app.state.step = 4;
    app.state.tab = "proposal";
    app.state.devices = ["example-mosfet"];
    const one = structuredClone(answers.proposal) as { candidates: { id: string; level: string }[] };
    one.candidates = one.candidates.filter((c) => c.id === "example-mosfet");
    expect(one.candidates[0].level).toBe("ok");
    res.proposal = one as never;
    const cycle = structuredClone(answers.cycle) as { checks: object[] };
    const message = "the motor cannot follow part of this motion: 30 N·m at 9000 rpm needs more voltage";
    cycle.checks.push({ level: "fail", topic: "motion", message });
    res.cycle = cycle as never;
    renderPanel();
    renderStage();
    expect(document.querySelector("#verdict-strip")!.textContent).toContain("Ruled out");
    expect(document.querySelector(".candidate summary")!.textContent).toContain("Ruled out");
    expect(document.querySelector(".candidate summary")!.textContent).not.toContain("Passes");
    expect(document.querySelector("#panel .verdict-line")!.textContent).toMatch(
      /passes at the design point, but not over the motion/,
    );
    expect(document.querySelector(".cand-body")!.textContent).toContain("cannot follow part of this motion");
    expect(document.querySelector("#announce")!.textContent).toMatch(/Ruled out/);
  });
});

describe("a fold the user has just moved", () => {
  it("is not moved back by a redraw that comes before the fold has said so", () => {
    app.state.step = 2;
    renderPanel();
    const fold = [...document.querySelectorAll<HTMLDetailsElement>("#panel details")].find((f) => !f.open)!;
    fold.open = true; // the press; the fold's own event has not been handled yet
    renderPanel(true);
    expect(fold.open).toBe(true);
    expect(ui.folds.get(fold.dataset.fold!)).toBe(true);
    fold.open = false;
    renderPanel(true);
    expect(fold.open).toBe(false);
  });
});
