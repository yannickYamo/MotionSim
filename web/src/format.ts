// Numbers as an engineer writes them: three significant figures, a real unit, no false precision.

export function sig(value: number, digits = 3): string {
  if (!Number.isFinite(value)) return "–";
  if (value === 0) return "0";
  const magnitude = Math.floor(Math.log10(Math.abs(value)));
  const decimals = Math.max(0, digits - 1 - magnitude);
  return value.toFixed(Math.min(decimals, 6));
}

/** A figure the engine worked out, to three figures however large: 1378 J is 1380 J. Not for
 *  a figure the user typed, which is shown as typed. */
export const fig = (value: number, digits = 3): string => (Number.isFinite(value) ? sig(Number(value.toPrecision(digits)), digits) : sig(value));

const PREFIX: [number, string][] = [[1e6, "M"], [1e3, "k"], [1, ""], [1e-3, "m"], [1e-6, "µ"], [1e-9, "n"]];

/** 0.00012 H becomes "120 µH". */
export function eng(value: number, unit: string, digits = 3): string {
  if (!Number.isFinite(value)) return "–";
  if (value === 0) return `0 ${unit}`;
  const [scale, prefix] = PREFIX.find(([s]) => Math.abs(value) >= s) ?? PREFIX[PREFIX.length - 1];
  return `${sig(value / scale, digits)} ${prefix}${unit}`;
}

export const watts = (w: number) => (Math.abs(w) >= 1000 ? `${sig(w / 1000)} kW` : `${sig(w)} W`);
export const degrees = (t: number) => `${Math.round(t)} °C`;
export const percent = (x: number, digits = 1) => `${(100 * x).toFixed(digits)} %`;

export function escape(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

/** First letter up, for sentences the engine writes in lower case. */
export const sentence = (text: string) => (text ? text[0].toUpperCase() + text.slice(1) : text);
