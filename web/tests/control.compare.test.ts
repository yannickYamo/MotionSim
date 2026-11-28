// Schemes compared: which are set beside the one recommended, which figure of a row is the best,
// and the line that chooses, read from the figures alone.
import { runWords } from "../src/control/verdictword";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  alternativesFor,
  bestOf,
  bestPassing,
  choose,
  ROWS,
  rowsShown,
  sensorOf,
  shortName,
  standingOf,
} from "../src/control/compare";
import { pulseDelay } from "../src/control/wiring";
import type { LEdge } from "../src/control/layout";
import type { Presets, Run, Scheme } from "../src/control/types";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";

const presets = presetsFile as unknown as Presets;
const scheme = (id: string) => presets.schemes.find((s) => s.id === id) as Scheme;

interface Figures {
  pm?: number;
  bw?: number;
  thd?: number;
  loss?: number;
  tj?: number;
  torque?: number;
  ripple?: number;
  fails?: boolean;
  /** One finding to change, not failing: the lab's "needs a change". */
  changes?: boolean;
}

/** A run of the hold with the figures given, and nothing else said of it. */
function runWith(f: Figures): Run {
  const run = JSON.parse(JSON.stringify(holdFile)) as Run;
  run.quality = {
    loops: { current: { phase_deg: f.pm ?? 60, bandwidth_hz: f.bw ?? 2000 } },
    loss: { total: f.loss ?? 10 },
    tj: { high: f.tj ?? 80 },
    ripple: { thd: f.thd ?? 0.02, torque_pp: f.ripple ?? 0.1, torque_mean: f.torque ?? 2 },
  } as unknown as Run["quality"];
  run.verdict = {
    ...(run.verdict ?? {}),
    findings: f.fails
      ? [{ id: "margin", tag: "improve", severity: 3, text: "It fails." }]
      : f.changes
        ? [{ id: "floor", tag: "improve", severity: 2, text: "Change it." }]
        : [],
  } as unknown as Run["verdict"];
  run.checks = [];
  if (run.step) run.step = { ...run.step, settling_time: null, recovery_time: null };
  return run;
}

describe("the best figure of a row", () => {
  it("marks the highest or the lowest, by which way is better", () => {
    expect(bestOf([50, 70, 60], "high")).toEqual([1]);
    expect(bestOf([5, 7, 6], "low")).toEqual([0]);
  });
  it("marks a best only where it is the one best, beyond the tie tolerance of every other figure", () => {
    expect(bestOf([5.28, 5.29, 9], "low")).toEqual([]);
    expect(bestOf([5.28, 5.29], "low")).toEqual([]);
    expect(bestOf([68.5, 67, 60], "high", { amount: 2 })).toEqual([]);
    expect(bestOf([68.5, 68.5, 62.8, 62.8], "high", { amount: 2 })).toEqual([]);
    expect(bestOf([68.5, 64, 62.8], "high", { amount: 2 })).toEqual([0]);
  });
  it("never marks two lowest in one row: the audit's torque ripple, 0.207, 0.218, 0.209 and 0.203", () => {
    expect(bestOf([0.207, 0.218, 0.209, 0.203], "low")).toEqual([]);
    expect(bestOf([0.207, 0.218, 0.209, 0.15], "low")).toEqual([3]);
  });
  it("marks the best among the schemes that pass, and none where none passes", () => {
    const runs = [runWith({ fails: true }), runWith({}), runWith({ changes: true })];
    // The failing scheme's 90 is the highest, but it is ruled out: the best is the 70 of those left.
    expect(bestPassing([90, 70, 50], runs, "high")).toEqual([1]);
    const ruled = [runWith({ fails: true }), runWith({ fails: true })];
    expect(bestPassing([90, 50], ruled, "high")).toEqual([]);
  });
  it("marks nothing with one figure, or in a row with no better way", () => {
    expect(bestOf([3, null], "low")).toEqual([]);
    expect(bestOf([1, 2], null)).toEqual([]);
  });
});

describe("the line that chooses", () => {
  const ids = ["foc_servo", "foc_high_speed"];
  const schemes = ids.map(scheme);
  const names = ["Servo", "High speed"];

  it("keeps the recommended scheme where the figures do not say otherwise", () => {
    const c = choose(names, [runWith({}), runWith({})], schemes, presets);
    expect(c.at).toBe(0);
    expect(c.passes).toBe(true);
    expect(c.said).toMatch(/^Choose Servo because it passes/);
  });

  it("chooses the scheme best on the figures that decide, and says each with the next best", () => {
    const c = choose(names, [runWith({}), runWith({ loss: 6, tj: 70 })], schemes, presets);
    expect(c.at).toBe(1);
    expect(c.said).toBe(
      "Choose High speed because it passes with the lowest device loss (6.00 W against 10.0 W) " +
        "and the coolest junction (70.0 °C against 80.0 °C).",
    );
  });

  it("is not moved by a wider bandwidth alone", () => {
    const c = choose(names, [runWith({}), runWith({ bw: 4000 })], schemes, presets);
    expect(c.at).toBe(0);
  });

  it("never chooses a scheme that fails, or one that delivers less torque", () => {
    expect(choose(names, [runWith({ fails: true }), runWith({})], schemes, presets).at).toBe(1);
    expect(choose(names, [runWith({}), runWith({ loss: 2, torque: 1 })], schemes, presets).at).toBe(0);
  });

  it("says when none passes, and which comes closest", () => {
    const c = choose(names, [runWith({ fails: true }), runWith({ fails: true })], schemes, presets);
    expect(c.passes).toBe(false);
    expect(c.said).toMatch(/^None passes as tuned: closest is Servo, with 1 failing/);
  });

  it("never chooses a scheme with anything to change over one that passes", () => {
    const c = choose(names, [runWith({ changes: true, loss: 5, tj: 60 }), runWith({})], schemes, presets);
    expect(c.at).toBe(1);
    expect(c.passes).toBe(true);
    expect(c.said).toMatch(/^Choose High speed because it is the only one here that passes/);
  });

  it("never says a scheme passes that has something to change", () => {
    const c = choose(names, [runWith({ changes: true }), runWith({ changes: true, loss: 5 })], schemes, presets);
    expect(c.passes).toBe(false);
    expect(c.said).not.toMatch(/because it passes/);
    expect(c.said).toMatch(/^None passes as tuned: closest is High speed, with 1 to change/);
  });

  it("waits for a run before it chooses", () => {
    expect(choose(names, [null, null], schemes, presets).at).toBe(-1);
  });
});

describe("the audit's comparison (25 Nov): two observers, the servo and the high-speed scheme", () => {
  // The recommended scheme needs no rotor sensor (the drive is built without one); the servo and
  // the high-speed scheme measure the rotor. Only the high-speed scheme passes.
  const observer = (id: string): Scheme => {
    const s = JSON.parse(JSON.stringify(scheme("foc_servo"))) as Scheme;
    s.id = id;
    s.blocks = s.blocks.map((b) => (b.kind === "position_sensing" ? { ...b, kind: "observer_" + id } : b));
    return s;
  };
  const schemes = [observer("emf"), observer("flux"), scheme("foc_servo"), scheme("foc_high_speed")];
  const names = ["Back-EMF observer", "Flux observer", "Servo", "High speed"];
  const runs = [
    runWith({ changes: true, pm: 68.5, ripple: 0.207, thd: 0.0145, torque: 2.78 }),
    runWith({ changes: true, pm: 68.5, ripple: 0.218, thd: 0.0148, torque: 2.76 }),
    runWith({ changes: true, pm: 62.8, ripple: 0.209, thd: 0.0146, torque: 2.76 }),
    runWith({ pm: 62.8, ripple: 0.203, thd: 0.0146, torque: 2.76 }),
  ];

  it("does not say the scheme it names passes, and says which one does and why it is not taken", () => {
    const c = choose(names, runs, schemes, presets);
    expect(c.passes).toBe(false);
    expect(c.said).not.toMatch(/because it passes/);
    expect(c.said).not.toMatch(/least torque ripple/);
    expect(c.said).toMatch(/^None passes as tuned without a rotor sensor: closest is Back-EMF observer/);
    expect(c.said).toMatch(/High speed passes, but needs a rotor sensor/);
  });

  it("chooses the scheme that passes where the drive can carry a sensor", () => {
    const sensored = [scheme("foc_servo"), observer("emf"), observer("flux"), scheme("foc_high_speed")];
    const c = choose(
      ["Servo", "Back-EMF observer", "Flux observer", "High speed"],
      [runs[2], runs[0], runs[1], runs[3]],
      sensored,
      presets,
    );
    expect(c.at).toBe(3);
    expect(c.passes).toBe(true);
    expect(c.said).toMatch(/^Choose High speed because it is the only one here that passes/);
  });

  it("marks at most one best in each row, and quotes the true best", () => {
    for (const row of rowsShown(runs, schemes, presets)) {
      const values = runs.map((r, k) => row.read(r, schemes[k], presets));
      expect(bestOf(values, row.better, row.within).length, row.id).toBeLessThanOrEqual(1);
    }
    const c = choose(
      ["Servo", "Back-EMF observer", "Flux observer", "High speed"],
      [runs[2], runs[0], runs[1], runs[3]],
      [scheme("foc_servo"), observer("emf"), observer("flux"), scheme("foc_high_speed")],
      presets,
    );
    // Every "against" figure the line quotes is the best of the others on that row.
    expect(c.said).not.toMatch(/0\.207 N·m/);
  });
});

describe("what is set beside the scheme recommended", () => {
  it("answers the same command: a speed scheme beside a speed scheme", () => {
    expect(alternativesFor(presets, "foc_servo", "hold")).toEqual(["foc_high_speed"]);
    expect(alternativesFor(presets, "foc_torque", "hold")).toEqual(["mpc_torque"]);
  });
  it("leaves out a scheme made for a load this design does not have", () => {
    const aside = {
      ...presets,
      schemes: presets.schemes.map((s) => (s.id === "foc_high_speed" ? { ...s, aside: "made for another load" } : s)),
    };
    expect(alternativesFor(aside, "foc_servo", "hold")).toEqual([]);
  });
  it("leaves out a scheme that does not take the test", () => {
    const narrowed = {
      ...presets,
      schemes: presets.schemes.map((s) => (s.id === "foc_high_speed" ? { ...s, tests: ["step"] } : s)),
    };
    expect(alternativesFor(narrowed, "foc_servo", "hold")).toEqual([]);
  });
});

describe("how the schemes are told", () => {
  it("shortens a name to what its brackets say, where that names it", () => {
    expect(shortName("Speed control at a low carrier ratio (high speed)")).toBe("Speed control at a low carrier ratio");
    expect(shortName("Speed control with no encoder (a flux observer)")).toBe("Flux observer");
    expect(shortName("Plain")).toBe("Plain");
    expect(shortName("Joint servo: speed and current control along an S-curve")).toBe("Joint servo");
  });
  it("says a scheme with a position sensor needs one", () => {
    expect(sensorOf(scheme("foc_servo"), presets)).toEqual({ needs: true, words: "Rotor sensor" });
  });
  it("counts a run's standing from its verdict", () => {
    expect(standingOf(runWith({ fails: true })).fails).toBe(1);
    expect(standingOf(runWith({})).fails).toBe(0);
  });
  it("shows a row only where some scheme has its figure", () => {
    const rows = rowsShown([runWith({}), null], [scheme("foc_servo"), undefined], presets).map((r) => r.id);
    expect(rows).toContain("loss");
    expect(rows).not.toContain("bw_speed");
  });
});

describe("the pulse along the drawing as it opens", () => {
  const edge = (x: number, back = false) =>
    ({
      points: [
        [x, 0],
        [x + 10, 0],
      ],
      back,
    }) as unknown as LEdge;
  it("reaches the wires forward from left to right, then comes back along the feedback", () => {
    expect(pulseDelay(edge(0), 1000)).toBeLessThan(pulseDelay(edge(500), 1000));
    expect(pulseDelay(edge(990), 1000)).toBeLessThanOrEqual(pulseDelay(edge(500, true), 1000));
    expect(pulseDelay(edge(900, true), 1000)).toBeLessThan(pulseDelay(edge(100, true), 1000));
  });
});

describe("the lab's styles", () => {
  const dir = join(__dirname, "../src/control");
  const sheets = readdirSync(dir).filter((f) => f.endsWith(".css"));
  it("use the page's shared tokens: no radius, ease or curve of their own", () => {
    for (const f of sheets) {
      const css = readFileSync(join(dir, f), "utf8");
      expect(css, f).not.toMatch(/var\(--radius\)/);
      expect(css, f).not.toMatch(/var\(--ease\)/);
      expect(css, f).not.toMatch(/cubic-bezier\(/);
    }
  });
  it("still everything that moves where motion is asked to be reduced", () => {
    for (const f of ["lab.css", "compare.css", "learn.css"]) {
      expect(readFileSync(join(dir, f), "utf8"), f).toMatch(/prefers-reduced-motion: reduce/);
    }
  });
});

describe("a speed swing below what a drive can read", () => {
  it("is written in one prefixed unit and marks no best among figures of the arithmetic's dust", () => {
    const row = ROWS.find((r) => r.id === "speed_swing")!;
    expect([1.98e-4, 2.4e-5, 5.28e-6].map(row.show)).toEqual(["198 µrad/s", "24.0 µrad/s", "5.28 µrad/s"]);
    expect(bestOf([1.98e-4, 2.4e-5, 5.28e-6, 2.97e-6], row.better, row.within)).toEqual([]);
    // A swing an engineer can see is still told apart.
    expect(bestOf([0.5, 0.2], row.better, row.within)).toEqual([1]);
  });
});

describe("a run's verdict word", () => {
  it("reads a pass with a design action where the only finding would make a result that holds better", () => {
    const run = runWith({ changes: true });
    run.verdict!.findings[0].severity = 1;
    expect(standingOf(run)).toMatchObject({ changes: 1, actions: 1, fails: 0 });
    expect(runWords(run).text).toBe("Passes · 1 design action");
    // A finding a grade heavier still asks for a change.
    expect(runWords(runWith({ changes: true })).text).toBe("Needs a change");
    expect(runWords(runWith({ fails: true })).text).toBe("Ruled out");
  });
});
