// What the user has entered. Kept in the browser so a reload loses nothing.

import type { Segment, Setup } from "./api";

export type Tab = "proposal" | "losses" | "motion" | "map" | "settings";

/** A load set beside the one of step 4, to compare what different loads ask of one device. */
export interface LoadItem { id: string; label: string; loadKind: string; load: State["load"]; segments: Segment[]; mission?: Mission | null }
/** Motor speed and torque against time, as measured or planned. */
export interface Mission { name: string; time: number[]; rpm: number[]; torque: number[] }

export interface State {
  step: number;
  reached: number; // furthest step the user has opened
  kind: string;
  motors: Record<string, Record<string, string | number>>;
  conditions: {
    v_dc: number; rpm: number; torque: number; f_khz: number; t_sink: number; pwm: string;
    v_drive: string; rg_on: string; rg_off: string; t_dead_ns: string; l_loop_nh: string;
    parallel: number;
  };
  mission: Mission | null; // a mission profile brought as a file, in place of the load and motion
  supply: "one-way" | "battery";
  load: {
    gear_ratio: number; gear_efficiency: number; motor_inertia: number; inertia: number;
    friction_coulomb: number; friction_viscous: number; mass: number; arm: number; start_angle_deg: number;
    constant_torque: number; fan_coefficient: number;
    v_mass: number; wheel_radius: number; rolling_resistance: number; drag_area: number; slope_percent: number;
  };
  mapAt: "" | "motor" | "load"; // which side of the gearbox the map's axes are on; empty: the tool picks
  pwmPeriods: number; // how many switching periods the drawing under the result shows
  compare: "devices" | "loads"; // what the results set side by side
  loadSet: LoadItem[]; // loads compared with the one of step 4
  loadKind: string; // which kind of load the figures describe
  loadTouched: boolean; // the user has picked a load or edited one
  segments: Segment[];
  sink: { rth: string; capacity: string; t_ambient: string; c_link_uf: string; precharge: string; repeats: number };
  start: { method: string; current: string; align_time: string; handover_rpm: string; flux_time: string };
  devices: string[];
  motorTouched: boolean; // the user has picked or edited the motor or the conditions
  added: string[]; // the parts this user brought to the page; nothing else is listed
  focus: string | null;
  tab: Tab;
  metric: "loss" | "tj" | "efficiency";
  map: { rpm_max: string; torque_max: string };
}

const KEY = "motionsim.bench.v9";

export function initial(setup: Setup): State {
  const kind = "pmsm";
  const start = setup.motors[kind].start;
  const load = setup.load as Record<string, any>;
  return {
    step: 0,
    reached: 0,
    kind,
    motors: Object.fromEntries(Object.entries(setup.motors).map(([k, m]) => [k, { ...m.values }])),
    conditions: {
      v_dc: start.v_dc, rpm: start.rpm, torque: start.torque, f_khz: start.f_sw / 1000, t_sink: 60, pwm: "",
      v_drive: "", rg_on: "", rg_off: "", t_dead_ns: "", l_loop_nh: "",
      parallel: 1,
    },
    mission: null,
    supply: "one-way",
    load: {
      gear_ratio: load.gear_ratio ?? 1, gear_efficiency: load.gear_efficiency ?? 1,
      motor_inertia: load.motor_inertia ?? 0, inertia: load.inertia ?? 0,
      friction_coulomb: load.friction_coulomb ?? 0, friction_viscous: load.friction_viscous ?? 0,
      mass: load.gravity?.mass ?? 0, arm: load.gravity?.arm ?? 0,
      start_angle_deg: setup.profile.start_angle_deg ?? 0,
      constant_torque: 0, fan_coefficient: 0,
      v_mass: 0, wheel_radius: 0, rolling_resistance: 0, drag_area: 0, slope_percent: 0,
    },
    loadKind: "",
    compare: "devices",
    loadSet: [],
    pwmPeriods: 5,
    mapAt: "",
    loadTouched: false,
    segments: setup.profile.segments.map((s) => ({ ...s })),
    sink: { rth: "", capacity: "", t_ambient: "", c_link_uf: "", precharge: "", repeats: 1 },
    start: { method: "sensor", current: "", align_time: "", handover_rpm: "", flux_time: "" },
    devices: [], // the user brings the part; none is chosen for them
    added: [],
    motorTouched: false,
    focus: null,
    tab: "proposal",
    metric: "loss",
    map: { rpm_max: "", torque_max: "" },
  };
}

/** `keepDevices`: the list of devices is not final yet, so the saved choice is kept as it is. */
export function restore(setup: Setup, keepDevices = false): State {
  const fresh = initial(setup);
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null") as State | null;
    if (!saved || !setup.motors[saved.kind]) return fresh;
    const known = new Set(setup.devices.map((d) => d.id));
    return {
      ...fresh, ...saved,
      motors: { ...fresh.motors, ...saved.motors },
      conditions: { ...fresh.conditions, ...saved.conditions },
      load: { ...fresh.load, ...saved.load },
      sink: { ...fresh.sink, ...saved.sink },
      start: { ...fresh.start, ...saved.start },
      map: { ...fresh.map, ...saved.map },
      devices: keepDevices ? saved.devices : saved.devices.filter((d) => known.has(d)),
      added: keepDevices ? saved.added ?? [] : (saved.added ?? []).filter((d) => known.has(d)),
      focus: saved.focus && (keepDevices || known.has(saved.focus)) ? saved.focus : null,
    };
  } catch {
    return fresh;
  }
}

export function save(state: State): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* a private window: the page still works, it just forgets */
  }
}

const number = (text: string, scale = 1): number | null => (text === "" || text === null ? null : Number(text) * scale);

/** The request the engine expects, in SI units. */
export function request(state: State) {
  const c = state.conditions;
  return {
    motor: { type: state.kind, ...state.motors[state.kind] },
    conditions: {
      v_dc: c.v_dc, rpm: c.rpm, torque: c.torque, f_sw: c.f_khz * 1000, t_sink: c.t_sink,
      pwm: c.pwm || null, v_drive: number(c.v_drive), rg_on: number(c.rg_on), rg_off: number(c.rg_off),
      t_dead: number(c.t_dead_ns, 1e-9) ?? 0, l_loop: number(c.l_loop_nh, 1e-9),
      parallel: Math.max(1, Math.round(Number(c.parallel) || 1)),
    },
    supply: state.supply,
  };
}

export function motionRequest(state: State) {
  const l = state.load;
  const gravity = l.mass > 0 && l.arm > 0 ? { gravity: { mass: l.mass, arm: l.arm } } : {};
  const vehicle = l.v_mass > 0 && l.wheel_radius > 0
    ? { vehicle: { mass: l.v_mass, wheel_radius: l.wheel_radius, rolling_resistance: l.rolling_resistance, drag_area: l.drag_area, slope_percent: l.slope_percent } }
    : {};
  return {
    load: {
      gear_ratio: l.gear_ratio, gear_efficiency: l.gear_efficiency, motor_inertia: l.motor_inertia,
      inertia: l.inertia, friction_coulomb: l.friction_coulomb, friction_viscous: l.friction_viscous,
      constant_torque: l.constant_torque, fan_coefficient: l.fan_coefficient, ...gravity, ...vehicle,
    },
    profile: { start_angle_deg: l.start_angle_deg, segments: state.segments },
    mission: state.mission ? { time: state.mission.time, rpm: state.mission.rpm, torque: state.mission.torque } : null,
    heatsink: { rth: number(state.sink.rth), capacity: number(state.sink.capacity), t_ambient: number(state.sink.t_ambient) ?? state.conditions.t_sink },
    c_link: number(state.sink.c_link_uf, 1e-6),
    precharge: number(state.sink.precharge),
    start: { ...state.start },
    repeats: state.sink.repeats,
  };
}
