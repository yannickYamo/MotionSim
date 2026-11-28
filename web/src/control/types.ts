// What the control addresses of the engine answer with, as the lab reads it. The engine may
// add names to any of these; the lab reads the ones it knows and leaves the rest alone.

import type { Check } from "../api/types";

export type Value = number | string | boolean;

export interface Block {
  name: string;
  kind: string;
  inputs: Record<string, string>;
  params: Record<string, Value>;
  sources?: Record<string, string>;
}

export interface Scheme {
  id: string;
  label: string;
  about: string;
  timing: { update: string; delay: boolean; f_control: number | null; per_carrier?: number; carriers?: number };
  actuation: { kind: string; wires: string[] };
  blocks: Block[];
  /** The tests this scheme can be given, as the presets list it; the others are refused. */
  tests?: string[];
  /** Why it is not one to set beside the others for this design, where it is made for a load
   *  this design does not have. */
  aside?: string | null;
}

export interface Port {
  name: string;
  unit: string;
  about: string;
  /** For a figure of a test: the bounds it is held to and the words it may be, where the engine says. */
  default?: Value;
  low?: number | null;
  high?: number | null;
  choices?: string[];
  optional?: boolean;
}

export interface Param {
  name: string;
  unit: string;
  value: Value;
  default: Value;
  low: number | null;
  high: number | null;
  choices: string[];
  about: string;
  source: string;
}

/** One kind of block, as the registry describes it. */
export interface Kind {
  kind: string;
  /** The part it plays in a scheme, as a hint for where it is drawn: where the engine says. */
  role?: string;
  title: string;
  /** What it does in two or three lines: shown first. */
  summary?: string;
  definition: string;
  math: string[];
  linear: boolean;
  loop: string;
  inputs: Port[];
  outputs: Port[];
  params: Param[];
}

export interface Scenario {
  kind: string;
  label: string;
  about: string;
  needs: string | null;
  fields: Port[];
  defaults: Record<string, Record<string, Value>>;
}

export interface Presets {
  chosen: string;
  why: string;
  schemes: Scheme[];
  blocks: Record<string, Kind>;
  sources: Port[];
  scenarios: Scenario[];
  fidelities: string[];
  limits: { duration: number; steps: number; points: number };
  design: Record<string, number | string | null>;
  /** The motor and load as the engine can simulate them beyond the controller's own model. */
  plant?: PlantOptions;
  taken: string[];
}

/** A figure of the shaft that twists, as a form draws it. */
export interface PlantField {
  name: string;
  unit: string;
  about: string;
  default: number;
  low: number;
  high: number;
}

export interface PlantOptions {
  coupling: PlantField[];
  iron: { choices: string[]; about: string };
}

/** The motor and load as asked of the engine: a shaft that twists, iron that saturates.
 *  Absent, each is the controller's own model (a rigid shaft, linear iron). */
export interface Plant {
  coupling?: Record<string, number>;
  iron?: string;
}

export interface Series {
  t: number[];
  wires: Record<string, number[]>;
  /** Where samples were left out: each kept instant's lowest and highest value up to the next,
   *  for the wires that swing beyond what the kept samples show. */
  lo?: Record<string, number[]>;
  hi?: Record<string, number[]>;
}

export interface Wire {
  name: string;
  unit: string;
  block: string;
  about: string;
}

export type { Check } from "../api/types";

export interface PerSwitch {
  name: string;
  conduction: number;
  switching: number;
  total: number;
  i_rms: number;
  i_peak: number;
  tj_mean: number;
  tj_peak: number;
  [figure: string]: number | string;
}

export interface Step {
  kind: string;
  wire: string;
  t_step: number;
  from: number;
  to: number;
  rise_time?: number | null;
  overshoot?: number | null;
  settling_time?: number | null;
  steady_state_error?: number | null;
  held?: number | null;
  deviation?: number | null;
  recovery_time?: number | null;
  /** The same step read on the load's own speed, where the shaft twists. */
  load?: { rise_time: number | null; overshoot: number | null; settling_time: number | null } | null;
}

export type Channels = Record<string, number | null>;

export interface Waveform {
  from: number;
  to: number;
  cut: boolean;
  t: number[];
  i_a: number[];
  i_b: number[];
  i_c: number[];
  s_a: number[];
  s_b: number[];
  s_c: number[];
  [trace: string]: unknown;
}

export interface Losses {
  loss: number;
  conduction: number;
  switching: number;
  tj_peak: number;
  tj_max?: number;
  per_switch: PerSwitch[];
}

export interface Engine {
  loss: number;
  conduction: number;
  switching: number;
  tj_peak: number;
  ripple_pp: number;
}

export interface Run {
  scheme: Scheme;
  scenario: Record<string, Value>;
  fidelity: string;
  taken: string[];
  timing: { ts: number; f_control: number; steps: number; duration: number; ended: string; analysed_from: number };
  engine: Engine | null;
  wires: Wire[];
  series: Series;
  /** The DC link through the run, where the drive is fed from the mains. */
  link?: { v_ref: number; v_min: number; v_max: number; ripple: number; thd: number | null; feed_forward: boolean };
  waveform: Waveform | null;
  losses: Losses;
  thermal: { t: number[]; tj_from_start: number[]; swing: number; settled_low: number; settled_high: number };
  channels: Channels;
  step: Step | null;
  checks: Check[];
  level: string;
  /** The figures the verdict is judged from, to be sent back to judge again (older engines: absent). */
  quality?: Quality;
  verdict?: Verdict;
  /** What the pulsed rating was held to: the run's own overshoot after a torque step, else the allowance. */
  pulsed?: { held: number; rating: number | null; overshoot: number; measured: boolean } | null;
  /** The observer's floor, a scheme with no encoder: this run's and a real stage's, rpm. */
  floor?: { rpm: number; hardware_rpm: number; design_rpm: number; handback_rpm: number } | null;
  /** A window of the motion: where it lies and how closely it was followed. */
  window?: { from: number; to: number; wire: string } | null;
  stability?: {
    linear_stable?: boolean;
    analysed?: boolean;
    loop?: string | null;
    said?: string;
    message?: string;
    [more: string]: unknown;
  } | null;
}

/** One step of a streamed run. */
export interface RunProbe {
  progress: number;
  t: number;
  series: Series;
}

export interface Polynomials {
  num: number[];
  den: number[];
}

export interface Pole {
  re: number;
  im: number;
  hz: number;
  damping: number;
  stable: boolean;
}

export interface Loop {
  name: string;
  ts: number;
  open: Polynomials;
  closed: Polynomials;
  bode: { f: number[]; open_db: number[]; open_deg: number[]; closed_db: number[]; closed_deg: number[] };
  margins: {
    crossover_hz: number | null;
    phase_deg: number | null;
    phase_crossover_hz: number | null;
    gain_db: number | null;
  };
  bandwidth_hz: number | null;
  poles: Pole[];
  zeros: Pole[];
  stable: boolean;
  step: { t: number[]; y: number[]; rise_time: number | null; overshoot: number | null; settling_time: number | null };
  transfer: string[];
  /** The same as LaTeX, then the open and the closed loop with this design's numbers: where the engine sends it. */
  transfer_latex?: string[];
}

export interface Loops {
  scheme: Scheme;
  tuning: { bandwidth_hz: number; delay_s: number; rule: string };
  /** The tests this scheme can be given. */
  tests?: string[];
  /** The test whose run answers each loop in time, or null where the scheme takes none. */
  simulated_by?: { current_d: string | null; current_q: string | null; speed: string | null };
  assumes: string[];
  missing: string[];
  current_d: Loop | null;
  current_q: Loop | null;
  speed: Loop | null;
}

export interface Vary {
  label: string;
  unit: string;
  path: string;
  values?: Value[];
  schemes?: string[];
}

/** What a figure a sweep reads is called and measured in, as the engine words it. */
/** `scale` takes a run's own figure (Hz, s, a share) to `unit`: 1e-3 for a frequency read in kHz. */
export type ReadWords = Record<string, { label: string; unit: string; kind?: string; scale?: number }>;

export interface Exploration {
  id: string;
  title: string;
  question: string;
  about: string;
  group: string;
  applies: boolean;
  why_not: string | null;
  scheme: string | Scheme;
  scenario: Record<string, Value>;
  fidelity: string;
  vary: Vary;
  reads: string[];
  /** The direction the physics gives, in words: where the engine says. */
  expects?: string;
  sources: { title: string; year: number | string; link: string }[];
}

export interface Variant {
  value?: Value;
  scheme?: string;
  label: string;
  channels: Channels | null;
  losses: Partial<Losses> | null;
  step: Step | null;
  stability?: unknown;
  level: string;
  refused?: string | { refused: string; fix?: string } | null;
  /** What the run checked of itself: a "tracking" check not ok is a run that did not do what was asked. */
  checks?: { topic: string; level: string }[];
}

export interface Sweep {
  vary: Vary;
  variants: Variant[];
  /** The variant the others are set against: its place among them, or its figures. */
  baseline: number | Partial<Variant> | null;
  said: string[];
  /** One for each of `said`: "short" where a run fell short of what was asked; never "good". */
  tags?: ("short" | "note")[];
}

/** One document of the local store, as its list names it. */
export interface Kept {
  id: string;
  name?: string;
  saved?: string;
}

/** The figures of a run a verdict is judged from: plain data, read here only for its test,
 *  its scheme and what it changed of the scheme as tuned. */
export interface Quality {
  test: string;
  scheme: { id: string; [more: string]: unknown };
  fidelity: string;
  tuned: { id: string; edits: Edit[]; loops: unknown } | null;
  [more: string]: unknown;
}

export interface Edit {
  block: string;
  param: string;
  tuned: Value | null;
  now: Value | null;
}

/** What moves a finding: a block's setting, a scheme, the test, the design, or back to as tuned. */
export type Lever =
  | { kind: "block"; block: string; param: string; direction: "raise" | "lower" | "set"; to: Value | null }
  | { kind: "scheme"; to: string }
  | { kind: "test"; param: string }
  | { kind: "design"; param: string }
  | { kind: "tuned" };

export interface Finding {
  id: string;
  topic: string;
  /** A note is a caveat on the figures themselves (a datasheet scaled past its data), not a change. */
  tag: "good" | "improve" | "note";
  severity: number;
  said: string;
  /** The finding in a clause, as the summary says it. */
  head?: string | null;
  lever: Lever | null;
  expect: string | null;
  change: {
    was: number;
    now: number;
    unit: string;
    against: "tuned" | "before";
    better: boolean | null;
    said: string;
  } | null;
}

export interface Verdict {
  findings: Finding[];
  edits: Edit[];
  edited: boolean;
  against: "tuned" | "before" | null;
  summary: string;
  by: string;
  key: string;
}

/** The summary as the language model set up phrased it, or why it was not. */
export interface Phrased {
  key: string;
  summary: string | null;
  model: string | null;
  cached: boolean;
  why: string | null;
}
