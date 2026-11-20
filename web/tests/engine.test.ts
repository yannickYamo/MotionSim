import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Candidate, Cycle, Proposal, Setup, Suggest } from "../src/api";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn()]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true } };
});

import { api, NotWorkedOut, Refused, Unreachable } from "../src/api";
import { compute } from "../src/engine";
import { loadFor, presetsFor } from "../src/engine/loads";
import { suggestFor } from "../src/engine/suggest";
import { shown } from "../src/shown";
import { initial } from "../src/state";
import { app, res, ui, verdictOf } from "../src/store";
import { LOAD, RESULTS } from "../src/steps";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const setup = fixture("setup") as Setup;
const suits = fixture("suggest") as Record<string, Suggest>;
const mock = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

/** A promise settled by hand, to let answers arrive in any order. */
function held<T>() {
  let give!: (v: T) => void;
  let fail!: (e: Error) => void;
  const promise = new Promise<T>((a, b) => {
    give = a;
    fail = b;
  });
  return { promise, give, fail };
}
const candidate = (id: string, loss: number): Candidate =>
  ({
    id,
    name: id,
    level: "ok",
    checks: [],
    needs: [],
    result: { loss, tj_peak: 80, tj_max: 150 },
  }) as unknown as Candidate;
const proposal = (id: string, loss: number) =>
  ({ candidates: [candidate(id, loss)], explain: [], level: 0.05 }) as unknown as Proposal;
const stage = { stage: { i_peak: 1, positions: 6 }, advice: null };

beforeEach(() => {
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  for (const f of Object.values(mock)) if (typeof f.mockReset === "function") f.mockReset();
  app.setup = setup;
  app.state = initial(setup);
  Object.assign(res, { stage: null, advice: null, proposal: null, blocked: null, fault: null, waiting: null });
  Object.assign(res, { suggestion: null, presets: null, cycle: null, stale: false, offline: false });
  ui.followed = null;
  mock.suggest.mockImplementation((id: string): Promise<Suggest> => Promise.resolve(suits[id]));
  mock.stage.mockResolvedValue(stage);
});

describe("what suits the device under test", () => {
  it("is asked once while the asking is on its way", async () => {
    const answer = held<Suggest>();
    mock.suggest.mockReturnValue(answer.promise);
    app.state.devices = ["example"];
    const all = [suggestFor(), suggestFor(), suggestFor()];
    answer.give(suits.example);
    await Promise.all(all);
    expect(mock.suggest).toHaveBeenCalledTimes(1);
    expect(res.suggestion?.id).toBe("example");
  });
  it("is dropped when it arrives for a device that is no longer under test", async () => {
    const first = held<Suggest>();
    mock.suggest.mockImplementation((id: string): Promise<Suggest> =>
      id === "example-mosfet" ? first.promise : Promise.resolve(suits[id]),
    );
    app.state.devices = ["example-mosfet"];
    const slow = suggestFor();
    // The user swaps the part while the first answer is still on its way.
    app.state.devices = ["example"];
    await suggestFor();
    expect(app.state.conditions.v_dc).toBe(400);
    first.give(suits["example-mosfet"]);
    await slow;
    expect(res.suggestion?.id).toBe("example");
    expect(app.state.conditions.v_dc).toBe(400); // the late answer changed nothing
  });
  it("is never moved by a device added to compare, in either order of adding", async () => {
    const shape = () => JSON.stringify([app.state.kind, app.state.conditions, app.state.motors]);
    for (const [first, second] of [
      ["example-mosfet", "example"],
      ["example", "example-mosfet"],
    ]) {
      app.state = initial(setup);
      res.suggestion = null;
      app.state.devices = [first];
      await suggestFor();
      // The design starts where the first part's own suggestion puts it.
      expect(app.state.conditions.v_dc).toBe(suits[first].motors[app.state.kind].start.v_dc);
      app.state.conditions.rpm = 1234;
      app.state.pointOf = { pmsm: { rpm: 1234 } };
      const alone = shape();
      app.state.devices = [first, second]; // a second device, to compare on this design
      await suggestFor();
      expect(shape(), `${second} added to ${first}`).toBe(alone);
      expect(app.state.lead).toBe(first);
    }
  });
  it("follows another device when the one it started from is unticked", async () => {
    app.state.devices = ["example-mosfet", "example"];
    app.state.lead = "example-mosfet";
    await suggestFor();
    expect(app.state.conditions.v_dc).toBe(suits["example-mosfet"].motors[app.state.kind].start.v_dc);
    app.state.devices = ["example"];
    await suggestFor();
    expect(app.state.conditions.v_dc).toBe(suits.example.motors[app.state.kind].start.v_dc);
    expect(app.state.lead).toBe("example");
  });
  it("says what moved only once the user has seen the figures that moved", async () => {
    app.state.devices = ["example"];
    await suggestFor();
    expect(ui.followed).toBeNull(); // still on the first step: nothing they saw has changed
    app.state.reached = LOAD;
    app.state.devices = ["example-mosfet"];
    await suggestFor();
    expect(ui.followed?.changes.map((c) => c.path)).toContain("conditions.v_dc");
  });
});

describe("the design point", () => {
  const ready = () => {
    app.state.devices = ["example"];
    app.state.reached = RESULTS;
    app.state.step = LOAD;
  };
  it("keeps the answer of the latest asking, whichever comes back last", async () => {
    ready();
    const slow = held<Proposal>();
    mock.proposal.mockReturnValueOnce(slow.promise).mockResolvedValueOnce(proposal("example", 22));
    const first = compute();
    await vi.waitFor(() => expect(mock.proposal).toHaveBeenCalledTimes(1));
    await compute();
    slow.give(proposal("example", 11));
    await first;
    expect(res.proposal?.candidates[0].result?.loss).toBe(22);
  });
  it("keeps the last figures, as from before, when the engine fails, and asks it nothing more", async () => {
    ready();
    mock.proposal.mockResolvedValue(proposal("example", 11));
    await compute();
    const before = res.proposal;
    expect(before).not.toBeNull();
    mock.stage.mockRejectedValue(new Error("the engine answered 500"));
    mock.cycle.mockClear();
    await compute();
    // No answer is not a refusal: the figures stay, marked by the fault as from before.
    expect(res.proposal).toBe(before);
    expect(res.blocked).toBeNull();
    expect(res.fault).toBe("the engine answered 500");
    expect(res.stale).toBe(false);
    expect(mock.cycle).not.toHaveBeenCalled();
  });
  it("keeps the last figures only as from before when the inputs moved before the engine failed", async () => {
    ready();
    app.state.step = RESULTS;
    mock.proposal.mockResolvedValue(proposal("example", 11));
    mock.cycle.mockResolvedValue({ summary: {}, checks: [] });
    await compute();
    await vi.waitFor(() => expect(res.cycle).not.toBeNull());
    const before = res.proposal;
    app.state.conditions.rpm += 500; // the inputs move, and their answer does not come
    mock.stage.mockRejectedValue(new Error("the engine answered 500"));
    mock.cycle.mockClear();
    await compute();
    // The figures stay, for the page to show dimmed and said to be from before; nothing
    // worked out over them for the inputs as they were is kept, and nothing more is asked.
    expect(res.proposal).toBe(before);
    expect(res.fault).toBe("the engine answered 500");
    expect(res.blocked).toBeNull();
    expect(res.cycle).toBeNull();
    expect(mock.cycle).not.toHaveBeenCalled();
  });
  it("keeps the design point's verdict when the motion has no answer, said as not worked out", async () => {
    ready();
    app.state.step = RESULTS;
    mock.proposal.mockResolvedValue(proposal("example", 11));
    mock.cycle.mockRejectedValue(new Unreachable());
    await compute();
    await vi.waitFor(() => expect(res.cycle).not.toBeNull());
    expect(res.cycle).toBeInstanceOf(NotWorkedOut);
    expect(res.fault).toBeNull();
    expect(res.proposal?.candidates[0].result?.loss).toBe(11);
    expect(verdictOf(res.proposal!.candidates[0])).toEqual({ level: "ok", motion: "unworked", why: null });
  });
  it("leaves no earlier verdict standing when the design is refused, and says so in plain words", async () => {
    ready();
    mock.proposal.mockResolvedValue(proposal("example", 11));
    await compute();
    mock.stage.mockRejectedValue(new Refused("switching frequency cannot be below 100", "raise it", "f_sw"));
    await compute();
    expect(res.proposal).toBeNull();
    expect(res.blocked?.reason).toBe("switching frequency cannot be below 0.100 kHz");
    expect(res.blocked?.field).toBe("f_sw");
  });
  it("waits for a figure the cooling needs, and asks the engine nothing meanwhile", async () => {
    ready();
    app.state.conditions.cooling = "heatsink";
    await compute();
    expect(mock.stage).not.toHaveBeenCalled();
    expect(res.waiting?.field).toBe("rth_sink");
    expect(res.blocked).toBeNull();
    app.state.conditions.cooling = "board";
    await compute();
    expect(res.waiting?.field).toBe("board_area");
    app.state.conditions.board_area = "40";
    mock.proposal.mockResolvedValue(proposal("example", 11));
    await compute();
    expect(res.waiting).toBeNull();
    expect(mock.stage).toHaveBeenCalledTimes(1);
  });
  it("is worked out only after the motor has settled on the device under test", async () => {
    ready();
    mock.proposal.mockResolvedValue(proposal("example", 11));
    await compute();
    const sent = mock.stage.mock.calls[0][0] as { conditions: { v_dc: number } };
    expect(sent.conditions.v_dc).toBe(400);
  });
});

describe("the loads usual for a motor", () => {
  const list = [{ id: "fan" }, { id: "joint" }, { id: "drum" }] as never[];
  it("start from the user's pick where the motor is offered it, else the usual one", () => {
    expect(loadFor(list, "joint")).toEqual({ id: "joint" });
    expect(loadFor(list, "")).toEqual({ id: "fan" });
    expect(loadFor(list, "vehicle")).toEqual({ id: "fan" });
    expect(loadFor([], "fan")).toBeUndefined();
  });
  it("are not asked for again and again when the engine fails", async () => {
    mock.loads.mockRejectedValue(new Error("500"));
    await presetsFor();
    await new Promise((r) => setTimeout(r, 50));
    expect(mock.loads).toHaveBeenCalledTimes(1);
    expect(res.presets).toBeNull();
  });
  it("are asked for again when the motor is settled while they are on their way", async () => {
    // The load step is opened while the motor's figures are still being fitted to the supply:
    // the loads come back for the motor as it was, and are asked for again for the one it is.
    const first = held<{ loads: never[] }>();
    mock.loads.mockReturnValueOnce(first.promise).mockResolvedValue({ loads: list });
    app.state.step = LOAD;
    app.state.loadTouched = true; // figures of the user's own: the list alone is looked at
    const asked = presetsFor();
    app.state.motors = { ...app.state.motors, [app.state.kind]: { ...app.state.motors[app.state.kind], rs: 0.5 } };
    first.give({ loads: [{ id: "conveyor" }] as never[] });
    await asked;
    await new Promise((r) => setTimeout(r, 0));
    expect(mock.loads).toHaveBeenCalledTimes(2);
    expect(mock.loads.mock.calls[1][4]).toMatchObject({ rs: 0.5 });
    expect(res.presets?.list.map((p) => p.id)).toEqual(["fan", "joint", "drum"]);
  });
});

describe("the verdict on the device on the drawing", () => {
  const cycle = (levels: string[]) =>
    ({
      checks: levels.map((level) => ({ level, topic: "motion", message: "the motor cannot follow part of it" })),
    }) as Cycle;
  beforeEach(() => {
    app.state.devices = ["example"];
    app.state.focus = "example";
    res.proposal = proposal("example", 11);
  });
  const c = () => res.proposal!.candidates[0];
  it("is not final while the motion has not been followed", () => {
    res.cycle = null;
    expect(verdictOf(c())).toEqual({ level: "ok", motion: "pending", why: null });
  });
  it("is the design point's when nothing fails over the motion, a caution there included", () => {
    res.cycle = cycle(["ok", "ok"]);
    expect(verdictOf(c())).toEqual({ level: "ok", motion: "followed", why: null });
    res.cycle = cycle(["ok", "caution", "undecided"]);
    expect(verdictOf(c())).toEqual({ level: "ok", motion: "followed", why: null });
  });
  it("fails when a check over the motion fails, however well the design point passes", () => {
    res.cycle = cycle(["ok", "caution", "fail"]);
    const v = verdictOf(c());
    expect(v.level).toBe("fail");
    expect(v.why).toBe("motion: the motor cannot follow part of it");
  });
  it("fails when the motion is refused outright", () => {
    res.cycle = new Refused("the motor cannot reach that speed", "", "motion");
    expect(verdictOf(c())).toMatchObject({
      level: "fail",
      motion: "refused",
      why: "the motor cannot reach that speed",
    });
  });
  it("is the design point's alone for a device that is not on the drawing", () => {
    res.cycle = cycle(["fail"]);
    expect(verdictOf(candidate("another", 5)).level).toBe("ok");
  });
});

describe("a figure the cooling needs and has not been given", () => {
  it("is asked for at its box, not called a failure, for a module with no heatsink", async () => {
    app.state.devices = ["example"];
    app.state.reached = RESULTS;
    app.state.step = LOAD;
    app.state.conditions.cooling = "none";
    mock.stage.mockRejectedValue(
      new Refused("with no heatsink, the thermal resistance from junction to air is needed", "", "rth_ja"),
    );
    await compute();
    expect(res.blocked).toBeNull();
    expect(res.fault).toBeNull();
    expect(res.waiting?.field).toBe("rth_ja");
    expect(res.waiting?.reason).toMatch(/^a module is built to sit on a heatsink/);
  });
  it("is a refusal once a figure is in the box and the engine still will not take it", async () => {
    app.state.devices = ["example"];
    app.state.reached = RESULTS;
    app.state.step = LOAD;
    app.state.conditions.cooling = "none";
    app.state.conditions.rth_ja = "0.1";
    mock.stage.mockRejectedValue(new Refused("junction to air of 0.1 K/W is not above this part's", "", "rth_ja"));
    await compute();
    expect(res.blocked?.field).toBe("rth_ja");
    expect(res.waiting).toBeNull();
  });
});

describe("a local server that stops answering", () => {
  it("is said plainly, with the inputs kept, and asked again until it answers", async () => {
    vi.useFakeTimers();
    try {
      app.state.devices = ["example-mosfet"];
      app.state.reached = RESULTS;
      mock.stage.mockRejectedValue(new Unreachable());
      await compute();
      expect(res.offline).toBe(true);
      expect(res.fault).toBe(
        "The local motionsim server is not answering. Start it again with motionsim serve; your inputs are kept.",
      );
      expect(app.state.devices).toEqual(["example-mosfet"]);
      // Back again: the next asking, two seconds on, finds it.
      mock.stage.mockResolvedValue(stage);
      mock.proposal.mockResolvedValue(proposal("example-mosfet", 9));
      await vi.advanceTimersByTimeAsync(2100);
      expect(res.offline).toBe(false);
      expect(res.fault).toBeNull();
      expect(res.proposal?.candidates[0].id).toBe("example-mosfet");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("an answer for the results", () => {
  it("redraws the readouts and the verdict as well as the panel, since both read the motion", async () => {
    const { deep } = await import("../src/engine/deep");
    const { draw } = await import("../src/store");
    Object.assign(app.state, { devices: ["example"], focus: "example", reached: RESULTS, step: RESULTS });
    Object.assign(res, { stage: stage.stage, proposal: proposal("example", 40) });
    const motion = { summary: { peak: 95 }, checks: [], p_stage: [1] } as unknown as Cycle;
    mock.cycle.mockResolvedValue(motion);
    mock.capability.mockResolvedValue({});
    mock.map.mockResolvedValue({});
    mock.recommend.mockResolvedValue({ items: [] });
    const seen: unknown[] = [];
    const before = draw.stage;
    draw.stage = () => void seen.push(res.cycle);
    try {
      await deep();
      await vi.waitFor(() => expect(seen).toContain(motion));
    } finally {
      draw.stage = before;
    }
  });
});

describe("changing only what is compared", () => {
  it("keeps the design's own map, and does not ask for it again", async () => {
    const { deep } = await import("../src/engine/deep");
    Object.assign(app.state, {
      devices: ["example"],
      focus: "example",
      reached: RESULTS,
      step: RESULTS,
      tab: "losses",
    });
    shown.map = true;
    Object.assign(res, { stage: stage.stage, proposal: proposal("example", 40) });
    const grid = { rpm: [1], torque: [1], loss: [[1]], tj: [[50]] };
    mock.cycle.mockResolvedValue({ summary: { peak: 95 }, checks: [], p_stage: [1] });
    mock.map.mockResolvedValue(grid);
    mock.recommend.mockResolvedValue({ items: [] });
    mock.capability.mockResolvedValue({});
    await deep();
    await vi.waitFor(() => expect(res.grid).toEqual(grid));
    const asked = mock.map.mock.calls.length;
    for (const compare of ["loads", "motors", "sweep", "devices"] as const) {
      app.state.compare = compare;
      await deep();
      expect(res.grid, compare).toEqual(grid);
    }
    expect(mock.map.mock.calls.length).toBe(asked);
    app.state.conditions.v_dc += 1; // a change to the design itself is worked out again
    await deep();
    await vi.waitFor(() => expect(mock.map.mock.calls.length).toBeGreaterThan(asked));
  });
});
