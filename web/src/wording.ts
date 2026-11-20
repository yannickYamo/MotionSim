// The engine's refusals, said the way the page speaks. The engine names a figure by its
// field and in its own unit (hertz, seconds), and passes on what its validator said; the
// user typed kilohertz into a box with a label. The reason is rewritten here, on the page's
// side, and nothing of what was refused is changed.

import { Refused } from "./api";
import { sig, whole } from "./format";

/** A box that takes another unit than the engine: the factor from the engine's to the box's. */
const BOX_UNITS: Record<string, { factor: number; unit: string }> = {
  f_sw: { factor: 1e-3, unit: "kHz" },
  t_dead: { factor: 1e9, unit: "ns" },
  t_min_pulse: { factor: 1e9, unit: "ns" },
  l_loop: { factor: 1e9, unit: "nH" },
};

/** The engine's names for figures, as the page labels them. */
const NAMES: Record<string, string> = {
  gear_ratio: "the gear ratio",
  gear_efficiency: "the gear efficiency",
  motor_inertia: "the rotor inertia",
  inertia: "the load inertia",
  friction_coulomb: "the friction",
  friction_viscous: "the friction growing with speed",
  constant_torque: "the steady torque",
  fan_coefficient: "the fan constant",
  mass: "the weight",
  arm: "the arm length",
  wheel_radius: "the wheel radius",
  rolling_resistance: "the rolling resistance",
  drag_area: "the drag area",
  slope_percent: "the slope",
  start_angle_deg: "the starting angle",
  speed_start: "its starting speed",
  speed_end: "its ending speed",
  duration: "its duration",
  tj_max: "the highest junction temperature",
  v_max: "the voltage rating",
  i_nominal: "the current rating",
  part_number: "the part number",
  vendor: "the maker",
};

/** What a validator says, and how a person would say it. Tried in order. */
const PHRASES: [RegExp, string][] = [
  [/should be a valid integer, got a number with a fractional part/g, "has to be a whole number"],
  [/should be a valid integer[^.;:]*/g, "has to be a whole number"],
  [/should be a valid number[^.;:]*/g, "has to be a number"],
  [/should be greater than or equal to (-?[\d.e+]+)/g, "cannot be below $1"],
  [/should be greater than (-?[\d.e+]+)/g, "has to be above $1"],
  [/should be less than or equal to (-?[\d.e+]+)/g, "cannot be above $1"],
  [/should be less than (-?[\d.e+]+)/g, "has to be below $1"],
  [/should be a valid dictionary or instance of \w+/g, "it does not hold the figures of one"],
  [/should be a valid (string|boolean|list|dictionary)[^.;:]*/g, "is not what is expected there"],
  [/:? ?[Ff]ield required/g, " is missing"],
  [/while (scanning|parsing)[^.;]*/g, "it is not written as YAML"],
];

const figure = (text: string, factor: number): string => {
  const value = Number(text.replace(/[,\u202f]/g, "")) * factor;
  if (!Number.isFinite(value)) return text;
  return Math.abs(value) >= 1000 && Number.isInteger(value) ? whole(value) : sig(value);
};

/** A sentence of the engine's, with validator phrases and field names put in plain words. */
export function plainly(text: string): string {
  let out = text;
  for (const [pattern, said] of PHRASES) out = out.replace(pattern, said);
  // A large figure with commas for its thousands is one the page could not read back.
  out = out.replace(/\b\d{1,3}(,\d{3})+\b/g, (n) => whole(Number(n.replace(/,/g, ""))));
  out = out.replace(/\b[a-z]+(_[a-z]+)+\b/g, (name) => NAMES[name] ?? name.replace(/_/g, " "));
  return out.replace(
    /\b(mass|arm|inertia|duration|vendor) (has to|cannot|is missing)/g,
    (_, n: string, rest: string) => {
      return `${NAMES[n] ?? n} ${rest}`;
    },
  );
}

/** The limit the engine names, in the unit of the box the user typed into. */
function inBoxUnit(text: string, field: string): string {
  const box = BOX_UNITS[field];
  if (!box) return text;
  // The engine says its limit in its own unit, hertz, seconds or henries: the box's takes its place.
  const limit =
    /(cannot be (?:below|above)|has to be (?:above|below)) (-?[\d.,\u202f]*\d(?:e[+-]?\d+)?)(?: (?:Hz|s|H)\b)?/g;
  return text.replace(limit, (_, said: string, n: string) => `${said} ${figure(n, box.factor)} ${box.unit}`);
}

/** What a request that failed came to: the engine's refusal, said the page's way, or what
 *  `otherwise` makes of the words of a failure that is not one. */
export function refusalOf(e: unknown, otherwise: (message: string) => Refused): Refused {
  return e instanceof Refused ? plainRefusal(e) : otherwise((e as Error).message);
}

/** A refusal as the page says it: same field, same meaning, plain words and the box's unit. */
export function plainRefusal(r: Refused): Refused {
  return new Refused(inBoxUnit(plainly(r.reason), r.field), plainly(r.fix), r.field);
}
