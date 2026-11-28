// @vitest-environment happy-dom
// The control lab as it is used: opened on a design, a block inspected and a gain changed, a
// test run and stopped, an exploration swept. The engine's answers are ones recorded from it;
// what the lab asks of the engine is read from what it hands to its own requests.
import { act, fireEvent, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Refused } from "../src/api/answers";
import { api } from "../src/api";
import { cancelRun } from "../src/control/actions";
import { KEY_SETTINGS, keysOf } from "../src/control/keysettings";
import { control, Missing } from "../src/control/client";
import { entryWords } from "../src/control/entry";
import { pitchOf } from "../src/control/explorewords";
import { learnOff, learnOn, learnShown } from "../src/control/learncard";
import { mount, unmount } from "../src/control/lab";
import { layoutOf } from "../src/control/layout";
import type { Layout } from "../src/control/layout";
import { setWiring } from "../src/control/path";
import { stop } from "../src/control/play";
import { valueAt, written } from "../src/control/series";
import { cursor, lab } from "../src/control/store";
import { Wiring } from "../src/control/wiring";
import type { Exploration, Loops, Presets, Run, RunProbe, Sweep } from "../src/control/types";
import designFile from "./fixtures/control-design.json";
import { relationWords } from "../src/control/laplace";
import loopsFile from "./fixtures/control-loops.json";
import mpcLoopsFile from "./fixtures/control-loops-mpc.json";
import presetsFile from "./fixtures/control-presets.json";
import kindsFile from "./fixtures/control-kinds.json";
import holdFile from "./fixtures/control-run-hold.json";
import stepFile from "./fixtures/control-run-step.json";

// A lever pressed opens its setting 60 ms later: the page outlives that, as a browser's does.
afterAll(() => new Promise((done) => setTimeout(done, 100)));

const presets = presetsFile as unknown as Presets;
const hold = holdFile as unknown as Run;
const stepRun = stepFile as unknown as Run;
const loops = loopsFile as unknown as Loops;
const copy = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDialogElement;
/** What a test has put up beside the lab, to be taken down after it. */
const cleanup: (() => unknown)[] = [];
const $ = <T extends Element = HTMLElement>(s: string) => host.querySelector<T>(s);
const text = (s: string) => $(s)?.textContent ?? "";
const press = (s: string) => act(() => fireEvent.click($(s)!));
const type = (s: string, value: string) => act(() => fireEvent.change($(s)!, { target: { value } }));
type Body = { scheme: Presets["schemes"][0]; scenario: Record<string, unknown>; fidelity: string; conditions: unknown };

async function opened(given: Presets = presets): Promise<void> {
  host = document.createElement("dialog");
  document.body.append(host);
  await act(async () => {
    mount(host, { key: `k${Math.random()}`, design: designFile, presets: given, name: "a made-up part" });
    await Promise.resolve();
  });
}

beforeEach(() => {
  // As narrow as a phone: the scheme is the list of its blocks, drawn by the lab's own code alone.
  const media = { matches: true, addEventListener: () => undefined, removeEventListener: () => undefined };
  vi.stubGlobal("matchMedia", () => media);
  localStorage.clear();
  lab.reset();
  vi.spyOn(control, "loops").mockResolvedValue(loops);
  vi.spyOn(control, "kept").mockResolvedValue([]);
  vi.spyOn(control, "run").mockResolvedValue(hold);
  vi.spyOn(control, "runStreamed").mockResolvedValue(hold);
  vi.spyOn(control, "explorations").mockRejectedValue(new Missing("/api/control/explorations"));
});

afterEach(() => {
  // A figure changed after a run asks for the run again a moment later: not in the next test.
  cancelRun();
  stop();
  cleanup.splice(0).forEach((undo) => undo());
  // The lab of one test is taken down before the next: none goes on drawing behind it.
  if (host) act(() => unmount(host));
  host?.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("the scheme, block by block", () => {
  it("names every block of the chosen scheme and says why it was chosen", async () => {
    await opened();
    const blocks = [...host.querySelectorAll("[data-block]")].map((b) => b.getAttribute("data-block"));
    expect(blocks).toEqual(expect.arrayContaining([...presets.schemes[0].blocks.map((b) => b.name), "cmd", "plant"]));
    expect(text(".lab-about")).toContain(presets.why);
    const chosen = presets.schemes.find((s) => s.id === presets.chosen)!;
    expect($("#lab-scheme")!.getAttribute("aria-label")).toBe(`Control scheme: ${chosen.label}`);
    // The scheme recommended for the design leads the list, under words that say so, with its reason.
    await press("#lab-scheme");
    const groups = [...host.querySelectorAll('.lab-picker-list [role="group"]')];
    expect(text(".lab-picker-list .lab-picker-group")).toBe("Recommended for this design");
    expect(groups[0].querySelector('[role="option"]')!.getAttribute("aria-selected")).toBe("true");
    expect(groups[0].querySelector(".lab-picker-label")!.textContent).toBe(chosen.label);
    expect(groups[0].querySelector(".lab-picker-note")!.textContent.length).toBeGreaterThan(10);
    // Every scheme is offered once, in families, and the search narrows them by its words.
    expect(host.querySelectorAll('.lab-picker-list [role="option"]').length).toBe(presets.schemes.length);
    const search = $<HTMLInputElement>('.lab-picker-search input[role="combobox"]')!;
    expect(document.activeElement).toBe(search);
    await act(() => fireEvent.change(search, { target: { value: "predictive" } }));
    const left = [...host.querySelectorAll(".lab-picker-list .lab-picker-label")].map((o) => o.textContent);
    expect(left.length).toBeGreaterThan(0);
    for (const l of left) expect(l.toLowerCase()).toContain("predictive");
    // Escape shuts the list, not the lab, and gives the keyboard back to the press.
    await act(() => fireEvent.keyDown(host, { key: "Escape" }));
    expect($(".lab-picker-panel")!.hidden).toBe(true);
    expect(document.activeElement).toBe($("#lab-scheme"));
  });

  it("draws each block at rest as its symbol alone: no value, face, trace or gain on it", async () => {
    await opened();
    await press(".lab-run button.primary");
    await waitFor(() => expect($(".lab-cost-view")).not.toBeNull());
    const chain = $(".lab-chain")!;
    for (const gone of [
      "[data-face]",
      ".lab-face",
      ".lab-port",
      ".lab-port-value",
      ".lab-spark",
      ".lab-gain",
      ".lab-live",
    ])
      expect(chain.querySelectorAll(gone).length, gone).toBe(0);
    for (const b of chain.querySelectorAll("[data-block]")) expect(b.querySelector("svg.lab-sym")).not.toBeNull();
    // Each block is drawn as its own symbol.
    expect(text('.lab-chain [data-block="speed"] .lab-sym')).toMatch(/K\s*p.*\+.*K\s*i.*s/);
    expect(text('.lab-chain [data-block="park"] .lab-sym-math')).toMatch(/αβ\s*→\s*dq/);
    expect(text('.lab-chain [data-block="inverse_park"] .lab-sym-math')).toMatch(/dq\s*→\s*αβ/);
    expect(text('.lab-chain [data-block="clarke"] .lab-sym-math')).toMatch(/abc\s*→\s*αβ/);
    expect(text('.lab-chain [data-block="plant"] .lab-sym-word')).toBe("M");
    expect(text('.lab-chain [data-block="plant"] .lab-sym-caption')).toBe("PMSM");
    expect(text('.lab-chain [data-block="modulator"] .lab-sym-word')).toBe("SVPWM");
    expect($('[data-block="speed"] .lab-node-head')!.getAttribute("aria-label")).toContain(
      "Drawn as K p plus K i over s",
    );
  });

  it("marks a block whose limit holds in words, in place of its name", async () => {
    await opened();
    const limited = copy(hold);
    limited.series.wires["current.limited"] = limited.series.t.map(() => 1);
    vi.mocked(control.runStreamed).mockResolvedValue(limited);
    await press(".lab-run button.primary");
    await waitFor(() => expect($('[data-block="current"]')!.hasAttribute("data-held")).toBe(true));
    expect(text('[data-block="current"] .lab-sym-held')).toContain("At limit");
    expect($('[data-block="current"] .lab-sym-held path')).not.toBeNull();
    expect($('[data-block="park"]')!.hasAttribute("data-held")).toBe(false);
  });
});

describe("the drawing and the keyboard", () => {
  it("is one tab stop: the block reached, arrows between blocks, W round its wires, Escape back", async () => {
    // As wide as a desk's screen: the drawing itself, not the phone's list.
    const wide = { matches: false, addEventListener: () => undefined, removeEventListener: () => undefined };
    vi.stubGlobal("matchMedia", () => wide);
    await opened();
    await waitFor(() => expect(host.querySelectorAll(".lab-canvas .lab-node-head").length).toBeGreaterThan(3));
    const stops = () =>
      [...host.querySelectorAll<HTMLElement>(".lab-canvas .lab-node-head, .lab-canvas .lab-hit")].filter(
        (el) => el.tabIndex >= 0,
      );
    expect(stops().length).toBe(1);
    const start = stops()[0];
    act(() => start.focus());
    // An arrow takes the keyboard to the next block along the wires, and that block is now the stop.
    await act(() => fireEvent.keyDown(start, { key: "ArrowRight" }));
    const next = document.activeElement as HTMLElement;
    expect(next).not.toBe(start);
    expect(next.classList.contains("lab-node-head")).toBe(true);
    await waitFor(() => expect(stops()).toEqual([next]));
    // W goes to the first of its wires, and Escape comes back to the block.
    await act(() => fireEvent.keyDown(next, { key: "w" }));
    const wire = document.activeElement as HTMLElement;
    expect(wire.classList.contains("lab-hit")).toBe(true);
    const block = next.closest("[data-block]")!.getAttribute("data-block")!;
    expect([
      wire.closest("[data-edge]")!.getAttribute("data-wire-from"),
      wire.closest("[data-edge]")!.getAttribute("data-wire-to"),
    ]).toContain(block);
    await act(() => fireEvent.keyDown(wire, { key: "Escape" }));
    expect(document.activeElement).toBe(next);
    // The keys are said with the drawing.
    expect($(".lab-canvas")!.getAttribute("aria-describedby")).toBe("lab-diagram-keys");
    expect(text("#lab-diagram-keys")).toContain("W: wires");
  });

  it("offers a skip past the drawing to the scope, first in the lab's body", async () => {
    await opened();
    const skip = $(".lab-main > a.skip")!;
    expect(skip.textContent).toBe("Skip to the scope");
    await act(() => fireEvent.click(skip));
    expect(document.activeElement?.id).toMatch(/^lab-(play|scope-h)$/);
  });
});

describe("a block pressed", () => {
  it("opens the inspector with its animation, its mathematics, its figures and its values", async () => {
    await opened();
    expect($(".lab-inspector")).toBeNull();
    await press('[data-block="park"] .lab-node-head');
    expect(text(".lab-inspector h3")).toBe(presets.blocks.park.title);
    expect($(".lab-inspector .lab-animation [data-face]")!.getAttribute("data-face")).toBe("park");
    expect(host.querySelectorAll(".lab-inspector .lab-maths .katex").length).toBeGreaterThan(0);
    expect($('.lab-inspector .lab-live[data-wire="park.q"]')).not.toBeNull();
    await press('[data-block="inverter"] .lab-node-head');
    expect($(".lab-inspector .lab-animation [data-face]")!.getAttribute("data-face")).toBe("legs");
    await press('[data-block="speed"] .lab-node-head');
    expect($("#lab-p-speed-kp")).not.toBeNull();
    expect($('.lab-inspector .lab-keys [role="spinbutton"]')).not.toBeNull();
    expect($('[data-block="speed"]')!.classList.contains("is-on")).toBe(true);
  });

  it("names what every face shows, each quantity by its symbol, its value with its unit, and its scale", async () => {
    await opened();
    await press(".lab-run button.primary");
    await waitFor(() => expect($(".lab-cost-view")).not.toBeNull());
    const blocks = [...new Set([...host.querySelectorAll("[data-block]")].map((b) => b.getAttribute("data-block")))];
    const seen = new Map<string, string[]>();
    for (const b of blocks) {
      if (!$(`[data-block="${b}"] .lab-node-head`)) continue;
      await press(`[data-block="${b}"] .lab-node-head`);
      act(() => {
        cursor.t = hold.series.t[20];
        cursor.again();
      });
      const face = $(".lab-inspector .lab-face")!;
      const kind = face.getAttribute("data-face")!;
      expect(text(".lab-inspector .lab-face-title").length, `${b} names what it shows`).toBeGreaterThan(8);
      expect(face.querySelectorAll(".f-sym").length, `${b} names its quantities`).toBeGreaterThan(0);
      expect(face.querySelectorAll(".f-note").length, `${b} says its scale`).toBeGreaterThan(0);
      const values = [...face.querySelectorAll(".f-val")].map((v) => v.textContent ?? "");
      expect(values.length, `${b} writes its values`).toBeGreaterThan(0);
      seen.set(kind, values);
    }
    // Every kind of face in the scheme was seen, each with its values at the cursor in their units.
    expect([...seen.keys()]).toEqual(
      expect.arrayContaining(["clarke", "park", "ipark", "regulator", "carrier", "legs", "rotor", "phases", "plane"]),
    );
    expect(seen.get("phases")!.every((v) => /\d \S*A$/.test(v))).toBe(true);
    expect(seen.get("plane")!.every((v) => /\d \S*A$/.test(v))).toBe(true);
    expect(seen.get("park")![0]).toMatch(/°$/);
    expect(
      seen
        .get("park")!
        .slice(1)
        .every((v) => /\d \S*A$/.test(v)),
    ).toBe(true);
    expect(
      seen
        .get("ipark")!
        .slice(1)
        .every((v) => /\d \S*V$/.test(v)),
    ).toBe(true);
    // A duty is a share, between its rails of 0 and 1.
    const duties = seen
      .get("carrier")!
      .filter((v) => !v.includes("%"))
      .map(Number);
    expect(duties.length).toBe(3);
    expect(duties.every((d) => d >= 0 && d <= 1)).toBe(true);
    expect(text(".lab-inspector .lab-face-title")).not.toBe("");
  }, 20000);

  it("shows in its inspector each output's value at the instant the cursor is on", async () => {
    await opened();
    await press(".lab-run button.primary");
    await waitFor(() => expect($(".lab-cost-view")).not.toBeNull());
    const t = hold.series.t;
    for (const [block, wire] of [
      ["speed", "speed.torque"],
      ["park", "park.q"],
      ["modulator", "modulator.d_a"],
    ]) {
      await press(`[data-block="${block}"] .lab-node-head`);
      for (const at of [t[5], (t[20] + t[21]) / 2]) {
        act(() => {
          cursor.t = at;
          cursor.again();
        });
        // A transform's outputs are in the unit of what goes into it: Park's q is a current.
        const unit = wire === "park.q" ? "A" : (hold.wires.find((w) => w.name === wire)?.unit ?? "");
        const shown = $(`.lab-inspector .lab-live[data-wire="${wire}"]`)!.textContent;
        expect(shown).toBe(written(valueAt(t, hold.series.wires[wire], at), unit));
        expect(shown).not.toBe("–");
      }
    }
  });

  it("steps a gain in the inspector with the arrow keys, within its bounds", async () => {
    await opened();
    await press('[data-block="speed"] .lab-node-head');
    const kp = presets.schemes[0].blocks.find((b) => b.name === "speed")!.params.kp as number;
    const gain = $("#lab-k-speed-kp")!;
    expect(gain.getAttribute("role")).toBe("spinbutton");
    await act(async () => {
      fireEvent.keyDown(gain, { key: "ArrowUp" });
      await Promise.resolve();
    });
    const now = lab.get().scheme!.blocks.find((b) => b.name === "speed")!.params.kp as number;
    expect(now).toBeCloseTo(kp * 1.05, 4);
    expect(text(".lab-edited")).toContain("edited");
  });
});

describe("the inspector of a block", () => {
  it("defines the block, writes its mathematics and lists its figures with unit, bounds and source", async () => {
    await opened();
    await press('[data-block="speed"] .lab-node-head');
    const kind = presets.blocks.speed_pi;
    expect(text(".lab-inspector h3")).toBe(kind.title);
    expect(text(".lab-definition")).toContain((kind.summary || kind.definition).slice(0, 40));
    expect(host.querySelectorAll(".lab-maths .katex").length).toBeGreaterThan(0);
    const field = $("#lab-p-speed-kp")!.closest(".field")!;
    expect(field.querySelector(".unit")!.textContent).toBe("N·m·s/rad");
    expect(field.textContent).toContain("0 N·m·s/rad or more");
    expect(field.textContent).toContain(presets.schemes[0].blocks.find((b) => b.name === "speed")!.sources!.kp);
  });

  it("sends the scheme as edited with the next run, and can put a figure back as tuned", async () => {
    await opened();
    await press('[data-block="speed"] .lab-node-head');
    await type("#lab-p-speed-kp", "7.25");
    await press(".lab-run button.primary");
    await waitFor(() => expect(control.runStreamed).toHaveBeenCalled());
    const body = vi.mocked(control.runStreamed).mock.calls[0][0] as Body;
    expect(body.scheme.blocks.find((b) => b.name === "speed")!.params.kp).toBe(7.25);
    expect(body.scheme.blocks.find((b) => b.name === "speed")!.params.ki).toBe(
      presets.schemes[0].blocks.find((b) => b.name === "speed")!.params.ki,
    );
    expect(body.conditions).toEqual(designFile.conditions);
    await press("#lab-p-speed-kp-reset, .lab-param .lab-reset");
    expect(lab.get().scheme!.blocks.find((b) => b.name === "speed")!.params.kp).toBe(
      presets.schemes[0].blocks.find((b) => b.name === "speed")!.params.kp,
    );
  });

  it("shows a refusal at the figure it names, with the way out", async () => {
    await opened();
    vi.mocked(control.runStreamed).mockRejectedValue(
      new Refused("the gain is below nought", "give a gain of nought or more", "scheme.blocks.speed.kp"),
    );
    await press('[data-block="speed"] .lab-node-head');
    await press(".lab-run button.primary");
    await waitFor(() => expect(text(".lab-run-said")).toContain("refused"));
    const field = $("#lab-p-speed-kp")!.closest(".field")!;
    expect(field.classList.contains("is-wrong")).toBe(true);
    expect(field.querySelector(".said-wrong")!.textContent).toBe(
      "The gain is below nought. Give a gain of nought or more.",
    );
    expect($("#lab-p-speed-ki")!.closest(".field")!.classList.contains("is-wrong")).toBe(false);
  });
});

describe("a test", () => {
  it("is asked with the figures of the scenario picked, typed ones in place of the defaults", async () => {
    await opened();
    await act(() => fireEvent.change($("#lab-scenario")!, { target: { value: "speed_step" } }));
    const usual = presets.scenarios.find((s) => s.kind === "speed_step")!.defaults.foc_servo;
    expect($<HTMLInputElement>("#lab-s-speed_step-from_rpm")!.value).toBe(String(usual.from_rpm));
    await type("#lab-s-speed_step-to_rpm", "2400");
    await press(".lab-run button.primary");
    await waitFor(() => expect(control.runStreamed).toHaveBeenCalled());
    const body = vi.mocked(control.runStreamed).mock.calls[0][0] as Body;
    // A figure left as the engine proposed it is left to the engine: only what was typed is sent.
    expect(body.scenario).toEqual({ kind: "speed_step", to_rpm: 2400 });
    expect(body.fidelity).toBe(presets.fidelities[0]);
    expect(body.scheme.id).toBe(presets.chosen);
  });

  it("shows what has come of a run under way, then the whole of it", async () => {
    await opened();
    let probe: (p: RunProbe) => void = () => undefined;
    let finish: (r: Run) => void = () => undefined;
    vi.mocked(control.runStreamed).mockImplementation((_, onProbe) => {
      probe = onProbe;
      return new Promise<Run>((done) => (finish = done));
    });
    await press(".lab-run button.primary");
    const t = stepRun.series.t.slice(0, 12);
    const wires = { "plant.omega_m": stepRun.series.wires["plant.omega_m"].slice(0, 12) };
    act(() => {
      probe({ progress: 0.25, t: t[11], series: { t, wires } });
    });
    expect($<HTMLElement>(".lab-run .lab-cancel")!.style.getPropertyValue("--done")).toBe("0.25");
    expect($(".lab-cost-view")).toBeNull();
    await press('[data-block="plant"] .lab-node-head');
    expect($('.lab-inspector .lab-live[data-wire="plant.omega_m"]')!.textContent).not.toBe("–");
    await act(async () => {
      finish(stepRun);
      await Promise.resolve();
    });
    await waitFor(() => expect($(".lab-cost-view")).not.toBeNull());
    expect(text(".lab-run-said")).toContain("finished");
    expect(text('[aria-label="The step"]')).toContain("Overshoot");
  });

  it("is stopped by Cancel, and says so", async () => {
    await opened();
    let signal: AbortSignal | undefined;
    vi.mocked(control.runStreamed).mockImplementation((_, __, s) => {
      signal = s;
      return new Promise<Run>((_, fail) =>
        s!.addEventListener("abort", () => fail(Object.assign(new Error("stopped"), { name: "AbortError" }))),
      );
    });
    await press(".lab-run button.primary");
    // One button in the Run button's place, its fill how far the run has come.
    act(() => lab.set({ run: { ...lab.get().run, progress: 0.42 } }));
    const cancel = $(".lab-run .lab-cancel") as HTMLButtonElement;
    expect(cancel.getAttribute("aria-label")).toBe("Cancel the run, 42 % done");
    expect(cancel.style.getPropertyValue("--done")).toBe("0.42");
    expect(host.querySelector(".lab-run progress")).toBeNull();
    await act(() => fireEvent.click(cancel));
    expect(signal!.aborted).toBe(true);
    expect(lab.get().run.status).toBe("idle");
    expect($(".lab-cost-view")).toBeNull();
  });

  it("is asked again whole when its progress is lost on the way, and says so", async () => {
    await opened();
    vi.mocked(control.runStreamed).mockRejectedValue(new Error("the connection dropped"));
    await press(".lab-run button.primary");
    await waitFor(() => expect($(".lab-cost-view")).not.toBeNull());
    expect(control.run).toHaveBeenCalledTimes(1);
    expect(host.textContent).toContain("progress was lost on the way");
  });
});

describe("the Laplace lens", () => {
  it("leads with the headline figures in one row, then sets the plots in a grid", async () => {
    await opened();
    await press("#lab-tab-laplace");
    await waitFor(() => expect($(".lab-laplace svg.chart")).not.toBeNull());
    const heads = [...host.querySelectorAll(".lab-margins dt")].map((d) => d.textContent);
    expect(heads).toEqual(["Closed-loop bandwidth", "Phase margin", "Gain margin", "Open-loop crossover"]);
    // The target it was tuned for, its crossover and its bandwidth are three readings of one
    // loop: said once, each for what it is, with the engine's own figures.
    const q = loops.current_q!;
    expect(text(".lab-relation")).toBe(relationWords(q, loops.tuning.bandwidth_hz));
    expect(text(".lab-relation")).toMatch(/^Tuned for a target of 1\.00 kHz; as tuned, its open loop crosses 0 dB at /);
    // Gain over phase as one linked pair; the step and the poles beside them.
    expect(host.querySelectorAll(".lab-plots > .lab-bode svg.chart").length).toBe(2);
    expect(text(".lab-plots-side")).toContain("The step it predicts");
    expect($(".lab-plots-side .lab-poles svg.chart")).not.toBeNull();
    // The transfer functions are there on demand.
    expect($<HTMLDetailsElement>("details.lab-transfer")!.open).toBe(false);
    expect(text("details.lab-transfer summary")).toBe("Transfer functions");
  });

  it("keys each chart's traces in its head, beside its title, the closed loop in its own ink", async () => {
    await opened();
    await press("#lab-tab-laplace");
    await waitFor(() => expect($(".lab-laplace svg.chart")).not.toBeNull());
    const head = $(".lab-bode .lab-plot-head")!;
    expect(head.querySelector(".lab-plot-title")!.textContent).toBe("Gain and phase against frequency");
    expect(head.querySelector(".series-legend")!.textContent).toBe("open loopclosed loop");
    expect(head.querySelector(".key.lab-closed")).not.toBeNull();
    expect(host.querySelectorAll(".lab-bode svg .series.lab-closed")).toHaveLength(2);
    expect($(".lab-laplace .lab-plot:not(.lab-poles) .lab-plot-head .series-legend")).not.toBeNull();
  });

  it("draws each loop with its margins, and follows a gain as it is edited", async () => {
    await opened();
    await press("#lab-tab-laplace");
    await waitFor(() => expect($(".lab-laplace svg.chart")).not.toBeNull());
    expect(text(".lab-margins")).toContain("62.7°");
    expect(host.querySelectorAll(".lab-laplace [data-mark-hz]").length).toBeGreaterThanOrEqual(2);
    expect(host.querySelectorAll(".lab-laplace .katex").length).toBeGreaterThan(0);
    await press('[data-block="speed"] .lab-node-head');
    const asked = vi.mocked(control.loops).mock.calls.length;
    vi.useFakeTimers();
    act(() => {
      fireEvent.keyDown($("#lab-k-speed-kp")!, { key: "ArrowUp" });
    });
    await act(() => vi.advanceTimersByTimeAsync(600));
    vi.useRealTimers();
    expect(vi.mocked(control.loops).mock.calls.length).toBe(asked + 1);
    const body = vi.mocked(control.loops).mock.calls[asked][0] as Body;
    expect(body.scheme.blocks.find((b) => b.name === "speed")!.params.kp).not.toBe(
      presets.schemes[0].blocks.find((b) => b.name === "speed")!.params.kp,
    );
  });

  it("gives the engine's own reason for a scheme with no transfer function", async () => {
    vi.mocked(control.loops).mockResolvedValue(mpcLoopsFile as unknown as Loops);
    await opened();
    await press("#lab-scheme");
    const mpc = presets.schemes.find((s) => s.id === "mpc_torque")!;
    const option = [...host.querySelectorAll<HTMLElement>('.lab-picker-list [role="option"]')].find(
      (o) => o.querySelector(".lab-picker-label")!.textContent === mpc.label,
    )!;
    await act(() => fireEvent.click(option));
    await press("#lab-tab-laplace");
    await waitFor(() => expect(text(".lab-laplace")).toContain("has no linear transfer function"));
    expect($(".lab-laplace svg.chart")).toBeNull();
  });
});

const VALUES = [10000, 20000, 40000];
const VARY = { label: "carrier frequency", unit: "Hz", path: "scheme.blocks.modulator.carrier", values: VALUES };
const EXPLORATIONS = [
  {
    id: "carrier",
    title: "Carrier frequency",
    question: "What does a faster carrier cost?",
    about: "The same drive at three carrier frequencies.",
    group: "losses",
    applies: true,
    why_not: null,
    scheme: "foc_servo",
    scenario: { kind: "hold" },
    fidelity: "switched",
    vary: VARY,
    reads: ["losses.loss", "channels.ripple_pp"],
    sources: [{ title: "A textbook of drives", year: 2001, link: "" }],
  },
  {
    id: "observer",
    title: "Observer bandwidth",
    question: "How slow may the observer be?",
    about: "",
    group: "sensing",
    applies: false,
    why_not: "this scheme reads the angle from a sensor, so there is no observer to detune",
    scheme: "foc_servo",
    scenario: { kind: "hold" },
    fidelity: "averaged",
    vary: { label: "bandwidth", unit: "Hz", path: "scheme.blocks.observer.bandwidth", values: [50, 100] },
    reads: ["step.overshoot"],
    sources: [],
  },
] as unknown as Exploration[];
const LIBRARY = { explorations: EXPLORATIONS, reads: { "losses.loss": { label: "inverter loss", unit: "W" } } };
const variant = (value: number, loss: number, ripple: number) => ({
  value,
  label: `${value / 1000} kHz`,
  channels: { ripple_pp: ripple },
  losses: { loss },
  step: null,
  level: "pass",
});
const SWEEP = {
  vary: VARY,
  variants: [
    variant(10000, 1.8, 3.1),
    variant(20000, 2.14, 1.58),
    {
      ...variant(40000, 0, 0),
      channels: null,
      losses: null,
      refused: "the carrier is above what the gate drive allows",
    },
  ],
  baseline: 1,
  said: ["doubling the carrier halves the ripple and adds 0.34 W"],
} as unknown as Sweep;

describe("the library of explorations", () => {
  it("says it is not in this build when the engine has no such address", async () => {
    await opened();
    await press("#lab-tab-library");
    await waitFor(() => expect(text("#lab-tab-body")).toContain("not in this build"));
    expect($(".lab-card")).toBeNull();
  });

  it("lists each exploration as a card, ordered by group, and says why one does not apply", async () => {
    vi.mocked(control.explorations).mockResolvedValue(LIBRARY);
    await opened();
    await press("#lab-tab-library");
    await waitFor(() => expect(host.querySelectorAll(".lab-card").length).toBe(2));
    const [carrier, observer] = [...host.querySelectorAll(".lab-card")];
    expect([carrier, observer].map((c) => c.getAttribute("data-group"))).toEqual(["losses", "sensing"]);
    expect(carrier.querySelector(".lab-card-run")!.textContent).toContain("3 runs");
    expect(observer.querySelector(".lab-card-run")).toBeNull();
    expect(observer.textContent).toContain("Does not apply to this design.");
    // Why it does not apply is told on demand, with the method.
    await act(() => fireEvent.click(observer.querySelector(".lab-card-open")!));
    expect(observer.textContent).toContain("This scheme reads the angle from a sensor");
  });

  it("shows each card's icon, group, problem and outcome, and opens its details on a press", async () => {
    vi.mocked(control.explorations).mockResolvedValue(LIBRARY);
    await opened();
    await press("#lab-tab-library");
    await waitFor(() => expect(host.querySelectorAll(".lab-card").length).toBe(2));
    const card = $(".lab-card")!;
    expect(card.querySelector(".lab-card-icon svg")).not.toBeNull();
    expect(text(".lab-card .lab-tag")).toBe("Losses");
    // A card the page has no words for is titled by its question, and says what is expected.
    expect(text(".lab-card .lab-card-open")).toBe("What does a faster carrier cost?");
    expect(text(".lab-card .lab-outcome")).not.toBe("");
    const open = card.querySelector<HTMLButtonElement>(".lab-card-open")!;
    const more = card.querySelector<HTMLElement>(".lab-card-more")!;
    expect(open.getAttribute("aria-expanded")).toBe("false");
    expect(open.getAttribute("aria-controls")).toBe(more.id);
    expect(more.hidden).toBe(true);
    await act(() => fireEvent.click(open));
    expect(open.getAttribute("aria-expanded")).toBe("true");
    expect(more.hidden).toBe(false);
    expect(more.textContent).toContain("The same drive at three carrier frequencies.");
    expect(more.textContent).toContain("carrier frequency, Hz: 3 runs");
    expect(more.textContent).toContain("inverter loss");
    expect(card.classList.contains("is-open")).toBe(true);
    await act(() => fireEvent.click(open));
    expect(more.hidden).toBe(true);
  });

  it("titles a known exploration by the problem it answers, not by its method", () => {
    const known: Exploration = { ...EXPLORATIONS[0], id: "variable_frequency" };
    expect(pitchOf(known).pain).toBe("Switching loss too high at light load");
    expect(pitchOf(EXPLORATIONS[0]).pain).toBe(EXPLORATIONS[0].question);
  });

  it("runs a sweep, draws each figure it reads against what was varied, and says what the engine says", async () => {
    vi.mocked(control.explorations).mockResolvedValue(LIBRARY);
    const sweep = vi.spyOn(control, "sweep").mockImplementation((_, onProbe) => {
      onProbe({ variant: 0, of: 3, progress: 1 / 3, result: SWEEP.variants[0] });
      return Promise.resolve(SWEEP);
    });
    await opened();
    await press("#lab-tab-library");
    await waitFor(() => expect($(".lab-card-run")).not.toBeNull());
    await press(".lab-card-run");
    await waitFor(() => expect(host.querySelectorAll(".lab-multiples svg.chart").length).toBe(2));
    expect(sweep.mock.calls[0][0]).toEqual({ ...designFile, exploration: "carrier" });
    expect(text(".lab-multiples .lab-plot-title")).toBe("Inverter loss");
    // The variant the others are set against is drawn as a level across: 2.14 W.
    expect($(".lab-multiples svg.chart")!.textContent).toContain("design 2.14");
    // Two variants were run and one refused: two dots on each chart.
    expect($(".lab-multiples svg.chart")!.querySelectorAll("circle.lab-dot").length).toBe(2);
    expect(text(".lab-said-list")).toBe("Doubling the carrier halves the ripple and adds 0.34 W");
    const rows = [...host.querySelectorAll(".lab-variants li")];
    expect(rows.length).toBe(3);
    expect(rows[2].textContent).toContain("not run. The carrier is above what the gate drive allows.");
    expect(rows[2].querySelector("button")).toBeNull();
    expect(rows[0].querySelector("button")!.textContent).toBe("Open this variant in the lab");
  });
});

describe("what the engine sends is shown as text", () => {
  it("writes a name with markup in it as the letters it is made of", async () => {
    const hostile = copy(presets);
    const bad = '<img src=x onerror="document.title=1"><script>document.title=2</script>';
    hostile.schemes[0].label = bad;
    hostile.schemes[0].about = bad;
    hostile.why = bad;
    hostile.blocks.speed_pi.title = bad;
    hostile.blocks.speed_pi.definition = bad;
    hostile.blocks.speed_pi.summary = bad;
    hostile.blocks.speed_pi.math = ["\\href{javascript:document.title=3}{x}", bad];
    hostile.scenarios[0].about = bad;
    await opened(hostile);
    await press('[data-block="speed"] .lab-node-head');
    expect(host.querySelector("img, script")).toBeNull();
    expect(host.querySelector('a[href^="javascript"]')).toBeNull();
    expect(text(".lab-about")).toContain("<img src=x");
    expect(text(".lab-inspector h3")).toBe(bad);
    expect(document.title).not.toMatch(/^[123]$/);
  });
});

describe("a block's words", () => {
  it("says what it does in a few lines first, and keeps the full account folded under it", async () => {
    const short = copy(presets);
    short.blocks.speed_pi.summary = "A PI that asks the torque closing the speed error.";
    await opened(short);
    await press('[data-block="speed"] .lab-node-head');
    expect(text(".lab-definition")).toBe("A PI that asks the torque closing the speed error.");
    const fold = host.querySelector<HTMLDetailsElement>(".lab-indetail")!;
    expect(fold.open).toBe(false);
    expect(fold.textContent).toContain(presets.blocks.speed_pi.definition.slice(0, 40));
  });
});

describe("where the engine runs in the browser", () => {
  it("says in one sentence that the lab runs on your own machine, and how to start it", () => {
    vi.spyOn(api, "mode").mockReturnValue("browser");
    const page = document.createElement("div");
    page.innerHTML = entryWords();
    expect(page.querySelectorAll("p").length).toBe(1);
    expect(page.querySelector("button")).toBeNull();
    expect(page.textContent).toContain("The control lab runs on your own machine");
    expect([...page.querySelectorAll("code")].map((c) => c.textContent)).toEqual([
      "motionsim serve",
      "docker compose up",
    ]);
  });
});

describe("the run played", () => {
  const frames = (n: number) =>
    act(async () => {
      for (let k = 0; k < n; k++) await new Promise((done) => requestAnimationFrame(() => done(null)));
    });

  it("offers one press to run, at the top, while nothing has run, and the player once something has", async () => {
    await opened();
    expect($("#lab-play")).toBeNull();
    expect(text(".lab-rest")).toContain("Nothing has run yet");
    // The scope points to the run at the top of the lab: it has no press of its own.
    expect(text(".lab-rest")).toContain("Run the test, at the top of the lab");
    expect($(".lab-rest button")).toBeNull();
    const runs = [...document.querySelectorAll(".lab button")].filter((b) =>
      /^(Run the test|Run again)/.test(b.textContent ?? ""),
    );
    expect(runs).toEqual([$(".lab-top .lab-go")]);
    expect($(".lab-diagram")!.classList.contains("is-resting")).toBe(true);
    await press(".lab-top .lab-go");
    await waitFor(() => expect($("#lab-play")).not.toBeNull());
    expect(control.runStreamed).toHaveBeenCalledTimes(1);
    expect($(".lab-diagram")!.classList.contains("is-resting")).toBe(false);
    // Once the run is of the inputs as they stand, "Run again" is no longer the one orange press.
    await waitFor(() => expect($(".lab-top .lab-go")!.classList.contains("primary")).toBe(false));
    expect($(".lab-top .lab-go")!.classList.contains("ghost")).toBe(true);
  });

  it("sweeps the cursor through the run on Play and holds it on Pause", async () => {
    await opened();
    await press(".lab-run button.primary");
    await waitFor(() => expect($("#lab-play")).not.toBeNull());
    // Motion is kept down here: the run is not played unasked.
    expect($("#lab-play")!.getAttribute("aria-pressed")).toBe("false");
    act(() => cursor.set(hold.series.t[0]));
    await frames(2);
    const from = cursor.t;
    await press("#lab-play");
    expect($("#lab-play")!.getAttribute("aria-pressed")).toBe("true");
    expect(text("#lab-play")).toContain("Pause");
    await frames(6);
    const moved = cursor.t;
    expect(moved).toBeGreaterThan(from);
    expect(moved).toBeLessThanOrEqual(hold.series.t[hold.series.t.length - 1]);
    // Every figure of the inspector is at the instant the player has come to.
    await press('[data-block="plant"] .lab-node-head');
    const wire = "plant.omega_m";
    const shown = host.querySelector(`.lab-inspector .lab-live[data-wire="${wire}"]`)!.textContent;
    expect(shown).toBe(written(valueAt(hold.series.t, hold.series.wires[wire], cursor.t), "rad/s"));
    await press("#lab-play");
    expect($("#lab-play")!.getAttribute("aria-pressed")).toBe("false");
    const held = cursor.t;
    await frames(4);
    expect(cursor.t).toBe(held);
  });

  it("draws every strip of the scope up to the cursor as it plays, and whole once it rests", async () => {
    await opened();
    await press(".lab-run button.primary");
    await waitFor(() => expect($(".scope-strip")).not.toBeNull());
    const clips = () =>
      [...host.querySelectorAll(".scope-plot svg")].map((svg) => ({
        drawn: Number(svg.querySelector(".scope-past-clip")!.getAttribute("width")),
        whole: Number(svg.querySelector("clipPath rect")!.getAttribute("width")),
        line: svg.querySelector(".scope-cursor")!.getAttribute("d"),
      }));
    expect(clips().length).toBeGreaterThan(1);
    act(() => cursor.set(hold.series.t[0]));
    await frames(2);
    await press("#lab-play");
    expect($(".scope-strips")!.classList.contains("is-playing")).toBe(true);
    await frames(4);
    const early = clips();
    await frames(8);
    const later = clips();
    expect(cursor.t).toBeGreaterThan(hold.series.t[0]);
    later.forEach((c, n) => {
      // Every strip is drawn as far as the cursor and no further, and further than a moment ago.
      expect(c.drawn).toBeGreaterThan(early[n].drawn);
      expect(c.drawn).toBeLessThan(c.whole);
      expect(c.line).toMatch(/^M[\d.]+ /);
    });
    // All strips share the one time axis: their cursors stand at the same place.
    expect(new Set(later.map((c) => /^M([\d.]+)/.exec(c.line!)![1])).size).toBe(1);
    // Every value read out beside a trace is the trace's own at the cursor.
    const omega = host.querySelector('.scope-legend [data-value="plant.omega_m"]')!.textContent;
    // A trace's own remove button is out of the Tab order; a strip's is in it, and named once.
    const rows = [...host.querySelectorAll<HTMLButtonElement>(".scope-legend li .scope-remove")];
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.every((b) => b.tabIndex === -1)).toBe(true);
    expect(host.querySelector(".scope-strip-head .scope-remove")!.getAttribute("tabindex")).toBeNull();
    expect(host.querySelector('[aria-label*="the the" i]')).toBeNull();
    // Read in rpm, to three figures of the strip's scale: thousands of rpm, to the whole one.
    const own = (valueAt(hold.series.t, hold.series.wires["plant.omega_m"], cursor.t)! * 30) / Math.PI;
    expect(omega).toMatch(/^-?\d+ rpm$/);
    expect(Math.abs(Number.parseFloat(omega ?? "") - own)).toBeLessThanOrEqual(0.5);
    await press("#lab-play");
    expect($(".scope-strips")!.classList.contains("is-playing")).toBe(false);
    await frames(2);
    // Held, the time at the cursor is read on the time axis, under the cursor, once: on the last strip.
    const chips = [...host.querySelectorAll(".scope-when")];
    expect(chips).toHaveLength(1);
    expect(chips[0].closest(".scope-strip")).toBe([...host.querySelectorAll(".scope-strip")].pop());
    expect(chips[0].getAttribute("visibility")).toBe("visible");
    expect(chips[0].querySelector("text")!.textContent).toBe(written(cursor.t, "s"));
    // Mid-run it stands under the cursor; at the run's start it is kept inside the plot, its
    // left edge at the plot's.
    const ts = hold.series.t;
    act(() => cursor.set((ts[0] + ts[ts.length - 1]) / 2));
    await frames(2);
    const at = /^M([\d.]+)/.exec(clips().pop()!.line!)![1];
    expect(Number(chips[0].querySelector("text")!.getAttribute("x"))).toBeCloseTo(Number(at), 1);
    act(() => cursor.set(ts[0]));
    await frames(2);
    const left = /^M([\d.]+)/.exec(clips().pop()!.line!)![1];
    expect(Number(chips[0].querySelector("rect")!.getAttribute("x"))).toBeCloseTo(Number(left), 1);
    // At rest, every trace is drawn whole.
    for (const c of clips()) expect(c.drawn).toBe(c.whole);
  });

  it("plays to the end of the run and holds there, and starts over when played from the end", async () => {
    await opened();
    await press(".lab-run button.primary");
    await waitFor(() => expect($("#lab-play")).not.toBeNull());
    const end = hold.series.t[hold.series.t.length - 1];
    act(() => cursor.set(end - (end - hold.series.t[0]) * 0.001));
    await frames(2);
    await press("#lab-play");
    // Played from its very end, it starts over.
    await frames(3);
    expect(cursor.t).toBeLessThan(end * 0.5);
    await act(() => fireEvent.click(host.querySelectorAll<HTMLButtonElement>(".lab-player .segmented button")[3]));
    act(() => cursor.set(end - (end - hold.series.t[0]) * 1e-5));
    await frames(6);
    expect(cursor.t).toBe(end);
    expect($("#lab-play")!.getAttribute("aria-pressed")).toBe("false");
  });

  it("is played from the scope: no switch shares the window between a diagram and results", async () => {
    await opened();
    await press(".lab-run button.primary");
    await waitFor(() => expect($("#lab-play")).not.toBeNull());
    expect($("#lab-play")!.closest(".scope")).not.toBeNull();
    expect($("#lab-cursor")!.closest(".scope")).not.toBeNull();
    const words = [...host.querySelectorAll("button")].map((b) => b.textContent?.trim());
    for (const gone of ["Diagram", "Split"]) expect(words).not.toContain(gone);
    expect(host.querySelector('[aria-label="What the window shows"]')).toBeNull();
    expect("room" in lab.get()).toBe(false);
    // The scope comes straight after the diagram, and what the run cost under it.
    const order = [".lab-diagram", ".scope", "#lab-tab-body"].map((q) => $(q)!);
    expect(order[0].compareDocumentPosition(order[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(order[1].compareDocumentPosition(order[2]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("is stopped by the cursor moved by hand, and plays faster at a faster pace", async () => {
    await opened();
    await press(".lab-run button.primary");
    await waitFor(() => expect($("#lab-play")).not.toBeNull());
    await press("#lab-play");
    await act(() => fireEvent.change($("#lab-cursor")!, { target: { value: String(hold.series.t[5]) } }));
    expect($("#lab-play")!.getAttribute("aria-pressed")).toBe("false");
    const paces = [...host.querySelectorAll<HTMLButtonElement>(".lab-player .segmented button")];
    // Each pace is named for how long one sweep takes: a run of milliseconds is not real time.
    expect(paces.map((b) => b.textContent)).toEqual(["32 s", "16 s", "8 s", "4 s"]);
    await act(() => fireEvent.click(paces[3]));
    expect(paces[3].getAttribute("aria-pressed") ?? paces[3].getAttribute("aria-checked")).toBe("true");
  });

  it("never plays a new run by itself: it is shown whole, and played when Play is pressed", async () => {
    const still = { matches: false, addEventListener: () => undefined, removeEventListener: () => undefined };
    // Narrow, so the chain is drawn; motion not kept down.
    vi.stubGlobal("matchMedia", (q: string) => (/reduced-motion/.test(q) ? still : { ...still, matches: true }));
    await opened();
    await press(".lab-run button.primary");
    await waitFor(() => expect($("#lab-play")).not.toBeNull());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect($("#lab-play")!.getAttribute("aria-pressed")).toBe("false");
    await press("#lab-play");
    expect($("#lab-play")!.getAttribute("aria-pressed")).toBe("true");
  });
});

describe("a wire of the drawing", () => {
  async function wired(): Promise<{ box: HTMLElement; layout: Layout }> {
    await opened();
    const layout = layoutOf(presets.schemes[0], presets.blocks, presets.sources);
    const box = document.createElement("div");
    box.className = "lab";
    box.innerHTML = '<p class="lab-said"></p><div class="lab-diagram"></div>';
    host.append(box);
    const root = createRoot(box.querySelector(".lab-diagram")!);
    act(() => root.render(createElement(Wiring, { layout })));
    cleanup.push(() => act(() => root.unmount()));
    return { box, layout };
  }

  it("is drawn in the scope when it is pressed, and no longer when pressed again", async () => {
    const { box, layout } = await wired();
    // A wire the plots do not draw by themselves.
    const edge = layout.edges.find((e) => e.wires.includes("current.v_d"))!;
    const hit = box.querySelector(`[data-edge="${edge.id}"] .lab-hit`)!;
    expect(lab.get().plotted).toBeNull();
    expect(box.querySelector(`[data-edge="${edge.id}"]`)!.classList.contains("is-pinned")).toBe(false);
    await act(() => fireEvent.click(hit));
    expect(lab.get().plotted).toEqual(expect.arrayContaining(edge.wires));
    expect(box.querySelector(`[data-edge="${edge.id}"]`)!.classList.contains("is-pinned")).toBe(true);
    expect(box.querySelector(".lab-said")!.textContent).toContain("drawn in the scope");
    await act(() => fireEvent.click(hit));
    expect(lab.get().plotted).not.toContain("current.v_d");
    expect(box.querySelector(`[data-edge="${edge.id}"]`)!.classList.contains("is-pinned")).toBe(false);
  });

  it("pins every line of a bus together, and the scope draws them", async () => {
    const { box, layout } = await wired();
    await press(".lab-run button.primary");
    await waitFor(() => expect($(".lab-cost-view")).not.toBeNull());
    const bus = layout.edges.find((e) => e.from === "clarke" && e.wires.length === 2)!;
    await act(() => fireEvent.click(box.querySelector(`[data-edge="${bus.id}"] .lab-hit`)!));
    expect(lab.get().plotted).toEqual(expect.arrayContaining(bus.wires));
    await waitFor(() => expect($('.scope-legend [data-wire="clarke.alpha"]')).not.toBeNull());
    expect($('.scope-legend [data-wire="clarke.beta"]')).not.toBeNull();
    // Named as an engineer writes them, never by the engine's own name for the wire.
    expect(text('.scope-legend [data-wire="clarke.alpha"] .scope-name')).toBe("iα");
  });

  it("is a probe: pressed, its trace comes into the scope with a dot in its ink; pressed again, it goes", async () => {
    const { box, layout } = await wired();
    await press(".lab-run button.primary");
    await waitFor(() => expect($(".scope-strip")).not.toBeNull());
    const edge = layout.edges.find((e) => e.wires[0] === "current.v_d")!;
    const hit = box.querySelector<SVGElement>(`[data-edge="${edge.id}"] .lab-hit`)!;
    const row = () => $('.scope-legend [data-wire="current.v_d"]');
    expect(row()).toBeNull();
    expect(hit.getAttribute("aria-pressed")).toBe("false");
    expect(box.querySelector(`[data-edge="${edge.id}"] .lab-probe`)).toBeNull();
    await act(() => fireEvent.click(hit));
    await waitFor(() => expect(row()).not.toBeNull());
    expect(hit.getAttribute("aria-pressed")).toBe("true");
    // Its strip is the voltages', and its dot on the wire is in the ink its trace is drawn in.
    const strip = row()!.closest<HTMLElement>(".scope-strip")!;
    const ink = /pr-(\d)/.exec(row()!.querySelector(".scope-swatch path")!.getAttribute("class")!)![1];
    const dot = box.querySelector(`[data-edge="${edge.id}"] .lab-probe circle`)!;
    expect(dot.getAttribute("class")).toBe(`pr-${ink}`);
    // The dot sits clear of the wire's name, after it or over it: never on its mark or its index.
    const l = edge.label!;
    const [cx, cy] = [Number(dot.getAttribute("cx")), Number(dot.getAttribute("cy"))];
    expect(cx - 3.6 >= l.x + l.w || cy + 3.6 <= l.y).toBe(true);
    expect(strip.querySelector(".scope-plot svg .scope-trace")).not.toBeNull();
    // The keyboard reaches it (by W from its block: the drawing is one tab stop) and takes it out again.
    expect(hit.getAttribute("tabindex")).toBe("-1");
    await act(() => fireEvent.keyDown(hit, { key: "Enter" }));
    await waitFor(() => expect(row()).toBeNull());
    expect(box.querySelector(`[data-edge="${edge.id}"] .lab-probe`)).toBeNull();
  });

  it("probes the speed, the torque and the currents with their references before anything is pressed", async () => {
    await opened();
    await press(".lab-run button.primary");
    await waitFor(() => expect($(".scope-strip")).not.toBeNull());
    const shown = [...host.querySelectorAll<HTMLElement>(".scope-legend [data-wire]")].map((li) => li.dataset.wire);
    for (const wire of ["plant.omega_m", "cmd.speed", "plant.torque", "plant.load_torque", "plant.i_q", "plant.i_d"])
      expect(shown).toContain(wire);
    expect(shown).toEqual(expect.arrayContaining(["current_ref.i_q", "plant.i_a", "plant.i_b", "plant.i_c"]));
    // What the legs are told is a probe away, not drawn unasked.
    expect(shown.some((w) => w?.startsWith("modulator."))).toBe(false);
    // A strip is taken out whole by its own press.
    const speed = host.querySelector<HTMLElement>('.scope-strip[data-strip="rpm"]')!;
    expect(speed.querySelector("h4")!.textContent).toBe("Speed, rpm");
    await act(() => fireEvent.click(speed.querySelector(".scope-strip-head .scope-remove")!));
    await waitFor(() => expect($('.scope-strip[data-strip="rpm"]')).toBeNull());
    expect(lab.get().plotted).not.toContain("plant.omega_m");
  });

  it("draws a bus thick with its count, a dot at a branch and a circle where signals are summed", async () => {
    const { box, layout } = await wired();
    expect(box.querySelectorAll(".lab-seg.is-bus").length).toBeGreaterThan(0);
    expect(box.querySelectorAll(".lab-dot").length).toBe(layout.nets.reduce((n, net) => n + net.dots.length, 0));
    expect(box.querySelectorAll(".lab-dot").length).toBeGreaterThan(0);
    const toMotor = box.querySelector('[data-wire-from="inverter"][data-wire-to="plant"] .lab-tick text')!;
    expect(toMotor.textContent).toBe("3");
    const sums = [...box.querySelectorAll(".lab-sum")];
    expect(sums.map((s) => s.getAttribute("data-sum")).sort()).toEqual(layout.sums.map((s) => s.node).sort());
    expect(sums[0].querySelector("circle")).not.toBeNull();
    expect([...sums[0].querySelectorAll("text")].map((t) => t.textContent).sort()).toEqual(["+", "−"]);
    // One arrowhead for each wire, where it comes in.
    expect(box.querySelectorAll(".lab-wire > .lab-arrow").length).toBe(layout.edges.length);
  });

  it("lights its own run and the two blocks it joins when pointed at", async () => {
    const { box, layout } = await wired();
    setWiring(layout.edges);
    const edge = layout.edges[2];
    await act(() => fireEvent.pointerOver(box.querySelector(`[data-edge="${edge.id}"] .lab-hit`)!));
    const lit = [...box.querySelectorAll(".lab-wire[data-path]")].map((w) => w.getAttribute("data-edge"));
    expect(lit).toEqual([edge.id]);
  });
});

describe("a gain changed in the inspector", () => {
  it("marks the gain and the block as changed, and is put back by its reset", async () => {
    await opened();
    await press('[data-block="speed"] .lab-node-head');
    const tuned = presets.schemes[0].blocks.find((b) => b.name === "speed")!.params.kp as number;
    const gain = () => $("#lab-k-speed-kp")!;
    const reset = () => $("#lab-k-speed-kp")!.closest(".lab-key")!.querySelector<HTMLButtonElement>(".lab-key-reset")!;
    expect(gain().getAttribute("aria-valuenow")).toBe(String(tuned));
    expect(reset().hidden).toBe(true);
    expect($('[data-block="speed"]')!.classList.contains("is-changed")).toBe(false);
    await act(() => fireEvent.keyDown(gain(), { key: "ArrowUp", shiftKey: true }));
    await waitFor(() => expect($('[data-block="speed"]')!.classList.contains("is-changed")).toBe(true));
    // On the diagram, the one mark of it: a dot, and the words for one who cannot see it.
    expect($('[data-block="speed"] .lab-sym-changed')).not.toBeNull();
    expect(text('[data-block="speed"] .lab-changed')).toBe("changed");
    expect($('[data-block="speed"] .lab-node-head')!.getAttribute("aria-label")).toContain("changed");
    expect(gain().closest(".lab-key")!.classList.contains("is-changed")).toBe(true);
    expect(reset().hidden).toBe(false);
    expect(reset().getAttribute("aria-label")).toContain("tuned value");
    expect($('[data-block="current"]')!.classList.contains("is-changed")).toBe(false);
    await act(() => fireEvent.click(reset()));
    await waitFor(() => expect($('[data-block="speed"]')!.classList.contains("is-changed")).toBe(false));
    expect(reset().hidden).toBe(true);
    expect(lab.get().scheme!.blocks.find((b) => b.name === "speed")!.params.kp).toBe(tuned);
  });
});

describe("the key settings of a block", () => {
  const kinds = kindsFile as Record<string, { name: string; choices: string[]; default: unknown }[]>;

  it("names one to four key settings for every kind with figures, each a figure the kind has", () => {
    expect(Object.keys(kinds).length).toBe(23);
    for (const [k, params] of Object.entries(kinds)) {
      expect(KEY_SETTINGS[k], k).toBeDefined();
      const names = params.map((p) => p.name);
      for (const [name] of KEY_SETTINGS[k]) expect(names, `${k}.${name}`).toContain(name);
      if (params.length) expect(KEY_SETTINGS[k].length, k).toBeGreaterThanOrEqual(1);
      else expect(KEY_SETTINGS[k], k).toEqual([]);
      expect(KEY_SETTINGS[k].length, k).toBeLessThanOrEqual(4);
      // A choice is a choice in the registry: a list of ways or on and off.
      for (const [name, control] of KEY_SETTINGS[k]) {
        const p = params.find((x) => x.name === name)!;
        expect(control === "choice", `${k}.${name}`).toBe(p.choices.length > 0 || typeof p.default === "boolean");
      }
    }
  });

  it("offers the first figures of a kind it does not know, its gains first", () => {
    const kind = { ...presets.blocks.speed_pi, kind: "made_up" };
    expect(keysOf(kind, ["ki"]).map(([p]) => p.name)).toEqual(["ki", "kp", "limit"]);
    expect(keysOf(undefined)).toEqual([]);
  });

  it("puts the key settings first, and folds every figure under All parameters", async () => {
    await opened();
    await press('[data-block="speed"] .lab-node-head');
    const order = [...host.querySelectorAll(".lab-inspector > *")].map((e) => e.className);
    expect(order.indexOf("lab-keys")).toBeLessThan(order.indexOf("lab-now"));
    expect(order.indexOf("lab-now")).toBeLessThan(order.indexOf("lab-all"));
    expect($<HTMLDetailsElement>(".lab-inspector .lab-all")!.open).toBe(false);
    expect($(".lab-inspector .lab-all #lab-p-speed-kp")).not.toBeNull();
    expect([...host.querySelectorAll(".lab-keys .lab-key-name")].map((e) => e.textContent)).toEqual([
      "Kp",
      "Ki",
      "Limit",
    ]);
  });

  it("takes a choice at once and marks the scheme edited, then resets it to the tuned value", async () => {
    await opened();
    await press('[data-block="modulator"] .lab-node-head');
    const tuned = presets.schemes[0].blocks.find((b) => b.name === "modulator")!.params.pwm ?? "space-vector";
    const sine = $('#lab-k-modulator-pwm [data-value="sine"]')!;
    expect(sine.getAttribute("role")).toBe("radio");
    await act(() => fireEvent.click(sine));
    expect(lab.get().scheme!.blocks.find((b) => b.name === "modulator")!.params.pwm).toBe("sine");
    expect(sine.getAttribute("aria-checked")).toBe("true");
    await waitFor(() => expect($('[data-block="modulator"]')!.classList.contains("is-changed")).toBe(true));
    const reset = $("#lab-k-modulator-pwm")!.closest(".lab-key")!.querySelector<HTMLButtonElement>(".lab-key-reset")!;
    await act(() => fireEvent.click(reset));
    expect(lab.get().scheme!.blocks.find((b) => b.name === "modulator")!.params.pwm).toBe(tuned);
  });

  it("steps a figure with its plus and minus, within its bounds, and resets it to the tuned value", async () => {
    await opened();
    await press('[data-block="position"] .lab-node-head');
    const counts = () => lab.get().scheme!.blocks.find((b) => b.name === "position")!.params.counts as number;
    const tuned = counts() ?? 4096;
    const key = $("#lab-k-position-counts")!.closest(".lab-key")!;
    const [less, more] = [...key.querySelectorAll<HTMLButtonElement>(".lab-key-step")];
    await act(() => fireEvent.click(more));
    expect(counts()).toBe(tuned * 2);
    await act(() => fireEvent.click(less));
    await act(() => fireEvent.click(less));
    expect(counts()).toBe(tuned / 2);
    expect($<HTMLInputElement>("#lab-k-position-counts")!.value).toBe(String(tuned / 2));
    await act(() => fireEvent.click(key.querySelector(".lab-key-reset")!));
    expect(counts()).toBe(tuned);
  });
});

describe("the commands' key settings", () => {
  it("expose the test and its target speed, and send what is set with the next run", async () => {
    await opened();
    await press('[data-block="cmd"] .lab-node-head');
    const test = $('.lab-keys [role="radiogroup"]')!;
    // Only the tests this scheme takes: it is told a speed, so no torque step and no stall.
    expect([...test.querySelectorAll("button")].map((b) => b.textContent)).toEqual([
      "Hold",
      "Speed step",
      "Start",
      "Load step",
    ]);
    // A hold runs at the design point, which the main page sets.
    expect(text(".lab-key-point")).toContain("2000");
    await act(() => fireEvent.click(test.querySelector('[data-value="speed_step"]')!));
    expect(lab.get().scenario).toBe("speed_step");
    const target = $<HTMLInputElement>("#lab-kt-speed_step-to_rpm")!;
    expect(target.closest(".lab-key")!.querySelector(".lab-key-name")!.textContent).toBe("Target speed");
    const usual = presets.scenarios.find((s) => s.kind === "speed_step")!.defaults.foc_servo.to_rpm as number;
    expect(Number(target.value)).toBe(usual);
    await type("#lab-kt-speed_step-to_rpm", "2400");
    expect(lab.get().figures.speed_step.to_rpm).toBe("2400");
    // The run panel shows the same figure: one test, set from either place.
    expect($<HTMLInputElement>("#lab-s-speed_step-to_rpm")!.value).toBe("2400");
    await press(".lab-run button.primary");
    await waitFor(() => expect(control.runStreamed).toHaveBeenCalled());
    const body = vi.mocked(control.runStreamed).mock.calls[0][0] as Body;
    expect(body.scenario).toEqual({ kind: "speed_step", to_rpm: 2400 });
    // Reset leaves the figure to the engine again.
    await act(() => fireEvent.click(target.closest(".lab-key")!.querySelector<HTMLButtonElement>(".lab-key-reset")!));
    expect(lab.get().figures.speed_step.to_rpm).toBeUndefined();
    expect(Number($<HTMLInputElement>("#lab-kt-speed_step-to_rpm")!.value)).toBe(usual);
  });

  it("offer the load torque and the step time of a load step, and the target speed on the speed ramp", async () => {
    await opened();
    await press('[data-block="cmd"] .lab-node-head');
    await act(() => fireEvent.click($('.lab-keys [data-value="load_step"]')!));
    const names = [...host.querySelectorAll(".lab-keys .lab-key-name")].map((e) => e.textContent);
    expect(names).toEqual(["Test", "Load torque", "Step at"]);
    await act(() => fireEvent.click($('.lab-keys [data-value="start"]')!));
    await press('[data-block="speed_ref"] .lab-node-head');
    expect($("#lab-kt-start-to_rpm")).not.toBeNull();
    expect($("#lab-k-speed_ref-shape")).not.toBeNull();
  });
});

describe("schemes compared", () => {
  it("runs the recommended scheme and others side by side, chooses in figures, takes one in a press", async () => {
    await opened();
    const waiting: ((r: Run) => void)[] = [];
    vi.mocked(control.run).mockImplementation(() => new Promise<Run>((resolve) => waiting.push(resolve)));
    await press(".lab-choose-open");
    await waitFor(() => expect(waiting.length).toBeGreaterThanOrEqual(2));
    // Every scheme is asked at once, before any has answered: they run in parallel.
    const asked = vi.mocked(control.run).mock.calls.map((c) => (c[0] as Body).scheme.id);
    expect(asked[0]).toBe(presets.chosen);
    expect(new Set(asked).size).toBe(asked.length);
    expect(host.querySelectorAll(".lab-cmp-skel").length).toBeGreaterThan(0);
    expect(text(".lab-choice")).toMatch(/Running \d schemes side by side/);
    await act(async () => {
      waiting.forEach((resolve) => resolve(copy(hold)));
      await Promise.resolve();
    });
    await waitFor(() => expect($(".lab-choice.is-ready")).not.toBeNull());
    expect(text(".lab-choice")).toMatch(/^Choose .+ because it passes/);
    const heads = [...host.querySelectorAll(".lab-cmp-table thead th")].map((th) => th.textContent ?? "");
    expect(heads.length).toBe(asked.length);
    expect(heads[0]).toContain("recommended");
    for (const row of ["Verdict", "THD", "Sensor"]) expect(text(".lab-cmp-table tbody")).toContain(row);
    // A scheme taken from the table comes into the lab with its run, and the run is shown.
    const other = asked[1];
    const use = [...host.querySelectorAll<HTMLButtonElement>(".lab-cmp-table tfoot button")].find((b) => !b.disabled)!;
    await act(() => fireEvent.click(use));
    expect(lab.get().scheme!.id).toBe(other);
    expect(lab.get().run.status).toBe("done");
    expect(lab.get().tab).toBe("run");
  });
});

describe("none passes", () => {
  it("offers the closest scheme's first change in one press, which takes it into the lab and opens it", async () => {
    await opened();
    const waiting: ((r: Run) => void)[] = [];
    vi.mocked(control.run).mockImplementation(() => new Promise<Run>((resolve) => waiting.push(resolve)));
    await press(".lab-choose-open");
    await waitFor(() => expect(waiting.length).toBeGreaterThanOrEqual(2));
    const asked = vi.mocked(control.run).mock.calls.map((c) => (c[0] as Body).scheme.id);
    const lever = {
      kind: "block" as const,
      block: "current",
      param: "bandwidth",
      direction: "raise" as const,
      to: null,
    };
    const needing = (k: number): Run => {
      const r = copy(hold);
      r.verdict = {
        ...(r.verdict ?? {}),
        findings: [
          {
            id: "a",
            topic: "step",
            tag: "improve",
            severity: 2,
            said: "slow",
            lever: null,
            expect: null,
            change: null,
          },
          {
            id: "b",
            topic: "step",
            tag: "improve",
            severity: 2 + k,
            said: "slower",
            lever,
            expect: null,
            change: null,
          },
        ],
      } as Run["verdict"];
      return r;
    };
    await act(async () => {
      waiting.forEach((resolve, k) => resolve(needing(k)));
      await Promise.resolve();
    });
    await waitFor(() => expect($(".lab-choice.is-ready")).not.toBeNull());
    const first = $<HTMLButtonElement>(".lab-choice .lab-choice-first");
    expect(first).not.toBeNull();
    expect(first!.textContent).toMatch(/^First change: raise/i);
    await act(() => fireEvent.click(first!));
    expect(asked).toContain(lab.get().scheme!.id);
    expect(lab.get().selected).toBe("current");
  });
});

describe("learning", () => {
  it("holds a block's card while it is pointed at, and lets it go soon after it is left", async () => {
    await opened();
    act(() => lab.set({ learn: true }));
    const block = $('[data-block="speed"]')!;
    const node = { id: "speed", kind: "pi", title: "Speed regulator" } as never;
    act(() => learnOn(node, block));
    expect(learnShown()).toBe(node);
    act(() => learnOff());
    // Long enough to cross over to the card: it is still there at once, and gone soon after.
    expect(learnShown()).toBe(node);
    await waitFor(() => expect(learnShown()).toBeNull(), { timeout: 1000 });
    // Pointed at again before it goes, it stays.
    act(() => learnOn(node, block));
    act(() => learnOff());
    act(() => learnOn(node, block));
    await new Promise((r) => setTimeout(r, 400));
    expect(learnShown()).toBe(node);
    act(() => learnOff(true));
    expect(learnShown()).toBeNull();
  });

  it("opens a regulator's theory first, with the loop it closes answering its gains", async () => {
    await opened();
    await act(async () => {
      lab.set({ learn: true });
      await Promise.resolve();
    });
    await press('[data-block="speed"] .lab-node-head');
    await waitFor(() => expect($(".lab-liveloop")).not.toBeNull());
    expect($<HTMLDetailsElement>(".lab-inspector details.lab-learn")!.open).toBe(true);
    expect(text(".lab-liveloop h5")).toMatch(/live/);
    expect(host.querySelectorAll(".lab-liveloop-plots svg").length).toBe(2);
    // A gain changed asks the loop again within the 400 ms a drag is answered in.
    vi.mocked(control.loops).mockClear();
    await type("#lab-p-speed-kp", "9");
    await waitFor(() => expect(control.loops).toHaveBeenCalled(), { timeout: 400 });
  });
});
