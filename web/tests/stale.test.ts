// @vitest-environment happy-dom
// Answers and the inputs they are of. An answer on its way while the user changes something
// is never set beside what it was not worked out from: the printed report, the motion, the
// loads of a part, the switching event and its full-screen plot. And the notes about what
// the browser keeps, which stand beside the page's other notes and never in their place.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability", "report"];
  names.push("addDevice", "setup", "event");
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true, forget: vi.fn(), remember: vi.fn() } };
});

import type { Cycle, LoadPreset, Proposal, Setup, Suggest, SwitchingEvent } from "../src/api";
import { api, Refused } from "../src/api";
import { printReport } from "../src/actions/reports";
import { applyState } from "../src/actions/setup";
import { schedule, scheduleDeep } from "../src/engine";
import { deep } from "../src/engine/deep";
import { presetsFor } from "../src/engine/loads";
import { suggestFor } from "../src/engine/suggest";
import { ev, openEvent } from "../src/eventask";
import { eventNow, setSpan, spanOf } from "../src/eventplot/spans";
import { eventView } from "../src/eventplot/view";
import { firstSpan } from "../src/eventplot/zoom";
import { openFull } from "../src/eventplot/full";
import { wire } from "../src/events";
import { shown } from "../src/shown";
import { initial } from "../src/state";
import type { State } from "../src/state";
import { LOAD, RESULTS } from "../src/steps";
import { app, res, ui, verdictOf, focused } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { loadResults } from "../src/views/resultsload";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const suits = fixture("suggest") as Record<string, Suggest>;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;
const event = fixture("event") as SwitchingEvent;
const mock = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function held<T>() {
  let give!: (v: T) => void;
  const promise = new Promise<T>((a) => (give = a));
  return { promise, give };
}
const settle = async () => {
  for (let k = 0; k < 10; k++) await new Promise((r) => setTimeout(r, 0));
};

function atResults(device = "example"): State {
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

beforeEach(() => {
  vi.useRealTimers();
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  vi.stubGlobal("print", () => undefined);
  Element.prototype.scrollIntoView = () => undefined;
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  wire();
  for (const f of Object.values(mock)) if (typeof f.mockReset === "function") f.mockReset();
  for (const n of ["stage", "proposal", "cycle", "loads", "fit", "map", "recommend", "capability", "report", "event"])
    mock[n].mockImplementation(() => new Promise(() => undefined));
  mock.suggest.mockImplementation((id: string) => Promise.resolve(suits[id]));
  app.setup = structuredClone(setup);
  app.state = atResults();
  Object.assign(res, { stage: null, advice: null, proposal: null, cycle: null, blocked: null, fault: null });
  Object.assign(res, { waiting: null, suggestion: null, presets: null, stale: false, offline: false, grid: null });
  res.loading.clear();
  res.started.clear();
  res.cycles.clear();
  res.grids.clear();
  res.resultsOf = "";
  shown.map = false;
  ui.forgotten = null;
  ui.savingMd = 0;
  ui.unsaved = false;
  ui.cleared = false;
});

describe("an answer that lands after its inputs have moved", () => {
  it("is not printed: the report stays empty while its figures are of an earlier design point", async () => {
    answered();
    const cycle = held<Cycle>();
    mock.cycle.mockReturnValueOnce(cycle.promise);
    const printing = printReport();
    await vi.waitFor(() => expect(mock.cycle).toHaveBeenCalledTimes(1));
    // The user moves the design point while the motion for the report is on its way.
    app.state.conditions.rpm += 1234;
    res.stale = true;
    res.cycle = null;
    cycle.give(answers.cycle as unknown as Cycle);
    await printing;
    expect(document.querySelector("#report")?.textContent ?? "").toBe("");
  });

  it("is asked for once when a design figure and the map's range are typed a moment apart", async () => {
    vi.useFakeTimers();
    answered();
    mock.stage.mockImplementation(() => Promise.resolve(answers.stage));
    mock.proposal.mockImplementation(() => Promise.resolve(answers.proposal));
    app.state.conditions.rpm += 100;
    schedule(); // a design figure typed
    vi.advanceTimersByTime(100);
    scheduleDeep(); // the map's range typed 100 ms later, on the timer the first one set
    await vi.advanceTimersByTimeAsync(5000);
    vi.useRealTimers();
    expect(mock.stage).toHaveBeenCalledTimes(1);
  });
});

describe("the motion of the design", () => {
  it("is asked for with parts compared and their maps shown, so the verdict does not wait on it for ever", async () => {
    app.state = atResults("example-mosfet");
    app.state.devices = ["example-mosfet", "example"];
    app.state.added = ["example-mosfet", "example"];
    app.state.tab = "losses";
    answered();
    shown.map = true;
    mock.map.mockImplementation(() => Promise.resolve(answers.map));
    mock.cycle.mockImplementation(() => Promise.resolve(answers.cycle));
    await deep();
    await settle();
    await settle();
    expect(mock.cycle).toHaveBeenCalled();
    expect(verdictOf(focused()!).motion).not.toBe("pending");
  });
});

describe("Reset", () => {
  it("forgets the switching event: its panel, its answer and the span it was zoomed to", async () => {
    answered();
    openEvent("on");
    // The event is drawn, and zoomed, only once the code that draws it has come.
    await loadResults();
    ev.answer = event;
    ev.key = "k";
    eventView(event, "on");
    setSpan("on", { t0: 1e-9, t1: 3e-9 });
    expect(spanOf("on", event.turn_on)).not.toEqual(firstSpan(event.turn_on));
    applyState(initial(app.setup));
    expect(ev.open).toBe(false);
    expect(ev.answer).toBeNull();
    expect(eventNow()).toBeNull();
    expect(spanOf("on", event.turn_on)).toEqual(firstSpan(event.turn_on));
  });
});

describe("the loads offered for a part", () => {
  it("are sized again once the part's application is known, when they landed before it", async () => {
    // The made-up part opens on its application (a drum), which is not the first load offered for its motor.
    const id = "example";
    const suit = {
      ...suits[id],
      application: { id: "drum", label: "Washing machine", start: "sensor", supply: "one-way" },
    } as Suggest;
    const offered = answers.loads.loads as LoadPreset[];
    expect(offered[0].id).not.toBe("drum");
    app.state = atResults(id);
    app.state.step = LOAD;
    // A visit where what suits the part came first, then the loads.
    mock.suggest.mockResolvedValue(suit);
    mock.loads.mockResolvedValue({ loads: offered });
    await suggestFor();
    await presetsFor();
    await settle();
    expect(app.state.loadKind).toBe("drum");
    // A reload, or a setup opened: both are asked at once, and the loads answer first.
    res.suggestion = null;
    res.presets = null;
    const suggest = held<Suggest>();
    mock.suggest.mockReturnValue(suggest.promise);
    void suggestFor();
    void presetsFor();
    await settle();
    suggest.give(suit);
    await settle();
    await settle();
    expect(app.state.loadKind).toBe("drum");
  });
});

describe("the full-screen plot of an edge", () => {
  it("says in its heading the event it draws, when a later answer is drawn behind it", () => {
    eventView(event, "on");
    document.body.insertAdjacentHTML("beforeend", `<div data-edge-plot="on"></div>`);
    openFull("on", "vi");
    expect(document.querySelector("#ev-full-said")!.textContent).not.toContain("ANOTHER PART");
    const later = { ...structuredClone(event), v_dc: 999, current: 1, name: "ANOTHER PART" };
    later.turn_on.i_peak = 0.5;
    eventView(later, "on"); // a later answer, drawn on the page behind the dialog
    const plot = document.querySelector<HTMLElement>("[data-full-plot]")!;
    plot.dispatchEvent(new KeyboardEvent("keydown", { key: "0", bubbles: true }));
    expect(document.querySelector("#ev-full-said")!.textContent).toContain("ANOTHER PART");
  });
});

describe("a note that the browser keeps nothing", () => {
  it("stands beside the refusal, the setup note and Try again, never in their place", () => {
    answered();
    app.state.step = 2;
    res.blocked = new Refused("the supply is below what the motor needs", "raise it", "v_dc");
    ui.setupNote = { bad: true, text: "x.json names a part it does not carry" };
    ui.fetchFault = { what: "report", text: "The printed report could not be fetched" };
    const banner = () => document.querySelector("#banner")!.textContent;
    const others = ["x.json names a part it does not carry", "The printed report could not be fetched"];
    renderPanel();
    const plain = banner();
    for (const text of others) expect(plain).toContain(text);
    for (const kept of [
      { unsaved: true, cleared: false },
      { unsaved: false, cleared: true },
    ]) {
      Object.assign(ui, kept);
      renderPanel();
      for (const text of others) expect(banner(), JSON.stringify(kept)).toContain(text);
      expect(banner().length, JSON.stringify(kept)).toBeGreaterThan(plain.length);
      expect(document.querySelector("[data-retry-fetch]"), JSON.stringify(kept)).not.toBeNull();
    }
  });
});
