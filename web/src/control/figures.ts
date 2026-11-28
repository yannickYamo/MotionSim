// Figures as the lab writes them, everywhere alike: a real unit written as an engineer writes
// it (rad/s², not rad/s2), a prefix where it reads better (72.0 µA, not 7.20e-5), four
// significant figures, and an angle in degrees within one turn. The values kept are the raw
// ones; only what is shown is rounded. A time under a second is typed and shown in ms.

import { eng, minus, sig } from "../format";

/** A unit as it is written: powers raised, degrees as their sign. */
export function unitWords(unit: string): string {
  if (!unit) return "";
  if (unit === "deg" || unit === "degrees") return "°";
  return unit
    .replace(/\*\*?(\d)/g, (_, d: string) => SUPER[d] ?? d)
    .replace(/([a-zA-Z])(\d)$/, (_, a: string, d: string) => `${a}${SUPER[d] ?? d}`)
    .replace(/\^(\d)/g, (_, d: string) => SUPER[d] ?? d)
    .replace(/Nm\b/, "N·m");
}

const SUPER: Record<string, string> = {
  "0": "⁰",
  "1": "¹",
  "2": "²",
  "3": "³",
  "4": "⁴",
  "5": "⁵",
  "6": "⁶",
  "7": "⁷",
  "8": "⁸",
  "9": "⁹",
  "-": "⁻",
};

/** A power of ten written as one: 7.2×10⁻⁵, for a figure with no unit to take a prefix. */
function powered(v: number, digits: number): string {
  const [m, e] = v.toExponential(digits - 1).split("e");
  const mant = String(Number(m));
  const exp = String(Number(e))
    .split("")
    .map((c) => SUPER[c] ?? c)
    .join("");
  return `${mant}×10${exp}`;
}

/** Units a figure is written with a prefix in: 0.00012 s reads better as 120 µs. */
const PREFIXED = new Set(["s", "A", "V", "W", "Hz", "H", "Ω", "J", "F", "Wb"]);

/** An angle in radians as it is read: degrees, wrapped to (−180°, 180°]. */
export function angle(rad: number | null | undefined): string {
  if (rad === null || rad === undefined || !Number.isFinite(rad)) return "–";
  let d = ((((rad * 180) / Math.PI) % 360) + 360) % 360;
  if (d > 180) d -= 360;
  const shown = Number(d.toFixed(1));
  return `${shown === -180 ? "180.0" : (Object.is(shown, -0) ? 0 : shown).toFixed(1)}°`;
}

/** A value with its unit, as every figure of the lab is written. `scale`: the size of what it
 *  is read against (a chart's span); a millionth of that or less is the arithmetic's dust, nought. */
export function written(value: number | null | undefined, unit: string, digits = 4, scale = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "–";
  return minus(figure(Math.abs(value) <= 1e-6 * scale ? 0 : value, unit, digits));
}

function figure(value: number, unit: string, digits: number): string {
  if (unit === "rad") return angle(value);
  const u = unitWords(unit);
  if (value === 0) return u ? `0 ${u}` : "0";
  if (PREFIXED.has(unit)) return eng(value, u, digits);
  const small = Math.abs(value) < 1e-3;
  // A figure too small for its decimals keeps its unit and takes a prefix: 70.9 µrad/s.
  if (u && small) return eng(value, u, digits);
  if (!u) return small || Math.abs(value) >= 1e7 ? powered(value, digits) : sig(value, digits);
  // An angle's degree sign stands against its figure, "11.4° rms"; every other unit after a space.
  return `${sig(value, digits)}${/^°(?!C)/.test(u) ? "" : " "}${u}`;
}

/** A value read at the cursor, set to hold still as the cursor moves: three significant figures
 *  of its strip's full scale (one resolution for every value on the strip), in the strip's own
 *  unit, with no prefix that comes and goes. */
export function reading(value: number | null | undefined, unit: string, lo: number, hi: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "–";
  const full = Math.max(Math.abs(lo), Math.abs(hi), Math.abs(value));
  if (!(full > 0) || unit === "rad" || unit === "s") return written(value, unit, 3, full);
  const places = Math.max(0, 2 - Math.floor(Math.log10(full)));
  const step = 10 ** -places;
  const held = Math.round(value / step) * step;
  const text = minus((Object.is(held, -0) || held === 0 ? 0 : held).toFixed(places));
  const u = unitWords(unit);
  return u ? `${text} ${u}` : text;
}

/** A figure as it is put in a box: four significant figures at most, no trailing noughts. */
export const boxed = (v: number): string => {
  const n = Number(v.toPrecision(4));
  return Object.is(n, -0) ? "0" : String(n);
};

/** The scale a figure is typed and shown in: a time under a second in ms (under a
 *  millisecond in µs), everything else as the engine gives it. */
export function scaleOf(unit: string, typical: number | null | undefined): { unit: string; k: number } {
  const t = Math.abs(Number(typical));
  if (unit === "s" && Number.isFinite(t) && t > 0 && t < 1) {
    return t < 1e-3 ? { unit: "µs", k: 1e6 } : { unit: "ms", k: 1e3 };
  }
  return { unit: unitWords(unit), k: 1 };
}

/** A bound as it is said: with a prefix where it has a unit (1 µs), as a power of ten where it
 *  has none; none for one so wide it bounds nothing. */
export function bound(v: number | null | undefined, unit = ""): string | null {
  if (v === null || v === undefined || !Number.isFinite(v) || Math.abs(v) >= 1e11) return null;
  const said = written(v, unit, 3);
  // Noughts after the point say nothing in a bound: 1 µs, not 1.00 µs.
  return said.replace(/(\d)\.0+(?=\D|$)/, "$1").replace(/(\.\d*?)0+(?=\D|$)/, "$1");
}
