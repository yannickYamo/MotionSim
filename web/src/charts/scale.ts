// The scales a chart is drawn on: round ticks, a range that holds the data with zero on it,
// and where a value falls along an axis.

/** No scale carries more ticks than this, whatever it is asked for. */
const MOST_TICKS = 12;

/** A value as a tick shows it: to twelve figures, so that 0.1 + 0.2 is 0.3. */
const rounded = (v: number): number => Number(v.toPrecision(12));

/** The figures in a list: what is missing, not a number or without end is left out. */
export const figures = (list: (number | null | undefined)[]): number[] =>
  list.filter((v): v is number => typeof v === "number" && Number.isFinite(v));

/** The round step that divides [lo, hi] into about `wanted` parts: 1, 2 or 5 times a power of
 *  ten. None where the range is too narrow or too wide for a number to count along in steps. */
function roundStep(lo: number, hi: number, wanted: number): number | null {
  const parts = Math.min(Math.max(Math.floor(wanted) || 1, 1), 10);
  // The two ends of what a number can hold are further apart than a number can say.
  const raw = Number.isFinite(hi - lo) ? (hi - lo) / parts : hi / parts - lo / parts;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= raw);
  if (step === undefined || !(step > 0) || !Number.isFinite(step)) return null;
  // A step that is lost in the figures of the values would give the same tick again and again.
  return rounded(lo + step) > rounded(lo) ? step : null;
}

/** Round tick values covering [lo, hi]. Where no round step can be counted in, its two ends. */
export function ticks(lo: number, hi: number, wanted = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [Number.isFinite(lo) ? lo : 0];
  if (!(hi > lo)) return [lo];
  const step = roundStep(lo, hi, wanted);
  if (step === null) return [lo, hi];
  // Each tick is a whole number of steps, counted and not added up: a count always ends.
  const first = Math.ceil(lo / step);
  const out: number[] = [];
  for (let k = 0; k < MOST_TICKS; k++) {
    const v = (first + k) * step;
    if (!(v <= hi + step * 1e-9)) break;
    const tick = rounded(v);
    if (Number.isFinite(tick) && !(tick <= out[out.length - 1])) out.push(tick);
  }
  return out.length ? out : [lo, hi];
}

/** Carries a scale on by whole steps until it reaches `to`: upward, or downward from its foot.
 *  It gives up after a few steps, or where the next one is more than a number can hold. */
export function extend(yt: number[], step: number, to: number, down = false): void {
  for (let k = 0; k < 4; k++) {
    const end = down ? yt[0] : yt[yt.length - 1];
    if (down ? end <= to : end >= to) return;
    const next = rounded(down ? end - step : end + step);
    if (!Number.isFinite(next) || next === end) return;
    if (down) yt.unshift(next);
    else yt.push(next);
  }
}

/** A value with a little room beyond it, kept within what a number can hold. */
export const withRoom = (v: number, room: number): number =>
  Math.max(Math.min(v * room, Number.MAX_VALUE), -Number.MAX_VALUE);

/** A scale on round values that holds everything from lo to hi, with zero always on it. What
 *  is not a figure is left out; with no figure at all the scale runs from nought to one. */
export function scale(values: number[], wanted = 4): number[] {
  const held = figures(values);
  const lo = Math.min(0, ...held),
    hi = Math.max(0, ...held);
  const top = hi > lo ? hi : lo + 1;
  const yt = ticks(lo, top, wanted);
  const step = roundStep(lo, top, wanted);
  if (step === null) return yt;
  // The scale ends on a round value beyond the highest and the lowest point, so that a level
  // stretch is a line inside the plot and not one drawn over its frame.
  extend(yt, step, hi > 0 ? withRoom(hi, 1.03) : hi);
  if (lo < 0) extend(yt, step, withRoom(lo, 1.03), true);
  // Where the next round value is more than a number can hold, the scale ends on the data.
  if (yt[yt.length - 1] < hi) yt.push(hi);
  if (yt[0] > lo) yt.unshift(lo);
  return yt;
}

/** How far a value lies from lo to hi, as a share of the way. Each is halved first, so that
 *  the two ends of what a number can hold are not further apart than a number can say. */
export function along(v: number, lo: number, hi: number): number {
  const span = hi / 2 - lo / 2;
  return span > 0 ? (v / 2 - lo / 2) / span : 0;
}

/** The length of a time axis: its last instant, and one second where that is no length. */
export function lengthOf(time: number[]): number {
  const end = time[time.length - 1];
  return Number.isFinite(end) && end > 0 ? end : 1;
}
