// @vitest-environment happy-dom
// What stands on the page while an answer is on its way, or will not come: the load of a part
// whose application is not known yet, the switching event's boxes under a design being worked
// out or refused, the results' own word for a part that cannot be run, and the report the
// browser prints after a figure has moved.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability", "report"];
  names.push("addDevice", "setup", "event");
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true, forget: vi.fn(), remember: vi.fn() } };
});

import type { Candidate, Cycle, LoadPreset, Proposal, Setup, Suggest, SwitchingEvent } from "../src/api";
import { api, Refused } from "../src/api";
import { printReport, reportForPrint } from "../src/actions/reports";
import { presetsFor } from "../src/engine/loads";
import { openEvent, resetEvent, toEventBox } from "../src/eventask";
import { wire } from "../src/events";
import { initial, KEY, save } from "../src/state";
import type { State } from "../src/state";
import { LOAD, RESULTS } from "../src/steps";
import { app, focused, pending, res, ui } from "../src/store";
import { connect, frame, topBar } from "../src/views/render";
import { renderStage } from "../src/views/stage";
import { notReady } from "../src/views/tabs/ready";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const suits = fixture("suggest") as Record<string, Suggest>;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;
const event = fixture("event") as SwitchingEvent;
const mock = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const $ = <T extends Element = HTMLElement>(s: string) => document.querySelector<T>(s);

function held<T>() {
  let give!: (v: T) => void;
  const promise = new Promise<T>((a) => (give = a));
  return { promise, give };
}
const settle = async () => {
  for (let k = 0; k < 10; k++) await new Promise((r) => setTimeout(r, 0));
};
const until = async (ok: () => boolean) => {
  for (let k = 0; k < 200 && !ok(); k++) await new Promise((r) => setTimeout(r, 10));
  return ok();
};

function atResults(device: string): State {
  const s = initial(setup);
  Object.assign(s, { devices: [device], added: [device], focus: device, reached: RESULTS, step: RESULTS });
  return s;
}
function answered(): void {
  Object.assign(res, { stage: answers.stage.stage, advice: answers.stage.advice });
  res.proposal = structuredClone(answers.proposal) as unknown as Proposal;
  app.state.focus = res.proposal.candidates[0].id;
  res.stale = false;
}

// Everything the page has kept, in the order it was written.
const written: State[] = [];

beforeEach(() => {
  written.length = 0;
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", {
    getItem: () => null,
    setItem: (k: string, v: string) => void (k === KEY && written.push(JSON.parse(v) as State)),
    removeItem: () => undefined,
  });
  vi.stubGlobal("print", vi.fn());
  Element.prototype.scrollIntoView = () => undefined;
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  wire();
  for (const f of Object.values(mock)) if (typeof f.mockReset === "function") f.mockReset();
  for (const n of ["stage", "proposal", "cycle", "loads", "fit", "map", "recommend", "capability", "report", "suggest"])
    mock[n].mockImplementation(() => new Promise(() => undefined));
  mock.event.mockImplementation(() => Promise.resolve(structuredClone(event)));
  app.setup = structuredClone(setup);
  app.state = atResults("example-mosfet");
  Object.assign(res, { stage: null, advice: null, proposal: null, cycle: null, blocked: null, fault: null });
  Object.assign(res, { waiting: null, suggestion: null, presets: null, stale: false, offline: false, grid: null });
  res.loading.clear();
  res.started.clear();
  res.cycles.clear();
  res.grids.clear();
  res.resultsOf = "";
  resetEvent();
  ui.folds.clear();
  ui.pwmOpen = true;
  ui.fetchFault = null;
  ui.unsaved = false;
  ui.cleared = false;
});

describe("the load of a part whose application is not known yet", () => {
  const offered = answers.loads.loads as LoadPreset[];
  const usual = "joint"; // the first load offered for the motor
  const keptKind = "fan"; // the load kept from the visit before: neither the usual one nor the application's

  /** A part of its own on the load step, with a load kept: what suits a part is asked once for
   *  each part and remembered, so every case here asks about a part not asked about before. */
  function partOnLoadStep(id: string): void {
    app.setup.devices.push({ ...structuredClone(setup.devices[0]), id, name: id });
    app.state = atResults(id);
    app.state.step = LOAD;
    app.state.loadKind = keptKind;
    save(app.state);
    mock.loads.mockResolvedValue({ loads: offered });
  }
  const keptKinds = () => written.map((s) => s.loadKind);

  it("stays as kept until the application is known, then is the application's, never the usual one", async () => {
    expect(offered[0].id).toBe(usual);
    expect(offered.map((l) => l.id)).toContain("drum");
    partOnLoadStep("part-of-a-drum");
    const suggest = held<Suggest>();
    mock.suggest.mockReturnValue(suggest.promise);
    // The loads answer at once; what suits the part is still on its way.
    const sizing = presetsFor();
    await settle();
    expect(app.state.loadKind).toBe(keptKind);
    expect(keptKinds()).toEqual([keptKind]);
    suggest.give({
      ...suits.example,
      application: { id: "drum", label: "Washing machine", start: "sensor", supply: "one-way" },
    });
    await sizing;
    await settle();
    expect(app.state.loadKind).toBe("drum");
    expect(keptKinds().at(-1)).toBe("drum");
    // The usual load was at no moment put in the application's place and kept.
    expect(keptKinds()).not.toContain(usual);
  });

  it("is the usual one for the motor where the part has no application", async () => {
    partOnLoadStep("part-of-no-application");
    expect(suits.example.application).toBeUndefined();
    mock.suggest.mockResolvedValue(structuredClone(suits.example));
    await presetsFor();
    await settle();
    expect(app.state.loadKind).toBe(usual);
    expect(keptKinds().at(-1)).toBe(usual);
  });

  it("is the usual one for the motor where nothing can be said of what suits the part", async () => {
    partOnLoadStep("part-not-answered-for");
    mock.suggest.mockRejectedValue(new Error("no answer"));
    await presetsFor();
    await settle();
    expect(app.state.loadKind).toBe(usual);
    expect(keptKinds().at(-1)).toBe(usual);
  });
});

describe("the switching event's boxes under the loss chart", () => {
  const LOOP = '#pwm [data-bind="conditions.l_loop_nh"]';

  /** The event open and drawn, and the keyboard in its loop-inductance box. */
  async function typingInTheLoopBox(): Promise<HTMLInputElement> {
    answered();
    renderStage();
    openEvent("on");
    expect(await until(() => !!$("#pwm .ev-edges"))).toBe(true);
    toEventBox("conditions.l_loop_nh");
    const box = $<HTMLInputElement>(LOOP)!;
    expect(box).not.toBeNull();
    expect(document.activeElement).toBe(box);
    return box;
  }

  it("stay on the page, the same boxes with the keyboard in them, while an answer is on its way", async () => {
    const box = await typingInTheLoopBox();
    // A figure moves: the page waits for the answer of the inputs as they now stand.
    res.stale = true;
    expect(pending()).toBe(true);
    renderStage();
    expect(box.isConnected).toBe(true);
    expect($("#pwm")!.contains(box)).toBe(true);
    expect($(LOOP)).toBe(box);
    expect(document.activeElement).toBe(box);
    // Drawn a second time while it still waits, as each later answer draws the stage.
    renderStage();
    expect($(LOOP)).toBe(box);
  }, 30_000);

  it("are all that is left under a design that is refused, for the figure at fault to be put right", async () => {
    await typingInTheLoopBox();
    res.blocked = new Refused("the loop inductance is more than the model takes", "lower it", "l_loop_nh");
    renderStage();
    const pwm = $("#pwm")!;
    expect($(LOOP)).not.toBeNull();
    expect(pwm.querySelector('details[data-fold="event-detail"]')).not.toBeNull();
    // No chart and no plot of the event: they would be of a design that has no answer.
    expect(pwm.querySelector("svg.chart, .ev-edges, [data-edge-plot], [data-event-show]")).toBeNull();
    for (const el of pwm.querySelectorAll("input"))
      expect(el.closest('details[data-fold="event-detail"]'), el.id).not.toBeNull();
  }, 30_000);

  it("are not there under a design that is refused where the event was never opened", () => {
    answered();
    renderStage();
    expect($("#pwm svg.chart")).not.toBeNull();
    res.blocked = new Refused("the supply is below what the motor needs", "raise it", "v_dc");
    renderStage();
    expect($("#pwm")!.innerHTML).toBe("");
  });
});

describe("a results tab with an answer in which no part could be run", () => {
  it("says the part cannot be worked out, with why, and waits for nothing", () => {
    answered();
    const problem = "Its 100 V rating is below the 400 V supply";
    const remedy = "Lower the supply, or bring a part rated above it";
    const only = { ...res.proposal!.candidates[0], result: null, problem, fix: remedy } as unknown as Candidate;
    res.proposal = { ...res.proposal!, candidates: [only] };
    // No part is on the drawing: none in the answer has a result to draw.
    app.state.focus = null;
    expect(focused()).toBeNull();
    document.body.insertAdjacentHTML("beforeend", `<div id="said">${notReady()}</div>`);
    const said = $("#said")!.textContent;
    expect(said).toContain(`${only.name} cannot be worked out`);
    expect(said).toContain(problem);
    expect(said).toContain(remedy);
    expect(said).not.toContain("Working out the losses");
  });
});

describe("the report the browser prints after a figure has moved", () => {
  const report = () => $("#report")!;

  /** The report made ready and printed at 13 kHz, with the motion already followed. */
  async function printedAt13(): Promise<void> {
    answered();
    res.cycle = structuredClone(answers.cycle) as unknown as Cycle;
    app.state.conditions.f_khz = 13;
    await printReport();
    expect(window.print).toHaveBeenCalledTimes(1);
    expect(report().textContent).toContain("13.0 kHz");
  }

  it("is written again from the answer now on the page", async () => {
    await printedAt13();
    app.state.conditions.f_khz = 37;
    reportForPrint();
    expect(report().textContent).toContain("37.0 kHz");
    expect(report().textContent).not.toContain("13.0 kHz");
  }, 30_000);

  it("gives way to a sentence saying the figures changed while the page waits for their answer", async () => {
    await printedAt13();
    app.state.conditions.f_khz = 37;
    res.stale = true;
    expect(pending()).toBe(true);
    reportForPrint();
    expect(report().textContent).toMatch(/figures changed/i);
    // No figure of the report made before is left to be printed beside the new inputs.
    expect(report().textContent).not.toContain("kHz");
    expect(report().querySelector("table")).toBeNull();
  }, 30_000);

  it("is left as it was where nothing has changed", async () => {
    await printedAt13();
    // A mark on what is there: a report written again, even to the same words, would lose it.
    report().firstElementChild!.setAttribute("data-as-printed", "");
    const before = report().innerHTML;
    reportForPrint();
    expect(report().innerHTML).toBe(before);
    expect(report().querySelector("[data-as-printed]")).not.toBeNull();
  }, 30_000);

  it("is put right as the browser's own Print begins, whichever way it was asked for", async () => {
    await printedAt13();
    app.state.conditions.f_khz = 37;
    window.dispatchEvent(new Event("beforeprint"));
    expect(report().textContent).toContain("37.0 kHz");
    expect(report().textContent).not.toContain("13.0 kHz");
    app.state.conditions.f_khz = 41;
    res.stale = true;
    window.dispatchEvent(new Event("beforeprint"));
    expect(report().textContent).toMatch(/figures changed/i);
    expect(report().textContent).not.toContain("kHz");
  }, 30_000);
});
