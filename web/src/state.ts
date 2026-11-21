// What the user has entered. Kept in the browser so a reload loses nothing.

import type { Phase, Segment, Setup } from "./api";
import { freshEntry } from "./motorentry";
import type { MotorEntry } from "./motorentry";
import { numberOr } from "./parse";

export type Tab = "proposal" | "losses" | "motion" | "limits";

/** A load set beside the one of step 4, to compare what different loads ask of one device. */
export interface LoadItem {
  id: string;
  label: string;
  loadKind: string;
  load: State["load"];
  segments: Segment[];
  phases?: Phase[] | null;
  mission?: Mission | null;
}
/** A motor kept as it was set, with the supply and design point that went with it. */
export interface MotorItem {
  id: string;
  label: string;
  motor: Record<string, string | number>;
  conditions: Record<string, number | string | null>;
}
/** Motor speed and torque against time, as measured or planned. */
export interface Mission {
  name: string;
  time: number[];
  rpm: number[];
  torque: number[];
}

/** The supply and the design point: the figures that start where the device under test belongs. */
export interface Point {
  v_dc: number;
  rpm: number;
  torque: number;
  f_khz: number;
  pwm: string;
}
export const POINT_KEYS = ["v_dc", "rpm", "torque", "f_khz", "pwm"] as const;

export interface State {
  step: number;
  reached: number; // furthest step the user has opened
  visited: number[]; // every step the user has opened: one skipped on the way is not among them
  kind: string;
  motors: Record<string, Record<string, string | number>>;
  /** How the motor's boxes show its figures: line to line or per phase, and which constant. */
  motorEntry: MotorEntry;
  conditions: {
    v_dc: number;
    rpm: number;
    torque: number;
    f_khz: number;
    t_sink: number;
    pwm: string;
    v_drive: string;
    rg_on: string;
    rg_off: string;
    t_dead_ns: string;
    l_loop_nh: string;
    parallel: number;
    t_motor: string;
    t_min_ns: string;
    cooling: "held" | "heatsink" | "none" | "board";
    t_ambient: number;
    rth_sink: string;
    rth_ja: string;
    board_area: string;
    copper: string;
    copper_ref: string;
    interface: "" | "pad";
    rth_case_sink: string; // what lies between a package and its heatsink
    sized: "" | "rth_sink" | "board_area"; // the cooling figure the tool sized, until the user edits it
    sizedFor: string; // what it was sized from: the inputs with its box empty, and the design's part
    edge_limit: EdgeLimit; // how fast an edge the tool may choose the gate resistors for
  };
  typed: Record<string, string>; // a part being typed in from its datasheet, kept until added
  typedOf: Record<string, Record<string, string>>; // each typed part's figures as added, to give one more of them
  mission: Mission | null; // a mission profile brought as a file, in place of the load and motion
  supply: "one-way" | "battery";
  load: {
    gear_ratio: number;
    gear_efficiency: number;
    motor_inertia: number;
    inertia: number;
    friction_coulomb: number;
    friction_viscous: number;
    mass: number;
    arm: number;
    start_angle_deg: number;
    constant_torque: number;
    fan_coefficient: number;
    v_mass: number;
    wheel_radius: number;
    rolling_resistance: number;
    drag_area: number;
    slope_percent: number;
    tumble_mass: number;
    tumble_radius: number;
    pulsation_torque: number;
    breakaway_torque: number;
    breakaway_rpm: number;
  };
  mapAt: "" | "motor" | "load"; // which side of the gearbox the map's axes are on; empty: the tool picks
  pwmPeriods: number; // how many switching periods the drawing under the result shows
  compare: "devices" | "loads" | "motors" | "sweep"; // what the results set side by side
  motorSet: MotorItem[]; // motors compared with the one of step 2
  sweep: { key: string; values: string }; // one setting, tried at several values
  loadSet: LoadItem[]; // loads compared with the one of step 4
  loadKind: string; // which kind of load the figures describe
  loadTouched: boolean; // the user has picked a load or edited one
  inertiaOwn: boolean; // the user typed the load's inertia: it no longer follows the weight on the arm
  loadTouchedBefore: boolean; // as it was before a mission profile was brought, to go back to
  segments: Segment[];
  /** A duty in named phases, as an application gives it: the stretches above are it written
   *  out, and editing one of them makes the motion those stretches alone. */
  phases: Phase[] | null;
  sink: { rth: string; capacity: string; t_ambient: string; c_link_uf: string; precharge: string; repeats: number };
  start: { method: string; current: string; align_time: string; handover_rpm: string; flux_time: string };
  devices: string[];
  /** The device the motor, the supply and the point started from. A device added to compare
   *  never moves the design: it is compared on it. Empty until there is a device. */
  lead: string;
  kindPicked: boolean; // the user chose the kind of motor: it no longer follows the device
  supplyOwn: boolean; // the user chose what the stage runs from: it no longer follows the device
  motorOwn: Record<string, string[]>; // for each kind of motor, the figures the user typed
  pointOf: Record<string, Partial<Point>>; // for each kind, the supply and design point figures the user typed
  loadPicked: string; // the kind of load the user picked; empty: the usual one for the motor
  added: string[]; // the parts this user brought to the page; nothing else is listed
  focus: string | null;
  focusPicked: boolean; // the user chose which device the drawing shows, and it stays theirs
  tab: Tab;
  metric: "loss" | "tj" | "efficiency";
  map: { rpm_max: string; torque_max: string };
  /** What only the switching event uses: the board's other inductances, the driver's low
   *  level, and a layout file's text with its name. Empty: assumed, and said so. */
  event: EventDetail;
}

export interface EventDetail {
  l_cs_nh: string;
  l_g_nh: string;
  v_off: string;
  layout: string;
  layout_name: string;
}

export const KEY = "motionsim.bench.v11";
/** The parts kept by the engine in the browser. */
export const DEVICES_KEY = "motionsim.devices.v1";
/** What earlier versions of the page kept, which this one no longer reads. */
export const STALE_KEYS = Array.from({ length: 10 }, (_, k) => `motionsim.bench.v${k + 1}`);

/** How fast an edge the tool may choose the gate resistors for: 5 V/ns for a motor on a
 *  cable (the usual), 20 V/ns for one close to the drive, or as fast as the part allows. */
export type EdgeLimit = "cable" | "close" | "none";
export const EDGE_LIMITS: EdgeLimit[] = ["cable", "close", "none"];

/** The supply, the design point and everything around them, as a first visit finds them. */
function freshConditions(start: Setup["motors"][string]["start"]): State["conditions"] {
  return {
    v_dc: start.v_dc,
    rpm: start.rpm,
    torque: start.torque,
    f_khz: start.f_sw / 1000,
    t_sink: 60,
    pwm: "",
    v_drive: "",
    rg_on: "",
    rg_off: "",
    t_dead_ns: "",
    l_loop_nh: "",
    parallel: 1,
    t_motor: "",
    t_min_ns: "",
    cooling: "held",
    t_ambient: 40,
    rth_sink: "",
    rth_ja: "",
    board_area: "",
    copper: "",
    copper_ref: "",
    interface: "",
    rth_case_sink: "",
    sized: "",
    sizedFor: "",
    edge_limit: "cable",
  };
}

/** The page's example load, as the figures the load step holds. */
function freshLoad(setup: Setup): State["load"] {
  const load = setup.load;
  return {
    gear_ratio: load.gear_ratio ?? 1,
    gear_efficiency: load.gear_efficiency ?? 1,
    motor_inertia: load.motor_inertia ?? 0,
    inertia: load.inertia ?? 0,
    friction_coulomb: load.friction_coulomb ?? 0,
    friction_viscous: load.friction_viscous ?? 0,
    mass: load.gravity?.mass ?? 0,
    arm: load.gravity?.arm ?? 0,
    start_angle_deg: setup.profile.start_angle_deg ?? 0,
    constant_torque: 0,
    fan_coefficient: 0,
    v_mass: 0,
    wheel_radius: 0,
    rolling_resistance: 0,
    drag_area: 0,
    slope_percent: 0,
    tumble_mass: 0,
    tumble_radius: 0,
    pulsation_torque: 0,
    breakaway_torque: 0,
    breakaway_rpm: 0,
  };
}

export function initial(setup: Setup): State {
  const kind = "pmsm";
  return {
    step: 0,
    reached: 0,
    visited: [0],
    kind,
    motors: Object.fromEntries(Object.entries(setup.motors).map(([k, m]) => [k, { ...m.values }])),
    motorEntry: freshEntry(),
    conditions: freshConditions(setup.motors[kind].start),
    typed: {},
    typedOf: {},
    mission: null,
    supply: "one-way",
    load: freshLoad(setup),
    loadKind: "",
    compare: "devices",
    motorSet: [],
    sweep: { key: "f_khz", values: "" },
    loadSet: [],
    pwmPeriods: 5,
    mapAt: "",
    loadTouched: false,
    inertiaOwn: false,
    loadTouchedBefore: false,
    segments: setup.profile.segments.map((s) => ({ ...s })),
    phases: null,
    sink: { rth: "", capacity: "", t_ambient: "", c_link_uf: "", precharge: "", repeats: 1 },
    start: { method: "sensor", current: "", align_time: "", handover_rpm: "", flux_time: "" },
    devices: [], // the user brings the part; none is chosen for them
    lead: "",
    added: [],
    kindPicked: false,
    supplyOwn: false,
    motorOwn: {},
    pointOf: {},
    loadPicked: "",
    focus: null,
    focusPicked: false,
    tab: "proposal",
    metric: "loss",
    map: { rpm_max: "", torque_max: "" },
    event: { l_cs_nh: "", l_g_nh: "", v_off: "", layout: "", layout_name: "" },
  };
}

let held = false;

/** Hold this tab's saving, or let it go on: held while the user has not yet chosen between
 *  this tab's setup and another tab's newer one. */
export function holdSaving(on: boolean): void {
  held = on;
}

/** Keep what was entered. Returns false where the browser would not take it (a private
 *  window, a full store): the page still works, it just forgets, and can say so. */
export function save(state: State): boolean {
  // While another tab's newer setup is on offer, this tab writes nothing over it.
  if (held) return true;
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
    return true;
  } catch {
    return false;
  }
}

/** A box that may be left empty: its figure in the engine's unit, or nothing. */
const number = (text: string | number, scale = 1): number | null => {
  const value = numberOr(text);
  return value === null ? null : value * scale;
};

/** The request the engine expects, in SI units. */
export function request(state: State) {
  const c = state.conditions;
  return {
    motor: {
      type: state.kind,
      ...Object.fromEntries(Object.entries(state.motors[state.kind]).filter(([, v]) => v !== "")),
      t_motor: number(c.t_motor),
    },
    conditions: {
      v_dc: c.v_dc,
      rpm: c.rpm,
      torque: c.torque,
      f_sw: c.f_khz * 1000,
      t_sink: c.t_sink,
      pwm: c.pwm || null,
      v_drive: number(c.v_drive),
      rg_on: number(c.rg_on),
      rg_off: number(c.rg_off),
      t_dead: number(c.t_dead_ns, 1e-9) ?? null,
      l_loop: number(c.l_loop_nh, 1e-9),
      t_min_pulse: number(c.t_min_ns, 1e-9) ?? 0,
      // As typed, so that 0 or 2.5 devices is refused at its box and not quietly taken as another number.
      parallel: numberOr(c.parallel, 1) ?? 1,
      edge_limit: c.edge_limit,
      cooling: c.cooling,
      t_ambient: c.t_ambient,
      rth_sink: number(c.rth_sink),
      rth_ja: number(c.rth_ja),
      board_area: number(c.board_area),
      copper: number(c.copper),
      copper_ref: number(c.copper_ref),
      interface: c.interface || null,
      rth_case_sink: number(c.rth_case_sink),
      sized: c.sized || null,
      // The design point moved after the cooling was sized: the verdict says it was sized for
      // an earlier point, and is held at a caution all the same.
      sized_earlier: sizedEarlier(state) || null,
    },
    supply: state.supply,
  };
}

/** What a cooling figure is sized from: the request with its box empty, and the part it is
 *  sized for. Two inputs with the same key are sized alike. */
export function sizingKey(state: State, figure: "rth_sink" | "board_area", device: string): string {
  const conditions = { ...state.conditions, [figure]: "", sized: "" as const, sizedFor: "" };
  return JSON.stringify({ ...request({ ...state, conditions }), device });
}

/** The cooling figure the tool sized was sized from inputs that have since moved, or for
 *  another part. A figure sized before this was kept with it is taken as sized here. */
export function sizedEarlier(state: State): boolean {
  const c = state.conditions;
  return !!c.sized && !!c.sizedFor && c.sizedFor !== sizingKey(state, c.sized, state.lead);
}

/** What a load adds as it turns, where it has it: a tumbling wash, a pulse once a turn, a
 *  break-away torque at standstill. */
function turning(l: State["load"]) {
  return {
    ...(l.tumble_mass > 0 && l.tumble_radius > 0 ? { tumble: { mass: l.tumble_mass, radius: l.tumble_radius } } : {}),
    ...(l.pulsation_torque > 0 ? { pulsation: { torque: l.pulsation_torque, per_turn: 1 } } : {}),
    ...(l.breakaway_torque > 0 && l.breakaway_rpm > 0
      ? { breakaway: { torque: l.breakaway_torque, rpm: l.breakaway_rpm } }
      : {}),
  };
}

/** A duty's phases written out as the stretches they are, each repeat in turn. */
export const writtenOut = (phases: Phase[]): Segment[] =>
  phases.flatMap((p) => Array.from({ length: p.repeat }, () => p.segments.map((s) => ({ ...s }))).flat());

export function motionRequest(state: State) {
  const l = state.load;
  const gravity = Number(l.mass) !== 0 && Number(l.arm) !== 0 ? { gravity: { mass: l.mass, arm: l.arm } } : {};
  const vehicle =
    l.v_mass > 0 && l.wheel_radius > 0
      ? {
          vehicle: {
            mass: l.v_mass,
            wheel_radius: l.wheel_radius,
            rolling_resistance: l.rolling_resistance,
            drag_area: l.drag_area,
            slope_percent: l.slope_percent,
          },
        }
      : {};
  return {
    load: {
      gear_ratio: l.gear_ratio,
      gear_efficiency: l.gear_efficiency,
      motor_inertia: l.motor_inertia,
      inertia: l.inertia,
      friction_coulomb: l.friction_coulomb,
      friction_viscous: l.friction_viscous,
      constant_torque: l.constant_torque,
      fan_coefficient: l.fan_coefficient,
      ...gravity,
      ...vehicle,
      ...turning(l),
    },
    profile: state.phases?.length
      ? { start_angle_deg: l.start_angle_deg, phases: state.phases }
      : { start_angle_deg: l.start_angle_deg, segments: state.segments },
    mission: state.mission ? { time: state.mission.time, rpm: state.mission.rpm, torque: state.mission.torque } : null,
    heatsink: {
      rth: number(state.sink.rth),
      capacity: number(state.sink.capacity),
      t_ambient: number(state.sink.t_ambient) ?? state.conditions.t_sink,
    },
    c_link: number(state.sink.c_link_uf, 1e-6),
    precharge: number(state.sink.precharge),
    start: { ...state.start },
    repeats: state.sink.repeats,
  };
}
