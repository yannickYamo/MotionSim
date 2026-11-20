import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it } from "vitest";
import type { Setup, Suggest } from "../src/api";
import { putBack, settle } from "../src/follow";
import { initial } from "../src/state";
import type { State } from "../src/state";
import { noteAt, setPath } from "../src/boxes";
import { app, ui } from "../src/store";

const fixture = (name: string) => JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
const setup = fixture("setup") as Setup;
// What the engine said suits each of two parts that differ visibly: a 600 V part on a
// 400 V supply and a 100 V part on a 48 V supply. Captured from the engine, not written here.
const suits = fixture("suggest") as Record<"example" | "example-mosfet" | "module-1200v-100a", Suggest>;
const high = suits.example;
const low = suits["example-mosfet"];
// A made-up 1200 V, 100 A IGBT module: industrial drives of its size run induction motors.
const industrial = suits["module-1200v-100a"];

beforeEach(() => {
  app.setup = setup;
  app.state = initial(setup);
  ui.notes.clear();
});
const shape = (s: State) => ({ kind: s.kind, motors: s.motors, conditions: s.conditions });

describe("the starting point of the motor and the design point", () => {
  it("is where the device under test belongs, for everything the user has not typed", () => {
    const changes = settle(app.state, setup, high);
    expect(app.state.conditions).toMatchObject({ v_dc: 400, rpm: 3000, torque: 5.93, f_khz: 16 });
    expect(app.state.motors.pmsm).toMatchObject({ pole_pairs: 4, kv: 9.375, l: 0.003, rs: 0.35, i_max: 19 });
    // Every figure that moved is named, with what it was and what it is.
    expect(changes.find((c) => c.path === "conditions.v_dc")).toMatchObject({ from: 48, to: 400, unit: "V" });
    expect(changes.find((c) => c.path === "motors.pmsm.kv")).toMatchObject({ from: 100, to: 9.375 });
    expect(changes.every((c) => c.from !== c.to)).toBe(true);
  });
  it("never rewrites a figure the user typed", () => {
    setPath("conditions.rpm", "1234");
    setPath("motors.pmsm.kv", "55");
    const changes = settle(app.state, setup, high);
    expect(app.state.conditions.rpm).toBe(1234);
    expect(app.state.motors.pmsm.kv).toBe(55);
    expect(app.state.conditions.v_dc).toBe(400); // untouched, so it follows
    expect(changes.map((c) => c.path)).not.toContain("conditions.rpm");
    expect(changes.map((c) => c.path)).not.toContain("motors.pmsm.kv");
  });
  it("does not depend on the order things were done in", () => {
    // The low-voltage part first, a speed typed, then the high-voltage part put under test.
    settle(app.state, setup, low);
    setPath("conditions.rpm", "1234");
    setPath("motors.pmsm.pole_pairs", "4");
    settle(app.state, setup, high);
    const one = shape(app.state);
    // The high-voltage part from the start, and the same two figures typed afterwards.
    app.state = initial(setup);
    settle(app.state, setup, high);
    setPath("motors.pmsm.pole_pairs", "4");
    setPath("conditions.rpm", "1234");
    settle(app.state, setup, high);
    expect(shape(app.state)).toEqual(one);
    // And by way of a third part's start in between.
    app.state = initial(setup);
    setPath("conditions.rpm", "1234");
    settle(app.state, setup, high);
    settle(app.state, setup, low);
    setPath("motors.pmsm.pole_pairs", "4");
    settle(app.state, setup, high);
    expect(shape(app.state)).toEqual(one);
  });
  it("moves nothing when it is asked twice for the same device", () => {
    settle(app.state, setup, low);
    expect(settle(app.state, setup, low)).toEqual([]);
  });
  it("leaves the kind of motor alone once the user has chosen it", () => {
    app.state.kind = "induction";
    app.state.kindPicked = true;
    settle(app.state, setup, low);
    expect(app.state.kind).toBe("induction");
  });
  it("starts on the kind of motor the part's class of drive runs, with that class's figures", () => {
    const changes = settle(app.state, setup, industrial);
    expect(app.state.kind).toBe("induction");
    expect(changes.find((c) => c.path === "kind")).toMatchObject({ to: setup.motors.induction.label });
    expect(app.state.motors.induction.pole_pairs).toBe(2);
    expect(app.state.conditions).toMatchObject({ v_dc: 800, rpm: 1450, f_khz: 8 });
    expect(industrial.motors.induction.why).toBe(
      "1200 V, 100 A IGBT module: industrial drives of this size run induction motors",
    );
    // From there to the 100 V part: a small motor of its own class, not the induction motor.
    settle(app.state, setup, low);
    expect(app.state.kind).toBe("pmsm");
  });
  it("keeps a kind the user picked, and every figure they typed, when the part's class changes", () => {
    settle(app.state, setup, low);
    app.state.kind = "pmsm";
    app.state.kindPicked = true;
    setPath("motors.pmsm.pole_pairs", "10");
    setPath("motors.induction.rs", "0.3");
    setPath("conditions.rpm", "1200");
    const rs = app.state.motors.induction.rs; // as the box read it, in its own unit
    settle(app.state, setup, industrial);
    expect(app.state.kind).toBe("pmsm");
    expect(app.state.motors.pmsm.pole_pairs).toBe(5);
    expect(app.state.motors.induction.rs).toBe(rs);
    expect(rs).not.toBe(industrial.motors.induction.values.rs);
    expect(app.state.conditions.rpm).toBe(1200);
    // What was not typed follows the module: the PMSM it would start a servo drive on.
    expect(app.state.motors.pmsm.kv).toBe(industrial.motors.pmsm.values.kv);
    expect(app.state.conditions.v_dc).toBe(800);
  });
  it("falls back to the page's own examples when nothing is known of what suits the device", () => {
    settle(app.state, setup, high);
    settle(app.state, setup, null);
    expect(shape(app.state)).toEqual(shape(initial(setup)));
  });
});

describe("a figure put back after it followed the device", () => {
  it("is as it was, and is the user's own from then on", () => {
    const before = { v: app.state.conditions.v_dc, kv: app.state.motors.pmsm.kv };
    const changes = settle(app.state, setup, high);
    for (const change of [...changes].reverse()) putBack(app.state, setup, change);
    expect(app.state.conditions.v_dc).toBe(before.v);
    expect(app.state.motors.pmsm.kv).toBe(before.kv);
    expect(settle(app.state, setup, high)).toEqual([]);
    expect(app.state.conditions.v_dc).toBe(before.v);
  });
});

describe("what is typed into a box", () => {
  it("is taken with a decimal comma, and kept out when it could be read two ways", () => {
    setPath("conditions.torque", "0,75");
    expect(app.state.conditions.torque).toBe(0.75);
    setPath("conditions.rpm", "1,500");
    expect(app.state.conditions.rpm).toBe(2000); // the figure it held is still in use
    expect(noteAt("conditions.rpm", 2000)).toMatchObject({ raw: "1,500" });
    expect(noteAt("conditions.rpm", 2000)!.why).toMatch(/two ways.*2000 is still in use/);
  });
  it("is refused at the box when it is not a plain number", () => {
    for (const typed of ["0x10", "Infinity", "48 A", "abc", ""]) {
      setPath("conditions.v_dc", typed, true, "V");
      expect(app.state.conditions.v_dc).toBe(48);
      expect(noteAt("conditions.v_dc", 48)!.raw).toBe(typed);
    }
    expect(noteAt("conditions.v_dc", 48)!.why).toBe("Empty: 48 is still in use.");
    setPath("conditions.v_dc", "48 A", true, "V");
    expect(noteAt("conditions.v_dc", 48)!.why).toBe("48 A is not a figure in V. 48 is still in use.");
  });
  it("is taken with its unit or a prefix, and says what it came to", () => {
    setPath("conditions.v_dc", "0.4 kV", true, "V");
    expect(app.state.conditions.v_dc).toBe(400);
    expect(noteAt("conditions.v_dc", 400)).toMatchObject({ raw: "0.4 kV", why: "= 400 V", echo: true });
    setPath("conditions.v_dc", "400 V", true, "V");
    expect(app.state.conditions.v_dc).toBe(400);
    expect(noteAt("conditions.v_dc", 400)).toBeNull();
  });
  it("loses its note once a number is typed", () => {
    setPath("conditions.v_dc", "abc");
    setPath("conditions.v_dc", "24");
    expect(app.state.conditions.v_dc).toBe(24);
    expect(noteAt("conditions.v_dc", 24)).toBeNull();
  });
  it("is not used where it is outside what the box takes: the figure before it stays", () => {
    const ratio = app.state.load.gear_ratio;
    setPath("load.gear_ratio", "0");
    expect(app.state.load.gear_ratio).toBe(ratio);
    expect(noteAt("load.gear_ratio", ratio)).toMatchObject({
      raw: "0",
      unused: true,
      why: `Gear ratio has to be above 0. ${ratio} is still in use.`,
    });
    setPath("conditions.f_khz", "0");
    expect(noteAt("conditions.f_khz", app.state.conditions.f_khz)!.why).toMatch(/kHz/);
  });
  it("keeps 1e9 typed for the speed as typed, says the range at the box, and the last figure taken stays", () => {
    setPath("conditions.rpm", "2000");
    setPath("conditions.rpm", "1e9");
    expect(app.state.conditions.rpm).toBe(2000);
    expect(noteAt("conditions.rpm", 2000)).toMatchObject({ raw: "1e9", why: expect.stringMatching(/Speed has to be/) });
    setPath("conditions.rpm", "abc");
    expect(noteAt("conditions.rpm", 2000)!.why).toBe("Not a number. 2000 is still in use.");
  });
  it("reads a comma before anything but three figures as a decimal point, and says so at the box", () => {
    setPath("conditions.torque", "12,5");
    expect(app.state.conditions.torque).toBe(12.5);
    expect(noteAt("conditions.torque", 12.5)!.why).toMatch(/^Read as 12.5: a comma/);
    setPath("conditions.rpm", "1,500");
    expect(noteAt("conditions.rpm", app.state.conditions.rpm)!.why).toMatch(/can be read two ways/);
  });
  it("makes the figure the user's own, and the load theirs when it is a load figure", () => {
    setPath("conditions.rpm", "900");
    expect(app.state.pointOf).toEqual({ pmsm: { rpm: 900 } });
    setPath("motors.pmsm.kv", "80");
    expect(app.state.motorOwn).toEqual({ pmsm: ["kv"] });
    expect(app.state.loadTouched).toBe(false);
    setPath("load.inertia", "0.5");
    expect(app.state.loadTouched).toBe(true);
  });
});
