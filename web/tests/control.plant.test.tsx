// @vitest-environment happy-dom
// The motor as simulated, on the motor's inspector: a shaft that twists and iron that saturates,
// off until asked for, carried in every request the lab makes, saved with a setup, and read back
// in what the run shows (the load's speed beside the rotor's, the shaft's swing among the costs).
import { act } from "@testing-library/react";
import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { readSaved, plantOf } from "../src/control/carry";
import { figuresOf } from "../src/control/cost";
import { PlantSettings, setPlant } from "../src/control/plantview";
import { designOf } from "../src/control/request";
import { lab } from "../src/control/store";
import type { PlantOptions, Presets, Run } from "../src/control/types";
import { usualWires } from "../src/control/wires";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

// What the engine sends of the motor as simulated (service/control/running.py, _plant_out).
const OPTIONS: PlantOptions = {
  coupling: [
    {
      name: "resonance_hz",
      unit: "Hz",
      about: "the frequency the motor and the load swing against each other at",
      default: 800,
      low: 1,
      high: 20000,
    },
    {
      name: "motor_share",
      unit: "",
      about: "the rotor's share of the whole inertia",
      default: 0.3,
      low: 0.02,
      high: 0.98,
    },
    { name: "damping_ratio", unit: "", about: "the damping ratio of that swing", default: 0.02, low: 0, high: 1 },
    { name: "backlash_deg", unit: "°", about: "the whole play, at the motor's side", default: 0, low: 0, high: 10 },
  ],
  iron: { choices: ["linear", "saturating"], about: "linear or saturating" },
};

const presets = { ...(copy(presetsFile) as unknown as Presets), plant: OPTIONS };

beforeEach(() => {
  lab.reset();
  const scheme = presets.schemes.find((s) => s.id === presets.chosen) ?? presets.schemes[0];
  lab.set({
    phase: "ready",
    designKey: "k",
    design: { rpm: 3000 },
    presets,
    scheme: copy(scheme),
    tuned: copy(scheme),
  });
});

afterEach(() => lab.reset());

describe("the motor as simulated, in every request", () => {
  it("is the page's design alone until something is asked of the motor", () => {
    const s = lab.get();
    expect(designOf(s)).toBe(s.design);
  });

  it("carries the shaft and the iron once they are asked for, and drops linear iron", () => {
    setPlant({ coupling: { resonance_hz: 120, motor_share: 0.3, damping_ratio: 0.02, backlash_deg: 0 } });
    setPlant({ iron: "saturating" });
    expect(designOf(lab.get())).toEqual({
      rpm: 3000,
      plant: {
        coupling: { resonance_hz: 120, motor_share: 0.3, damping_ratio: 0.02, backlash_deg: 0 },
        iron: "saturating",
      },
    });
    setPlant({ iron: "linear", coupling: undefined });
    expect(lab.get().plant).toEqual({});
    expect(designOf(lab.get())).toEqual({ rpm: 3000 });
  });

  it("marks the run as of the motor before, and asks the explorations again for it", () => {
    lab.set((s) => ({
      run: { ...s.run, status: "done", answer: copy(holdFile) as unknown as Run },
      library: { ...s.library, status: "done", open: "bandwidth" },
    }));
    setPlant({ iron: "saturating" });
    const s = lab.get();
    expect(s.run.stale).toBe(true);
    expect(s.library.status).toBe("idle");
    expect(s.library.open).toBeNull();
  });
});

describe("a setup carries the motor as simulated", () => {
  it("reads a shaft's figures and the iron back, and nothing that is not of their shape", () => {
    expect(plantOf({ coupling: { resonance_hz: 300, damping_ratio: 0.05 }, iron: "saturating" })).toEqual({
      coupling: { resonance_hz: 300, damping_ratio: 0.05 },
      iron: "saturating",
    });
    // A shaft with no resonance is no shaft; a figure that is not a number is left; any other iron is linear.
    expect(plantOf({ coupling: { damping_ratio: 0.05 }, iron: "soft" })).toEqual({});
    expect(plantOf({ coupling: { resonance_hz: "300", motor_share: 0.4 } })).toEqual({});
    expect(plantOf(null)).toEqual({});
    const saved = readSaved({ v: 1, scheme: "servo_joint", plant: { coupling: { resonance_hz: 300 } } });
    expect(saved?.plant).toEqual({ coupling: { resonance_hz: 300 } });
  });
});

describe("what the run shows of the shaft", () => {
  it("draws the load's speed beside the rotor's only where the shaft twists", () => {
    expect(usualWires(lab.get())).not.toContain("plant.omega_load");
    setPlant({ coupling: { resonance_hz: 120 } });
    const wires = usualWires(lab.get());
    expect(wires.indexOf("plant.omega_load")).toBe(wires.indexOf("plant.omega_m") + 1);
  });

  it("lists the speed's swing and the shaft's swing among the costs only where the run reads them", () => {
    const run = copy(holdFile) as unknown as Run;
    const keys = (r: Run) => figuresOf(r).map((f) => f.key);
    run.channels = { ...run.channels, speed_ripple_pp: null, shaft_swing_pp: 0 };
    expect(keys(run)).not.toContain("speed_ripple_pp");
    expect(keys(run)).not.toContain("shaft_swing_pp");
    run.channels = { ...run.channels, speed_ripple_pp: 0.12, shaft_swing_pp: 4.5 };
    const shown = figuresOf(run);
    expect(shown.find((f) => f.key === "speed_ripple_pp")?.value).toBe(0.12);
    expect(shown.find((f) => f.key === "shaft_swing_pp")?.unit).toBe("rad/s");
  });
});

describe("the section on the motor's inspector", () => {
  let host: HTMLElement;
  let root: ReturnType<typeof createRoot>;
  beforeEach(() => {
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
  });
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  it("shows a rigid shaft and linear iron at first, and the shaft's figures once it twists", () => {
    act(() => root.render(createElement(PlantSettings, { options: OPTIONS })));
    expect(host.textContent).toContain("The motor as simulated");
    expect(host.querySelector("#lab-plant-resonance_hz")).toBeNull();
    const twists = [...host.querySelectorAll<HTMLElement>("[role=radio]")].find((b) =>
      /twists/i.test(b.textContent ?? ""),
    );
    expect(twists).toBeTruthy();
    act(() => twists!.click());
    // The suggested shaft is taken whole, and its figures are shown to change.
    expect(lab.get().plant.coupling).toEqual({
      resonance_hz: 800,
      motor_share: 0.3,
      damping_ratio: 0.02,
      backlash_deg: 0,
    });
    const box = host.querySelector<HTMLInputElement>("#lab-plant-resonance_hz");
    expect(box?.value).toBe("800");
  });

  it("is not shown where the engine says nothing of the motor as simulated", () => {
    act(() => root.render(createElement(PlantSettings, { options: undefined })));
    expect(host.textContent).toBe("");
  });
});
