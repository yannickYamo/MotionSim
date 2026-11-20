// @vitest-environment happy-dom
// A figure typed with its unit or an SI prefix is taken in the box's unit, and the box says
// what it came to; a figure a motor rarely has is cautioned at its box, and still used.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { initial } from "../src/state";
import { setPath } from "../src/boxes";
import { app, res, ui } from "../src/store";
import { connect, frame, renderPanel, topBar } from "../src/views/render";

const fixture = (name: string) => JSON.parse(readFileSync(`tests/fixtures/${name}.json`, "utf8"));
const setup = fixture("setup") as Setup;
const answers = fixture("answers") as Record<string, Record<string, unknown>>;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  Object.assign(app.state, { devices: ["example-mosfet"], added: ["example-mosfet"], reached: 4, step: 1 });
  Object.assign(res, { stage: answers.stage.stage, advice: null, proposal: answers.proposal, cycle: null });
  res.blocked = res.fault = res.waiting = null;
  ui.notes.clear();
});

const box = (path: string) => document.querySelector<HTMLInputElement>(`[data-bind="${path}"]`)!;
const fieldOf = (path: string) => box(path).closest(".field")!;

describe("a motor figure typed with a prefix", () => {
  it("is turned into the box's unit and then the model's, and the box keeps what was typed", () => {
    app.state.kind = "pmsm";
    // 240 µH between two terminals is 0.24 mH, and the model takes half of it: 0.00012 H a phase.
    setPath("motors.pmsm.l", "240 µH", true, "mH");
    expect(app.state.motors.pmsm.l).toBe(0.00012);
    renderPanel();
    expect(box("motors.pmsm.l").value).toBe("240 µH");
    const echo = fieldOf("motors.pmsm.l").querySelector(".help.echo")!;
    expect(echo.textContent).toBe("= 0.24 mH");
    expect(box("motors.pmsm.l").getAttribute("aria-describedby")).toContain(echo.id);
    expect(box("motors.pmsm.l").hasAttribute("aria-invalid")).toBe(false);
  });
  it("is cautioned, not refused, where a motor rarely has it", () => {
    app.state.kind = "pmsm";
    setPath("motors.pmsm.l", "1000", true, "mH");
    setPath("motors.pmsm.rs", "80000", true, "mΩ");
    renderPanel();
    expect(app.state.motors.pmsm.l).toBe(0.5);
    expect(fieldOf("motors.pmsm.l").querySelector(".help.caution")!.textContent).toMatch(/1 µH and 100 mH/);
    expect(fieldOf("motors.pmsm.rs").querySelector(".help.caution")!.textContent).toMatch(/below 10 Ω/);
    expect(box("motors.pmsm.rs").hasAttribute("aria-invalid")).toBe(false);
    setPath("motors.pmsm.l", "2m", true, "mH");
    renderPanel();
    expect(fieldOf("motors.pmsm.l").querySelector(".help.caution")).toBeNull();
  });
  it("of another kind is refused with the box's unit named", () => {
    app.state.kind = "pmsm";
    const before = app.state.motors.pmsm.l;
    setPath("motors.pmsm.l", "48 V", true, "mH");
    renderPanel();
    expect(fieldOf("motors.pmsm.l").textContent).toContain("48 V is not a figure in mH.");
    expect(app.state.motors.pmsm.l === before || app.state.motors.pmsm.l === "").toBe(true);
  });
});

describe("the inertia of a weight on an arm", () => {
  const joint = () => {
    Object.assign(app.state.load, { mass: 3, arm: 0.25, inertia: 0.1875 });
    app.state.inertiaOwn = false;
    app.state.step = 3;
  };
  it("follows the weight and the arm while the user has not typed one, and says the sum", () => {
    joint();
    setPath("load.mass", "6", true, "kg");
    expect(app.state.load.inertia).toBe(0.375);
    setPath("load.arm", "500 mm", true, "m");
    expect(app.state.load.arm).toBe(0.5);
    expect(app.state.load.inertia).toBe(1.5);
    renderPanel();
    const help = document.querySelector(`#${CSS.escape("f-load-inertia")}-h`)!;
    expect(help.textContent).toBe(
      "6 kg × (0.5 m)² = 1.5 kg·m², from the weight on the arm. It follows them until you type your own.",
    );
  });
  it("is the user's once typed, and no longer follows", () => {
    joint();
    setPath("load.inertia", "0.3", true, "kg·m²");
    setPath("load.mass", "6", true, "kg");
    expect(app.state.load.inertia).toBe(0.3);
  });
  it("is left alone where there is no weight on an arm", () => {
    Object.assign(app.state.load, { mass: 0, arm: 0.25, inertia: 0.02 });
    setPath("load.arm", "0.5", true, "m");
    expect(app.state.load.inertia).toBe(0.02);
  });
});
