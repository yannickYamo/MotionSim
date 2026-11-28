// @vitest-environment happy-dom
// A motion the motor can follow only in part: the verdict carries that reason, the
// figures of the motion are said to be of the part that was followed or withheld, the
// checks that pass are said to be the design point's, and the readout says which junction
// it gives.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Cycle, Setup } from "../src/api";
import { initial } from "../src/state";
import { app, res, ui, verdictOf } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";
import { renderStage } from "../src/views/stage";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;

function partly(): Cycle {
  const cycle = structuredClone(answers.cycle) as unknown as Cycle;
  cycle.p_stage = cycle.p_stage.map((p, k) => (k % 2 ? null : p));
  cycle.summary.peak = 141.2;
  cycle.checks = [
    { level: "fail", topic: "current", message: "the drive trips at 40 A" },
    { level: "fail", topic: "motion", message: "the motor cannot follow part of this motion: it needs 60 A" },
    { level: "ok", topic: "voltage", message: "the link stays under its rating" },
  ];
  return cycle;
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example-mosfet"], added: ["example-mosfet"], reached: 4, step: 4 });
  Object.assign(app.state, { focus: "example-mosfet" });
  const proposal = structuredClone(answers.proposal) as { candidates: { id: string }[] };
  proposal.candidates = proposal.candidates.filter((c) => c.id === "example-mosfet");
  Object.assign(res, { stage: answers.stage.stage, advice: null, proposal, cycle: partly() });
  res.blocked = res.fault = res.waiting = null;
  res.stale = false;
  ui.notes.clear();
});

describe("a motion followed in part", () => {
  it("rules the part out for the motion's own reason, not for a trip", () => {
    const v = verdictOf(res.proposal!.candidates[0]);
    expect(v.level).toBe("fail");
    expect(v.why).toMatch(/^motion: the motor cannot follow part of this motion/);
  });
  it("says the hottest junction is of the part followed, and gives no life", () => {
    app.state.tab = "motion";
    renderPanel();
    const text = document.querySelector("#tab-body")!.textContent;
    expect(text).toContain("In the part it can, the hottest junction reaches 141 °C; the rest is not known.");
    expect(text).toContain("Not given: the motor cannot follow part of this motion");
    expect(text).not.toMatch(/repeats of this motion/);
  });
  it("says the checks that pass are the design point's", () => {
    app.state.tab = "proposal";
    renderPanel();
    expect(document.querySelector("#tab-body")!.textContent).toMatch(/checks? pass(es)? at the design point/);
  });
  it("names the readout's junction as the design point's where the motion differs", () => {
    renderStage();
    const text = document.querySelector("#readouts")!.textContent;
    expect(text).toContain("Tj peak, design point");
    expect(text).toContain("through the motion, in the part followed: 141 °C");
  });
  it("off the results, gives the readout as a reload does: the motion is followed only on the results", () => {
    // A motion kept from a visit to the results is not asked for again after a reload until
    // the results are opened, so off them the readout does not lean on it.
    app.state.step = 1;
    renderStage();
    const text = document.querySelector("#readouts")!.textContent;
    expect(text).not.toContain("design point");
    expect(text).not.toContain("through the motion");
    res.cycle = null;
    renderStage();
    expect(document.querySelector("#readouts")!.textContent).toBe(text);
  });
});
