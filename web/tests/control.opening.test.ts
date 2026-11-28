// Where the scope opens on a run that has an event (a trip, a step): on the stretch where things
// change, the cursor on the largest phase current in it. A run that changes throughout, or has
// no event, opens whole.
import { describe, expect, it } from "vitest";
import { openingOf } from "../src/control/opening";
import type { Run } from "../src/control/types";

/** A run of 1 s in 1 ms samples: a trip at 0.1 s, after which i_q dies within 0.05 s while the
 *  phase currents swing on; the largest phase current at 0.104 s. */
function tripRun(): Run {
  const t = Array.from({ length: 1001 }, (_, k) => k / 1000);
  const iq = t.map((x) => (x < 0.1 ? 20 : x < 0.15 ? 20 * (1 - (x - 0.1) / 0.05) : 0));
  const ia = t.map((x, k) => (k === 104 ? 106 : 30 * Math.sin(2 * Math.PI * 200 * x)));
  const theta = t.map((x) => (x * 1000) % 6.28);
  return {
    scenario: { kind: "trip", t_trip: 0.1, duration: 1 },
    series: { t, wires: { "plant.i_q": iq, "plant.i_a": ia, "plant.theta_e": theta } },
  } as unknown as Run;
}

describe("where the scope opens", () => {
  it("opens on the stretch the trip changes, the cursor on the largest phase current", () => {
    const at = openingOf(tripRun())!;
    // From a little before the trip to a little after i_q settles at 0.15 s.
    expect(at.view![0]).toBeGreaterThanOrEqual(0.09);
    expect(at.view![0]).toBeLessThan(0.1);
    expect(at.view![1]).toBeGreaterThan(0.15);
    expect(at.view![1]).toBeLessThan(0.17);
    expect(at.t).toBeCloseTo(0.104, 6);
  });

  it("opens whole where the run changes throughout, and is left alone where it has no event", () => {
    const run = tripRun();
    run.series.wires["plant.i_q"] = run.series.t.map((x) => (x < 0.1 ? 20 : 20 * (1 - (x - 0.1) / 0.9)));
    expect(openingOf(run)!.view).toBeNull();
    const hold = tripRun();
    hold.scenario = { kind: "hold" };
    expect(openingOf(hold)).toBeNull();
  });

  it("opens on a step's instant too", () => {
    const run = tripRun();
    run.scenario = { kind: "torque_step", t_step: 0.1 };
    expect(openingOf(run)!.view![0]).toBeLessThan(0.1);
  });
});
