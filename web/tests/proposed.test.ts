// @vitest-environment happy-dom
// The load proposed for the part: put in as the load of step 4 while the load is not the
// user's own, never over figures they typed; the usual load one press away and back; a load
// of the user's own set against the proposal by its motion; and the results saying which
// load they are of.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Cycle, LoadPreset, LoadProposal, Setup } from "../src/api";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability"];
  const api = Object.fromEntries([...names, "loadProposal"].map((n) => [n, vi.fn()]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true } };
});

import { api } from "../src/api";
import { applyPreset } from "../src/engine/loads";
import { feedbackFor, forgetProposal, isProposed, propose, proposed } from "../src/engine/proposed";
import { onClick } from "../src/events/presses";
import { initial } from "../src/state";
import { LOAD, RESULTS } from "../src/steps";
import { app, res, ui } from "../src/store";
import { against, junctionSaid } from "../src/views/proposed";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { loadResults } from "../src/views/resultsload";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;
const mock = api as unknown as Record<string, ReturnType<typeof vi.fn>>;
const presets = answers.loads.loads as LoadPreset[];
const joint = presets.find((p) => p.id === "joint")!;

/** The joint's load made twice as heavy, as the engine proposes it. */
const proposal: LoadProposal = {
  application: "joint",
  label: joint.label,
  scale: 2,
  open: false,
  preset: { ...joint, load: { ...joint.load, inertia: 2 * joint.load.inertia!, friction_coulomb: 8 } },
  binding: {
    limit: "motor current",
    words: "the motor's current limit",
    check: "the motor cannot follow part of this motion: 9.6 N·m at 1500 rpm needs 64.2 A rms",
    level: "fail",
    scale: 2.04,
  },
  margin: { wanted: 25, junction: 79 },
  figures: {
    peak_torque: 10,
    rms_torque: 6,
    top_rpm: 1500,
    i_peak: 88,
    tj_peak: 80,
    tj_top: 96,
    tj_max: 175,
    points: [],
  },
  usual: null,
  checks: [],
  why: "The robot joint load made 2 times as heavy as the usual one.",
};

const cycle = answers.cycle as unknown as Cycle;

/** A motion of the user's own load: its torque `k` times the proposal's peak, its junction
 *  at `tj`, with these checks. */
const own = (k: number, tj: number, checks: Cycle["checks"] = []): Cycle => ({
  ...cycle,
  torque: [0, 10 * k, 5],
  summary: { ...cycle.summary, peak: tj, peak_top: tj, tj_max: 175, rms_torque: 6 * k },
  checks,
});

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example"], added: ["example"], lead: "example", reached: 4 });
  ui.notes.clear();
  Object.assign(res, { stage: answers.stage.stage, advice: answers.stage.advice, proposal: answers.proposal });
  res.presets = { key: "k", list: presets };
  res.blocked = res.fault = res.waiting = null;
  res.cycle = null;
  res.stale = false;
  forgetProposal();
  for (const f of Object.values(mock)) if (typeof f === "function" && "mockReset" in f) f.mockReset();
  mock.loadProposal.mockResolvedValue(proposal);
  applyPreset(joint);
  app.state.step = LOAD;
});

describe("the load proposed for the part", () => {
  it("is offered beside the duty, labelled as a proposal, and never put in for the user", async () => {
    await propose("joint", applyPreset);
    expect(mock.loadProposal).toHaveBeenCalledTimes(1);
    const body = mock.loadProposal.mock.calls[0][0];
    expect(body).toMatchObject({ device: "example", application: "joint" });
    expect(body).not.toHaveProperty("load"); // what it proposes is no part of what it is asked
    // The duty stands: the usual load is the load until the user takes the proposal.
    expect(app.state.load.inertia).toBe(joint.load.inertia);
    expect(isProposed()).toBe(false);
    renderPanel();
    const offered = document.querySelector("#load-proposal")!.textContent.replace(/\s+/g, " ");
    expect(offered).toContain("proposal This part carries up to 2× this load, limited by the motor's current limit");
    expect(document.querySelector("[data-proposed-load]")!.textContent).toBe("Use 2×");
    // One press puts it in, said as the proposal in use, with what limits it.
    onClick({ target: document.querySelector("[data-proposed-load]") } as unknown as Event);
    expect(app.state.load.inertia).toBe(2 * joint.load.inertia!);
    expect(app.state.load.friction_coulomb).toBe(8);
    expect(isProposed()).toBe(true);
    renderPanel();
    const said = document.querySelector("#load-proposal")!.textContent.replace(/\s+/g, " ");
    expect(said).toContain("proposal in use Robot joint, 2× the usual load");
    // The margin is from the top of the thermal assumptions' band, and said beside it: 175 − 96 = 79.
    expect(said).toContain(
      "limited by the motor's current limit, with the junction peaking at 80 °C " +
        "(up to 96 °C across the thermal assumptions), 79 K under its 175 °C rating",
    );
    // Said once, and its figures written as every figure on the page is: thousands set apart.
    expect(said.match(/°C rating/g)).toHaveLength(1);
    expect(document.querySelector(".proposed-figures")!.textContent).toContain("1\u202f500 rpm");
    expect(document.querySelector("[data-usual-load]")).not.toBeNull();
    // The same design is asked once.
    await propose("joint", applyPreset);
    expect(mock.loadProposal).toHaveBeenCalledTimes(1);
  });

  it("says at once that it is on its way, and the usual load stands meanwhile", async () => {
    let give!: (p: LoadProposal) => void;
    mock.loadProposal.mockReturnValue(new Promise<LoadProposal>((ok) => (give = ok)));
    renderPanel();
    const asked = propose("joint", applyPreset);
    expect(document.querySelector("#load-proposal .waiting")?.textContent).toContain(
      "Finding how much of this robot joint load the part carries",
    );
    expect(app.state.load.inertia).toBe(joint.load.inertia);
    give(proposal);
    await asked;
    // It comes as an offer: the duty stays the load.
    expect(app.state.load.inertia).toBe(joint.load.inertia);
  });

  it("is never put in over figures the user typed", async () => {
    app.state.loadTouched = true;
    app.state.load.inertia = 5;
    await propose("joint", applyPreset);
    expect(app.state.load.inertia).toBe(5);
    expect(isProposed()).toBe(false);
  });

  it("gives way to the usual load at one press, and comes back at another", async () => {
    await propose("joint", applyPreset);
    renderPanel();
    onClick({ target: document.querySelector("[data-proposed-load]") } as unknown as Event);
    expect(app.state.load.inertia).toBe(2 * joint.load.inertia!);
    renderPanel();
    onClick({ target: document.querySelector("[data-usual-load]") } as unknown as Event);
    expect(app.state.loadUsual).toBe(true);
    expect(app.state.loadTouched).toBe(false);
    expect(app.state.load.inertia).toBe(joint.load.inertia);
    expect(document.querySelector("#load-proposal")!.textContent).toContain("This part carries up to 2×");
    // Asked again for the same design, the usual load stays: it was the user's choice.
    await propose("joint", applyPreset);
    expect(app.state.load.inertia).toBe(joint.load.inertia);
    onClick({ target: document.querySelector("[data-proposed-load]") } as unknown as Event);
    expect(app.state.loadUsual).toBe(false);
    expect(app.state.load.inertia).toBe(2 * joint.load.inertia!);
  });
});

describe("where a junction stands against its rating", () => {
  it("takes the distance from the figures written, so the two always add up", () => {
    // 175 − 95.5 is 79.5, which would round to 80 beside a 96 °C written: 175 − 96 is 79.
    expect(junctionSaid(79.4, 95.5, 175)).toEqual({
      text: "79 °C (up to 96 °C across the thermal assumptions), 79 K under its 175 °C rating",
      room: 79,
    });
    expect(junctionSaid(120.2, 120.4, 150).text).toBe("120 °C, 30 K under its 150 °C rating");
    expect(junctionSaid(170, 181, 175)).toEqual({
      text: "170 °C (up to 181 °C across the thermal assumptions), 6 K over its 175 °C rating",
      room: -6,
    });
  });
});

describe("a load of the user's own, set against the proposal", () => {
  it("is said by its torque against the proposal's and where its junction gets to", () => {
    expect(against(proposal, own(1.18, 168)).text).toBe(
      "+18% torque over the proposal: the junction reaches 168 °C, 7 K under its 175 °C rating, " +
        "inside the 25 K margin.",
    );
    expect(against(proposal, own(1.18, 168)).level).toBe("caution");
    expect(against(proposal, own(0.5, 70)).text).toBe(
      "50% less torque than the proposal: the junction reaches 70 °C, 105 K under its 175 °C rating.",
    );
    const failing = own(1.3, 120, [{ level: "fail", topic: "motion", message: "the motor cannot follow it" }]);
    expect(against(proposal, failing)).toEqual({
      level: "fail",
      text:
        "+30% torque over the proposal: the junction reaches 120 °C, 55 K under its 175 °C rating. " +
        "Does not pass: the motor cannot follow it.",
    });
  });

  it("is followed through its motion once the user edits it, and the step says how it stands", async () => {
    await propose("joint", applyPreset);
    app.state.loadTouched = true;
    app.state.load.inertia = 9;
    mock.cycle.mockResolvedValue(own(1.18, 168));
    await feedbackFor();
    expect(mock.cycle).toHaveBeenCalledTimes(1);
    expect(mock.cycle.mock.calls[0][0].load.inertia).toBe(9);
    renderPanel();
    const box = document.querySelector("#load-proposal")!;
    expect(box.querySelector(".proposed-against")!.textContent).toContain("+18% torque over the proposal");
    expect(box.querySelector("[data-proposed-load]")).not.toBeNull();
    // Asked once for the same load.
    await feedbackFor();
    expect(mock.cycle).toHaveBeenCalledTimes(1);
    expect(proposed.feedback?.cycle).not.toBeNull();
  });
});

describe("the results", () => {
  it("say the load is the duty or the one proposed, and what limits it", async () => {
    await loadResults();
    await propose("joint", applyPreset);
    Object.assign(app.state, { step: RESULTS, tab: "proposal", focus: "example" });
    res.cycle = cycle;
    renderPanel();
    // The duty, with what the part could carry beside it: assumed until the user sets it, and
    // for a part alone said as its third key figure, once.
    const said = () =>
      document.querySelector(".results-load")?.textContent ?? document.querySelector(".key-figures")!.textContent;
    const alone = !!document.querySelector(".candidate.alone");
    if (alone) {
      expect(said()).toContain("Load margin2×limit: the motor's current limit");
      expect(document.querySelector(".results-load")).toBeNull();
    } else {
      expect(said()).toContain(
        "Assumed duty: the usual robot joint load. This part carries up to 2×, limited by the motor's current limit",
      );
    }
    app.state.loadUsual = false;
    renderPanel();
    if (alone) expect(said()).toContain("Load margin2×limit: the motor's current limit");
    else
      expect(said()).toContain(
        "The load is the one proposed for this part: 2× the usual robot joint load, " +
          "limited by the motor's current limit",
      );
  });

  it("set a load of the user's own against the proposal", async () => {
    await loadResults();
    await propose("joint", applyPreset);
    Object.assign(app.state, { step: RESULTS, tab: "proposal", focus: "example", loadTouched: true });
    res.cycle = own(1.18, 168);
    renderPanel();
    expect(document.querySelector(".results-load")!.textContent).toContain(
      "Your load. +18% torque over the proposal: the junction reaches 168 °C, 7 K under its 175 °C rating",
    );
  });
});
