// What-if: a result pinned as A, and every key figure after a change said against it. One
// input changed, the figures that moved say by how much and which way, in their own unit,
// with an arrow and a sign (never colour alone): worse in Fail, better in Pass.

import type { Candidate } from "./api";
import { comparing } from "./compare";
import { sig } from "./format";
import { app, designNow, focused } from "./store";
import { worstJunction } from "./views/junction";

/** The figures a what-if is read by: what the stage loses, how hot it runs, and how far from
 *  the rating. Lower is better for each but the margin and the efficiency. */
export interface Figures {
  loss: number;
  tj: number;
  margin: number;
  still: number | null;
  /** The hottest junction of every case (design point, standstill, motion), once the motion
   *  is in; null before, so that a figure without the motion is never set against one with it. */
  tjmax: number | null;
  efficiency: number | null;
  conduction: number;
  switching: number;
}

export interface Pinned {
  name: string;
  /** The design's inputs when it was pinned, as `designNow` writes them. */
  inputs: string;
  figures: Figures;
}

/** The pinned result, if any: kept while the page is open. */
export const pin = { a: null as Pinned | null };

export function figuresOf(c: Candidate | null): Figures | null {
  const r = c?.result;
  if (!c || !r) return null;
  const worst = worstJunction(c);
  return {
    loss: r.loss,
    tj: r.tj_peak,
    margin: r.tj_max - r.tj_peak,
    still: c.stall_tj,
    tjmax: worst?.settled ? worst.value : null,
    efficiency: c.efficiency,
    conduction: r.conduction,
    switching: r.switching,
  };
}

/** Pin the result on the drawing as A. Returns whether there was one to pin. */
export function pinNow(): boolean {
  const c = focused();
  const figures = figuresOf(c);
  if (!c || !figures) return false;
  pin.a = { name: c.name, inputs: designNow(), figures };
  return true;
}

export function unpin(): void {
  pin.a = null;
}

/** Each figure: its unit for a difference, whether higher is better, and how finely it is told. */
const KINDS: Record<keyof Figures, { unit: string; higher: boolean; least: number }> = {
  loss: { unit: "W", higher: false, least: 0.005 },
  tj: { unit: "K", higher: false, least: 0.05 },
  margin: { unit: "K", higher: true, least: 0.05 },
  still: { unit: "K", higher: false, least: 0.05 },
  tjmax: { unit: "K", higher: false, least: 0.05 },
  efficiency: { unit: "pt", higher: true, least: 0.0005 },
  conduction: { unit: "W", higher: false, least: 0.005 },
  switching: { unit: "W", higher: false, least: 0.005 },
};

export interface Delta {
  /** "▲ 0.40 W", "▼ 3.2 K", or "= A". */
  text: string;
  /** For a screen reader: "0.40 W more than A". */
  said: string;
  tone: "better" | "worse" | "same";
}

/** A figure now against the same figure of A. Null where either is missing, or nothing is pinned. */
export function deltaOf(key: keyof Figures, now: number | null | undefined): Delta | null {
  const was = pin.a?.figures[key];
  if (was == null || now == null || !Number.isFinite(now)) return null;
  const k = KINDS[key];
  const scale = key === "efficiency" ? 100 : 1;
  const d = (now - was) * scale;
  if (Math.abs(d) < k.least * scale) return { text: "= A", said: "the same as A", tone: "same" };
  const better = k.higher ? d > 0 : d < 0;
  const size = sig(Math.abs(d), Math.abs(d) < 1 ? 2 : 3);
  const arrow = d > 0 ? "▲" : "▼";
  return {
    text: `${arrow} ${size} ${k.unit}`,
    said: `${size} ${k.unit} ${d > 0 ? "more" : "less"} than A`,
    tone: better ? "better" : "worse",
  };
}

/** A delta as the small tag beside a figure. */
export function deltaTag(key: keyof Figures, now: number | null | undefined): string {
  // Nothing changed since A: no figure is set against it. While other things are compared
  // beside the design, the table is the one comparison on the screen: one baseline at a time.
  if (!pin.a || designNow() === pin.a.inputs || comparing()) return "";
  const d = deltaOf(key, now);
  if (!d) return "";
  return `<span class="delta is-${d.tone}" aria-label="${d.said}">${d.text}</span>`;
}

/** How each input is named in the line that says what moved since A. */
const NAMES: Record<string, string> = {
  "conditions.v_dc": "Vdc",
  "conditions.rpm": "speed",
  "conditions.torque": "torque",
  "conditions.f_khz": "f_sw",
  "conditions.pwm": "modulation",
  "conditions.t_sink": "heatsink",
  "conditions.t_ambient": "ambient",
  "conditions.cooling": "cooling",
  "conditions.parallel": "parallel",
  "conditions.rg_on": "Rg on",
  "conditions.rg_off": "Rg off",
  "conditions.v_drive": "gate drive",
  "conditions.t_dead_ns": "dead time",
  devices: "parts",
  lead: "part",
  kind: "motor kind",
};

/** The inputs as paths and values, flattened. */
function flat(value: unknown, path = "", out: Map<string, string> = new Map()): Map<string, string> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const [k, v] of Object.entries(value)) flat(v, path ? `${path}.${k}` : k, out);
  } else out.set(path, JSON.stringify(value ?? null));
  return out;
}

const shownValue = (json: string | undefined): string => {
  if (json === undefined) return "–";
  const v = JSON.parse(json) as unknown;
  if (Array.isArray(v)) return String(v.length);
  if (v === null || v === "") return "–";
  return typeof v === "string" ? v : JSON.stringify(v);
};

/** What moved since A, as "f_sw 16 → 20", a few at most, and how many more. */
export function changedSinceA(): { lines: string[]; more: number } {
  const a = pin.a;
  if (!a) return { lines: [], more: 0 };
  const was = flat(JSON.parse(a.inputs));
  const now = flat(JSON.parse(designNow()));
  const keys = [...new Set([...was.keys(), ...now.keys()])].filter((k) => was.get(k) !== now.get(k));
  const name = (k: string) => {
    if (NAMES[k]) return NAMES[k];
    if (k.startsWith(`motors.${app.state.kind}.`)) return `motor ${k.split(".").pop()!.replace(/_/g, " ")}`;
    const last = k.split(".").pop()!;
    return last.replace(/_/g, " ");
  };
  // A motor kept for another kind than the one in use is not what moved the figures.
  // Where the user has been, and whose a figure is, say nothing of what the figures are of.
  const bookkeeping = /^(visited|lead|loadUsual)$|Touched|Picked|Own|Before/;
  const moved = keys.filter(
    (k) =>
      !bookkeeping.test(k) &&
      (!k.startsWith("motors.") || k.startsWith(`motors.${app.state.kind}.`)) &&
      !k.startsWith("devices."),
  );
  if (keys.some((k) => k.startsWith("devices.") || k === "lead") && !moved.includes("devices"))
    moved.unshift("devices");
  const lines = moved
    .slice(0, 3)
    .map((k) => (k === "devices" ? "parts" : `${name(k)} ${shownValue(was.get(k))} → ${shownValue(now.get(k))}`));
  return { lines: [...new Set(lines)], more: Math.max(moved.length - 3, 0) };
}
