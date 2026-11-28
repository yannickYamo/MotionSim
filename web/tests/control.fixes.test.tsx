// @vitest-environment happy-dom
// What an expert drive engineer found wrong with the control lab, each kept put right: Escape
// closes the innermost thing first, a design changed or reset starts the lab afresh, a setup
// carries the lab, only the tests a scheme takes are offered, a probe pressed twice takes out
// only what it added, every figure is written one way, and a test's box says when it is wrong.

import { act, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelRun, pinWires, setParam, takeScheme, testsFor } from "../src/control/actions";
import { carry, readSaved } from "../src/control/carry";
import { control, Missing } from "../src/control/client";
import { bound, scaleOf, written } from "../src/control/figures";
import { mount, unmount } from "../src/control/lab";
import { foundOf, scaleOfRead } from "../src/control/library";
import { stop } from "../src/control/play";
import { figureWrong } from "../src/control/runpanel";
import { cursor, lab } from "../src/control/store";
import { unitsOf } from "../src/control/units";
import { usualWires } from "../src/control/wires";
import type { Loops, Presets, Run, Scheme } from "../src/control/types";
import designFile from "./fixtures/control-design.json";
import loopsFile from "./fixtures/control-loops.json";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";

const presets = presetsFile as unknown as Presets;
const hold = holdFile as unknown as Run;
const copy = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDialogElement;
const $ = <T extends Element = HTMLElement>(s: string) => host.querySelector<T>(s);
const press = (s: string) => act(() => fireEvent.click($(s)!));

async function opened(key = `k${Math.random()}`): Promise<void> {
  host ??= document.body.appendChild(document.createElement("dialog"));
  await act(async () => {
    mount(host, { key, design: designFile, presets, name: "a made-up part" });
    await Promise.resolve();
  });
}

/** Escape pressed where the keyboard is: whether the lab kept it from closing the dialog. */
const escape = (at: Element): boolean => {
  const e = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
  act(() => {
    at.dispatchEvent(e);
  });
  return e.defaultPrevented;
};

beforeEach(() => {
  const media = { matches: true, addEventListener: () => undefined, removeEventListener: () => undefined };
  vi.stubGlobal("matchMedia", () => media);
  localStorage.clear();
  lab.reset();
  carry.take();
  vi.spyOn(control, "loops").mockResolvedValue(loopsFile as unknown as Loops);
  vi.spyOn(control, "kept").mockResolvedValue([]);
  vi.spyOn(control, "run").mockResolvedValue(hold);
  vi.spyOn(control, "runStreamed").mockResolvedValue(hold);
  vi.spyOn(control, "explorations").mockRejectedValue(new Missing("/api/control/explorations"));
});

afterEach(() => {
  cancelRun();
  stop();
  if (host) act(() => unmount(host));
  host?.remove();
  host = undefined as unknown as HTMLDialogElement;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Escape in the lab", () => {
  it("closes the inspector first, and only then lets the lab close", async () => {
    await opened();
    await press('[data-block="speed"] .lab-node-head');
    expect(lab.get().selected).toBe("speed");
    expect(escape($(".lab-inspector h3")!)).toBe(true);
    expect(lab.get().selected).toBeNull();
    // Nothing is open in the lab now: Escape is the dialog's own, and closes the lab.
    expect(escape($(".lab-top")!)).toBe(false);
  });

  it("closes the test's settings first, wherever the keyboard is, then the inspector, then the lab", async () => {
    await opened();
    await press('[data-block="speed"] .lab-node-head');
    await press(".lab-test-open");
    expect($(".lab-test-open")!.getAttribute("aria-expanded")).toBe("true");
    // The keyboard on the Run press, outside the settings.
    expect(escape($(".lab-go")!)).toBe(true);
    expect($(".lab-test-open")!.getAttribute("aria-expanded")).toBe("false");
    expect(lab.get().selected).toBe("speed");
    expect(escape($(".lab-go")!)).toBe(true);
    expect(lab.get().selected).toBeNull();
    expect(escape($(".lab-go")!)).toBe(false);
  });
});

describe("the lab on another design", () => {
  it("starts from the scheme recommended for the new design as tuned, and says the edits were left", async () => {
    await opened("design-a");
    const other = presets.schemes.find((s) => s.id !== presets.chosen)!;
    act(() => takeScheme(other));
    act(() => setParam("current", "kp_q", 9.5));
    await act(async () => {
      mount(host, { key: "design-b", design: designFile, presets, name: "another part" });
      await Promise.resolve();
    });
    const s = lab.get();
    expect(s.scheme?.id).toBe(presets.chosen);
    expect(s.scheme).toEqual(presets.schemes.find((x) => x.id === presets.chosen));
    expect(s.said).toMatch(/not carried/);
    expect($(".lab-carried")?.textContent).toMatch(/not carried/);
  });

  it("starts from nothing after a Reset, on the same design too", async () => {
    await opened("design-a");
    act(() => setParam("speed", "kp", 3));
    act(() => carry.clear());
    await opened("design-a");
    expect(lab.get().scheme?.blocks.find((b) => b.name === "speed")?.params.kp).not.toBe(3);
    expect(lab.get().said).toBeNull();
  });

  it("keeps everything as it was on the same design", async () => {
    await opened("design-a");
    act(() => setParam("speed", "kp", 3));
    await opened("design-a");
    expect(lab.get().scheme?.blocks.find((b) => b.name === "speed")?.params.kp).toBe(3);
  });
});

describe("a setup file", () => {
  it("carries the scheme, its edits, the test, its figures and the fidelity, and brings them back", async () => {
    await opened("design-a");
    const other = presets.schemes.find((s) => s.id === "foc_torque")!;
    act(() => takeScheme(other));
    act(() => setParam("current", "kp_q", 0.9));
    act(() => lab.set({ scenario: "torque_step", fidelity: "averaged", figures: { torque_step: { to: "2.5" } } }));
    const saved = JSON.parse(JSON.stringify(carry.saved()));
    expect(saved).toMatchObject({ v: 1, key: "design-a", scheme: "foc_torque", scenario: "torque_step" });
    expect(saved.fidelity).toBe("averaged");
    expect(saved.figures).toEqual({ torque_step: { to: "2.5" } });
    // Opened on a page that has started again: everything comes back, the edits with it.
    act(() => unmount(host));
    lab.reset();
    carry.open(saved);
    expect(carry.saved()).toEqual(readSaved(saved));
    await opened("design-a");
    const s = lab.get();
    expect(s.scheme?.id).toBe("foc_torque");
    expect(s.scheme?.blocks.find((b) => b.name === "current")?.params.kp_q).toBe(0.9);
    expect(s.tuned).toEqual(other);
    expect([s.scenario, s.fidelity, s.figures.torque_step?.to]).toEqual(["torque_step", "averaged", "2.5"]);
    expect(s.said).toMatch(/edits .* are carried/);
  });

  it("leaves edits made on another design out, and reads a file with fields missing", async () => {
    carry.open({ v: 1, key: "design-a", scheme: "foc_torque", edits: copy(presets.schemes[1]), scenario: "hold" });
    await opened("design-z");
    expect(lab.get().scheme).toEqual(presets.schemes.find((x) => x.id === "foc_torque"));
    expect(lab.get().said).toMatch(/another design/);
    expect(readSaved({ scheme: "foc_servo" })).toMatchObject({ scheme: "foc_servo", figures: {}, edits: null });
    expect(readSaved({ v: 7, scheme: "foc_servo" })).toBeNull();
    expect(readSaved("nonsense")).toBeNull();
  });
});

describe("the tests a scheme is offered", () => {
  it("offers a scheme told a speed no torque step, and follows the engine's own list where it sends one", async () => {
    await opened();
    const servo = lab.get();
    expect(servo.scheme?.id).toBe("foc_servo");
    expect(testsFor(servo)).not.toContain("torque_step");
    expect(testsFor(servo)).toContain("speed_step");
    const torque = presets.schemes.find((s) => s.id === "foc_torque")!;
    expect(testsFor(servo, torque)).toContain("torque_step");
    const listed = { ...torque, tests: ["hold", "start"] } as Scheme;
    expect(testsFor(servo, listed)).toEqual(["hold", "start"]);
    // The test settings list the others as not for this scheme, and cannot pick them.
    await press(".lab-test-open");
    const options = [...host.querySelectorAll<HTMLOptionElement>("#lab-scenario option")];
    expect(options.filter((o) => !o.disabled).map((o) => o.value)).not.toContain("torque_step");
  });

  it("takes a test the scheme cannot take off a scheme it was on, for the first it can", async () => {
    await opened();
    act(() => takeScheme(presets.schemes.find((s) => s.id === "foc_torque")!));
    act(() => lab.set({ scenario: "torque_step" }));
    act(() => takeScheme(presets.schemes.find((s) => s.id === "foc_servo")!));
    expect(lab.get().scenario).not.toBe("torque_step");
  });
});

describe("a wire of several lines, pressed", () => {
  it("adds what it does not draw yet, and takes out only that when pressed again", async () => {
    await opened();
    const usual = usualWires(lab.get());
    expect(usual).toContain("plant.omega_m");
    const bus = ["position.theta", "plant.omega_m"];
    act(() => void pinWires(bus, usual));
    expect(lab.get().plotted).toEqual(expect.arrayContaining(bus));
    act(() => void pinWires(bus, usualWires(lab.get())));
    expect(lab.get().plotted).toContain("plant.omega_m");
    expect(lab.get().plotted).not.toContain("position.theta");
    expect(lab.get().plotted).toEqual(usual);
  });
});

describe("the scope, dragged across", () => {
  it("shows the stretch dragged across while the strips hold the pointer, and the whole run again", async () => {
    await opened();
    await press(".lab-go");
    await waitFor(() => expect($(".scope-plot svg")).not.toBeNull());
    const svg = $(".scope-plot svg")!;
    const width = Number(svg.getAttribute("width"));
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      width,
      height: 100,
      right: width,
      bottom: 100,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    const strips = $(".scope-strips")!;
    // Pressed on a plot; then moved and let go with the strips holding the pointer, as a
    // captured pointer is: what is under it is the strips, not the plot.
    act(() => void fireEvent.pointerDown(svg, { button: 0, clientX: width * 0.4, pointerId: 1 }));
    act(() => void fireEvent.pointerMove(strips, { clientX: width * 0.7, pointerId: 1 }));
    expect(($(".scope-band") as HTMLElement).hidden).toBe(false);
    act(() => void fireEvent.pointerUp(strips, { clientX: width * 0.7, pointerId: 1 }));
    const view = lab.get().view!;
    expect(view).not.toBeNull();
    expect(view[1]).toBeGreaterThan(view[0]);
    expect(($(".scope-band") as HTMLElement).hidden).toBe(true);
    await press(".scope-tool");
    expect(lab.get().view).toBeNull();
  });
});

describe("a run there was, after a change", () => {
  it("is run again by itself when another scheme is taken or the scheme goes back to as tuned", async () => {
    await opened();
    await press(".lab-go");
    await waitFor(() => expect(lab.get().run.answer).not.toBeNull());
    expect(control.runStreamed).toHaveBeenCalledTimes(1);
    act(() => takeScheme(presets.schemes.find((s) => s.id === "foc_torque")!));
    await waitFor(() => expect(control.runStreamed).toHaveBeenCalledTimes(2), { timeout: 2000 });
    act(() => setParam("current", "kp_q", 0.7));
    act(() => takeScheme(lab.get().tuned!));
    await waitFor(() => expect(control.runStreamed).toHaveBeenCalledTimes(3), { timeout: 2000 });
  });
});

describe("a figure of the test", () => {
  it("is in ms where it is a time under a second, and says at its box when it is wrong", async () => {
    await opened();
    act(() => lab.set({ scenario: "speed_step" }));
    await press(".lab-test-open");
    const box = $<HTMLInputElement>("#lab-s-speed_step-t_step")!;
    const field = box.closest(".field")!;
    expect(field.querySelector(".unit")!.textContent).toBe("ms");
    expect(field.querySelector("label")!.textContent).toBe("Step at");
    const usual = presets.scenarios.find((s) => s.kind === "speed_step")!.defaults.foc_servo.t_step as number;
    expect(Number(box.value)).toBeCloseTo(usual * 1e3, 6);
    // A time the engine sized is written to three figures; the speed, the design's own, as it is.
    const preset = presets.scenarios.find((s) => s.kind === "speed_step")!.defaults.foc_servo;
    const duration = $<HTMLInputElement>("#lab-s-speed_step-duration")!;
    expect(duration.value).toBe(String(Number(((preset.duration as number) * 1e3).toPrecision(3))));
    expect(duration.value.replace(".", "").replace(/^0+/, "").length).toBeLessThanOrEqual(3);
    expect($<HTMLInputElement>("#lab-s-speed_step-to_rpm")!.value).toBe(String(preset.to_rpm));
    await act(() => fireEvent.change(box, { target: { value: "3" } }));
    expect(lab.get().figures.speed_step.t_step).toBe("0.003");
    await act(() => fireEvent.change(box, { target: { value: "abc" } }));
    await act(() => fireEvent.blur(box));
    expect(box.getAttribute("aria-invalid")).toBe("true");
    expect(field.querySelector(".said-wrong")!.textContent).toMatch(/A number .*is needed here/);
    // What was wrong was not taken: the last figure read is the one sent.
    expect(lab.get().figures.speed_step.t_step).toBe("0.003");
    const rpm = $<HTMLInputElement>("#lab-s-speed_step-to_rpm")!;
    expect(rpm.closest(".field")!.querySelector("label")!.textContent).toBe("Target speed");
  });

  it("is checked against its bounds, in the scale it is typed in", () => {
    const field = { name: "t_step", unit: "s", about: "", low: 0, high: 2 } as never;
    expect(figureWrong("3", field, 1e3)).toBe("");
    expect(figureWrong("2000", field, 1e3)).toBe("");
    expect(figureWrong("2001", field, 1e3)).toMatch(/from 0 s to 2 s/);
    expect(figureWrong("", field, 1e3)).not.toBe("");
  });
});

describe("one way of writing a figure", () => {
  it("gives units, prefixes and four figures, and an angle in degrees within one turn", () => {
    expect(written(7.2e-5, "A")).toBe("72.00 µA");
    expect(written(44.8, "A")).toBe("44.80 A");
    expect(written(0.44428403307066855, "")).toBe("0.4443");
    expect(written(51.3, "rad")).toBe("59.3°");
    expect(scaleOf("s", 0.0119)).toEqual({ unit: "ms", k: 1e3 });
    expect(scaleOf("s", 2)).toEqual({ unit: "s", k: 1 });
    expect(scaleOf("rad/s2", 5)).toEqual({ unit: "rad/s²", k: 1 });
    expect(bound(1e-6, "s")).toBe("1 µs");
    expect(bound(1e12, "s")).toBeNull();
  });

  it("gives a transform's outputs the unit of what goes into it", () => {
    const scheme = presets.schemes.find((s) => s.id === "foc_servo")!;
    const known = new Map([...hold.wires.map((w) => [w.name, w.unit] as [string, string])]);
    const units = unitsOf(scheme, presets.blocks, known);
    expect(known.get("park.d")).toBe("");
    expect(units.get("park.d")).toBe("A");
    expect(units.get("park.q")).toBe("A");
    // A duty is not a transform's: it stays without a unit.
    expect(units.get("modulator.d_a")).toBe("");
  });

  it("shows In and out, the inspector's head and Add a signal in names, never the scheme's identifiers", async () => {
    await opened();
    await press(".lab-go");
    await waitFor(() => expect($(".scope-add select")).not.toBeNull());
    const groups = [...host.querySelectorAll(".scope-add optgroup")].map((g) => g.getAttribute("label"));
    expect(groups).not.toContain("plant");
    expect(groups).not.toContain("const");
    expect(groups.join(" ")).not.toMatch(/\bconst\b|\bsample\b|_/);
    expect($(".scope-add")!.textContent).not.toMatch(/nought/);
    await press('[data-block="current"] .lab-node-head');
    const insp = $(".lab-inspector")!;
    expect(insp.querySelector(".lab-insp-tag")).toBeNull();
    expect(insp.querySelector(".lab-io")!.textContent).not.toMatch(/position\.|park\.|err_d|current_ref/);
    expect(insp.querySelector(".lab-plotted")!.textContent).not.toMatch(/err_d|prop_d|ff_q/);
    act(() => {
      cursor.t = hold.series.t[10];
      cursor.again();
    });
    const id = insp.querySelector('.lab-io .lab-live[data-wire="park.d"]');
    expect(id?.textContent).toMatch(/A$/);
  });
});

describe("what an exploration found", () => {
  it("is drawn in the unit its axis names, and marked as its tag says", () => {
    expect(scaleOfRead("f_switch_mean", "kHz", undefined, [13357, 9000])).toBe(1e-3);
    expect(scaleOfRead("f_switch_mean", "kHz", undefined, [13.4, 9])).toBe(1);
    expect(scaleOfRead("f_switch_mean", "kHz", { scale: 1 }, [13357])).toBe(1);
    expect(scaleOfRead("thd", "", undefined, [0.05])).toBe(100);
    expect(foundOf({ said: "switches too often", tag: "improve" }, null)).toEqual({
      said: "switches too often",
      tag: "short",
    });
    expect(foundOf("it holds", { tag: "good" })?.tag).toBe("good");
    // No tag given: a plain note, never a pass mark.
    expect(foundOf("switches too often", {})?.tag).toBe("note");
  });
});

describe("the speed the test commands and the speed the loop follows", () => {
  it("are told apart, and a sentence that opens on a Greek symbol keeps it", async () => {
    const { commanded } = await import("../src/control/naming");
    const { sentence } = await import("../src/format");
    expect(commanded("cmd.speed", { text: "ω", sub: "", star: true }).sub).toBe("cmd");
    expect(commanded("speed_ref.ref", { text: "ω", sub: "", star: true }).sub).toBe("");
    expect(sentence("λ 3.39 A of torque short")).toBe("λ 3.39 A of torque short");
    expect(sentence("the loop settles")).toBe("The loop settles");
  });
});
