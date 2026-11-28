// The design on the page as a design file: the file `motionsim design run` takes, so that
// what was set up here can be run, kept and compared from a terminal or by an agent.

import { motionRequest, request, tied } from "./state";
import type { State } from "./state";

type Plain = string | number | boolean | null | Plain[] | { [key: string]: Plain };

/** A figure as YAML reads it back as a number. A very small or very large one is written with
 *  an exponent, which YAML takes for a number only with a point in it and a sign on it
 *  (1.0e-8, not 1e-8, which it reads as text). Held to twelve figures, so that a sum made in
 *  binary (200 ns as 2.0000000000000002e-7) is written as the figure it stands for. */
export function figure(v: number): string {
  const said = String(Number(v.toPrecision(12)));
  if (!said.includes("e")) return said;
  const [mantissa, exponent] = said.split("e");
  return `${mantissa.includes(".") ? mantissa : `${mantissa}.0`}e${/^[-+]/.test(exponent) ? exponent : `+${exponent}`}`;
}

/** A text as YAML reads it back: quoted the way JSON quotes, which YAML takes as it is. */
const scalar = (v: string | number | boolean | null): string =>
  v === null ? "null" : typeof v === "string" ? JSON.stringify(v) : typeof v === "number" ? figure(v) : String(v);

/** Plain data as YAML, a key a line, nested by two spaces. */
export function yaml(value: Plain, indent = ""): string {
  if (Array.isArray(value)) {
    if (!value.length) return "[]";
    return value
      .map((item) => {
        const body = yaml(item, `${indent}  `);
        return `\n${indent}- ${typeof item === "object" && item !== null ? body.trimStart() : body}`;
      })
      .join("");
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value);
    if (!entries.length) return "{}";
    return entries
      .map(([k, v]) => {
        const body = yaml(v, `${indent}  `);
        const nested = v !== null && typeof v === "object" && body !== "[]" && body !== "{}";
        return `\n${indent}${k}:${nested ? body : ` ${body}`}`;
      })
      .join("");
  }
  return scalar(value);
}

/** Leave out what a design file has no place for: empty figures, which mean "not given". */
function given<T extends Record<string, unknown>>(record: T): Record<string, Plain> {
  return Object.fromEntries(Object.entries(record).filter(([, v]) => v !== null && v !== "")) as Record<string, Plain>;
}

/** How a device is named in the design file: a made-up one by its name, the user's own by
 *  the device file they save beside it. */
const deviceEntry = (id: string, examples: Set<string>): string => (examples.has(id) ? id : `${id}.device.yaml`);

/**
 * The design file for the page as it stands. `lead`: the device the design was started
 * from, named first so that it is the one followed through the motion.
 */
export function designFile(state: State, examples: Set<string>, lead: string | undefined): string {
  const req = request(state);
  const motion = motionRequest(state);
  const devices = [...new Set([...(lead ? [lead] : []), ...state.devices])].map((id) => deviceEntry(id, examples));
  const design: Record<string, Plain> = {
    devices,
    motor: given(req.motor),
    conditions: given(req.conditions),
    supply: req.supply,
    load: motion.load as Plain,
    profile: motion.profile as unknown as Plain,
    start: given(motion.start),
    repeats: motion.repeats,
  };
  if (req.supply === "mains" && "mains" in req) {
    // Fed from the mains: the mains and the stage chosen; the link is the stage's unless typed.
    const c = state.conditions;
    if (!c.link_own) delete (design.conditions as Record<string, Plain>).v_dc;
    design.mains = given(req.mains as Record<string, unknown>);
    design.front_end = given({
      topology: c.front_end || null,
      f_sw: req.front_end?.f_sw ?? null,
      feed_forward: tied(state) ? null : "off",
    });
    if (!Object.keys(design.front_end).length) delete design.front_end;
  }
  const heatsink = given(motion.heatsink);
  if (heatsink.rth !== undefined) design.heatsink = heatsink;
  if (motion.c_link !== null) design.c_link = motion.c_link;
  const own = devices.filter((d) => d.endsWith(".device.yaml"));
  const head = [
    "# A design saved from the MotionSim page. Run it with `motionsim design run` and this file's name.",
    ...(own.length
      ? ["# Save each of your own parts beside it under the name it has below (step 1, Save it as a device file)."]
      : []),
    ...(state.mission ? ["# The mission profile is not carried here: the load and its stretches are."] : []),
  ];
  return `${head.join("\n")}${yaml(design)}\n`;
}
