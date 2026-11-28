// What each block is drawn as on the diagram: the symbol a control engineer draws for it, as
// in Simulink or PSIM, and a short name under it. The symbol is read from what the block does
// (its ports, the part the registry says it plays, its figures); the short name is the
// registry's for the kinds this page knows, and the kind's own title for any other.

import type { Block } from "./types";

export type SymbolKind =
  "source" | "ramp" | "saturation" | "pi" | "math" | "word" | "bridge" | "machine" | "hold" | "encoder" | "title";

export interface Sym {
  kind: SymbolKind;
  /** For "math": the parts set in a row, each as letters with what is written small under them. */
  math?: MathPart[];
  /** For "word": the letters drawn, upright. */
  word?: string;
  /** The short name under the symbol. */
  caption: string;
}

/** A piece of a symbol set in mathematics: a letter, what is written small under or over it,
 *  or an arrow between two frames. */
export interface MathPart {
  text: string;
  sub?: string;
  star?: boolean;
  hat?: boolean;
  /** Set upright, as a word or an arrow is. */
  upright?: boolean;
}

/** The short names of the kinds this page knows. */
const CAPTIONS: Record<string, string> = {
  speed_reference: "Speed ramp",
  speed_pi: "Speed PI",
  speed_adrc: "Speed ADRC",
  voltage_feedback_fw: "FW on |v|",
  periodic_compensation: "Learned turn",
  torque_notch: "Notch",
  torque_shaper: "Limiter",
  current_reference: "Current ref",
  current_pi_dq: "Current PI",
  current_discrete_dq: "Current reg",
  deadbeat_dq: "Deadbeat",
  fcs_mpc: "Predictive",
  dtc: "Hysteresis",
  inverse_park: "Inv. Park",
  park: "Park",
  clarke: "Clarke",
  modulator: "Modulator",
  current_sampling: "Sampling",
  shunt_sampling: "Shunts",
  hf_injection: "HFI",
  injection_sum: "+ h",
  position_sensing: "Position",
  observer_flux: "Observer",
  observer_emf_pll: "Observer",
  observer_smo: "Observer",
  if_startup: "Start angle",
  if_current: "Start ref",
  variable_frequency: "Frequency",
  dead_time_compensation: "Dead time",
  thermal_supervisor: "Thermal",
};

const ARROW: MathPart = { text: "→", upright: true };
const PWM: Record<string, string> = {
  "space-vector": "SVPWM",
  sinusoidal: "SPWM",
  "third-harmonic": "THIPWM",
  discontinuous: "DPWM",
  dpwm: "DPWM",
};

/** What a symbol needs to know of a block: its kind, the part it plays, its ports, its figures. */
export interface SymbolOf {
  role: "block" | "reference" | "inverter" | "motor";
  kind: string;
  hint: string;
  title: string;
  known: boolean;
  block: Block | null;
  inputs: { port: string }[];
  outputs: { name: string }[];
}

const puts = (n: SymbolOf, names: string[]) => names.every((x) => n.outputs.some((o) => o.name === x));
const takes = (n: SymbolOf, names: string[]) => names.every((x) => n.inputs.some((i) => i.port === x));

type Drawn = Omit<Sym, "caption">;
const math = (...parts: MathPart[]): Drawn => ({ kind: "math", math: parts });
const word = (w: string): Drawn => ({ kind: "word", word: w });
const params = (n: SymbolOf) => n.block?.params ?? {};
const has = (n: SymbolOf, re: RegExp) => Object.keys(params(n)).some((k) => re.test(k));
const named = (n: SymbolOf, re: RegExp) => re.test(`${n.kind} ${n.title}`);
const pwmOf = (n: SymbolOf): string => {
  const p = params(n).pwm;
  return typeof p === "string" ? (PWM[p] ?? "PWM") : "PWM";
};

/** The symbols, the first that fits a block being its own: what it takes and puts out first,
 *  then the part it plays. */
const RULES: [(n: SymbolOf) => boolean, (n: SymbolOf) => Drawn][] = [
  [(n) => n.role === "reference", () => ({ kind: "source" })],
  [(n) => n.role === "inverter", () => ({ kind: "bridge" })],
  [(n) => n.role === "motor", () => ({ kind: "machine" })],
  [(n) => takes(n, ["a", "b", "c"]) && puts(n, ["alpha", "beta"]), () => math({ text: "abc" }, ARROW, { text: "αβ" })],
  [
    (n) => takes(n, ["alpha", "beta", "theta"]) && puts(n, ["d", "q"]),
    () => math({ text: "αβ" }, ARROW, { text: "dq" }),
  ],
  [
    (n) => takes(n, ["d", "q", "theta"]) && puts(n, ["alpha", "beta"]),
    () => math({ text: "dq" }, ARROW, { text: "αβ" }),
  ],
  [(n) => puts(n, ["d_a", "d_b", "d_c", "m"]), (n) => word(pwmOf(n))],
  [(n) => puts(n, ["s_a", "s_b", "s_c"]), (n) => word(named(n, /dtc|direct/i) ? "DTC" : "MPC")],
  [(n) => puts(n, ["i_a", "i_b", "i_c"]), () => ({ kind: "hold" })],
  [
    // What reads the rotor's own angle and speed is its sensor.
    (n) => puts(n, ["theta"]) && (n.hint === "sensing" || takes(n, ["theta", "omega_m"])),
    () => ({ kind: "encoder" }),
  ],
  [
    (n) => puts(n, ["theta"]) && named(n, /observer|pll/i),
    () => math({ text: "θ", hat: true }, { text: ",", upright: true }, { text: "ω", hat: true }),
  ],
  [(n) => puts(n, ["theta"]), () => word("I‑f")],
  [(n) => n.outputs.some((o) => /^err/.test(o.name)) && has(n, /^kp/) && has(n, /^ki/), () => ({ kind: "pi" })],
  [(n) => n.outputs.some((o) => /^err/.test(o.name)) && named(n, /deadbeat/i), () => word("DBC")],
  [(n) => n.outputs.some((o) => o.name === "disturbance") && named(n, /disturbance/i), () => word("ADRC")],
  [(n) => n.outputs.some((o) => /^err/.test(o.name)), () => math({ text: "C" }, { text: "(z)", upright: true })],
  [
    (n) => puts(n, ["i_d", "i_q"]) && takes(n, ["torque"]),
    () => math({ text: "T", star: true }, ARROW, { text: "i", sub: "dq", star: true }),
  ],
  [(n) => puts(n, ["i_d", "i_q"]), () => word("I‑f")],
  [
    (n) => typeof params(n).limit === "number" && n.inputs.length === 1 && n.outputs.length > 0,
    () => ({ kind: "saturation" }),
  ],
  [(n) => puts(n, ["ref"]) && (/reference/.test(n.hint) || takes(n, ["target"])), () => ({ kind: "ramp" })],
  [(n) => puts(n, ["f_sw"]), () => math({ text: "f", sub: "sw" })],
  [(n) => puts(n, ["tj"]), () => math({ text: "T", sub: "j" })],
  [(n) => has(n, /^dead_time$/), () => math({ text: "t", sub: "d" })],
];

const KERNEL_CAPTIONS: Record<string, string> = { reference: "Command", inverter: "Inverter", motor: "PMSM" };

/** The symbol of a block, from what it does. */
export function symbolOf(n: SymbolOf): Sym {
  const rule = RULES.find(([fits]) => fits(n));
  if (!rule) return { kind: "title", caption: n.title };
  return { ...rule[1](n), caption: KERNEL_CAPTIONS[n.role] ?? CAPTIONS[n.kind] ?? n.title };
}

/** How wide a block is drawn, in the drawing's units: the symbol's room and its name's. */
export function widthOf(s: Sym): number {
  if (s.kind === "source") return 80;
  if (s.kind === "title") return 128;
  return 96;
}
