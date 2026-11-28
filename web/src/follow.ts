// Where the motor and the design point start. They start where the device under test
// belongs: the kind of motor it suits, that motor's example wound for the supply the device
// suits, and a point on it. The rule is one, and does not depend on the order things were
// done in: what the user typed stays as typed; everything they have not touched is the
// starting point for the device under test now.

import type { MotorKind, Setup, Suggest } from "./api";
import { fieldsOf, remagnetised } from "./motorentry";
import { POINT_KEYS } from "./state";
import type { Point, State } from "./state";

/** One figure that moved when the starting point did. */
export interface Change {
  /** Where the figure lives in the state, as its box is bound. */
  path: string;
  label: string;
  unit: string;
  from: string | number;
  to: string | number;
}

const POINT_LABELS: Record<keyof Point, [string, string]> = {
  v_dc: ["Supply voltage", "V"],
  rpm: ["Speed", "rpm"],
  torque: ["Torque", "N·m"],
  f_khz: ["Switching frequency", "kHz"],
  pwm: ["Modulation", ""],
};

/** What the stage runs from, in the words of the supply's own choice. */
const SUPPLY: Record<State["supply"], string> = { "one-way": "Power supply", battery: "Battery", mains: "Mains" };

/** The point a kind of motor starts at for this device; without one, the page's own example. */
function startOf(kind: string, setup: Setup, suggest: Suggest | null): Point {
  const start = suggest?.motors[kind]?.start ?? setup.motors[kind].start;
  return { v_dc: start.v_dc, rpm: start.rpm, torque: start.torque, f_khz: start.f_sw / 1000, pwm: "" };
}

/** Each kind of motor's figures: the example for this device, with the user's own laid over. */
function settleMotors(state: State, setup: Setup, suggest: Suggest | null, changes: Change[]): void {
  for (const [kind, spec] of Object.entries(setup.motors)) {
    const example = { ...spec.values, ...suggest?.motors[kind]?.values };
    state.motors[kind] = settledMotor(state, kind, example, kind === state.kind ? spec : null, changes);
  }
}

/** Whether a motor is asked for a figure, as its magnets have it: one inductance, or the two axes'. */
const askedFor = (kind: string, key: string, now: Record<string, string | number>): boolean =>
  key !== "l" || fieldsOf(kind, [{ key, label: "", help: "" }], now).some((f) => f.key === key);

/** One kind of motor's figures moved to its example where the user has not typed their own.
 *  `shown`: the kind on the page, whose figures that move are said; null for any other. */
function settledMotor(
  state: State,
  kind: string,
  example: Record<string, string | number>,
  shown: MotorKind | null,
  changes: Change[],
): Record<string, string | number> {
  const own = new Set(state.motorOwn[kind] ?? []);
  const now = state.motors[kind] ?? {};
  const next = { ...now };
  for (const [key, value] of Object.entries(example)) {
    if (key === "type" || own.has(key) || now[key] === value || !askedFor(kind, key, now)) continue;
    next[key] = value;
    const field = shown && [...shown.fields, ...(shown.optional ?? [])].find((f) => f.key === key);
    if (!field) continue;
    const change = { path: `motors.${kind}.${key}`, label: field.label ?? key, unit: field.unit ?? "" };
    changes.push({ ...change, from: now[key] ?? "", to: value });
  }
  return next.magnets === undefined ? next : remagnetised(next, String(next.magnets));
}

/** The link's voltage is no longer a front end's to hold: the figure it held is let go, for
 *  every kind of motor, so the supply's voltage is the part's own start again. */
/** What one phase of a mains usually gives, W: 16 A at 230 V. A drive over it is fed from three. */
export const ONE_PHASE_MOST = 3700;

/** The design point's shaft power, W. */
export const shaftPower = (state: State): number =>
  ((Number(state.conditions.rpm) || 0) * Math.PI * (Number(state.conditions.torque) || 0)) / 30;

/** The usual voltage of a mains, one phase against three (line to line), where each is found. */
const USUAL_MAINS: [string, string][] = [
  ["230", "400"],
  ["120", "208"],
];

/** The usual voltage of the other count of phases, for a usual one; a figure of the user's own is kept. */
export function usualMains(state: State): void {
  const c = state.conditions;
  const three = c.mains_phases === "3";
  const pair = USUAL_MAINS.find((u) => u[three ? 0 : 1] === c.mains_v.trim());
  if (pair) c.mains_v = pair[three ? 1 : 0];
}

/** The drive is put on the mains: a point over what one phase gives starts on three phases,
 *  where the mains is still the usual one phase the page opens on. Returns whether it moved. */
export function ontoMains(state: State): boolean {
  const c = state.conditions;
  if (c.mains_phases !== "1" || shaftPower(state) <= ONE_PHASE_MOST) return false;
  if (!USUAL_MAINS.some((u) => u[0] === c.mains_v.trim())) return false;
  c.mains_phases = "3";
  usualMains(state);
  return true;
}

export function offTheLink(state: State): void {
  state.conditions.link_own = "";
  state.pointOf = Object.fromEntries(
    Object.entries(state.pointOf).map(([kind, typed]) => [
      kind,
      Object.fromEntries(Object.entries(typed).filter(([key]) => key !== "v_dc")),
    ]),
  );
}

/** A part that cannot stand the link a mains makes (the mains' crest is above the supply the
 *  part suits) is not left on the mains another part was put on: the supply goes back to what
 *  this part runs from, and the link's voltage with it. Returns what moved, to be said. */
export function leaveMains(state: State, suggest: Suggest | null): Change | null {
  if (state.supply !== "mains" || !suggest) return null;
  const crest = Math.SQRT2 * (Number(state.conditions.mains_v) || 230);
  if (suggest.v_supply >= crest) return null;
  const back = suggest.application?.supply ?? "one-way";
  state.supply = back;
  state.supplyOwn = false;
  offTheLink(state);
  return { path: "supply", label: "Supply", unit: "", from: SUPPLY.mains, to: SUPPLY[back] };
}

/** The figures of the point that follow the part. On the mains the link's voltage is the front
 *  end's to hold, unless the user typed one: it is left out. */
const pointKeys = (state: State): (keyof Point)[] =>
  state.supply === "mains" && !state.conditions.link_own ? POINT_KEYS.filter((k) => k !== "v_dc") : [...POINT_KEYS];

/**
 * Put every figure the user has not typed where the device under test starts it, and say
 * what moved. `suggest`: what suits the device under test; null when there is none, and the
 * page's own examples are the starting point.
 */
export function settle(state: State, setup: Setup, suggest: Suggest | null): Change[] {
  const changes: Change[] = [];
  if (!state.kindPicked && suggest) {
    const kinds = Object.keys(suggest.motors).filter((k) => setup.motors[k]);
    const recommended = kinds.find((k) => suggest.motors[k].fit === "recommended");
    if (recommended && recommended !== state.kind) {
      const label = (k: string) => setup.motors[k].label;
      changes.push({ path: "kind", label: "Kind of motor", unit: "", from: label(state.kind), to: label(recommended) });
      state.kind = recommended;
    }
  }
  const supply = suggest?.application?.supply;
  if (supply && !state.supplyOwn && state.supply !== supply) {
    changes.push({ path: "supply", label: "Supply", unit: "", from: SUPPLY[state.supply], to: SUPPLY[supply] });
    state.supply = supply;
  }
  settleMotors(state, setup, suggest, changes);
  const point = { ...startOf(state.kind, setup, suggest), ...state.pointOf[state.kind] };
  for (const key of pointKeys(state)) {
    const from = state.conditions[key];
    const to = point[key];
    if (from === to) continue;
    (state.conditions as Record<string, unknown>)[key] = to;
    const [label, unit] = POINT_LABELS[key];
    // The modulation going back to the usual one for the motor is said by its box.
    if (key !== "pwm") changes.push({ path: `conditions.${key}`, label, unit, from, to });
  }
  return changes;
}

/** A figure put back where it was before the starting point moved: it is the user's own
 *  from then on, and stays. */
export function putBack(state: State, setup: Setup, change: Change): void {
  const [group, kind, key] = change.path.split(".");
  if (group === "kind") {
    const was = Object.keys(setup.motors).find((k) => setup.motors[k].label === change.from);
    if (was) state.kind = was;
    state.kindPicked = true;
  } else if (group === "motors") {
    state.motors[kind][key] = change.from;
    state.motorOwn[kind] = [...new Set([...(state.motorOwn[kind] ?? []), key])];
  } else if (group === "supply") {
    state.supply = change.from === SUPPLY.battery ? "battery" : change.from === SUPPLY.mains ? "mains" : "one-way";
    state.supplyOwn = true;
  } else if (group === "conditions") {
    own(state, kind as keyof Point, change.from);
  }
}

/** A figure of the supply or the point the user typed: theirs for this kind of motor. */
function own(state: State, key: keyof Point, value: string | number): void {
  (state.conditions as Record<string, unknown>)[key] = value;
  state.pointOf = { ...state.pointOf, [state.kind]: { ...state.pointOf[state.kind], [key]: value } };
}
