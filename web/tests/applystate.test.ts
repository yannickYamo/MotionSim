// @vitest-environment happy-dom
// Reset and Open setup put a fresh state in place. Nothing that was on its way for the state
// before lands on the fresh one: no design point, no motion, no report, no Undo.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability", "report"];
  names.push("addDevice", "setup");
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true, forget: vi.fn(), remember: vi.fn() } };
});

import type { Cycle, Proposal, Setup, Suggest } from "../src/api";
import { api } from "../src/api";
import { addPart } from "../src/actions/parts";
import { printReport, saveMarkdown } from "../src/actions/reports";
import { applyState, clearEverything, openSetup } from "../src/actions/setup";
import { compute } from "../src/engine";
import { deep } from "../src/engine/deep";
import { wire } from "../src/events";
import { addFromMenu, removeColumn, settleSwitch, undoColumn } from "../src/events/columns";
import { shown } from "../src/shown";
import { initial } from "../src/state";
import type { State } from "../src/state";
import { RESULTS } from "../src/steps";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const suits = fixture("suggest") as Record<string, Suggest>;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;
const mock = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function held<T>() {
  let give!: (v: T) => void;
  const promise = new Promise<T>((a) => (give = a));
  return { promise, give };
}
const settle = async () => {
  for (let k = 0; k < 10; k++) await new Promise((r) => setTimeout(r, 0));
};
let downloads: string[] = [];

beforeEach(() => {
  vi.useRealTimers();
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  vi.stubGlobal("print", () => undefined);
  // Only the two calls a download makes are stood in for: the page's modules still load by URL.
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
  vi.spyOn(URL, "revokeObjectURL").mockReturnValue(undefined);
  downloads = [];
  HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
    downloads.push(this.download);
  };
  Element.prototype.scrollIntoView = () => undefined;
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  wire();
  for (const f of Object.values(mock)) if (typeof f.mockReset === "function") f.mockReset();
  for (const n of ["stage", "proposal", "cycle", "loads", "fit", "map", "recommend", "capability", "report"])
    mock[n].mockImplementation(() => new Promise(() => undefined));
  mock.suggest.mockImplementation((id: string) => Promise.resolve(suits[id]));
  app.setup = structuredClone(setup);
  app.state = atResults();
  Object.assign(res, { stage: null, advice: null, proposal: null, cycle: null, blocked: null, fault: null });
  Object.assign(res, { waiting: null, suggestion: null, presets: null, stale: false, offline: false });
  res.loading.clear();
  res.started.clear();
  ui.forgotten = null;
  ui.savingMd = 0;
});

function atResults(device = "example"): State {
  const s = initial(setup);
  Object.assign(s, { devices: [device], added: [device], focus: device, reached: RESULTS, step: RESULTS });
  return s;
}

/** The design point and the proposal answered for the state on the page. */
function answered(): void {
  Object.assign(res, { stage: answers.stage.stage, advice: answers.stage.advice });
  res.proposal = structuredClone(answers.proposal) as unknown as Proposal;
  app.state.focus = res.proposal.candidates[0].id;
  res.stale = false;
}

describe("a fresh state put in place", () => {
  it("drops the design point that was on its way for the state before", async () => {
    const stage = held<unknown>();
    mock.stage.mockReturnValueOnce(stage.promise);
    mock.proposal.mockResolvedValueOnce(answers.proposal);
    const old = compute();
    await vi.waitFor(() => expect(mock.stage).toHaveBeenCalledTimes(1));
    applyState(atResults("example-mosfet"));
    stage.give(answers.stage);
    await old;
    await settle();
    expect(res.stage).toBeNull();
    expect(res.proposal).toBeNull();
    expect(app.state.focus).toBe("example-mosfet");
  });
  it("drops the motion that was on its way for the state before, even for the same inputs", async () => {
    answered();
    const cycle = held<Cycle>();
    mock.cycle.mockReturnValueOnce(cycle.promise);
    void deep();
    await vi.waitFor(() => expect(mock.cycle).toHaveBeenCalledTimes(1));
    applyState({ ...app.state });
    expect(res.loading.size).toBe(0);
    cycle.give(answers.cycle as unknown as Cycle);
    await settle();
    expect(res.cycle).toBeNull();
  });
  it("drops the motion asked for the report of the state before, and prints nothing for it", async () => {
    answered();
    const cycle = held<Cycle>();
    mock.cycle.mockReturnValueOnce(cycle.promise);
    const printing = vi.fn();
    vi.stubGlobal("print", printing);
    const old = printReport();
    applyState(atResults("example-mosfet"));
    cycle.give(answers.cycle as unknown as Cycle);
    await old;
    expect(res.cycle).toBeNull();
    expect(printing).not.toHaveBeenCalled();
  });
  it("drops the .md report that was being written for the state before", async () => {
    answered();
    const report = held<{ markdown: string }>();
    mock.report.mockReturnValueOnce(report.promise);
    const old = saveMarkdown();
    expect(ui.savingMd).toBeGreaterThan(0);
    applyState(atResults("example-mosfet"));
    expect(ui.savingMd).toBe(0);
    report.give({ markdown: "# old" });
    await old;
    expect(downloads).toEqual([]);
    expect(ui.savedMd).toBe("");
  });
  it("writes the .md report again after a reset, where the same inputs could stand for another part", async () => {
    answered();
    mock.report.mockResolvedValue({ markdown: "# first" });
    await saveMarkdown();
    expect(mock.report).toHaveBeenCalledTimes(1);
    applyState({ ...app.state });
    answered();
    await saveMarkdown();
    expect(mock.report).toHaveBeenCalledTimes(2);
  });
  it("leaves no Undo standing from the state before", () => {
    app.setup.devices.push({ ...setup.devices[1], id: "mine", name: "Part mine", example: false });
    Object.assign(app.state, { devices: ["mine", "example"], added: ["mine"], step: 0 });
    vi.useFakeTimers();
    renderPanel();
    document.querySelector<HTMLElement>('[data-forget-device="mine"]')!.click();
    expect(ui.forgotten).not.toBeNull();
    applyState(initial(app.setup));
    expect(ui.forgotten).toBeNull();
    expect(document.querySelector("[data-undo-forget]")).toBeNull();
    vi.useRealTimers();
  });
});

describe("the .md report saved again with nothing changed", () => {
  const brought = () => ({ ...setup.devices[1], id: "mine", name: "Part mine", example: false });
  beforeEach(() => {
    app.setup.devices.push(brought());
    Object.assign(app.state, { devices: ["mine"], added: ["mine"], focus: "mine" });
    applyState({ ...app.state }); // nothing written before this test
    res.proposal = { ...(answers.proposal as unknown as Proposal) };
    res.proposal.candidates = [{ ...res.proposal.candidates[0], id: "mine", name: "Part mine" }];
    mock.report.mockResolvedValue({ markdown: "# report" });
  });
  it("is saved from the last one written", async () => {
    await saveMarkdown();
    await saveMarkdown();
    expect(mock.report).toHaveBeenCalledTimes(1);
  });
  it("is written again once the part is brought again under the same name, as a new model", async () => {
    await saveMarkdown();
    mock.addDevice.mockResolvedValue({ device: brought() });
    mock.setup.mockResolvedValue({ ...app.setup, devices: [...app.setup.devices] });
    await addPart({ name: "mine.yaml", text: () => Promise.resolve("model") } as File);
    await saveMarkdown();
    expect(mock.report).toHaveBeenCalledTimes(2);
  });
  it("is written again once the part is taken off and put back", async () => {
    vi.useFakeTimers();
    app.state.step = 0;
    renderPanel();
    await saveMarkdown();
    document.querySelector<HTMLElement>('[data-forget-device="mine"]')!.click();
    document.querySelector<HTMLElement>("[data-undo-forget]")!.click();
    vi.useRealTimers();
    app.state.step = RESULTS;
    await saveMarkdown();
    expect(mock.report).toHaveBeenCalledTimes(2);
  });
});

describe("a question or an Undo of the comparison, pending when a fresh state is put in place", () => {
  const load = (id: string, label: string) =>
    ({ id, label, loadKind: "fan", load: atResults().load, segments: [] }) as State["loadSet"][number];
  const asFile = (state: State) =>
    ({ name: "mine.json", text: () => Promise.resolve(JSON.stringify({ app: "MotionSim", setup: 2, state })) }) as File;
  const button = (attrs: Record<string, string>) => {
    const el = document.createElement("button");
    for (const [k, v] of Object.entries(attrs)) el.dataset[k] = v;
    return el;
  };
  const reset = async (how: string) => {
    if (how === "Reset") {
      clearEverything();
    } else {
      mock.setup.mockResolvedValue(app.setup);
      await openSetup(asFile(atResults()));
    }
  };
  beforeEach(() => {
    Object.assign(shown, { confirm: null, removed: null, editing: null, wrong: {} });
    Object.assign(app.state, { compare: "loads", loadSet: [load("fan-1", "Fan"), load("pump-1", "Conveyor")] });
    renderPanel();
  });

  for (const how of ["Reset", "Open setup"]) {
    it(`asks nothing more after ${how}, and a late answer changes nothing`, async () => {
      addFromMenu(button({ adding: "device" }));
      expect(shown.confirm).not.toBeNull();
      await reset(how);
      expect(shown.confirm).toBeNull();
      expect(document.querySelector("#confirm")).toBeNull();
      const before = JSON.stringify(app.state);
      settleSwitch(button({ switchYes: "" }));
      expect(JSON.stringify(app.state)).toBe(before);
    });

    it(`offers no Undo after ${how}, and the Undo of before puts nothing back`, async () => {
      vi.useFakeTimers();
      removeColumn(button({ colRemove: "pump-1" }));
      expect(shown.removed).not.toBeNull();
      await reset(how);
      expect(shown.removed).toBeNull();
      expect(document.querySelector("[data-undo-column]")).toBeNull();
      undoColumn();
      expect(app.state.loadSet).toEqual([]);
      // The few seconds of the Undo of before run out on the fresh state, with nothing to do.
      vi.advanceTimersByTime(7000);
      expect(app.state.loadSet).toEqual([]);
      expect(shown.removed).toBeNull();
      vi.useRealTimers();
    });

    it(`leaves no small dialog editing a copy of the motor after ${how}`, async () => {
      shown.editing = { kind: "motor", id: null };
      shown.wrong = { "motor.r": "This figure is needed." };
      await reset(how);
      expect(shown.editing).toBeNull();
      expect(shown.wrong).toEqual({});
    });
  }
});
