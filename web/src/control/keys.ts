// What is set first on a block, as tables: kind → its key settings, test → its targets, and
// the words and the steps they are set in. Nothing here draws; keysettings.tsx does.

import { gainWord } from "./gain";
import type { Kind, Param, Port, Scenario } from "./types";
import { worded } from "./ui";

export type Control = "choice" | "figure";

/** Kind of block → its key settings, most important first, each with the control it takes.
 *  A kind not named here offers its gains, then its first figures. Kinds with nothing to set
 *  (the transforms) offer nothing. */
export const KEY_SETTINGS: Record<string, [string, Control][]> = {
  clarke: [],
  park: [],
  if_current: [],
  inverse_park: [["advance", "figure"]],
  current_sampling: [
    ["bits", "figure"],
    ["noise", "figure"],
    ["offset", "figure"],
  ],
  shunt_sampling: [
    ["shunts", "choice"],
    ["window", "figure"],
    ["fix", "choice"],
  ],
  hf_injection: [
    ["amplitude", "figure"],
    ["polarity", "choice"],
    ["cross", "figure"],
  ],
  injection_sum: [],
  position_sensing: [
    ["sensor", "choice"],
    ["counts", "figure"],
    ["latency", "figure"],
  ],
  speed_reference: [
    ["shape", "choice"],
    ["slew", "figure"],
    ["jerk", "figure"],
  ],
  speed_pi: [
    ["kp", "figure"],
    ["ki", "figure"],
    ["limit", "figure"],
  ],
  torque_notch: [
    ["frequency", "figure"],
    ["depth", "figure"],
  ],
  periodic_compensation: [
    ["harmonics", "figure"],
    ["reach", "figure"],
  ],
  voltage_feedback_fw: [
    ["headroom", "figure"],
    ["bandwidth", "figure"],
  ],
  speed_adrc: [
    ["bandwidth", "figure"],
    ["inertia", "figure"],
    ["limit", "figure"],
  ],
  torque_shaper: [
    ["shape", "choice"],
    ["limit", "figure"],
    ["rate", "figure"],
  ],
  current_reference: [
    ["strategy", "choice"],
    ["i_limit", "figure"],
  ],
  current_pi_dq: [
    ["kp_q", "figure"],
    ["ki_q", "figure"],
    ["kp_d", "figure"],
    ["ki_d", "figure"],
  ],
  current_discrete_dq: [
    ["gain", "figure"],
    ["bemf_feedforward", "choice"],
  ],
  deadbeat_dq: [
    ["gain", "figure"],
    ["delay_compensation", "choice"],
  ],
  fcs_mpc: [
    ["cost", "choice"],
    ["weighting", "choice"],
    ["weight", "figure"],
    ["horizon", "figure"],
  ],
  dtc: [
    ["torque_band", "figure"],
    ["flux_band", "figure"],
  ],
  modulator: [
    ["pwm", "choice"],
    ["threshold", "figure"],
  ],
  dead_time_compensation: [
    ["dead_time", "figure"],
    ["drop", "figure"],
    ["band", "figure"],
  ],
  observer_emf_pll: [
    ["bandwidth", "figure"],
    ["pll_bandwidth", "figure"],
  ],
  observer_smo: [
    ["gain", "figure"],
    ["cutoff", "figure"],
    ["pll_bandwidth", "figure"],
  ],
  observer_flux: [
    ["crossover", "figure"],
    ["pll_bandwidth", "figure"],
  ],
  if_startup: [
    ["current", "figure"],
    ["ramp", "figure"],
    ["handover", "figure"],
    ["handback", "figure"],
  ],
  thermal_supervisor: [
    ["actuators", "choice"],
    ["limit", "figure"],
    ["t_derate", "figure"],
  ],
  variable_frequency: [
    ["mode", "choice"],
    ["f_min", "figure"],
    ["f_max", "figure"],
  ],
};

const isChoice = (p: Pick<Param, "choices" | "default">): boolean =>
  p.choices.length > 0 || typeof p.default === "boolean";

/** The key settings of a block: the table's, where it names the kind; else its gains, then
 *  its first figures, three at most. Only figures the block has are offered. */
export function keysOf(kind: Kind | undefined, gains: string[] = []): [Param, Control][] {
  const params = kind?.params ?? [];
  const named = kind ? KEY_SETTINGS[kind.kind] : undefined;
  const pick = named
    ? named.map(([n]) => n)
    : [...gains, ...params.map((p) => p.name)].filter((n, i, all) => all.indexOf(n) === i).slice(0, 3);
  return pick.flatMap((n) => {
    const p = params.find((x) => x.name === n);
    return p ? [[p, isChoice(p) ? "choice" : "figure"] as [Param, Control]] : [];
  });
}

/** Names as an engineer says them; anything else as the registry writes it. */
const WORDS: Record<string, string> = {
  pwm: "PWM scheme",
  shape: "Shape",
  slew: "Slew rate",
  jerk: "Jerk",
  limit: "Limit",
  rate: "Rate",
  strategy: "Strategy",
  i_limit: "Current limit",
  sensor: "Sensor",
  counts: "Encoder counts",
  latency: "Latency",
  bits: "ADC resolution",
  noise: "Noise",
  offset: "Offset",
  advance: "Advance",
  threshold: "Threshold",
  dead_time: "Dead time",
  drop: "Device drop",
  band: "Current band",
  torque_band: "Torque band",
  flux_band: "Flux band",
  bandwidth: "Observer bandwidth",
  pll_bandwidth: "PLL bandwidth",
  crossover: "Crossover",
  cutoff: "Cutoff",
  current: "Current",
  ramp: "Ramp",
  handover: "Hand-over speed",
  handback: "Hand-back speed",
  actuators: "Actuators",
  t_derate: "Derate from",
  mode: "Mode",
  f_min: "Lowest carrier",
  f_max: "Highest carrier",
  cost: "Cost",
  weighting: "Weighting",
  weight: "Weight",
  horizon: "Horizon",
  bemf_feedforward: "Back-EMF feed-forward",
  delay_compensation: "Delay compensation",
  // The test's figures.
  to_rpm: "Target speed",
  from_rpm: "Speed before the step",
  rpm: "Speed",
  to: "Torque after the step",
  from: "Torque before the step",
  torque: "Load torque",
  t_step: "Step at",
  t_trip: "Trip at",
  safe: "Safe state",
  shaft: "Shaft",
  cause: "Cause",
  brake_torque: "Holding brake",
  brake_delay: "Brake bites after",
  duration: "Duration",
  current_limit: "Current limit",
  angle: "Angle",
  periods: "Periods analysed",
  settle: "Settling time",
  pick: "Window",
  span: "Window length",
};

const KIND_WORDS: Record<string, Record<string, string>> = {
  stall: { torque: "Torque held" },
  trip: { torque: "Torque before the trip", rpm: "Speed at the trip" },
};

export const keyWord = (name: string, kind = ""): string => KIND_WORDS[kind]?.[name] ?? WORDS[name] ?? gainWord(name);

const CHOICE_WORDS: Record<string, string> = {
  mtpa_fw: "MTPA + field weakening",
  id_zero: "id = 0",
  least_loss: "Least loss",
  "space-vector": "Space vector",
  "third-harmonic": "Third harmonic",
  "s-curve": "S-curve",
  true: "On",
  false: "Off",
  change: "Fastest change",
  torque: "Peak torque",
  off: "Every gate off",
  short: "Shorted",
  hybrid: "Shorted at speed, off below",
  held: "Held at its speed",
  free: "Free, under its load",
  protection: "Protection trips it",
  encoder: "The encoder freezes",
  open_switch: "A switch fails open",
};
export const choiceWord = (o: string): string => {
  const w = CHOICE_WORDS[o] ?? worded(o);
  return w.charAt(0).toUpperCase() + w.slice(1);
};

/** The tests as they are named on a switch: short. */
export const TEST_WORDS: Record<string, string> = {
  hold: "Hold",
  torque_step: "Torque step",
  speed_step: "Speed step",
  start: "Start",
  load_step: "Load step",
  stall: "Stall",
  motion: "Motion",
  trip: "Trip",
};

/** Test → its targets, the figures an engineer changes first; the rest of a test's figures
 *  are under All parameters. A test not named here offers its first three. */
export const TEST_TARGETS: Record<string, string[]> = {
  hold: [],
  torque_step: ["to", "rpm", "t_step"],
  speed_step: ["to_rpm", "from_rpm", "t_step"],
  start: ["to_rpm", "shape", "current_limit"],
  load_step: ["torque", "t_step"],
  stall: ["torque", "angle", "rpm"],
  motion: ["pick", "span"],
  trip: ["safe", "rpm", "torque"],
};

export const targetsOf = (scenario: Scenario): Port[] => {
  const named = TEST_TARGETS[scenario.kind];
  if (!named) return scenario.fields.slice(0, 3);
  return named.flatMap((n) => scenario.fields.filter((f) => f.name === n));
};

/** No bound at all: the engine's "none", 1e12. */
export const unbounded = (v: number): boolean => Math.abs(v) >= 1e11;

/** A figure written for its box: plain, four significant figures at most (the figure kept is the engine's, whole). */
export const boxed = (v: number): string => (unbounded(v) ? "" : String(Number(v.toPrecision(4))));

/** A figure counted in whole steps: bits, counts, samples, turns. */
export const whole = (name: string, unit: string): boolean =>
  /^(bit|1\/turn|samples|steps|turns)$/.test(unit) || /^(bits|counts|horizon|periods)$/.test(name);

/** Where a figure that stands at nought goes with one step: a small step in its own unit. */
const FROM_NOUGHT: Record<string, number> = { s: 1e-6, A: 0.1, V: 0.1, "N·m": 0.1, rpm: 100, "°": 5 };

/** One step of a figure, up or down: a twentieth of it (a quarter with Shift), as a gain is
 *  tuned; whole figures by one, or by doubling once they are large; an angle by degrees. */
export function stepped(v: number, way: 1 | -1, big: boolean, name: string, unit: string): number {
  if (whole(name, unit)) {
    if (Math.abs(v) >= 64) return Math.round(v * 2 ** way);
    return Math.round(v) + way * (big ? 4 : 1);
  }
  if (unit === "°" || unit === "deg") return v + way * (big ? 15 : 5);
  if (v === 0) return way * (FROM_NOUGHT[unit] ?? 0.1);
  return Number((v * (big ? 1.25 : 1.05) ** way).toPrecision(6));
}

export const held = (v: number, low?: number | null, high?: number | null): number =>
  Math.min(high ?? Infinity, Math.max(low ?? -Infinity, v));
