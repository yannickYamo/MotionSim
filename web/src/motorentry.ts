// A motor's figures as its datasheet gives them, and as the engine's model takes them. The page
// keeps the engine's figures; a box shows them in the datasheet's terms and turns what is typed
// back. Nothing here changes a motor: a switch changes how its figures are shown.

import { eng } from "./format";
import { plainly } from "./parse";

/** Between two terminals, as datasheets give a resistance and an inductance, or one phase. */
export type Wiring = "line" | "phase";
/** Which constant a motor's box is given in: the speed constant or the torque constant. */
export type Constant = "kv" | "kt";
export interface MotorEntry {
  wiring: Wiring;
  /** By kind of motor, where the user switched it from the kind's own. */
  constant: Record<string, Constant>;
}

export const freshEntry = (): MotorEntry => ({ wiring: "line", constant: {} });

/** The figures a three-phase model takes for one phase of the star: a datasheet's figure
 *  between two terminals is twice that, for a star and for the star a delta is equal to. */
const PER_PHASE: Record<string, string[]> = { pmsm: ["l", "rs"], synrm: ["rs"], induction: ["rs"] };
/** The figures the block-commutated model takes between two terminals, as two phases conduct. */
const LINE_TO_LINE: Record<string, string[]> = { bldc: ["r", "l"] };
const HENRY = new Set(["l", "ld", "lq", "lm", "lls", "llr"]);
const OHM = new Set(["rs", "rr", "r"]);
/** The name of a figure that can be given either way, without saying which way. */
const NOUN: Record<string, string> = { l: "Inductance", rs: "Resistance", r: "Resistance" };
const NOUN_OF: Record<string, Record<string, string>> = { induction: { rs: "Stator resistance" } };

/** Kv · Kt for each kind whose constant may be given either way, and the constant its model holds.
 *  Permanent-magnet: Kt per A rms, T = 3/2 · √2 · p · ψ and ψ = 60 / (√3 · 2π · p · Kv), so
 *  Kt · Kv = √(3/2) · 60 / 2π. Brushless and brushed DC: Kt = Ke in SI units, Kt · Kv = 60 / 2π. */
const BY_TURN = 60 / (2 * Math.PI);
const CONSTANTS: Record<string, { held: Constant; product: number }> = {
  pmsm: { held: "kv", product: Math.sqrt(1.5) * BY_TURN },
  bldc: { held: "kt", product: BY_TURN },
  dc: { held: "kt", product: BY_TURN },
};
const CONSTANT_BOX: Record<string, { label: string; unit: string }> = {
  pmsm_kv: { label: "Speed constant Kv", unit: "rpm/V" },
  pmsm_kt: { label: "Torque constant Kt", unit: "N·m/A rms" },
  bldc_kt: { label: "Torque constant Kt", unit: "N·m/A" },
  bldc_kv: { label: "Speed constant Kv", unit: "rpm/V" },
  dc_kt: { label: "Torque constant Kt", unit: "N·m/A" },
  dc_kv: { label: "Speed constant Kv", unit: "rpm/V" },
};

/** How a box shows a figure the engine holds, and takes one typed in it back. */
export interface Shown {
  label: string;
  unit: string;
  /** The figure in the box, from the engine's. */
  shown: (engine: number) => number;
  /** The engine's figure from the box's, or why the box's cannot be one. */
  engine: (shown: number) => number | string;
  /** What the box says under it, from the engine's figure as it stands. */
  help: (engine: number | null) => string;
  /** Significant figures the box shows of a figure worked out from the engine's: a constant
   *  turned the other way round has more than any catalogue prints. */
  digits?: number;
}

/** Whether a kind of motor has figures that can be given between two terminals or for one phase. */
export const hasWiring = (kind: string): boolean => !!(PER_PHASE[kind] ?? LINE_TO_LINE[kind]);
/** Whether a kind of motor has a constant that can be given either way. */
export const hasConstant = (kind: string): boolean => kind in CONSTANTS;
/** The constant a kind of motor's box is given in. */
export const constantOf = (kind: string, e: MotorEntry): Constant | null =>
  CONSTANTS[kind] ? (e.constant[kind] ?? CONSTANTS[kind].held) : null;

/** How many of the box's figure the engine takes: a half for a per-phase model given a figure
 *  between two terminals, twice for a line-to-line model given one phase. */
function wiringFactor(kind: string, key: string, wiring: Wiring): number {
  if (PER_PHASE[kind]?.includes(key)) return wiring === "line" ? 0.5 : 1;
  if (LINE_TO_LINE[kind]?.includes(key)) return wiring === "phase" ? 2 : 1;
  return 1;
}

const wired = (kind: string, key: string): boolean =>
  !!(PER_PHASE[kind]?.includes(key) || LINE_TO_LINE[kind]?.includes(key));

/** What a figure given one way is said to come to in the model, under its box. */
function wiringHelp(kind: string, key: string, wiring: Wiring, engine: number | null, unit: string): string {
  const perPhase = !!PER_PHASE[kind]?.includes(key);
  const given = wiring === "line" ? "Between two terminals, as datasheets give it." : "For one phase of the star.";
  const scale = unit === "mH" ? "H" : "Ω";
  const taken = engine === null ? "" : `, ${eng(engine, scale)}`;
  if (perPhase && wiring === "line") return `${given} The model takes half of it for one phase${taken}.`;
  if (!perPhase && wiring === "phase") return `${given} The model takes twice it, between two terminals${taken}.`;
  return `${given} The model takes it as it is.`;
}

/** A resistance in mΩ or an inductance in mH, halved or doubled where the model wants it so. */
function scaled(kind: string, key: string, label: string, help: string, e: MotorEntry): Shown {
  const unit = HENRY.has(key) ? "mH" : "mΩ";
  const k = wiringFactor(kind, key, e.wiring) * 1e-3;
  const both = wired(kind, key);
  const noun = NOUN_OF[kind]?.[key] ?? NOUN[key] ?? label;
  return {
    label: both ? `${noun}, ${e.wiring === "line" ? "line to line" : "per phase"}` : label,
    unit,
    shown: (v) => v / k,
    engine: (v) => v * k,
    help: (engine) => (both ? `${wiringHelp(kind, key, e.wiring, engine, unit)} ${help}`.trim() : help),
  };
}

/** A figure to four places, written out plainly: 100, not 100.0. */
const round = (v: number): string => plainly(Number(v.toPrecision(4)));

/** The kinds whose poles are magnets: the others' poles are their winding's. */
const MAGNET_POLES = new Set(["pmsm", "bldc"]);

/** Poles in full, as a catalogue counts them: the engine takes the pairs. Said per kind, with
 *  the kind's own help after it. */
function poles(kind: string, help: string): Shown {
  const which = MAGNET_POLES.has(kind) ? "Every magnet pole" : "Every pole of the winding";
  const own = help.trim() ? ` ${help.trim().replace(/\.?$/, ".")}` : "";
  return {
    label: "Poles",
    unit: "",
    shown: (pairs) => 2 * pairs,
    engine: (n) =>
      Number.isInteger(n) && n % 2 === 0 && n > 0
        ? n / 2
        : "Poles come in pairs: give an even whole number, as the catalogue counts them.",
    help: (pairs) => `${which}, north and south${pairs === null ? "" : `: ${round(pairs)} pairs`}.${own}`,
  };
}

/** A constant given the other way round from the one the model holds: Kt from Kv, or Kv from Kt. */
function constantBox(kind: string, e: MotorEntry, help: string): Shown {
  const { held, product } = CONSTANTS[kind];
  const now = constantOf(kind, e)!;
  const box = CONSTANT_BOX[`${kind}_${now}`];
  if (now === held) return { ...box, shown: (v) => v, engine: (v) => v, help: () => help };
  const other = CONSTANT_BOX[`${kind}_${held}`];
  const name = held === "kv" ? "Kv" : "Kt";
  return {
    ...box,
    digits: 4,
    shown: (v) => product / v,
    engine: (v) => product / v,
    help: (engine) =>
      `Turned into ${name} = ${plainly(Number(product.toPrecision(5)))} / ${now === "kv" ? "Kv" : "Kt"}` +
      (engine === null ? "." : `: ${round(engine)} ${other.unit}.`),
  };
}

/** How the box of one of a motor's figures shows it, or null where it shows the engine's figure
 *  as it is. `label`, `help`: the box's own, for figures whose name does not change. */
export function shownAs(kind: string, key: string, e: MotorEntry, label = "", help = ""): Shown | null {
  if (key === "pole_pairs") return poles(kind, help);
  if (HENRY.has(key) || OHM.has(key)) return scaled(kind, key, label, help, e);
  if (CONSTANTS[kind] && key === CONSTANTS[kind].held) return constantBox(kind, e, help);
  return null;
}

/** The figure a box shows, written out: empty where the engine holds none. */
export function shownText(s: Shown | null, engine: string | number | undefined): string | number {
  if (engine === undefined || engine === "") return "";
  if (!s) return engine;
  const v = Number(engine);
  if (!(Number.isFinite(v) && v > 0)) return engine;
  return plainly(s.digits ? Number(s.shown(v).toPrecision(s.digits)) : s.shown(v));
}
