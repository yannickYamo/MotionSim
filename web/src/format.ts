// Numbers as an engineer writes them: three significant figures, a real unit, no false precision.

/** A figure that is missing: the engine gave none, or what it gave is not a number. Never
 *  written as a figure, since "0 °C" for a temperature that is not known reads as a result. */
const missing = (value: unknown): boolean => typeof value !== "number" || !Number.isFinite(value);
const NONE = "–";

/** The power of ten of a value once it is rounded to the digits shown: 0.09996 is 0.100. */
const magnitudeOf = (value: number, digits: number): number =>
  Math.floor(Math.log10(Math.abs(Number(value.toPrecision(digits)))));

export function sig(value: number | null | undefined, digits = 3): string {
  if (missing(value)) return NONE;
  const v = value as number;
  if (v === 0) return "0";
  const decimals = Math.max(0, digits - 1 - magnitudeOf(v, digits));
  // Past six decimals the plain form would drop the figures it is there to show.
  return decimals > 6 ? v.toExponential(digits - 1) : v.toFixed(decimals);
}

/** A figure the engine worked out, to three figures however large: 1378 J is 1380 J. Not for
 *  a figure the user typed, which is shown as typed. */
export const fig = (value: number | null | undefined, digits = 3): string =>
  missing(value) ? NONE : sig(Number((value as number).toPrecision(digits)), digits);

const PREFIX: [number, string][] = [
  [1e6, "M"],
  [1e3, "k"],
  [1, ""],
  [1e-3, "m"],
  [1e-6, "µ"],
  [1e-9, "n"],
  [1e-12, "p"],
];

/** 0.00012 H becomes "120 µH". The prefix is chosen for the figure as it is shown, so that
 *  999.6 µH is "1.00 mH" and not "1000 µH". */
export function eng(value: number | null | undefined, unit: string, digits = 3): string {
  if (missing(value)) return NONE;
  if (value === 0) return `0 ${unit}`;
  const shown = Number((value as number).toPrecision(digits));
  const [scale, prefix] = PREFIX.find(([s]) => Math.abs(shown) >= s) ?? PREFIX[PREFIX.length - 1];
  return `${sig(shown / scale, digits)} ${prefix}${unit}`;
}

export function watts(w: number | null | undefined): string {
  if (missing(w)) return NONE;
  const shown = Number((w as number).toPrecision(3));
  return Math.abs(shown) >= 1000 ? `${sig((w as number) / 1000)} kW` : `${sig(w)} W`;
}

/** The labels of one axis's ticks: as many decimals as tell every tick from the next and
 *  write each as it is, and the same number of them on every tick (0, 0.5, 1.0 is never
 *  written; 0.0, 0.5, 1.0 is). Ticks zoomed close together keep a label each. */
export function tickLabels(values: number[]): string[] {
  const span = Math.max(...values.map(Math.abs), 0);
  if (!values.length || !values.every(Number.isFinite) || span >= 1e15) return values.map((v) => sig(v));
  const written = (d: number) => values.map((v) => (Object.is(Number(v.toFixed(d)), -0) ? 0 : v).toFixed(d));
  // As it is: within a millionth of the distance between two ticks.
  const steps = values
    .slice(1)
    .map((v, k) => Math.abs(v - values[k]))
    .filter((x) => x > 0);
  const near = (steps.length ? Math.min(...steps) : Math.max(span, 1)) * 1e-6;
  for (let d = 0; d <= 9; d++) {
    const out = written(d);
    const apart = new Set(out).size === new Set(values).size;
    if (apart && values.every((v, k) => Math.abs(Number(out[k]) - v) <= near)) return out;
  }
  return values.map((v) => sig(v));
}

export const degrees = (t: number | null | undefined): string =>
  missing(t) ? NONE : `${Math.round(t as number) || 0} °C`;

export const percent = (x: number | null | undefined, digits = 1): string =>
  // A share that rounds to nothing is 0, never -0.
  missing(x) ? NONE : `${(Number((100 * (x as number)).toFixed(digits)) || 0).toFixed(digits)} %`;

/** A whole number with its thousands set apart by a thin space, which the page reads back:
 *  20 000, never 20,000, which half the world reads as twenty. */
export const whole = (value: number): string =>
  missing(value) ? NONE : String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, "\u202f");

export function escape(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

/** A sentence with its first letter raised, unless its first word is a name that mixes its
 *  cases on purpose (eGaN, xFET), which is left as it is written. */
export const sentence = (text: string) => {
  if (!text) return text;
  const first = text.split(" ", 1)[0];
  return /[A-Z]/.test(first.slice(1)) ? text : text[0].toUpperCase() + text.slice(1);
};
