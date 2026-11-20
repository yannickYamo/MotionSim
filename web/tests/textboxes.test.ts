// A box that may be left empty holds its figure as text. A figure typed into one with the
// box's own unit, or with a prefix, reaches the engine as the number it is, stays text, and
// can be emptied again; a reload or a setup file keeps it.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { fromSetupFile, restore, SETUP_VERSION } from "../src/restore";
import { initial, KEY, motionRequest, request, save } from "../src/state";
import { setPath } from "../src/boxes";
import { app, ui } from "../src/store";
import { coolingWords } from "../src/views/html";

const setup = JSON.parse(readFileSync(new URL("./fixtures/setup.json", import.meta.url), "utf8")) as Setup;
const store = new Map<string, string>();

beforeEach(() => {
  store.clear();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  ui.notes.clear();
});

describe("a figure typed with the box's own unit", () => {
  it("reaches the engine, for the supply's text boxes", () => {
    setPath("conditions.t_dead_ns", "50 ns", true, "ns");
    setPath("conditions.rth_case_sink", "0.5 K/W", true, "K/W");
    setPath("conditions.v_drive", "15 V", true, "V");
    setPath("conditions.rg_on", "4.7 Ω", true, "Ω");
    setPath("conditions.l_loop_nh", "20 nH", true, "nH");
    const c = request(app.state).conditions;
    expect(c.t_dead).toBeCloseTo(50e-9, 15);
    expect(c.rth_case_sink).toBe(0.5);
    expect(c.v_drive).toBe(15);
    expect(c.rg_on).toBe(4.7);
    expect(c.l_loop).toBeCloseTo(20e-9, 15);
  });
  it("reaches the engine for the heatsink of the motion and the map's own range", () => {
    setPath("sink.rth", "0.8 K/W", true, "K/W");
    setPath("sink.t_ambient", "35 °C", true, "°C");
    setPath("map.rpm_max", "6000 rpm", true, "rpm");
    const sink = motionRequest(app.state).heatsink;
    expect(sink.rth).toBe(0.8);
    expect(sink.t_ambient).toBe(35);
    expect(Number(app.state.map.rpm_max)).toBe(6000);
  });
  it("is said once with its unit in the words of the cooling", () => {
    app.state.conditions.cooling = "heatsink";
    setPath("conditions.rth_sink", "0.4 K/W", true, "K/W");
    setPath("conditions.rth_case_sink", "0.5 K/W", true, "K/W");
    expect(coolingWords()).not.toContain("K/W K/W");
    expect(coolingWords()).toContain("0.5 K/W from each case");
  });
});

describe("a figure typed with a prefix into a text box", () => {
  it("stays text, so the box can be emptied again", () => {
    setPath("conditions.t_dead_ns", "0.05 µs", true, "ns");
    expect(app.state.conditions.t_dead_ns).toBe("50");
    expect(request(app.state).conditions.t_dead).toBeCloseTo(50e-9, 15);
    setPath("conditions.t_dead_ns", "", true, "ns");
    expect(app.state.conditions.t_dead_ns).toBe("");
    expect(ui.notes.get("conditions.t_dead_ns")?.unused).toBeFalsy();
    expect(request(app.state).conditions.t_dead).toBeNull();
  });
  it("comes back on a reload", () => {
    setPath("conditions.t_dead_ns", "0.05 µs", true, "ns");
    save(app.state);
    expect(restore(setup).conditions.t_dead_ns).toBe("50");
  });
  it("comes back from a reload or a setup file that kept it as a number", () => {
    const kept = { ...initial(setup), conditions: { ...initial(setup).conditions, t_dead_ns: 50 } };
    store.set(KEY, JSON.stringify({ ...kept, sink: { ...kept.sink, rth: 0.8 }, map: { rpm_max: 6000 } }));
    const back = restore(setup);
    expect(back.conditions.t_dead_ns).toBe("50");
    expect(back.sink.rth).toBe("0.8");
    expect(back.map.rpm_max).toBe("6000");
    const file = { app: "MotionSim", setup: SETUP_VERSION, state: kept, parts: [] };
    expect(fromSetupFile(file, setup)!.conditions.t_dead_ns).toBe("50");
  });
});
