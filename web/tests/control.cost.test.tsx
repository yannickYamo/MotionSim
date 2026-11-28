// @vitest-environment happy-dom
// The cost of a run's control, read first: a figure the run did not model is said to be so,
// never drawn as nought, and a change is shown only where there is something to set it against.
import { act } from "@testing-library/react";
import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CostView, valueOf } from "../src/control/costview";
import { lab } from "../src/control/store";
import type { Run } from "../src/control/types";
import holdFile from "./fixtures/control-run-hold.json";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

let host: HTMLElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  lab.reset();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function shown(run: Run): Record<string, string> {
  act(() => root.render(createElement(CostView, { run, name: "test" })));
  const out: Record<string, string> = {};
  host.querySelectorAll(".lab-headline .readout").forEach((r) => {
    out[r.querySelector("dt")!.textContent ?? ""] = r.querySelector("dd")!.textContent ?? "";
  });
  return out;
}

describe("the cost of this control", () => {
  it("says an averaged run's switching loss was not modelled, and that its loss is conduction alone", () => {
    const run = copy(holdFile) as unknown as Run;
    run.fidelity = "averaged";
    run.losses = { ...run.losses, switching: 0 };
    const figures = shown(run);
    expect(figures.Switching).toContain("Not modelled when averaged");
    expect(figures.Switching).not.toMatch(/^0 W/);
    expect(figures["Power-stage loss"]).toContain("Conduction alone");
  });

  it("says an averaged run's edges, and the ripple they make, were not modelled, never nought", () => {
    const run = copy(holdFile) as unknown as Run;
    run.fidelity = "averaged";
    run.channels = { ...run.channels, commutations_per_s: 0, i_at_commutation: 0, ripple_pp: null };
    const figures = shown(run);
    expect(figures["Current ripple, peak to peak"]).toContain("Not modelled when averaged");
    const cells: Record<string, string> = {};
    host.querySelectorAll(".lab-more tbody tr").forEach((tr) => {
      cells[tr.querySelector("th, td")!.textContent ?? ""] = tr.querySelectorAll("td")[0]?.textContent ?? "";
    });
    expect(cells["Commutations a second"]).not.toMatch(/^0/);
    // A count is written as one, its thousands apart, with no "1/s" for a unit.
    expect(valueOf({ value: 119999.99, unit: "" })).toBe("120\u202f000");
    expect(valueOf({ value: 2.4, unit: "W" })).toBe("2.40 W");
    expect(cells["Current at commutation, mean"]).not.toMatch(/^0/);
  });

  it("says what the DC-link capacitor must carry, where the run read it", () => {
    const run = copy(holdFile) as unknown as Run;
    run.channels = { ...run.channels, link_ripple_rms: 12.34 };
    shown(run);
    const cells: Record<string, string> = {};
    host.querySelectorAll(".lab-more tbody tr").forEach((tr) => {
      cells[tr.querySelector("th, td")!.textContent ?? ""] = tr.querySelectorAll("td")[0]?.textContent ?? "";
    });
    expect(cells["DC-link capacitor current, rms"]).toMatch(/^12\.3 A/);
  });

  it("says of a trip which stretch its figures are of", () => {
    const run = copy(holdFile) as unknown as Run;
    run.scenario = { ...run.scenario, kind: "trip" };
    shown(run);
    expect(host.querySelector(".lab-window")!.textContent).toContain("after the trip");
    run.scenario = { ...run.scenario, kind: "hold" };
    shown(run);
    expect(host.querySelector(".lab-window")).toBeNull();
  });

  it("shows no change, and no line about one, where there is nothing to set it against", () => {
    const run = copy(holdFile) as unknown as Run;
    run.engine = null;
    shown(run);
    expect(host.querySelectorAll(".lab-headline .note")).toHaveLength(0);
    expect(host.querySelector(".lab-settled")).toBeNull();
  });

  it("shows each figure's change against the settled design point where the run has one", () => {
    const run = copy(holdFile) as unknown as Run;
    expect(run.engine).toBeTruthy();
    shown(run);
    expect(host.querySelector(".lab-settled")!.textContent).toContain("design point");
  });

  it("says beside this run's junction peak how hot it can run at the hottest cooling assumed", () => {
    const run = copy(holdFile) as unknown as Run;
    run.fidelity = "averaged";
    run.channels = { ...run.channels, tj_peak: 72.6 };
    run.quality = { ...(run.quality ?? {}), tj: { peak: 72.6, high: 105, max: 175, swing: 1 } } as Run["quality"];
    expect(shown(run)["Junction, peak"]).toBe("72.6 °CUp to 105 °C at the hottest cooling assumed");
  });
});
