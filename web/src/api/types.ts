// The shapes of what the engine answers, as the page reads them.

import type { DutyAnswer, PresetDuty, Segment } from "./duty";
export type { Phase, Segment } from "./duty";

/** undecided: what the data leaves out could change the answer; neither a pass nor a fail. */
export type Level = "ok" | "caution" | "undecided" | "fail";
export interface Check {
  level: Level;
  topic: string;
  message: string;
  /** The box whose figure the check is about, where it is about one: a figure the tool took
   *  for one left empty, or a cooling it sized. */
  field?: string;
  /** The part the check was made of, put on by the page where the check names a box. */
  device?: string;
}
export interface Field {
  key: string;
  label: string;
  unit: string;
  help: string;
  options: string[] | null;
  required?: boolean;
}
export interface MotorKind {
  family: string;
  label: string;
  about: string;
  start: Record<string, number>;
  values: Record<string, string | number>;
  fields: Field[];
  fixed_scheme: string | null;
  default_pwm: string;
  optional: { key: string; label: string; unit: string; help: string }[];
}
export interface DeviceSummary {
  id: string;
  name: string;
  technology: string;
  v_max: number;
  i_nominal: number;
  tj_max: number;
  positions: number;
  integrated_driver: boolean;
  example: boolean;
  /** A made-up part's application in a few words; null for any other part. */
  use?: string | null;
  switching: string;
  support: string;
  needs_gate_drive: boolean;
}
export interface Setup {
  motors: Record<string, MotorKind>;
  pwm: string[];
  load: LoadFigures;
  profile: { name?: string; start_angle_deg?: number; segments: Segment[] };
  devices: DeviceSummary[];
  can_read: boolean;
  typed: {
    technologies: string[];
    outlines: string[];
    fields: TypedFigure[];
    /** An IGBT and its diode: its technology, how many sit in its package, and its figures. */
    igbt?: { technology: string; topologies: string[]; fields: TypedFigure[] };
  };
}
/** The cooling figure the tool works out for a cooling chosen with its figure left empty:
 *  the heatsink that holds itself at `held` °C, or the smallest board that keeps the junction
 *  under `tj_max`. value is null where there is none to offer, and `why` says why. */
export interface CoolingOffer {
  cooling: "heatsink" | "board";
  figure: "rth_sink" | "board_area";
  value: number | null;
  why?: string;
  held?: number;
  tj_max?: number;
}
/** One figure of a part typed in. main: shown with the figures needed, though it may be left
 *  empty, since the tool then takes a figure for it and says so. */
export interface TypedFigure {
  key: string;
  label: string;
  unit: string;
  required: boolean;
  help: string;
  main?: boolean;
  /** The range the engine holds the figure to, in the unit it is typed in. */
  low?: number;
  high?: number;
}

export interface Role {
  name: string;
  count: number;
  forward: number;
  reverse: number;
  switching: number;
}
export interface Stage {
  positions: number;
  i_peak: number;
  p_shaft: number;
  p_electrical: number;
  p_motor_loss: number;
  scheme: string;
  summary: { label: string; value: number; unit: string }[];
  notes: string[];
  roles: Role[];
}
export interface Advice {
  lines: string[];
  v_minimum: number;
  v_comfortable: number;
  i_peak: number;
  i_stall: number | null;
}
export interface Losses {
  conduction: number;
  turn_on: number;
  turn_off: number;
  dead_time: number;
  recovery: number;
  diode_conduction: number;
  diode_recovery: number;
  total: number;
}
export interface Position extends Losses {
  name: string;
  count: number;
  tj: number;
  tj_switch: number;
  tj_diode: number;
  tj_switch_mean: number;
  tj_diode_mean: number;
}
export interface Result {
  loss: number;
  conduction: number;
  switching: number;
  efficiency: number | null;
  tj_peak: number;
  tj_range: [number, number] | null;
  range_lead?: string | null;
  tj_max: number;
  t_case: number;
  t_sink?: number | null;
  validity: string;
  notes: string[];
  limits: string[];
  assumptions: string[];
  warnings: string[];
  hottest: Losses;
  positions: Position[];
}
export interface GateUsed {
  kind: "chosen" | "given" | "datasheet" | "built in";
  v_drive: number | null;
  rg_on: number | null;
  rg_off: number | null;
  lines: string[];
  t_dead?: number | null;
}
/** One PWM period of the hottest switch at the instant it works hardest. */
export interface SwitchingPeriod {
  current: number;
  duty: number;
  p_on: number;
  e_on: number;
  e_off: number;
  f_sw: number;
  position: string;
}
export interface Candidate {
  gate: GateUsed;
  pwm: SwitchingPeriod | null;
  link: { capacitor_rms: number | null; ripple_pp: number | null } | null;
  id: string;
  name: string;
  technology: string;
  level: Level;
  problem: string | null;
  fix: string;
  result: Result | null;
  stall_tj: number | null;
  efficiency: number | null;
  checks: Check[];
  needs: string[];
  /** °C left to the junction limit, at the design point and holding the torque at standstill. */
  margin: number | null;
  stall_margin: number | null;
  /** What the switching loss rests on, so that two devices can be seen to be like for like. */
  switching: { kind: "measured" | "from times" | "from charge" | "none"; text: string } | null;
}
/** level: losses closer than this share of the lowest are not told apart. */
export interface Proposal {
  candidates: Candidate[];
  explain: string[];
  level: number;
}
export interface Cycle extends DutyAnswer {
  time: number[];
  tj: (number | null)[];
  steady: (number | null)[];
  t_sink: number[];
  sink_name?: string;
  rpm: number[];
  torque: number[];
  p_stage: (number | null)[];
  p_dc: (number | null)[];
  summary: Record<string, number | null>;
  checks: Check[];
  i_peak: (number | null)[];
  life: {
    repeats: number | null;
    hours: number | null;
    swing: number;
    swing_mean: number;
    swing_share: number;
    swings: number;
    chip: string;
    within_turn: boolean;
    /** The swings the life model was fitted to, K, and whether this one is outside them. */
    fitted?: [number, number];
    extrapolated?: boolean;
  };
  start: {
    applies: "method" | "flux" | "none";
    method: string;
    current?: number;
    align_time?: number;
    handover_rpm?: number;
    flux_time?: number;
    lines: string[];
  };
  inrush: { energy: number; peak: number | null; time: number | null } | null;
}
export interface MapGrid {
  rpm: number[];
  torque: number[];
  loss: (number | null)[][];
  tj: (number | null)[][];
  efficiency: (number | null)[][];
  reason: string[][];
  tj_max: number;
}
export interface Recommendation {
  topic: string;
  value: Record<string, number>;
  lines: string[];
}
export interface ReadOutcome {
  device: DeviceSummary;
  read: {
    values: number;
    curves: number;
    from_images?: number;
    flagged: { what: string; page: number; why: string }[];
  };
}

/** What a device can hold at a point: the torque, what stops it, and where it is then. */
export interface LimitRow {
  torque: number;
  why: string;
  tj: number | null;
  current: number | null;
}
export interface Capability {
  rpm: number[];
  edge: LimitRow[];
  design: LimitRow & { rpm: number; share: number | null; power: number; rated: number };
  f_sw: number[];
  by_f_sw: LimitRow[];
  t_sink: number[];
  by_t_sink: LimitRow[];
}
export interface Largest {
  scale: number;
  open: boolean;
  why: string;
  peak: number | null;
  tj_max: number | null;
}
/** One probe of the search for the largest load, as it finishes: the scale tried, whether
 *  every check passed there, what failed, the hottest junction where the motion was followed,
 *  and the bounds the answer lies between once it is counted. `full`: the answer worked out
 *  again in full, the last probe. */
export interface Probe {
  scale: number;
  passes: boolean;
  full: boolean;
  why: string;
  peak: number | null;
  tj_max: number | null;
  low: number;
  high: number;
  /** In the search for the proposed load: the limit a load that does not pass ran into. */
  limit?: string;
}

/** What a proposed load asks of the motor and the part, read from its motion. */
export interface ProposedFigures {
  peak_torque: number;
  rms_torque: number;
  top_rpm: number;
  i_peak: number | null;
  tj_peak: number;
  tj_top: number;
  tj_max: number;
  points: { name: string; rpm: number; torque: number }[];
}

/** The load the part under test can carry: the application's own load made as heavy as it
 *  can be with every check of the motion passing and the junction a margin under its rating,
 *  what stops it going further, and the figures. */
export interface LoadProposal {
  application: string;
  label: string;
  /** Times the usual load of the application, sized to the design point. */
  scale: number;
  /** Still passing at the heaviest tried: something other than this drive limits it. */
  open: boolean;
  preset: LoadPreset;
  binding: { limit: string; words: string; check: string; level: string; scale: number | null };
  margin: { wanted: number; junction: number };
  figures: ProposedFigures;
  usual: ProposedFigures | null;
  checks: Check[];
  why: string;
}

/** A load as the engine takes it: what turns, what rubs, and what gravity or a road adds. */
export interface LoadFigures {
  gear_ratio?: number;
  gear_efficiency?: number;
  motor_inertia?: number;
  inertia?: number;
  friction_coulomb?: number;
  friction_viscous?: number;
  constant_torque?: number;
  fan_coefficient?: number;
  gravity?: { mass: number; arm: number } | null;
  tumble?: { mass: number; radius: number } | null;
  pulsation?: { torque: number; per_turn: number } | null;
  breakaway?: { torque: number; rpm: number } | null;
  vehicle?: {
    mass: number;
    wheel_radius: number;
    rolling_resistance: number;
    drag_area: number;
    slope_percent: number;
  } | null;
}

/** A kind of load a motor usually drives, sized from the motor's design point. */
export interface LoadPreset extends PresetDuty {
  id: string;
  label: string;
  about: string;
  link: string;
  fields: string[];
  start_angle_deg: number;
  load: LoadFigures;
  segments: Segment[];
}

/** For a device: the supply it suits, and how each kind of motor fits it. */
export interface Suggest {
  v_supply: number;
  /** A made-up part's application: the load it opens on, how such products start their
   *  motor, and what they run from. Null for any other part. */
  application?: { id: string; label: string; start: string; supply: "one-way" | "battery"; swings?: boolean } | null;
  /** Why the part starts on the kind it does: its rating and the drives of its class. */
  why?: string;
  motors: Record<
    string,
    {
      fit: "recommended" | "suits" | "unusual";
      why: string;
      values: Record<string, string | number>;
      start: { v_dc: number; rpm: number; torque: number; f_sw: number };
    }
  >;
}

/** One table of a device model: a value against current, one curve a temperature. */
export interface ModelTable {
  unit: string;
  basis: string;
  assumption: string | null;
  source: string | null;
  page: number | null;
  curves: { tj: number; x: number[]; y: number[] }[];
}
/** A device model's tables, and what the reader took from the datasheet it came from. */
export interface Reading {
  summary: DeviceSummary;
  /** The device file the model is, for a setup saved from the page to carry. */
  file?: { name: string; text: string };
  conduction: ModelTable | null;
  e_on: ModelTable | null;
  e_off: ModelTable | null;
  reverse: ModelTable | null;
  diode: ModelTable | null;
  e_rr: ModelTable | null;
  reading: {
    document: string;
    pages: number;
    from_images: number;
    values: { what: string; printed: string; at: string; page: number; flags: string[] }[];
    figures: {
      what: string;
      label: string;
      page: number;
      tj: number | null;
      points: number;
      flags: string[];
      notes: string[];
      within: number | null;
      method: string;
    }[];
  } | null;
}

/** A part the engine in the browser was given, kept so that the next visit has it too: the
 *  request that made it, to be made again in the order the parts were brought. */
export interface KeptPart {
  id: string;
  route: "/api/device" | "/api/measure";
  body: Record<string, string>;
}

/** One edge of a switching event through time, in SI units: the gate, the device's voltage,
 *  its current and the power it loses, then what is read from them as a double-pulse test
 *  reads them. `factor` is the free factor that makes the edge lose the loss model's energy. */
export interface EventEdge {
  t: number[];
  v_gs: number[];
  v_ds: number[];
  i: number[];
  p: number[];
  energy: number;
  target: number;
  met: boolean;
  factor: number;
  /** On the reverse path's stored charge at turn-on, the second figure moved to meet the energy. */
  recovery: number;
  /** A figure was moved more than a factor of two: the energy is the datasheet's, the shape indicative. */
  corrected: boolean;
  tail: number | null;
  di_dt: number | null;
  dv_dt: number | null;
  t_rise: number | null;
  t_fall: number | null;
  t_delay: number | null;
  i_peak: number;
  v_peak: number;
  ring: number | null;
  window: [number, number] | null;
}

/** The model's switching times beside the datasheet's, at the datasheet's own test. */
export interface EventDatasheet {
  v_test: number;
  i_test: number;
  rg_test: number;
  rows: { what: string; model: number; datasheet: number; error: number }[];
  assumed: string[];
}

/** A feature that sets this kind of switch apart, named where it is on its trace. */
export interface EventFeature {
  edge: "on" | "off";
  trace: "v_ds" | "i" | "v_gs" | "p";
  t: number;
  value: number;
  label: string;
  caution: boolean;
}

/** What sets the kind of switch apart in its event, and the plain line that says it. */
export interface EventSignature {
  kind: "si" | "sic" | "gan" | "igbt" | "hybrid";
  line: string;
  features: EventFeature[];
  third_quadrant: number;
  tail_share: number;
}

/** One switching event of the switch the loss chart draws: its turn-on and its turn-off, and
 *  every figure it rests on that was assumed, by the name of the figure that replaces it. */
export interface SwitchingEvent {
  name: string;
  position: string;
  kind: string;
  technology: string;
  v_dc: number;
  current: number;
  tj: number;
  v_max: number;
  turn_on: EventEdge;
  turn_off: EventEdge;
  assumed: { field: string; text: string }[];
  used: Record<string, number>;
  notes: string[];
  /** Where the edge limit is what slows the part, said once above the edges. */
  held?: string | null;
  signature: EventSignature;
  datasheet: EventDatasheet | null;
}
