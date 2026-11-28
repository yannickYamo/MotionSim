// What a control costs the power stage, as differences: this run against the design point
// as the loss engine settles it, and against the run before it. Every edit reads as a change.

import { sig } from "../format";
import type { Channels, Engine, Run } from "./types";

export interface Figure {
  key: string;
  label: string;
  unit: string;
  value: number | null;
  /** Costs energy or runs hot: drawn in the ink of heat. */
  hot: boolean;
}

export interface Difference {
  /** now − then. */
  by: number;
  /** As a share of then; null where then is nought. */
  share: number | null;
  /** In words: "−12 %" for a figure that scales, "+0.4 A" for one read on its own scale. */
  text: string;
}

/** Figures read as a share of what they were; the rest are read on their own scale. */
const AS_SHARE = new Set(["loss", "conduction", "switching", "commutations_per_s", "f_switch_mean"]);

const number = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** A run whose stage is averaged over each carrier period: it makes no switching edges. */
export const averaged = (run: Run): boolean => run.fidelity === "averaged";

/** What an averaged stage does not model: its edges, what they cost and the ripple they make. */
export const EDGES = ["switching", "commutations_per_s", "i_at_commutation", "ripple_pp"];

/** The headline figures of a run: the channels the control moves, and the loss it comes to. */
export function figuresOf(run: Run): Figure[] {
  const c: Channels = run.channels ?? {};
  // An averaged stage makes no edges: what they would cost is not modelled, not nought.
  const row = (key: string, label: string, unit: string, value: unknown, hot = false): Figure => ({
    key,
    label,
    unit,
    value: averaged(run) && EDGES.includes(key) ? null : number(value),
    hot,
  });
  return [
    row("loss", "Power-stage loss", "W", run.losses?.loss),
    row("conduction", "Conduction", "W", run.losses?.conduction),
    row("switching", "Switching", "W", run.losses?.switching, true),
    row("i_switch_rms", "Switch current, rms", "A", c.i_switch_rms),
    row("i_switch_peak", "Switch current, peak", "A", c.i_switch_peak),
    // What the link's capacitor must carry: the stage draws in pulses, the supply gives their average.
    ...(number(c.link_ripple_rms) !== null
      ? [row("link_ripple_rms", "DC-link capacitor current, rms", "A", c.link_ripple_rms)]
      : []),
    row("commutations_per_s", "Commutations a second", "", c.commutations_per_s, true),
    row("i_at_commutation", "Current at commutation, mean", "A", c.i_at_commutation, true),
    row("thd", "Current distortion (THD)", "%", number(c.thd) === null ? null : number(c.thd)! * 100),
    row("ripple_pp", "Current ripple, peak to peak", "A", c.ripple_pp),
    row("torque_ripple_pp", "Torque ripple, peak to peak", "N·m", c.torque_ripple_pp),
    // What the shaft does: its speed's swing within a turn where a hold reads it, and how far
    // motor and load swing against each other where the shaft twists (nought on a rigid one).
    ...(number(c.speed_ripple_pp) !== null
      ? [row("speed_ripple_pp", "Speed swing within a turn, peak to peak", "rad/s", c.speed_ripple_pp)]
      : []),
    ...(number(c.shaft_swing_pp)
      ? [row("shaft_swing_pp", "Shaft swing, motor against load, peak to peak", "rad/s", c.shaft_swing_pp)]
      : []),
    // What shunts in the stage read, where the drive senses through them: how often a phase
    // could not be read and was kept from before, and how far the current as read is off.
    ...(number(c.unread_share) !== null
      ? [
          row("unread_share", "Periods a phase could not be read", "%", number(c.unread_share)! * 100),
          row("read_error_rms", "Current as read, off the true one, rms", "A", c.read_error_rms),
        ]
      : []),
    row("tj_peak", "Junction, peak", "°C", c.tj_peak ?? run.losses?.tj_peak, true),
    row("tj_swing", "Junction swing", "K", c.tj_swing, true),
  ];
}

/** The same figures where the loss engine's settled answer gives them; null where it does not. */
export function settledFigure(engine: Engine | null, key: string): number | null {
  if (!engine) return null;
  const from: Record<string, unknown> = {
    loss: engine.loss,
    conduction: engine.conduction,
    switching: engine.switching,
    tj_peak: engine.tj_peak,
    ripple_pp: engine.ripple_pp,
  };
  return number(from[key]);
}

const DUST = 1e-3;
const signed = (text: string, by: number): string => `${by > 0 ? "+" : by < 0 ? "−" : "±"}${text}`;

/** How a figure differs from what it was. Null where either is missing; "no change" in words
 *  where the two round to the same figure. */
export function difference(key: string, unit: string, now: number | null, then: number | null): Difference | null {
  if (now === null || then === null) return null;
  const by = now - then;
  const share = then !== 0 ? by / Math.abs(then) : null;
  const asShare = AS_SHARE.has(key) && share !== null;
  const size = asShare ? Math.abs(share * 100) : Math.abs(by);
  // A change that rounds to nought at the figures shown is no change.
  const shown = asShare ? (size >= 10 ? size.toFixed(0) : size.toFixed(1)) : sig(size, 2);
  // So is one under a thousandth of the figure itself: the arithmetic's, not the control's.
  const none = Number(shown) === 0 || Math.abs(by) <= DUST * Math.max(Math.abs(now), Math.abs(then));
  const text = none ? "no change" : signed(`${shown} ${asShare ? "%" : unit}`, by);
  return { by: none ? 0 : by, share, text };
}

export interface Compared extends Figure {
  /** Against the design point as the loss engine settles it. */
  settled: Difference | null;
  /** Against the run before. */
  before: Difference | null;
}

/** Every headline figure of a run, each against the settled design point and the run before. */
export function compared(run: Run, before: Run | null): Compared[] {
  const earlier = before ? new Map(figuresOf(before).map((f) => [f.key, f.value])) : null;
  return figuresOf(run).map((f) => ({
    ...f,
    settled: difference(f.key, f.unit, f.value, settledFigure(run.engine, f.key)),
    before: difference(f.key, f.unit, f.value, earlier?.get(f.key) ?? null),
  }));
}
