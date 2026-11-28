// The scope reads the shaft's speed in rpm, as the rest of the product does: the engine's
// rad/s are turned once, at the scope's door, and nothing the engine sent is changed.
import { describe, expect, it } from "vitest";

import { notesOf } from "../src/control/findings";
import { reading } from "../src/control/figures";
import { stripsOf, tracedOf } from "../src/control/probes";
import { RPM, shaftRun, shaftSeries, shaftWires } from "../src/control/scopeview";
import type { Run, Series, Wire } from "../src/control/types";
import stepFile from "./fixtures/control-run-step.json";

const step = stepFile as unknown as Run;
const wire = (name: string, unit: string): Wire => ({ name, unit, block: name.split(".")[0], about: "" });
const known = [
  wire("plant.omega_m", "rad/s"),
  wire("cmd.speed", "rad/s"),
  wire("position.omega_e", "rad/s"),
  wire("plant.torque", "N·m"),
];
const series: Series = {
  t: [0, 1],
  wires: { "plant.omega_m": [0, 100], "cmd.speed": [100, 100], "position.omega_e": [0, 400], "plant.torque": [1, 2] },
  lo: { "plant.omega_m": [-1, 99] },
  hi: { "plant.omega_m": [1, 101] },
};

describe("the shaft's speed on the scope", () => {
  it("names the shaft's speeds in rpm and leaves the electrical speed as the engine gives it", () => {
    const units = Object.fromEntries(shaftWires(known).map((w) => [w.name, w.unit]));
    expect(units).toEqual({
      "plant.omega_m": "rpm",
      "cmd.speed": "rpm",
      "position.omega_e": "rad/s",
      "plant.torque": "N·m",
    });
    expect(known[0].unit).toBe("rad/s");
  });

  it("turns the samples and the lowest and highest between them, once, and nothing else", () => {
    const shown = shaftSeries(series, known);
    expect(shown.wires["plant.omega_m"][1]).toBeCloseTo(954.9297, 3);
    expect(shown.wires["cmd.speed"][0]).toBeCloseTo(100 * RPM, 9);
    expect(shown.lo!["plant.omega_m"][1]).toBeCloseTo(99 * RPM, 9);
    expect(shown.hi!["plant.omega_m"][1]).toBeCloseTo(101 * RPM, 9);
    expect(shown.wires["position.omega_e"]).toBe(series.wires["position.omega_e"]);
    expect(shown.wires["plant.torque"]).toBe(series.wires["plant.torque"]);
    expect(shown.t).toBe(series.t);
    // The engine's own figures stand, and the same answer is turned only once.
    expect(series.wires["plant.omega_m"]).toEqual([0, 100]);
    expect(shaftSeries(series, known)).toBe(shown);
  });

  it("draws the speed strip in rpm: its key, its title, its axis and what the cursor reads", () => {
    const run = shaftRun(step);
    expect(shaftRun(step)).toBe(run);
    const probes = ["plant.omega_m", "cmd.speed", "plant.torque"];
    const groups = stripsOf(probes, run.wires, run.series, "speed_step");
    expect(groups[0]).toMatchObject({ key: "rpm", title: "Speed", yLabel: "speed, rpm" });
    const [speed] = tracedOf(groups, new Map(), shaftRun(step), run.series);
    const last = step.series.wires["plant.omega_m"].length - 1;
    expect(speed.map((x) => x.name)).toEqual(["plant.omega_m, run A", "plant.omega_m", "cmd.speed"]);
    for (const trace of speed) {
      const own = step.series.wires[trace.name.replace(", run A", "")];
      expect(trace.values[last]).toBeCloseTo(own[last] * RPM, 6);
    }
    // 209.44 rad/s is 2000 rpm, read to the whole one.
    expect(reading(run.series.wires["plant.omega_m"][last], "rpm", 0, 2100)).toMatch(/^\d{4} rpm$/);
    expect(run.series.wires["plant.torque"]).toBe(step.series.wires["plant.torque"]);
  });

  it("sets what the run found on the speed strip, in rpm", () => {
    const run = shaftRun(step);
    expect(run.step).toMatchObject({ wire: step.step!.wire, t_step: step.step!.t_step });
    expect(run.step!.to).toBeCloseTo(step.step!.to * RPM, 9);
    const notes = notesOf(run);
    expect(notes.has("rad/s")).toBe(false);
    const over = notes.get("rpm")!.find((n) => n.id === "overshoot")!;
    expect(over.kind === "band" && over.lo).toBeCloseTo(2000, 0);
    // The observer's floor is known in rpm, and drawn at that.
    const floored = notesOf({ ...run, floor: { rpm: 80, hardware_rpm: 120, design_rpm: 100, handback_rpm: 90 } });
    expect(floored.get("rpm")).toContainEqual(expect.objectContaining({ kind: "level", id: "floor", value: 120 }));
  });
});
