// What a box can hold, said at the box before the engine is asked. The engine has the last
// word and refuses what it will not take; these are its own limits and plain physical ones
// (a gear ratio above zero, a weight not below it), repeated here so that a wrong figure is
// marked where it was typed and in the unit it was typed in.

import { whole as grouped } from "./format";

interface Limit {
  name: string;
  unit?: string;
  min?: number;
  max?: number;
  /** The figure has to be above this, and may not equal it. */
  above?: number;
  whole?: boolean;
}

const LIMITS: Record<string, Limit> = {
  "conditions.v_dc": { name: "Supply voltage", unit: "V", min: 1, max: 2000 },
  "conditions.f_khz": { name: "Switching frequency", unit: "kHz", min: 0.1, max: 10000 },
  "conditions.parallel": { name: "Devices in parallel", min: 1, max: 12, whole: true },
  "conditions.t_sink": { name: "Heatsink temperature", unit: "°C", min: -40, max: 200 },
  // The engine's own bounds on a design point: past any rotor that holds together.
  "conditions.rpm": { name: "Speed", unit: "rpm", min: -1e6, max: 1e6 },
  "conditions.torque": { name: "Torque", unit: "N·m", min: -1e6, max: 1e6 },
  "load.gear_ratio": { name: "Gear ratio", above: 0 },
  "load.gear_efficiency": { name: "Gear efficiency", above: 0, max: 1 },
  "load.inertia": { name: "Load inertia", min: 0 },
  "load.motor_inertia": { name: "Rotor inertia", min: 0 },
  "load.friction_coulomb": { name: "Friction", min: 0 },
  "load.friction_viscous": { name: "Friction growing with speed", min: 0 },
  "load.fan_coefficient": { name: "Fan constant", min: 0 },
  "load.mass": { name: "Weight", min: 0 },
  "load.arm": { name: "Arm length", min: 0 },
  "load.v_mass": { name: "Mass carried", min: 0 },
  "load.wheel_radius": { name: "Wheel radius", min: 0 },
  "load.rolling_resistance": { name: "Rolling resistance", min: 0 },
  "load.drag_area": { name: "Drag area", min: 0 },
  "segments.duration": { name: "A stretch", unit: "s", above: 0 },
  "segments.speed_start": { name: "Speed", unit: "rpm", min: -1e6, max: 1e6 },
  "segments.speed_end": { name: "Speed", unit: "rpm", min: -1e6, max: 1e6 },
  "event.l_cs_nh": { name: "Common-source inductance", unit: "nH", min: 0, max: 100 },
  "event.l_g_nh": { name: "Gate-loop inductance", unit: "nH", min: 0, max: 1000 },
  "event.v_off": { name: "Driver's low level", unit: "V", min: -25, max: 0 },
  "sink.repeats": { name: "Repeats", min: 1, max: 50, whole: true },
};

/** `segments.2.duration` is held to the limit of every stretch's duration. */
const keyOf = (path: string): string => path.replace(/^segments\.\d+\./, "segments.");

const shown = (v: number): string => (Math.abs(v) >= 10000 ? grouped(v) : String(v));

/** Whether a figure is inside what a box takes. */
const inside = (l: Limit, value: number): boolean =>
  (l.min === undefined || value >= l.min) &&
  (l.max === undefined || value <= l.max) &&
  (l.above === undefined || value > l.above) &&
  (!l.whole || Number.isInteger(value));

/** A plain sentence saying what the box takes, when the figure is outside it; else null. */
export function outOfRange(path: string, value: number): string | null {
  const l = LIMITS[keyOf(path)];
  if (!l || inside(l, value)) return null;
  return takes(l);
}

/** What a box takes, in a plain sentence. */
function takes(l: Limit): string {
  const unit = l.unit ? ` ${l.unit}` : "";
  const number = l.whole ? "a whole number" : "";
  if (l.min !== undefined && l.max !== undefined) {
    const [from, to] = number ? [`${number} from`, "to"] : ["between", "and"];
    return `${l.name} has to be ${from} ${shown(l.min)} ${to} ${shown(l.max)}${unit}.`;
  }
  if (l.above !== undefined && l.max !== undefined) {
    return `${l.name} has to be above ${shown(l.above)}, and ${shown(l.max)} at most.`;
  }
  if (l.above !== undefined) return `${l.name} has to be above ${shown(l.above)}${unit}.`;
  return `${l.name} cannot be below ${shown(l.min!)}${unit}.`;
}

/** How a sign is taken, where a figure may be negative and it is not obvious what that means. */
export function signNote(path: string, value: number): string | null {
  if (value >= 0) return null;
  if (path === "conditions.rpm") {
    return "A negative speed is the motor turning the other way. With the torque still positive, it is braking.";
  }
  if (path === "conditions.torque") {
    return "A negative torque works against the turning: the motor is braking, and gives power back.";
  }
  return null;
}
