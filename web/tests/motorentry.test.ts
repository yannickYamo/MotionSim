// A motor's figures shown the way its datasheet gives them, and turned back into the figures
// the engine's model holds. Every expected value here is worked out by hand in its comment.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Setup } from "../src/api";
import {
  constantOf,
  fieldsOf,
  freshEntry,
  hasConstant,
  hasWiring,
  remagnetised,
  shownAs,
  shownText,
} from "../src/motorentry";
import type { MotorEntry } from "../src/motorentry";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;

const line: MotorEntry = freshEntry();
const phase: MotorEntry = { wiring: "phase", constant: {} };

describe("a resistance or an inductance", () => {
  it("of a per-phase model given between two terminals is halved, in mH and mΩ", () => {
    const l = shownAs("pmsm", "l", line, "Phase inductance")!;
    // 0.00012 H for one phase is 0.24 mH between two terminals.
    expect(l.unit).toBe("mH");
    expect(l.label).toBe("Inductance, line to line");
    expect(l.shown(0.00012)).toBeCloseTo(0.24, 12);
    expect(l.engine(0.24)).toBeCloseTo(0.00012, 15);
    // 0.045 Ω for one phase is 90 mΩ between two terminals.
    const rs = shownAs("pmsm", "rs", line)!;
    expect(rs.unit).toBe("mΩ");
    expect(rs.shown(0.045)).toBeCloseTo(90, 9);
    expect(rs.help(0.045)).toBe(
      "Between two terminals, as datasheets give it. The model takes half of it for one phase, 45.0 mΩ.",
    );
  });
  it("of a per-phase model given for one phase is taken as it is", () => {
    const l = shownAs("pmsm", "l", phase)!;
    expect(l.label).toBe("Inductance, per phase");
    expect(l.shown(0.00012)).toBeCloseTo(0.12, 12);
    expect(l.engine(0.12)).toBeCloseTo(0.00012, 15);
  });
  it("of the block-commutated model, which takes it between two terminals, is doubled from one phase", () => {
    const r = shownAs("bldc", "r", phase)!;
    // 40 mΩ for one phase is 0.08 Ω between two terminals.
    expect(r.engine(40)).toBeCloseTo(0.08, 15);
    expect(r.shown(0.08)).toBeCloseTo(40, 9);
    expect(shownAs("bldc", "r", line)!.shown(0.08)).toBeCloseTo(80, 9);
  });
  it("of an equivalent circuit's own figures is only put in mH and mΩ", () => {
    const rr = shownAs("induction", "rr", line, "Rotor resistance", "Referred to the stator")!;
    expect(rr.label).toBe("Rotor resistance");
    expect(rr.help(3.5)).toBe("Referred to the stator");
    expect(rr.shown(3.5)).toBeCloseTo(3500, 9);
    // The stator's resistance is measured between terminals: 4 Ω a phase is 8000 mΩ between two.
    expect(shownAs("induction", "rs", line)!.shown(4)).toBeCloseTo(8000, 9);
    const step = shownAs("stepper", "r", line, "Phase resistance")!;
    expect(step.label).toBe("Phase resistance");
    expect(step.shown(0.9)).toBeCloseTo(900, 9);
  });
  it("is switched only for a three-phase motor", () => {
    expect(["pmsm", "bldc", "synrm", "induction"].every(hasWiring)).toBe(true);
    expect(["dc", "dc_series", "stepper"].some(hasWiring)).toBe(false);
  });
});

describe("poles", () => {
  it("are given in full and held as pairs", () => {
    const poles = shownAs("pmsm", "pole_pairs", line)!;
    expect(poles.shown(7)).toBe(14);
    expect(poles.engine(14)).toBe(7);
    expect(poles.help(7)).toBe("Every magnet pole, north and south: 7 pairs.");
  });
  it("are said per kind of motor: magnets only where it has them, and with the kind's own help", () => {
    const pm = "A catalogue that gives pole pairs gives half as many.";
    const im = "Four poles turn at about 1500 rpm on 50 Hz.";
    expect(shownAs("pmsm", "pole_pairs", line, "Pole pairs", pm)!.help(7)).toBe(
      `Every magnet pole, north and south: 7 pairs. ${pm}`,
    );
    expect(shownAs("bldc", "pole_pairs", line, "Pole pairs", pm)!.help(null)).toBe(
      `Every magnet pole, north and south. ${pm}`,
    );
    const induction = shownAs("induction", "pole_pairs", line, "Pole pairs", im)!.help(2);
    expect(induction).toBe(`Every pole of the winding, north and south: 2 pairs. ${im}`);
    const reluctance = shownAs("synrm", "pole_pairs", line, "Pole pairs", "")!.help(2);
    expect(reluctance).toBe("Every pole of the winding, north and south: 2 pairs.");
    for (const said of [induction, reluctance]) expect(said).not.toMatch(/magnet/i);
  });
  it("are said with the help each kind is served with, in the terms of poles, not pairs", () => {
    for (const kind of ["pmsm", "bldc", "synrm", "induction"]) {
      const f = setup.motors[kind].fields.find((x) => x.key === "pole_pairs")!;
      const said = shownAs(kind, "pole_pairs", line, f.label, f.help)!.help(2);
      expect(said).not.toMatch(/divided by|Two pole pairs/);
      if (kind === "synrm" || kind === "induction") expect(said).not.toMatch(/magnet/i);
    }
  });
  it("in an odd number are refused", () => {
    expect(typeof shownAs("bldc", "pole_pairs", line)!.engine(15)).toBe("string");
    expect(typeof shownAs("bldc", "pole_pairs", line)!.engine(14.5)).toBe("string");
  });
});

describe("a motor's constant", () => {
  it("of a permanent-magnet motor, given as Kt per A rms, is turned into Kv", () => {
    const e: MotorEntry = { wiring: "line", constant: { pmsm: "kt" } };
    const kt = shownAs("pmsm", "kv", e)!;
    expect(kt.unit).toBe("N·m/A rms");
    // Kt · Kv = √(3/2) · 60/(2π) = 1.2247449 · 9.5492966 = 11.695452: Kv 100 is Kt 0.11695452.
    expect(kt.shown(100)).toBeCloseTo(0.11695452, 7);
    expect(kt.engine(0.11695452)).toBeCloseTo(100, 4);
    expect(kt.help(100)).toBe("Turned into Kv = 11.695 / Kt: 100 rpm/V.");
  });
  it("of a brushless or brushed DC motor, given as Kv, is turned into Kt", () => {
    const e: MotorEntry = { wiring: "line", constant: { bldc: "kv", dc: "kv" } };
    // Kt = 60 / (2π · Kv): Kt 0.09 is Kv 9.5492966 / 0.09 = 106.10330; Kt 0.05 is Kv 190.98593.
    expect(shownAs("bldc", "kt", e)!.shown(0.09)).toBeCloseTo(106.1033, 3);
    expect(shownAs("dc", "kt", e)!.shown(0.05)).toBeCloseTo(190.98593, 4);
    expect(shownAs("dc", "kt", e)!.engine(190.98593)).toBeCloseTo(0.05, 8);
  });
  it("is shown as the model holds it until switched", () => {
    expect(constantOf("pmsm", line)).toBe("kv");
    expect(constantOf("bldc", line)).toBe("kt");
    expect(shownAs("pmsm", "kv", line)!.shown(100)).toBe(100);
    expect(constantOf("stepper", line)).toBeNull();
    expect(["pmsm", "bldc", "dc"].every(hasConstant)).toBe(true);
    expect(["synrm", "induction", "dc_series", "stepper"].some(hasConstant)).toBe(false);
  });
});

describe("the figure a box shows", () => {
  it("is written out plainly, and empty where the engine holds none", () => {
    expect(shownText(shownAs("pmsm", "l", line), 0.00012)).toBe("0.24");
    expect(shownText(shownAs("bldc", "l", line), "")).toBe("");
    expect(shownText(null, 40)).toBe(40);
  });
});

describe("magnets set in or buried", () => {
  const pmsm = setup.motors.pmsm;
  const keys = (magnets: string) => fieldsOf("pmsm", pmsm.fields, { magnets }).map((f) => f.key);

  it("asks for the two axis inductances in place of one, and one on a surface motor", () => {
    expect(keys("surface")).toContain("l");
    expect(keys("surface")).not.toContain("lq");
    for (const m of ["inset", "interior"]) {
      const k = keys(m);
      expect(k).not.toContain("l");
      // Where the one inductance stood, d first.
      expect(k.slice(k.indexOf("ld"), k.indexOf("ld") + 2)).toEqual(["ld", "lq"]);
    }
    // Another kind's list is its own.
    expect(fieldsOf("synrm", setup.motors.synrm.fields, { magnets: "interior" })).toBe(setup.motors.synrm.fields);
  });

  it("takes them line to line as the one inductance is: 2 mH between terminals is 1 mH a phase", () => {
    const ld = shownAs("pmsm", "ld", line)!;
    expect(ld.label).toBe("Inductance Ld, line to line");
    expect(ld.engine(2)).toBeCloseTo(1e-3, 12);
    expect(shownAs("pmsm", "lq", phase)!.engine(2)).toBeCloseTo(2e-3, 12);
  });

  it("carries the figure across when the magnets change, and back as the d axis's", () => {
    const buried = remagnetised({ magnets: "surface", l: 7e-5, rs: 0.02 }, "interior");
    expect(buried).toEqual({ magnets: "interior", ld: 7e-5, lq: 7e-5, rs: 0.02 });
    const faced = remagnetised({ ...buried, lq: 1.4e-4 }, "surface");
    expect(faced).toEqual({ magnets: "surface", l: 7e-5, rs: 0.02 });
    // Given already, the two axes are kept through a move between inset and interior.
    expect(remagnetised({ magnets: "inset", ld: 1, lq: 2 }, "interior")).toEqual({ magnets: "interior", ld: 1, lq: 2 });
  });
});
