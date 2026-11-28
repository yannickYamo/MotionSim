// The one junction figure of a result: the hottest of the design point, holding the torque at
// standstill and the motion, said with where it occurs. The others are named under it, one
// hover or focus away, so that no two junction figures on a screen disagree about the worst.

import { notRefused } from "../api";
import type { Candidate } from "../api";
import { degrees } from "../format";
import { RESULTS } from "../steps";
import { app, focused, res } from "../store";

export interface JunctionCase {
  where: "at the design point" | "at standstill" | "through the motion";
  value: number;
}

export interface Worst {
  /** The hottest junction of the cases known, °C. */
  value: number;
  where: JunctionCase["where"];
  rating: number;
  cases: JunctionCase[];
  /** The motion has been followed (or cannot be): the figure will not move when it comes. */
  settled: boolean;
  /** "at the design point: 63 to 71 °C across the thermal assumptions", where they part. */
  range: string;
}

/** The motion's hottest junction for this part, where the results have followed it. */
function motionPeak(c: Candidate): { peak: number | null; settled: boolean } {
  const onResults = app.state.step === RESULTS && c.id === focused()?.id;
  if (!onResults) return { peak: null, settled: true };
  if (res.cycle === null) return { peak: null, settled: false };
  return { peak: notRefused(res.cycle)?.summary.peak ?? null, settled: true };
}

export function worstJunction(c: Candidate): Worst | null {
  const r = c.result;
  if (!r) return null;
  const motion = motionPeak(c);
  const cases: JunctionCase[] = [{ where: "at the design point", value: r.tj_peak }];
  if (c.stall_tj != null) cases.push({ where: "at standstill", value: c.stall_tj });
  if (motion.peak != null) cases.push({ where: "through the motion", value: motion.peak });
  // The first of equals wins: the design point, then standstill, then the motion.
  const worst = cases.reduce((a, b) => (b.value > a.value + 1e-9 ? b : a));
  const spread = r.tj_range && Math.round(r.tj_range[0]) !== Math.round(r.tj_range[1]);
  const [low, high] = (r.tj_range ?? [0, 0]).map(Math.round);
  const range = spread ? `At the design point, ${low} to ${high} °C across the thermal assumptions.` : "";
  return { value: worst.value, where: worst.where, rating: r.tj_max, cases, settled: motion.settled, range };
}

/** The cases behind the figure, as its tooltip says them. */
export function casesSaid(w: Worst): string {
  const each = w.cases.map((x) => `${x.where} ${degrees(x.value)}`).join(", ");
  const later = w.settled ? "" : " The motion is still being followed.";
  return `The hottest junction of every case: ${each}.${w.range ? ` ${w.range}` : ""}${later}`;
}
