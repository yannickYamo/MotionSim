// Where the motor and the design point start. They start where the device under test
// belongs: the kind of motor it suits, that motor's example wound for the supply the device
// suits, and a point on it. The rule is one, and does not depend on the order things were
// done in: what the user typed stays as typed; everything they have not touched is the
// starting point for the device under test now.

import type { MotorKind, Setup, Suggest } from "./api";
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
    if (key === "type" || own.has(key) || now[key] === value) continue;
    next[key] = value;
    const field = shown && [...shown.fields, ...(shown.optional ?? [])].find((f) => f.key === key);
    if (!field) continue;
    const change = { path: `motors.${kind}.${key}`, label: field.label ?? key, unit: field.unit ?? "" };
    changes.push({ ...change, from: now[key] ?? "", to: value });
  }
  return next;
}

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
  settleMotors(state, setup, suggest, changes);
  const point = { ...startOf(state.kind, setup, suggest), ...state.pointOf[state.kind] };
  for (const key of POINT_KEYS) {
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
  } else if (group === "conditions") {
    own(state, kind as keyof Point, change.from);
  }
}

/** A figure of the supply or the point the user typed: theirs for this kind of motor. */
function own(state: State, key: keyof Point, value: string | number): void {
  (state.conditions as Record<string, unknown>)[key] = value;
  state.pointOf = { ...state.pointOf, [state.kind]: { ...state.pointOf[state.kind], [key]: value } };
}
