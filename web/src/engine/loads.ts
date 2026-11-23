// The loads a motor usually drives, sized from its design point, and the load of step 4.

import { api } from "../api";
import type { LoadFigures, LoadPreset, Phase, Segment } from "../api";
import { latest, once } from "../guard";
import { save, writtenOut } from "../state";
import type { LoadItem, State } from "../state";
import { LOAD, RESULTS } from "../steps";
import { app, draw, invalidate, res, underTest } from "../store";
import { deep } from "./deep";

/** The gearbox, inertia and friction of a preset, with what it leaves out at its plain value. */
const driveOf = (l: LoadFigures) => ({
  gear_ratio: l.gear_ratio ?? 1,
  gear_efficiency: l.gear_efficiency ?? 1,
  motor_inertia: l.motor_inertia ?? 0,
  inertia: l.inertia ?? 0,
  friction_coulomb: l.friction_coulomb ?? 0,
  friction_viscous: l.friction_viscous ?? 0,
});

/** A vehicle's figures in a preset, all nought for a preset that is no vehicle. */
const vehicleOf = (v: LoadFigures["vehicle"]) => ({
  v_mass: v?.mass ?? 0,
  wheel_radius: v?.wheel_radius ?? 0,
  rolling_resistance: v?.rolling_resistance ?? 0,
  drag_area: v?.drag_area ?? 0,
  slope_percent: v?.slope_percent ?? 0,
});

/** A preset as the figures the page holds for a load. */
function figuresOf(p: LoadPreset): State["load"] {
  const l = p.load;
  return {
    ...driveOf(l),
    mass: l.gravity?.mass ?? 0,
    arm: l.gravity?.arm ?? 0,
    start_angle_deg: p.start_angle_deg ?? 0,
    constant_torque: l.constant_torque ?? 0,
    fan_coefficient: l.fan_coefficient ?? 0,
    ...vehicleOf(l.vehicle),
    ...turningOf(l),
  };
}

/** What a preset's load adds as it turns, all nought where it adds nothing. */
const turningOf = (l: LoadFigures) => ({
  tumble_mass: l.tumble?.mass ?? 0,
  tumble_radius: l.tumble?.radius ?? 0,
  pulsation_torque: l.pulsation?.torque ?? 0,
  breakaway_torque: l.breakaway?.torque ?? 0,
  breakaway_rpm: l.breakaway?.rpm ?? 0,
});

/** A preset's motion as the page holds it: its phases where it is a duty, and the stretches
 *  they come to, written out. */
const motionOf = (p: LoadPreset): { segments: Segment[]; phases: Phase[] | null } => {
  const phases = p.phases?.length ? p.phases.map((x) => ({ ...x, segments: x.segments.map((s) => ({ ...s })) })) : null;
  return { segments: phases ? writtenOut(phases) : p.segments.map((s) => ({ ...s })), phases };
};

/** A preset as a load set beside the one of step 4. */
export const itemOf = (p: LoadPreset): LoadItem => ({
  id: p.id,
  label: p.label,
  loadKind: p.id,
  load: figuresOf(p),
  ...motionOf(p),
});

/** Make a preset the load of step 4. */
export function applyPreset(p: LoadPreset): void {
  const { state } = app;
  state.load = figuresOf(p);
  state.inertiaOwn = false;
  const { segments, phases } = motionOf(p);
  state.segments = segments;
  state.phases = phases;
  state.loadKind = p.id;
  res.cycle = null;
  save(state);
}

/** The load of step 4 while the user has not put in figures of their own: the kind they
 *  picked where this motor is offered it, else the usual one for the motor. It depends on
 *  the motor and on the pick alone, never on which motors were looked at on the way. */
export const loadFor = (list: LoadPreset[], picked: string, suggested = ""): LoadPreset | undefined =>
  list.find((p) => p.id === picked) ?? list.find((p) => p.id === suggested) ?? list[0];

/** The application each device is tried on, as the engine said it: kept by device, so that the
 *  loads are never sized for a part before what suits it is known. */
const applications = new Map<string, string>();

/** The application the device under test is tried on, where it is a made-up part with one. */
const suggestedLoad = (): string => {
  const id = underTest();
  if (!id) return "";
  if (res.suggestion?.id === id) return res.suggestion.data?.application?.id ?? "";
  return applications.get(id) ?? "";
};

/** Wait until what suits the device under test is known (the question is asked once, and
 *  shared with whoever else asks it). Loads sized before it would be the motor's usual ones,
 *  put in place of the application's and kept: a reload would then change the load. */
async function applicationKnown(): Promise<void> {
  const id = underTest();
  if (!id || applications.has(id) || res.suggestion?.id === id) return;
  try {
    const data = await once(`suggest:${id}`, () => api.suggest(id));
    applications.set(id, data?.application?.id ?? "");
  } catch {
    // Nothing is known of what suits it: the usual load stands.
  }
}

/** What the loads were asked and sized for: the motor, its design point, and the application
 *  the part under test is tried on. Loads that landed before that application was known are
 *  sized again once it is, or the usual load would stand in the application's place. */
const presetKey = (): string => {
  const { kind, conditions: c, motors } = app.state;
  return `${kind}|${c.rpm}|${c.torque}|${c.v_dc}|${JSON.stringify(motors[kind] ?? {})}|${suggestedLoad()}`;
};

/** The loads are sized from the design point, so when that moves they are sized again:
 *  the load of step 4, unless the user has put in figures of their own, and the ones set
 *  beside it to compare. A load not offered for this motor gives way to the usual one. */
function sizeLoads(fresh: LoadPreset[]): void {
  const { state } = app;
  const mine = loadFor(fresh, state.loadPicked, suggestedLoad());
  if (!state.loadTouched && mine) applyPreset(mine);
  state.loadSet = state.loadSet.flatMap((item) => {
    if (item.id.startsWith("own-")) return [item];
    if (!state.loadTouched && item.id === state.loadKind) return []; // it is the load of step 4 now
    const now = fresh.find((p) => p.id === item.id);
    return now ? [itemOf(now)] : [];
  });
  invalidate("motion"); // the motion followed so far was of the load as it stood before it was sized
  save(state);
}

/** Fetch the loads usual for this motor at this design point. Until the user has picked or
 *  edited a load, the most usual one is theirs to start from. Asked once for a design
 *  point: an engine that fails is not asked again until something changes or the user
 *  comes back to the step. */
export async function presetsFor(): Promise<void> {
  const { state } = app;
  const c = state.conditions;
  const asked = latest("presets");
  await applicationKnown();
  if (!asked()) return; // asked again since, for the page as it is now
  const key = presetKey();
  if (res.presets?.key === key) return;
  const current = latest("presets");
  let list: LoadPreset[];
  try {
    // The motor goes too, so that an application of a size of its own says whether it can run it.
    const motor = state.motors[state.kind];
    list = (await once(`loads:${key}`, () => api.loads(state.kind, c.rpm, c.torque, c.v_dc, motor))).loads;
  } catch {
    return; // a design point that cannot be worked out: the step says so itself
  }
  if (!current()) return;
  // The motor or its design point moved while the loads were on their way (its figures fitted
  // to the supply as the step opened): they are asked for again for the motor as it is now,
  // or the step would wait for them for ever.
  if (key !== presetKey()) return presetsFor();
  res.presets = { key, list };
  sizeLoads(list);
  if (state.step === LOAD) {
    draw.panel(true);
    draw.preview();
  }
  if (state.step === RESULTS) {
    draw.panel(true);
    draw.stage();
    void deep();
  }
}
