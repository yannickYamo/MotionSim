// @vitest-environment happy-dom
// The motor step takes the figures the way a datasheet gives them: between two terminals or
// for one phase, poles in full, milli-units, and the constant either way. The engine is sent
// the figures its model takes, and what an earlier visit or an older setup file kept opens
// with the same figures as before.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { setPath } from "../src/boxes";
import { onChange } from "../src/events/choosing";
import { settle } from "../src/follow";
import { fromSetupFile, restore } from "../src/restore";
import { initial, KEY, request } from "../src/state";
import { MOTOR } from "../src/steps";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const store = new Map<string, string>();

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  store.clear();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example-mosfet"], added: ["example-mosfet"], reached: 4, step: MOTOR });
  res.blocked = res.fault = res.waiting = null;
  res.fit = null;
  ui.notes.clear();
});

const box = (path: string) => document.querySelector<HTMLInputElement>(`[data-bind="${path}"]`)!;
const labelOf = (path: string) => document.querySelector(`label[for="${box(path).id}"]`)!.textContent;
const unitOf = (path: string) => box(path).parentElement!.querySelector(".unit")!.textContent;
const sent = () => request(app.state).motor as unknown as Record<string, number>;
const choose = (name: string, value: string) => {
  const el = document.querySelector<HTMLInputElement>(`[data-entry="${name}"][value="${value}"]`)!;
  el.checked = true;
  onChange({ target: el } as unknown as Event);
};

describe("the motor step of a permanent-magnet motor", () => {
  it("shows the example's figures line to line, in mH and mΩ, with its poles in full", () => {
    renderPanel();
    // The example's 0.00012 H and 0.045 Ω a phase are 0.24 mH and 90 mΩ between two terminals.
    expect(box("motors.pmsm.l").value).toBe("0.24");
    expect(unitOf("motors.pmsm.l")).toBe("mH");
    expect(labelOf("motors.pmsm.l")).toBe("Inductance, line to line");
    expect(box("motors.pmsm.rs").value).toBe("90");
    expect(unitOf("motors.pmsm.rs")).toBe("mΩ");
    expect(box("motors.pmsm.pole_pairs").value).toBe("14");
    expect(labelOf("motors.pmsm.pole_pairs")).toBe("Poles");
    const wiring = document.querySelector<HTMLInputElement>('[data-entry="wiring"][value="line"]')!;
    expect(wiring.checked).toBe(true);
    expect(wiring.closest("fieldset")!.querySelector("legend")!.textContent).toBe(
      "Resistance and inductance are given",
    );
  });
  it("sends the engine its own figures whichever way they are shown", () => {
    renderPanel();
    const before = request(app.state).motor;
    choose("wiring", "phase");
    choose("constant", "kt");
    expect(request(app.state).motor).toEqual(before);
    expect(box("motors.pmsm.l").value).toBe("0.12");
    expect(labelOf("motors.pmsm.l")).toBe("Inductance, per phase");
    // Kv 100 is Kt √(3/2) · 60/(2π) / 100 = 0.1169545 N·m/A rms, shown to four figures.
    expect(box("motors.pmsm.kv").value).toBe("0.117");
    expect(unitOf("motors.pmsm.kv")).toBe("N·m/A rms");
    expect(document.activeElement).toBe(document.querySelector('[data-entry="constant"][value="kt"]'));
  });
  it("turns what is typed into the model's figures", () => {
    renderPanel();
    setPath("motors.pmsm.pole_pairs", "10", true, "");
    setPath("motors.pmsm.rs", "120", true, "mΩ");
    choose("constant", "kt");
    setPath("motors.pmsm.kv", "0.2", true, "N·m/A rms");
    const motor = sent();
    expect(motor.pole_pairs).toBe(5);
    expect(motor.rs).toBe(0.06); // half of 120 mΩ
    expect(motor.kv).toBeCloseTo(58.4772601, 6); // 11.6954520 / 0.2
  });
  it("refuses an odd number of poles at its box, and keeps the pairs it had", () => {
    renderPanel();
    setPath("motors.pmsm.pole_pairs", "15", true, "");
    renderPanel();
    expect(app.state.motors.pmsm.pole_pairs).toBe(7);
    const said = box("motors.pmsm.pole_pairs").closest(".field")!.textContent;
    expect(said).toContain("Poles come in pairs");
    expect(said).toContain("14 is still in use.");
  });
});

describe("magnets set in or buried", () => {
  const pick = (path: string, value: string) => {
    const el = document.querySelector<HTMLSelectElement>(`select[data-bind="${path}"]`)!;
    el.value = value;
    onChange({ target: el } as unknown as Event);
  };
  it("are sent as chosen, and the step asks for both axes' inductances, line to line", () => {
    renderPanel();
    pick("motors.pmsm.magnets", "interior");
    expect(app.state.motors.pmsm.magnets).toBe("interior");
    expect(ui.notes.size).toBe(0); // the word is taken, not refused as a figure
    expect(document.querySelector('[data-bind="motors.pmsm.l"]')).toBeNull();
    expect(labelOf("motors.pmsm.ld")).toBe("Inductance Ld, line to line");
    // The example's one 0.12 mH a phase becomes both axes', 0.24 mH between terminals.
    expect(box("motors.pmsm.lq").value).toBe("0.24");
    setPath("motors.pmsm.lq", "0.48", true, "mH");
    const motor = sent();
    expect(motor.magnets).toBe("interior");
    expect(motor.ld).toBe(0.00012);
    expect(motor.lq).toBe(0.00024); // half of 0.48 mH
    expect("l" in motor).toBe(false);
    pick("motors.pmsm.magnets", "surface");
    expect(sent().l).toBe(0.00012);
  });
  it("are settled to the device's example without its one inductance coming back beside the two", () => {
    // What a browser kept from before: buried magnets, both axes given, the rest the example's.
    app.state.motors.pmsm = { ...app.state.motors.pmsm, magnets: "interior", ld: 7e-5, lq: 1.5e-4 };
    delete app.state.motors.pmsm.l;
    app.state.motorOwn = { pmsm: ["magnets", "lq"] };
    const changes = settle(app.state, app.setup, null);
    const motor = sent();
    expect("l" in motor).toBe(false);
    expect([motor.ld, motor.lq]).toEqual([7e-5, 1.5e-4]);
    expect(changes.some((c) => c.path === "motors.pmsm.l")).toBe(false);
  });
  it("leave a brushed motor's drive as the word chosen", () => {
    app.state.kind = "dc";
    renderPanel();
    pick("motors.dc.drive", "bipolar");
    expect(sent().drive).toBe("bipolar");
  });
});

describe("the motor step of a brushless DC motor", () => {
  it("takes the resistance between two terminals as it is, and doubles one phase's", () => {
    app.state.kind = "bldc";
    renderPanel();
    expect(box("motors.bldc.r").value).toBe("80");
    choose("wiring", "phase");
    setPath("motors.bldc.r", "50", true, "mΩ");
    expect(sent().r).toBe(0.1);
  });
  it("takes its speed constant in place of the torque constant", () => {
    app.state.kind = "bldc";
    renderPanel();
    choose("constant", "kv");
    setPath("motors.bldc.kt", "100", true, "rpm/V");
    // Kt = 60 / (2π · 100) = 0.0954929659 N·m/A.
    expect(sent().kt).toBeCloseTo(0.0954929659, 10);
  });
});

describe("a kind of motor with no such choice", () => {
  it("shows no switch, and its figures only in milli-units", () => {
    app.state.kind = "dc_series";
    renderPanel();
    expect(document.querySelector('[data-entry="wiring"]')).toBeNull();
    expect(document.querySelector('[data-entry="constant"]')).toBeNull();
    expect(box("motors.dc_series.r").value).toBe("250");
  });
});

describe("what was kept before the motor's figures could be given either way", () => {
  // A motor of every kind, as the page before kept it: the engine's own figures.
  const motors = {
    pmsm: { type: "pmsm", magnets: "surface", pole_pairs: 5, kv: 80, l: 0.0002, rs: 0.07, i_max: 30 },
    bldc: { type: "bldc", pole_pairs: 4, kt: 0.12, r: 0.1, l: 0.0003, i_max: 20 },
    induction: { ...setup.motors.induction.values, rs: 3.1, rr: 2.9 },
    stepper: { ...setup.motors.stepper.values, r: 1.1, l: 0.003 },
  };
  const old = (kind: string) => ({ ...initial(setup), kind, motors: { ...initial(setup).motors, ...motors } });
  const without = (state: object) => {
    const kept = { ...state } as Record<string, unknown>;
    delete kept.motorEntry;
    return kept;
  };

  it("opens from the browser with the same figures sent to the engine", () => {
    for (const kind of Object.keys(motors)) {
      store.set(KEY, JSON.stringify(without(old(kind))));
      const state = restore(setup);
      expect(state.motorEntry).toEqual({ wiring: "line", constant: {} });
      expect(request(state).motor).toEqual(request(old(kind)).motor);
      expect(request(state).motor).toMatchObject(motors[kind as keyof typeof motors]);
    }
  });
  it("opens from a setup file of every version with the same figures", () => {
    for (const version of [1, 2, 3]) {
      const state = fromSetupFile({ app: "MotionSim", setup: version, state: without(old("pmsm")) }, setup)!;
      expect(request(state).motor).toEqual(request(old("pmsm")).motor);
    }
  });
  it("keeps the way the figures were shown, where it was kept, and nothing else", () => {
    const kept = { ...old("pmsm"), motorEntry: { wiring: "phase", constant: { pmsm: "kt", nowhere: "kt", dc: 7 } } };
    store.set(KEY, JSON.stringify(kept));
    expect(restore(setup).motorEntry).toEqual({ wiring: "phase", constant: { pmsm: "kt" } });
    store.set(KEY, JSON.stringify({ ...old("pmsm"), motorEntry: { wiring: "star" } }));
    expect(restore(setup).motorEntry).toEqual({ wiring: "line", constant: {} });
  });
});

describe("the kind of motor the device starts on", () => {
  it("is tagged, with the line that says why under the tag", () => {
    const suits = JSON.parse(readFileSync("tests/fixtures/suggest.json", "utf8"));
    res.suggestion = { id: "example-mosfet", data: suits["module-1200v-100a"] };
    renderPanel();
    const tagged = [...document.querySelectorAll("label.kind")].filter((l) => l.querySelector(".tag.recommended"));
    expect(tagged).toHaveLength(1);
    expect(tagged[0].querySelector<HTMLInputElement>("input[data-kind]")!.value).toBe("induction");
    expect(tagged[0].querySelector(".tag")!.textContent).toBe("Starting point for your device");
    expect(tagged[0].querySelector(".kind-why")!.textContent).toBe(
      "1200 V, 100 A IGBT module: industrial drives of this size run induction motors.",
    );
    res.suggestion = null;
  });
});
