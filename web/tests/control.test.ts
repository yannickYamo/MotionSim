// The control lab's reckoning, apart from anything drawn by React: where the blocks of a
// scheme are placed and how its wires run, a wire's value at an instant, what a run costs
// against another, and where the marks of the linear view fall. The schemes, runs and loops
// are answers recorded from the engine for a made-up 48 V drive.
import { optionWords, signalWords, typedWords } from "../src/control/probes";
import { describe, expect, it } from "vitest";
import { gainPlot, phasePlot, poleZeroMap, settlesWords, stepPlot, transferTex } from "../src/control/bode";
import { compared, difference } from "../src/control/cost";
import { faceOf } from "../src/control/faces";
import { INVERTER, layoutOf, MOTOR, REFERENCE } from "../src/control/layout";
import type { Layout } from "../src/control/layout";
import { reached } from "../src/control/path";
import { indexAt, valueAt, written } from "../src/control/series";
import type { Loop, Loops, Presets, Run, Scheme } from "../src/control/types";
import loopsFile from "./fixtures/control-loops.json";
import presetsFile from "./fixtures/control-presets.json";
import holdFile from "./fixtures/control-run-hold.json";

const presets = presetsFile as unknown as Presets;
const hold = holdFile as unknown as Run;
const loops = loopsFile as unknown as Loops;
const drawn = (s: Scheme): Layout => layoutOf(s, presets.blocks, presets.sources);
const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

const apart = (l: Layout): boolean =>
  l.nodes.every((a, i) =>
    l.nodes.every((b, j) => i >= j || a.x + a.w <= b.x || b.x + b.w <= a.x || a.y + a.h <= b.y || b.y + b.h <= a.y),
  );

describe("the drawing of a scheme", () => {
  it.each(presets.schemes.map((s) => [s.id, s] as const))("places every block of %s once, none on another", (_, s) => {
    const l = drawn(s);
    expect(l.nodes.map((n) => n.id).sort()).toEqual(
      [...s.blocks.map((b) => b.name), REFERENCE, INVERTER, MOTOR].sort(),
    );
    expect(apart(l)).toBe(true);
    expect(l.nodes.every((n) => n.x >= 0 && n.y >= 0 && n.x + n.w <= l.width && n.y + n.h <= l.height)).toBe(true);
  });

  it.each(presets.schemes.map((s) => [s.id, s] as const))("runs %s left to right, the way back underneath", (_, s) => {
    const l = drawn(s);
    const at = (id: string) => l.nodes.find((n) => n.id === id)!;
    const forward = l.nodes.filter((n) => n.row === 0).sort((a, b) => a.x - b.x);
    expect(forward[0].id).toBe(REFERENCE);
    expect(forward[forward.length - 1].id).toBe(MOTOR);
    expect(at(INVERTER).x).toBeLessThan(at(MOTOR).x);
    // What reads the motor's own signals is the way back: under the forward path.
    for (const b of s.blocks.filter((x) => Object.values(x.inputs).some((w) => /^plant\.(i_|theta|omega)/.test(w)))) {
      expect(at(b.name).row).toBeGreaterThan(0);
    }
    // Every wire of a forward block to the next forward block goes rightwards.
    for (const e of l.edges.filter((x) => !x.back && at(x.from).row === 0 && at(x.to).row === 0)) {
      expect(at(e.from).x).toBeLessThan(at(e.to).x);
    }
  });

  it.each(presets.schemes.map((s) => [s.id, s] as const))("draws every wire of %s square-cornered", (_, s) => {
    const l = drawn(s);
    const wired = s.blocks.flatMap((b) => Object.values(b.inputs)).filter((w) => !/^(plant\.v_dc|time\.)/.test(w));
    // Wires that go the same way are drawn as one: every wire is carried by one of the runs.
    expect(l.edges.reduce((n, e) => n + e.wires.length, 0)).toBeGreaterThanOrEqual(wired.length);
    for (const e of l.edges) {
      expect(e.points.length).toBeGreaterThanOrEqual(2);
      e.points.slice(1).forEach(([x, y], k) => {
        const [px, py] = e.points[k];
        expect(x === px || y === py).toBe(true);
      });
    }
  });

  it("is the same drawing every time for the same scheme", () => {
    const s = presets.schemes[0];
    expect(drawn(copy(s))).toEqual(drawn(s));
  });

  it("moves nothing when only a figure of a block changes", () => {
    const s = copy(presets.schemes[0]);
    const before = drawn(s);
    s.blocks.find((b) => b.name === "speed")!.params.kp = 99;
    const after = drawn(s);
    expect(after.nodes.map((n) => [n.id, n.x, n.y])).toEqual(before.nodes.map((n) => [n.id, n.x, n.y]));
  });

  it("gives a kind of block it has never seen a place on the path it is wired into", () => {
    const s = copy(presets.schemes[0]);
    s.blocks.push({ name: "notch", kind: "resonance_notch", params: { depth: 0.5 }, inputs: { x: "speed.torque" } });
    s.blocks.find((b) => b.name === "shaper")!.inputs.torque = "notch.out";
    const l = drawn(s);
    const at = (id: string) => l.nodes.find((n) => n.id === id)!;
    expect(at("notch").known).toBe(false);
    expect(at("notch").title).toBe("resonance notch");
    expect(at("notch").row).toBe(0);
    expect(at("speed").x).toBeLessThan(at("notch").x);
    expect(at("notch").x).toBeLessThan(at("shaper").x);
    expect(apart(l)).toBe(true);
    expect(faceOf(at("notch"))).toBe("trace");
  });

  it("stays apart with twenty blocks more and forty wires", () => {
    const s = copy(presets.schemes[0]);
    for (let k = 0; k < 20; k++) {
      s.blocks.push({
        name: `extra${k}`,
        kind: "unknown_kind",
        params: {},
        inputs: { a: k ? `extra${k - 1}.out` : "park.q" },
      });
    }
    const l = drawn(s);
    expect(l.nodes.length).toBeGreaterThanOrEqual(34);
    expect(l.edges.reduce((n, e) => n + e.wires.length, 0)).toBeGreaterThanOrEqual(40);
    expect(apart(l)).toBe(true);
  });

  it("gives each block the face its ports call for", () => {
    const l = drawn(presets.schemes[0]);
    const face = (id: string) => faceOf(l.nodes.find((n) => n.id === id)!);
    expect(["clarke", "park", "inverse_park"].map(face)).toEqual(["clarke", "park", "ipark"]);
    expect([face("speed"), face("current")]).toEqual(["regulator", "regulator"]);
    expect([face("modulator"), face(INVERTER), face(MOTOR)]).toEqual(["carrier", "legs", "rotor"]);
    expect([face("position"), face("sample"), face("shaper")]).toEqual(["angle", "phases", "limit"]);
    const mpc = drawn(presets.schemes.find((s) => s.id === "mpc_torque")!);
    expect(faceOf(mpc.nodes.find((n) => n.id === "predictive")!)).toBe("states");
  });

  it("offers the gains of a regulator to tune in its inspector, and none on a block without", () => {
    const l = drawn(presets.schemes[0]);
    const gains = (id: string) => l.nodes.find((n) => n.id === id)!.gains;
    expect(gains("speed")).toEqual(["kp", "ki"]);
    expect(gains("current")).toEqual(["kp_d", "ki_d", "kp_q", "ki_q"]);
    expect(gains("park")).toEqual([]);
  });

  it("draws each block as the symbol a control engineer draws for its kind", () => {
    const l = drawn(presets.schemes[0]);
    const sym = (id: string) => l.nodes.find((n) => n.id === id)!.symbol;
    expect(sym("speed").kind).toBe("pi");
    expect(sym("current").kind).toBe("pi");
    const row = (id: string) => (sym(id).math ?? []).map((p) => p.text.trim()).join(" ");
    expect(row("park")).toBe("αβ → dq");
    expect(row("inverse_park")).toBe("dq → αβ");
    expect(row("clarke")).toBe("abc → αβ");
    expect(row("current_ref")).toBe("T → i");
    expect([sym(MOTOR).kind, sym(MOTOR).caption]).toEqual(["machine", "PMSM"]);
    expect([sym(INVERTER).kind, sym(REFERENCE).kind]).toEqual(["bridge", "source"]);
    expect([sym("modulator").kind, sym("modulator").word]).toEqual(["word", "SVPWM"]);
    expect([sym("sample").kind, sym("position").kind]).toEqual(["hold", "encoder"]);
    expect([sym("shaper").kind, sym("speed_ref").kind]).toEqual(["saturation", "ramp"]);
    const mpc = drawn(presets.schemes.find((s) => s.id === "mpc_torque")!);
    expect(mpc.nodes.find((n) => n.id === "predictive")!.symbol.word).toBe("MPC");
    // A kind this page has never seen is a box with its title.
    const s = copy(presets.schemes[0]);
    s.blocks.push({ name: "notch", kind: "resonance_notch", params: {}, inputs: { x: "speed.torque" } });
    const notch = drawn(s).nodes.find((n) => n.id === "notch")!.symbol;
    expect([notch.kind, notch.caption]).toEqual(["title", "resonance notch"]);
  });

  it("follows a signal up to the motor and down to it, never through it", () => {
    const { edges } = drawn(presets.schemes[0]);
    const down = reached(edges, "speed", true);
    expect([...down].sort()).toEqual(
      ["current", "current_ref", "inverse_park", INVERTER, "modulator", MOTOR, "shaper"].sort(),
    );
    const up = reached(edges, "speed", false);
    expect(up.has("speed_ref") && up.has(REFERENCE) && up.has("position") && up.has(MOTOR)).toBe(true);
    expect(up.has("modulator")).toBe(false);
  });
});

describe("a wire at an instant", () => {
  it("is read between the two points the instant lies between", () => {
    expect(valueAt([0, 1, 2], [10, 20, 40], 1.5)).toBe(30);
    expect(valueAt([0, 1, 2], [10, 20, 40], -1)).toBe(10);
    expect(valueAt([0, 1, 2], [10, 20, 40], 9)).toBe(40);
    expect(valueAt([0, 1, 2], undefined, 1)).toBeNull();
  });

  it("is found among five thousand points without going through them", () => {
    const t = Array.from({ length: 5000 }, (_, k) => k * 1e-4);
    expect(indexAt(t, 0.25004)).toBe(2500);
    expect(valueAt(t, t, 0.25004)).toBeCloseTo(0.25004, 9);
  });

  it("is written with its unit, four figures, small figures with a prefix", () => {
    expect(written(12.34, "A")).toBe("12.34 A");
    expect(written(0.00012, "s")).toBe("120.0 µs");
    expect(written(7.2e-5, "A")).toBe("72.00 µA");
    expect(written(null, "A")).toBe("–");
    expect(written(0.5, "")).toBe("0.5000");
    // A figure with no unit to take a prefix is a power of ten, never 7.20e-5.
    expect(written(7.2e-5, "")).toBe("7.2×10⁻⁵");
    expect(written(2, "rad/s2")).toBe("2.000 rad/s²");
  });

  it("writes an angle in degrees within one turn, however far it has turned", () => {
    // 51.3 rad is eight turns and 59.3° more.
    expect(written(51.3, "rad")).toBe("59.3°");
    expect(written(Math.PI / 2, "rad")).toBe("90.0°");
    expect(written(-Math.PI / 2, "rad")).toBe("−90.0°");
    expect(written(Math.PI, "rad")).toBe("180.0°");
    expect(written(3 * Math.PI, "rad")).toBe("180.0°");
    expect(written(2 * Math.PI + 0.1, "rad")).toBe("5.7°");
  });
});

describe("what a control costs, against another", () => {
  it("gives a loss as a share of what it was, and a current as amperes more or less", () => {
    // 2.20 W after 2.00 W is a tenth more; 6.5 A after 6.0 A is half an ampere more.
    expect(difference("loss", "W", 2.2, 2.0)?.text).toBe("+10 %");
    expect(difference("switching", "W", 0.95, 1.0)?.text).toBe("−5.0 %");
    expect(difference("i_switch_rms", "A", 6.5, 6.0)?.text).toBe("+0.50 A");
    expect(difference("tj_peak", "°C", 58.5, 60.5)?.text).toBe("−2.0 °C");
  });

  it("says no change where the two round to the same figure, and nothing where one is missing", () => {
    expect(difference("loss", "W", 2.00001, 2.0)?.text).toBe("no change");
    // Under a thousandth of the figure itself, a difference is the arithmetic's: no change.
    expect(difference("i_switch_rms", "A", 44.77701, 44.778)?.text).toBe("no change");
    expect(difference("tj_peak", "°C", 65.585, 65.53)?.text).toBe("no change");
    expect(difference("tj_peak", "°C", 65.9, 65.5)?.text).toBe("+0.40 °C");
    expect(difference("loss", "W", 2, null)).toBeNull();
  });

  it("sets a run beside the settled design point and beside the run before", () => {
    const before = copy(hold);
    // The run before lost 1.9005 W where this one loses 2.1381 W: 12.5 % more, shown as 13 %.
    before.losses.loss = 1.9005;
    before.channels.i_switch_rms = 6.5527;
    const rows = compared(hold, before);
    const row = (key: string) => rows.find((r) => r.key === key)!;
    expect(row("loss").value).toBe(2.1381);
    expect(row("loss").before?.text).toBe("+13 %");
    expect(row("i_switch_rms").before?.text).toBe("−0.50 A");
    expect(row("conduction").before?.text).toBe("no change");
    const engine = hold.engine as unknown as Record<string, number>;
    const share = ((2.1381 - engine.loss) / engine.loss) * 100;
    expect(row("loss").settled?.share).toBeCloseTo(share / 100, 9);
    expect(compared(hold, null).every((r) => r.before === null)).toBe(true);
  });
});

describe("the linear view of a loop, drawn", () => {
  const q = loops.current_q!;
  const cx = (svg: string, n = 0) => Number([...svg.matchAll(/<circle class="lab-dot" cx="([\d.]+)"/g)][n][1]);

  it("marks the crossover where the frequency axis has it", () => {
    // The axis runs from 5 Hz to 9998 Hz on a logarithmic scale across 460 units from 56.
    const f = q.bode.f;
    const at = (hz: number) => 56 + (Math.log10(hz / f[0]) / Math.log10(f[f.length - 1] / f[0])) * 460;
    const gain = gainPlot(q);
    expect(cx(gain, 0)).toBeCloseTo(at(q.margins.crossover_hz!), 6);
    expect(cx(gain, 1)).toBeCloseTo(at(q.margins.phase_crossover_hz!), 6);
    expect(gain).toContain(`data-mark-hz="${q.margins.crossover_hz}"`);
    expect(gain).toContain("crossover 1.01 kHz");
    expect(gain).toContain("gain margin 9.98 dB");
    const phase = phasePlot(q);
    expect(cx(phase, 0)).toBeCloseTo(at(q.margins.crossover_hz!), 6);
    expect(phase).toContain("phase margin 62.7°");
  });

  it("puts the phase margin's dot that many degrees above −180", () => {
    const phase = phasePlot(q);
    const cy = Number(/<circle class="lab-dot" cx="[\d.]+" cy="([\d.]+)"/.exec(phase)![1]);
    const line = Number(/<path class="zero" d="M56 ([\d.]+)h460"/.exec(phase)![1]);
    const ticks = [...phase.matchAll(/<text class="tick" x="48" y="([\d.]+)" text-anchor="end">([-−]?\d+)<\/text>/g)];
    expect(ticks.length).toBeGreaterThan(1);
    // The zero line of the phase plot is −180°; a quarter turn is the distance between two ticks.
    const perDegree = Math.abs(Number(ticks[0][1]) - Number(ticks[1][1])) / 90;
    expect(line - cy).toBeCloseTo(q.margins.phase_deg! * perDegree, 3);
  });

  it("draws every pole against the unit circle, one outside it marked", () => {
    const map = poleZeroMap(q);
    expect((map.match(/class="lab-pole"/g) ?? []).length).toBe(q.poles.length);
    expect(map).toContain('class="lab-unit"');
    const out = copy(q);
    out.poles[0] = { re: 1.2, im: 0, stable: false } as (typeof out.poles)[0];
    expect(poleZeroMap(out)).toContain('class="lab-pole out"');
    expect(poleZeroMap(out)).toContain("1 outside the unit circle");
  });

  it("writes a transfer function from its two polynomials", () => {
    expect(transferTex("G", { num: [0.5, 0], den: [1, -1.5, 0.5] })).toBe(
      "G(z) = \\frac{0.5000\\,z}{z^{2} -1.500\\,z +0.5000}",
    );
  });
});

describe("the loop's plots at the size the inspector gives them", () => {
  const q = (loopsFile as unknown as Loops).current_q!;
  const ticksOf = (svg: string) =>
    [...svg.matchAll(/<text class="tick"[^>]*text-anchor="middle"[^>]*>([^<]+)</g)].map((m) => m[1]);

  it("writes each decade as a figure is written, never padded to the smallest's decimals", () => {
    const names = ticksOf(gainPlot(q));
    expect(names).toContain("10");
    expect(names).toContain("1k");
    expect(names.some((n) => /\.\d*0$/.test(n))).toBe(false);
  });

  it("draws in a frame narrow enough that its words read at about their own size in the inspector", () => {
    for (const svg of [gainPlot(q, true), stepPlot(q, null, true)]) {
      const width = Number(/viewBox="0 0 (\d+)/.exec(svg)![1]);
      expect(width).toBeLessThanOrEqual(340);
    }
  });
});

describe("poles and zeros crowded at z = 1", () => {
  const q = (loopsFile as unknown as Loops).current_q!;
  const slow = {
    ...q,
    poles: [
      { re: 0.999969, im: 0, stable: true },
      { re: 0.999969, im: 0, stable: true },
      { re: 0.995801, im: 0, stable: true },
      { re: 0.5, im: 0.1, stable: true },
    ],
    zeros: [
      { re: 0.999984, im: 0 },
      { re: 0.995801, im: 0 },
    ],
  } as Loop;

  it("says how many lie there and which pair cancels, where at this scale they are one mark", () => {
    const svg = poleZeroMap(slow);
    expect(svg).toContain("near z = 1: 3 poles, 2 zeros");
    expect(svg).toMatch(/1 pair cancels/);
    expect(svg).toMatch(/aria-label="[^"]*3 poles and 2 zeros lie within 0\.01 of z = 1, 1 pair cancelling/);
  });

  it("says nothing of the kind where none lies there", () => {
    expect(poleZeroMap(q)).not.toContain("near z = 1");
  });
});

describe("a loop that does not settle", () => {
  const q = (loopsFile as unknown as Loops).current_q!;
  const out: Loop = {
    ...q,
    stable: false,
    bandwidth_hz: null,
    step: { ...q.step, y: q.step.y.map((_, k) => Math.min(10, 1.2 ** k * 0.01)), settling_time: null, overshoot: null },
  };

  it("says so on its predicted step, with no settling marked and no figure written in e-notation", () => {
    const svg = stepPlot(out, null, true);
    expect(svg).toContain("does not settle");
    expect(svg).not.toMatch(/settles \d/);
    expect(svg).not.toMatch(/\de[+-]\d/);
  });

  it("is said in words where its figures are listed", () => {
    expect(settlesWords(out)).toBe("does not settle");
    expect(settlesWords(q)).toMatch(/^[\d.]+ (ms|µs|s)$/);
  });
});

describe("a signal's name in a list", () => {
  it("writes every phase and axis the same way, never one in small letters and the next after an underscore", () => {
    const of = (name: string) => typedWords(signalWords(name, "A"));
    expect([of("plant.i_a"), of("plant.i_b"), of("plant.i_c")]).toEqual(["i_a", "i_b", "i_c"]);
    expect(typedWords({ text: "x", sub: "1", star: false })).toBe("x₁");
  });

  it("says what the signal is and leaves out a symbol that is only its code name", () => {
    expect(optionWords("Inverter", "a reading that was skipped", "skip", "inverter.skip")).toBe(
      "Inverter: A reading that was skipped",
    );
    expect(optionWords("Inverter", "the link current at the first reading", "i dc 1", "inverter.i_dc_1")).toBe(
      "Inverter: The link current at the first reading",
    );
    expect(optionWords("The motor", "true shaft speed", "ω_m", "plant.omega_m")).toBe(
      "The motor: True shaft speed · ω_m",
    );
    expect(optionWords("Inverter", "", "skip", "inverter.skip")).toBe("Inverter: Skip");
  });
});
