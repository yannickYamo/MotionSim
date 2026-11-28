// @vitest-environment happy-dom
// A trip at speed: the scope draws what the stage returned to the DC link and the safe state it
// was in, on charts of their own; the trip's instant is marked where it is read from; and the
// arithmetic's dust after the currents die reads as nought, not in picoamps.
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { written } from "../src/control/figures";
import { notesOf, targetOf } from "../src/control/findings";
import { choiceWord, keyWord } from "../src/control/keys";
import { lab } from "../src/control/store";
import type { Finding, Presets, Run } from "../src/control/types";
import { groupOf, usualWires } from "../src/control/wires";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";

const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const presets = copy(presetsFile) as unknown as Presets;

/** The hold fixture's answer made a trip's: tripped at 6 ms, its figures as the engine gives them. */
function tripped(findings: Finding[] = []): Run {
  const run = copy(holdFile) as unknown as Run & { trip: Record<string, unknown> };
  run.trip = { t_trip: 0.006, rpm: 6000, link_peak: 105.6, i_peak: 106.0, states: ["off"] };
  if (run.verdict) run.verdict.findings = findings;
  return run;
}

beforeEach(() => {
  lab.reset();
  const scheme = copy(presets.schemes[0]);
  lab.set({ phase: "ready", designKey: "k", design: {}, presets, scheme, tuned: copy(scheme) });
});

afterEach(() => lab.reset());

describe("a trip at speed", () => {
  it("draws the link's current and the safe state, on charts of their own, only for a trip", () => {
    expect(usualWires(lab.get())).not.toContain("inverter.i_link");
    lab.set({ scenario: "trip" });
    const wires = usualWires(lab.get());
    expect(wires).toContain("inverter.i_link");
    expect(wires).toContain("inverter.safe");
    expect(groupOf({ name: "inverter.i_link", unit: "A" })).toBe("link A");
    expect(groupOf({ name: "inverter.safe", unit: "" })).toBe("safe");
    // Another current of no frame keeps the chart of its unit.
    expect(groupOf({ name: "inverter.i_dc_1", unit: "A" })).toBe("A");
  });

  it("marks the instant it tripped on the phase currents, and no settled instant", () => {
    const notes = notesOf(tripped());
    const ticks = [...notes.entries()].flatMap(([g, ns]) => ns.filter((n) => n.kind === "tick").map((n) => [g, n]));
    expect(ticks).toHaveLength(1);
    const [group, tick] = ticks[0] as [string, { id: string; t: number }];
    expect([group, tick.id, tick.t]).toEqual(["abc A", "trip", 0.006]);
  });

  it("points the link's finding at the link's chart", () => {
    const link: Finding = {
      id: "trip_link",
      topic: "trip",
      tag: "improve",
      severity: 3,
      said: "",
      head: null,
      lever: null,
      expect: null,
      change: null,
    };
    expect(targetOf(link, tripped([link]))).toMatchObject({ group: "link A", wire: "inverter.i_link" });
  });

  it("points the fall's finding at the shaft's speed, with how far it fell", () => {
    const fall: Finding = {
      id: "trip_fall",
      topic: "trip",
      tag: "improve",
      severity: 2,
      said: "",
      head: null,
      lever: null,
      expect: null,
      change: null,
    };
    const run = tripped([fall]) as Run & { trip: Record<string, unknown> };
    run.trip.fall_deg = 0.8616;
    expect(targetOf(fall, run)).toMatchObject({ group: "rpm", wire: "plant.omega_m" });
  });

  it("names its figures as a trip's", () => {
    expect(keyWord("torque", "trip")).toBe("Torque before the trip");
    expect(keyWord("rpm", "trip")).toBe("Speed at the trip");
    expect(keyWord("brake_delay", "trip")).toBe("Brake bites after");
    expect(keyWord("cause", "trip")).toBe("Cause");
    expect(choiceWord("encoder")).toBe("The encoder freezes");
    expect(choiceWord("open_switch")).toBe("A switch fails open");
    expect(keyWord("torque", "load_step")).toBe("Load torque");
  });
});

describe("a figure read against its chart", () => {
  it("is nought where it is a millionth of the chart's span or less, and itself above that", () => {
    expect(written(5.9e-15, "A", 4, 50)).toBe("0 A");
    expect(written(-2.6e-4 * 1e-12, "N·m", 4, 5)).toBe("0 N·m");
    // Above that, read against a chart or not, it is written alike.
    expect(written(0.5, "A", 4, 50)).toBe(written(0.5, "A"));
    expect(written(1e-4, "A", 4, 50)).toBe(written(1e-4, "A"));
    // With no chart to read it against, a small figure keeps its prefix.
    expect(written(5.9e-6, "A")).toBe("5.900 µA");
  });
});
