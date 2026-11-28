// @vitest-environment happy-dom
// What a run found, set where it is seen: the chips over the scope (worst first, a fail never
// softened), the same findings drawn on the strips and the Laplace plots as labelled regions,
// "At limit" only on a block that really reaches its limit, the learning layer of a block's
// values, and the lab after a run read in at most 250 words of prose.

import { act, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { stepPlot } from "../src/control/bode";
import { cancelRun } from "../src/control/actions";
import { control, Missing } from "../src/control/client";
import { chipsOf, firstFigure, notesOf, placedNotes } from "../src/control/findings";
import { mount, unmount } from "../src/control/lab";
import { effectOf, ruleOf } from "../src/control/learn";
import { reachesLimit } from "../src/control/node";
import { stop } from "../src/control/play";
import { stripPlot } from "../src/control/plots";
import { RPM, shaftRun } from "../src/control/scopeview";
import { lab } from "../src/control/store";
import { easeOut } from "../src/control/strip";
import type { LNode } from "../src/control/layout";
import type { Loop, Loops, Presets, Run } from "../src/control/types";
import designFile from "./fixtures/control-design.json";
import loopsFile from "./fixtures/control-loops.json";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";
import stepFile from "./fixtures/control-run-step.json";
import judgedFile from "./fixtures/control-verdict-hold.json";

const presets = presetsFile as unknown as Presets;
const loops = loopsFile as unknown as Loops;
const copy = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

/** The recorded hold run with what a newer engine judged of a run like it. */
const judged = (): Run => ({ ...copy(holdFile as unknown as Run), ...(copy(judgedFile) as unknown as Partial<Run>) });

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("the chips", () => {
  it("are the findings to change first, then the passing headline figures, then how many pass", () => {
    const chips = chipsOf(judged());
    expect(chips.map((c) => [c.label, c.figure, c.tone])).toEqual([
      ["Data note", "", "note"],
      ["PM", "68.5°", "good"],
      ["THD", "1.45 %", "good"],
      ["Tj", "≤ 64.7 °C", "good"],
      ["✓", "6", "good"],
    ]);
    // Each check with a trace points at it.
    expect(chips.find((c) => c.label === "PM")!.target).toEqual({ kind: "laplace", loop: "current_q" });
    expect(chips.find((c) => c.label === "THD")!.target).toMatchObject({
      kind: "strip",
      group: "abc A",
      note: "ripple",
    });
  });

  it("names whose limit each of a trip's currents is against, and how far the shaft fell, in degrees", () => {
    const run = judged();
    const trip = (id: string, topic: string, said: string) => ({
      id,
      topic,
      tag: "improve" as const,
      severity: 2,
      said,
      lever: null,
      expect: null,
      change: null,
    });
    run.verdict!.findings.push(
      trip("trip_link", "trip", "switched off at 6000 rpm, the motor charges the DC link with 106 A"),
      trip("trip_peak", "trip", "after the trip a phase carried 106 A, 1.19× the motor's limit"),
      trip("trip_fall", "trip", "the shaft fell 18.7° before the brake bit"),
    );
    run.verdict!.findings.push({ ...trip("guard", "current", "peak current 106 A is above the device's rated 100 A") });
    (run as { trip?: unknown }).trip = { link_peak: 106, i_peak: 106, fall_deg: 18.7 };
    const chips = chipsOf(run).map((c) => `${c.label} ${c.figure}`);
    expect(chips).toEqual(expect.arrayContaining(["Into link 106 A", "Î motor 106 A", "Î device 106 A", "Fell 18.7°"]));
  });

  it("puts a fail first and never turns it into a pass", () => {
    const run = judged();
    run.verdict!.findings.push({
      id: "junction",
      topic: "thermal",
      tag: "improve",
      severity: 3,
      said: "junction peaks at 171 °C, 21 K over its 150 °C rating",
      lever: null,
      expect: null,
      change: null,
    });
    run.verdict!.findings = run.verdict!.findings.filter((f) => !(f.id === "junction" && f.tag === "good"));
    const chips = chipsOf(run);
    expect(chips[0]).toMatchObject({ label: "Tj", tone: "fail" });
    expect(chips.filter((c) => c.label === "Tj")).toHaveLength(1);
    expect(chips.at(-1)).toMatchObject({ label: "✓", figure: "5" });
  });

  it("reads a figure from a finding's own words where the engine sends no number", () => {
    expect(firstFigure("observer angle error 0.095° rms once it has the rotor")).toBe("0.095°");
    expect(firstFigure("device loss 5.31 W: 52.5% conduction")).toBe("5.31 W");
    expect(firstFigure("no figure here")).toBe("");
    expect(chipsOf(null)).toEqual([]);
  });
});

describe("the findings drawn on the strips", () => {
  it("marks the stretch the ripple was read over, the current limit and the instant it settled", () => {
    const notes = notesOf(judged());
    const ripple = notes.get("abc A")!.find((n) => n.id === "ripple")!;
    expect(ripple).toMatchObject({ kind: "span", tone: "good" });
    expect(ripple.kind === "span" && ripple.label).toBe("THD 1.45 % · 107 mA pk-pk");
    expect(notes.get("abc A")!.some((n) => n.kind === "level" && n.id === "i-limit")).toBe(true);
    expect(notes.get("rpm")).toEqual([
      expect.objectContaining({ kind: "tick", id: "settled", t: (holdFile as unknown as Run).timing.analysed_from }),
    ]);
    // The settled tick goes on the first strip shown where the speed is not.
    const placed = placedNotes(notes, [{ key: "abc A" }, { key: "dq A" }]);
    expect(placed.get("abc A")!.some((n) => n.kind === "tick")).toBe(true);
    expect(placed.has("rpm")).toBe(false);
  });

  it("draws the torque's ripple band only on a strip that carries the true torque", () => {
    const notes = notesOf(judged());
    const band = notes.get("N·m")!.find((x) => x.id === "torque-ripple")!;
    expect(band).toMatchObject({ kind: "band", wire: "plant.torque" });
    const asked = [{ key: "N·m", traces: [{ name: "speed.torque" }] }];
    expect(placedNotes(notes, asked).get("N·m") ?? []).not.toContainEqual(
      expect.objectContaining({ id: "torque-ripple" }),
    );
    const made = [{ key: "N·m", traces: [{ name: "speed.torque" }, { name: "plant.torque" }] }];
    expect(placedNotes(notes, made).get("N·m")).toContainEqual(expect.objectContaining({ id: "torque-ripple" }));
  });

  it("calls the instant a hold is read from by that, not a settling", () => {
    const tick = notesOf(judged()).get("rpm")![0];
    expect(tick.label).toBe("read from here");
  });

  it("marks a step's overshoot as a band over its target and its settling as a stretch", () => {
    const run = copy(stepFile as unknown as Run);
    // As the scope reads the run: the speed's step and its band in rpm.
    const notes = notesOf(shaftRun(run)).get("rpm")!;
    const over = notes.find((n) => n.id === "overshoot")!;
    const [lo, hi] = over.kind === "band" ? [over.lo, over.hi] : [NaN, NaN];
    expect(lo).toBeCloseTo(209.44 * RPM, 9);
    expect(hi).toBeCloseTo((209.44 + 0.0036996 * (209.44 - 188.5)) * RPM, 9);
    const settling = notes.find((n) => n.id === "settling")!;
    expect(settling.kind === "span" && [settling.from, settling.to]).toEqual([0.02, 0.02 + 0.03145]);
    expect(notes.find((n) => n.id === "settled")).toMatchObject({ kind: "tick", t: 0.02 + 0.03145 });
  });

  it("writes nought among the value rules whenever only some of them are written", () => {
    const t = [0, 1, 2, 3, 4];
    const ranges = Array.from({ length: 40 }, (_, n) => [-(n + 1) * 1.7, 60, 45, 45, 45]);
    for (const values of ranges) {
      const { svg } = stripPlot({
        title: "Currents",
        t,
        traces: [{ name: "plant.i_q", values, ink: 0, dash: 0 }],
        from: 0,
        to: 4,
        width: 600,
        height: 100,
        axis: false,
      });
      const d = document.createElement("div");
      d.innerHTML = svg;
      const written = [...d.querySelectorAll("text.tick")].map((x) => x.textContent);
      const rules = d.querySelectorAll("path.grid.zero").length;
      if (rules) expect(written, `values ${values.join(", ")}`).toContain("0");
    }
  });
  it("draws each as a labelled region, and a limit off the scale at the edge it lies past", () => {
    const t = [0, 1, 2, 3, 4];
    const { svg } = stripPlot({
      title: "Phase currents",
      t,
      traces: [{ name: "plant.i_a", values: [0, 1, 0, -1, 0], ink: 0, dash: 0 }],
      from: 0,
      to: 4,
      width: 600,
      height: 100,
      axis: true,
      notes: [
        { kind: "span", id: "ripple", from: 2, to: 4, label: "THD 1.5 %", tone: "good" },
        { kind: "level", id: "i-limit", value: 12, both: true, label: "limit ±12 A", tone: "note" },
        { kind: "band", id: "angle", lo: -0.5, hi: 0.5, label: "±0.5", tone: "improve" },
      ],
    });
    const box = document.createElement("div");
    box.innerHTML = svg;
    expect(box.querySelector('[data-note="ripple"] rect')).not.toBeNull();
    expect(box.querySelector('[data-note="ripple"] text')!.textContent).toBe("THD 1.5 %");
    expect(box.querySelector('[data-note="i-limit"].is-edge text')!.textContent).toBe("↑ limit ±12 A");
    expect(box.querySelector('[data-note="angle"].tone-improve rect')).not.toBeNull();
  });

  it("marks the predicted step's overshoot and settling on the Laplace lens", () => {
    const loop: Loop = copy(loops.current_q!);
    loop.step.overshoot = 0.12;
    const box = document.createElement("div");
    box.innerHTML = stepPlot(loop, null);
    expect(box.querySelector('[data-note="overshoot"] text')!.textContent).toBe("overshoot 12.0 %");
    if (loop.step.settling_time)
      expect(box.querySelector('[data-note="settling"] text')!.textContent).toMatch(/^settles /);
  });
});

describe("At limit", () => {
  const node = (outputs: { name: string; wire: string }[]) => ({ id: "current", outputs }) as unknown as LNode;

  it("is drawn only on a block that reaches its limit somewhere in the run", () => {
    const run = copy(holdFile as unknown as Run);
    const current = node([
      { name: "v_d", wire: "current.v_d" },
      { name: "limited", wire: "current.limited" },
    ]);
    run.series.wires["current.limited"] = run.series.t.map(() => 0);
    expect(reachesLimit(current, run.series, null)).toBe(false);
    run.series.wires["current.limited"][5] = 1;
    expect(reachesLimit(current, run.series, null)).toBe(true);
    // A block with no limit at all is never marked.
    expect(reachesLimit(node([{ name: "d", wire: "park.d" }]), run.series, null)).toBe(false);
    expect(reachesLimit(current, null, null)).toBe(false);
  });
});

describe("the learning layer", () => {
  it("cuts a value's account to the rule it was tuned by", () => {
    expect(
      ruleOf(
        "held to where an inductance wrong by 30% cannot make the loop oscillate (ωs/2π = 1.03 Hz, a = 4): a long " +
          "account of it. This tool's own rule. Kp = J·ωs, J = 0.774 kg·m²",
      ),
    ).toBe("Kp = J·ωs, J = 0.774 kg·m²");
    expect(ruleOf("the torque of the drive's current limit")).toBe("The torque of the drive's current limit");
    expect(
      ruleOf(
        "K = 0.25: both poles of z² − z + K at z = 0.5, the fastest answer with no overshoot, whatever the speed " +
          "(direct discrete design on the winding's exact model)",
      ),
    ).toBe("K = 0.25: both poles of z² − z + K at z = 0.5");
    expect(ruleOf("")).toBe("");
  });

  it("says what changing a key setting does", () => {
    expect(effectOf("speed_pi", "kp")).toMatch(/^Raise: faster answer/);
    expect(effectOf("current_discrete_dq", "gain")).toMatch(/0\.25/);
    expect(effectOf("park", "nothing")).toBe("");
  });

  it("draws in on the shared curve, from nought to one", () => {
    expect(easeOut(0)).toBe(0);
    expect(easeOut(1)).toBe(1);
    expect(easeOut(0.5)).toBeGreaterThan(0.75);
  });
});

describe("the lab after a run", () => {
  let host: HTMLDialogElement;
  const $ = <T extends Element = HTMLElement>(s: string) => host.querySelector<T>(s);

  beforeEach(() => {
    // As wide as a desk: the diagram drawn whole.
    const media = { matches: false, addEventListener: () => undefined, removeEventListener: () => undefined };
    vi.stubGlobal("matchMedia", () => media);
    localStorage.clear();
    lab.reset();
    vi.spyOn(control, "loops").mockResolvedValue(loops);
    vi.spyOn(control, "kept").mockResolvedValue([]);
    vi.spyOn(control, "runStreamed").mockResolvedValue(judged());
    vi.spyOn(control, "phrase").mockRejectedValue(new Missing("/api/control/phrase"));
    vi.spyOn(control, "explorations").mockRejectedValue(new Missing("/api/control/explorations"));
  });

  afterEach(() => {
    cancelRun();
    stop();
    if (host) act(() => unmount(host));
    host?.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  async function ran(): Promise<void> {
    host = document.createElement("dialog");
    document.body.append(host);
    await act(async () => {
      mount(host, { key: `k${Math.random()}`, design: designFile, presets, name: "a made-up part" });
      await Promise.resolve();
    });
    await act(() => fireEvent.click($(".lab-run button.primary")!));
    await waitFor(() => expect($(".lab-chip")).not.toBeNull());
  }

  /** The words of prose shown: no figure, no symbol, nothing folded, hidden or drawn in a chart. */
  function proseWords(root: Element): string[] {
    const words: string[] = [];
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      const el = n.parentElement;
      // What a screen reader alone is told (the diagram's keyboard help among it) is not read on screen.
      const unseen = "svg, .katex, select, option, .sr-only, [hidden], [aria-hidden='true'], [style*='display: none']";
      if (!el || el.closest(`${unseen}, style, script`)) continue;
      const fold = el.closest("details");
      if (fold && !fold.open && !el.closest("summary")) continue;
      for (const w of (n.textContent ?? "").split(/\s+/)) if (/^[A-Za-z’'-]{2,}[.,:;)]?$/.test(w)) words.push(w);
    }
    return words;
  }

  it("reads in at most 250 words of prose, every figure still a press away", async () => {
    await ran();
    const words = proseWords(host);
    expect(words.length, words.join(" ")).toBeLessThanOrEqual(250);
    // The verdict is one line; its findings, the checks and the export's account are folded.
    expect($(".lab-verdict-said")).not.toBeNull();
    expect($("#lab-verdict-all")).toBeNull();
    expect($<HTMLDetailsElement>(".lab-checks-all")!.open).toBe(false);
    await act(() => fireEvent.click($(".lab-verdict-more")!));
    expect(host.querySelectorAll("#lab-verdict-all .lab-finding").length).toBe(judged().verdict!.findings.length);
  });

  it("sets the scope before the cost: the scope's verdict, chips and strips come first", async () => {
    await ran();
    const order = [".lab-chips", ".scope-strips", "#lab-tab-body"].map((s) => $(s)!);
    for (let k = 1; k < order.length; k++)
      expect(order[k - 1].compareDocumentPosition(order[k]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The scheme's why is behind the info press in the head, not a paragraph over the drawing.
    expect($(".lab-main > .lab-about")).toBeNull();
    expect($<HTMLElement>("#lab-why-panel")!.hidden).toBe(true);
    await act(() => fireEvent.click($(".lab-why-open")!));
    expect($<HTMLElement>("#lab-why-panel")!.hidden).toBe(false);
    expect($(".lab-about")!.textContent).toContain(presets.why);
  });

  it("opens a chip's finding under the row, and points a check at its trace", async () => {
    await ran();
    const thd = [...host.querySelectorAll<HTMLButtonElement>(".lab-chip")].find((c) =>
      /THD/.test(c.textContent ?? ""),
    )!;
    await act(() => fireEvent.click(thd));
    expect(thd.getAttribute("aria-expanded")).toBe("true");
    expect($("#lab-chip-detail")!.textContent).toContain("Current THD 1.5%");
    expect($("#lab-chip-detail .lab-finding-see")!.textContent).toBe("Show on trace");
  });

  it("draws no block as At limit where none reaches its limit in the run", async () => {
    await ran();
    expect(host.querySelectorAll(".lab-sym-held").length).toBe(0);
    expect(host.querySelectorAll("[data-held]").length).toBe(0);
  });
});
