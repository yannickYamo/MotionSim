// What a duty adds: its phases, and what a motion of minutes or an hour says it did.

/** A stretch of a motion: how long it lasts and the load speeds it runs between, rpm. */
export interface Segment {
  duration: number;
  speed_start: number;
  speed_end: number;
  /** Run up as fast as the drive's current limit lets the load. */
  at_limit?: boolean;
  /** Held until the junction is steady, the duration its most. */
  until_steady?: boolean;
  /** The road's own slope on this stretch, for a vehicle. */
  slope_percent?: number | null;
}

/** A named part of a duty, repeated as many times as it says. */
export interface Phase {
  name: string;
  repeat: number;
  segments: Segment[];
}

/** What an application adds to a load offered: its phases, its start, its use in a year,
 *  the reasons for its figures, and the motor such products usually have. */
export interface PresetDuty {
  phases: Phase[] | null;
  /** How the drive of such a product starts: with a sensor, or sensorless. */
  start: string;
  /** How much such a product runs in a year, in runs of the duty or in hours. */
  usage: { per_year: number; unit: "runs" | "hours"; said: string };
  /** Each figure of the application and why it is that. */
  why: string[];
  duration: number;
  /** The motor such products usually have, for an application of a size of its own. */
  motor: {
    kind: string;
    v_dc: number;
    own_v_dc: number;
    values: Record<string, string | number>;
    point: { rpm: number; torque: number };
  } | null;
  /** Whether the motor given can run it, and why not. */
  runs: { ok: boolean; why: string } | null;
}

/** What a duty says it did: its phases in time, its start-up, where it got steady, its
 *  worst swing, and how the heatsink was followed. */
export interface DutyAnswer {
  /** The junction's swing within one output period or one turn of the load, each instant. */
  swing?: (number | null)[];
  /** A duty's named parts, from when each began to when it ended, s. */
  phases?: { name: string; start: number; end: number }[];
  startup?: {
    current: number;
    time: number;
    at: number;
    until: number;
    tj_peak: number | null;
    tj_at: number | null;
    limit: number | null;
    at_limit: boolean;
    run_up: number | null;
    run_up_reached: boolean | null;
  } | null;
  steady_at?: {
    phase: string | null;
    start: number;
    time: number;
    after: number;
    tj: number | null;
    reached: boolean;
  }[];
  worst_swing?: {
    swing: number;
    time: number;
    phase: string | null;
    rpm: number;
    torque: number;
    f_e: number | null;
    loss: number | null;
  } | null;
  method?: {
    method: string;
    tau: number | null;
    capacity?: number | null;
    assumed?: boolean;
    said: string;
  };
  taken?: string[];
  thinned?: { from: number; to: number };
}
