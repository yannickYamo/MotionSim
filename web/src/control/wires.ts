// Which wires a test is usually read by, and how the wires drawn through time are set out:
// one chart for each quantity, the reference dashed beside what was simulated.

import type { LabState } from "./store";
import type { Trace } from "./plots";
import type { Series, Wire } from "./types";

/** What is drawn first for each test: the quantity it steps, then what answers it. */
const ORDER: Record<string, string[]> = {
  hold: ["abc A", "dq A", "duty", "N·m"],
  torque_step: ["N·m", "dq A", "abc A", "duty"],
  speed_step: ["rpm", "N·m", "dq A", "abc A"],
  start: ["rpm", "N·m", "dq A", "abc A"],
  load_step: ["rpm", "N·m", "dq A", "abc A"],
  motion: ["rpm", "N·m", "dq A", "abc A"],
  trip: ["abc A", "N·m", "rpm", "link A", "safe", "dq A"],
};
/** A drive fed from the mains: its link and what the mains gives, after what the test is read by. */
const MAINS = ["link V", "mains W"];

/** Wires drawn on a chart of their own, whatever their unit: what the stage did once tripped. */
const OWN_CHART: Record<string, string> = {
  "inverter.i_link": "link A",
  "inverter.safe": "safe",
  "link.v_dc": "link V",
  "link.p_in": "mains W",
  "link.i_line": "mains A",
};

const frameOf = (name: string): string => {
  const port = name.slice(name.indexOf(".") + 1);
  if (/(^|_)(a|b|c)$/.test(port)) return "abc";
  if (/alpha|beta/.test(port)) return "αβ";
  return /(^|_)(d|q)$|^i[dq]_ref$/.test(port) ? "dq" : "";
};

/** The chart a wire is drawn on: wires of one unit and one frame share one. */
export function groupOf(wire: { name: string; unit: string }): string {
  if (OWN_CHART[wire.name]) return OWN_CHART[wire.name];
  const frame = frameOf(wire.name);
  if (!wire.unit && frame === "abc") return "duty";
  return [frame, wire.unit].filter(Boolean).join(" ") || "other";
}

const TITLES: Record<string, [string, string]> = {
  // The scope reads the shaft's speed in rpm (scopeview.ts); the electrical speed stays in rad/s.
  rpm: ["Speed", "speed, rpm"],
  "rad/s": ["Electrical speed", "electrical speed, rad/s"],
  "N·m": ["Torque", "torque, N·m"],
  "dq A": ["Currents in the rotor's frame", "d and q current, A"],
  "abc A": ["Phase currents", "phase current, A"],
  "αβ A": ["Currents in the stator's frame", "α and β current, A"],
  "dq V": ["Voltages asked for, rotor's frame", "d and q voltage, V"],
  "αβ V": ["Voltages asked for, stator's frame", "α and β voltage, V"],
  duty: ["What each leg is told", "duty cycle or state, 0 to 1"],
  "link A": ["Current back into the DC link", "current, A"],
  safe: ["The stage: 1 every gate off, 2 shorted", "state"],
  "link V": ["DC link, as the front end holds it", "link voltage, V"],
  "mains W": ["Power drawn from the mains", "power, W"],
  "mains A": ["Mains current, one line", "current, A"],
};

export const titleOf = (group: string): [string, string] =>
  TITLES[group] ?? [group === "other" ? "Other signals" : `Signals, ${group}`, group === "other" ? "value" : group];

/** Whether a wire is what was asked for and not what happened: a command or a reference. */
export const asked = (name: string): boolean => name.startsWith("cmd.") || /ref|shaper|speed\.torque/.test(name);

/** The wires a test is usually read by, of those this scheme has: the speed against the speed
 *  asked for, the torque against the load, the currents in the rotor's frame against their
 *  references, and the phase currents. What the legs are told is a probe away. */
export function usualWires(s: LabState): string[] {
  const scheme = s.scheme;
  if (!scheme) return [];
  const taken = new Set(scheme.blocks.flatMap((b) => Object.values(b.inputs)));
  const has = (w: string) => taken.has(w);
  const refs = scheme.blocks.flatMap((b) => {
    const kind = s.presets?.blocks[b.kind];
    if (b.kind === "current_reference") return [`${b.name}.i_q`, `${b.name}.i_d`];
    if (b.kind === "speed_reference") return [`${b.name}.ref`];
    return kind?.loop === "speed" ? [`${b.name}.torque`] : [];
  });
  // Where the shaft twists, the load's speed is drawn on the rotor's chart: the two apart is
  // the shaft swinging.
  const load = s.plant.coupling ? ["plant.omega_load"] : [];
  const plant = ["plant.omega_m", ...load, "plant.torque", "plant.load_torque", "plant.i_q", "plant.i_d"];
  // Where the currents are read through shunts, phase a as read beside the true one: the two
  // apart is what the shunts missed or read late.
  const shunt = scheme.blocks.find((b) => b.kind === "shunt_sampling");
  const phases = ["plant.i_a", ...(shunt ? [`${shunt.name}.i_a`] : []), "plant.i_b", "plant.i_c"];
  const commands = ["cmd.speed", "cmd.torque"].filter(has);
  // Where the angle is read by injection, its error against the rotor's and the observer's share
  // of it: the run-up reads as injecting, blending and handed over.
  const injection = scheme.blocks.find((b) => b.kind === "hf_injection");
  const injected = injection ? [`${injection.name}.error`, `${injection.name}.share`] : [];
  // A trip: what the stage returned to the DC link, and which safe state it was in.
  const tripped = s.scenario === "trip" ? ["inverter.i_link", "inverter.safe"] : [];
  // Fed from the mains: the link through the test and the power the front end draws for it.
  const mains = ["link.v_dc", "link.p_in"];
  return [...plant, ...phases, ...commands, ...refs, ...injected, ...tripped, ...mains];
}

const SOLID = ["s1", "s4", "s5"];
const DASHED = ["s3", "s6"];

export interface Group {
  key: string;
  title: string;
  yLabel: string;
  traces: Trace[];
}

/** The wires to draw, set out chart by chart in the order the test is read in. What was
 *  asked for is dashed; what was simulated is solid, each line told from the next by its dash. */
export function grouped(wires: string[], known: Wire[], series: Series, scenario: string): Group[] {
  const units = new Map(known.map((w) => [w.name, w.unit]));
  const groups = new Map<string, string[]>();
  for (const name of wires) {
    if (!series.wires[name]) continue;
    const key = groupOf({ name, unit: units.get(name) ?? "" });
    groups.set(key, [...(groups.get(key) ?? []), name]);
  }
  const order = ORDER[scenario] ?? ORDER.hold;
  // What the test is read by, then any other signal, then the link and the mains: always last.
  const rank = (key: string) => {
    if (MAINS.includes(key)) return order.length + 1 + MAINS.indexOf(key);
    return order.includes(key) ? order.indexOf(key) : order.length;
  };
  return [...groups.entries()]
    .sort((a, b) => rank(a[0]) - rank(b[0]))
    .map(([key, names]) => {
      const [title, yLabel] = titleOf(key);
      let solid = 0;
      let dashed = 0;
      const traces = names.map((name) => ({
        name,
        values: series.wires[name],
        cls: asked(name) ? DASHED[dashed++ % DASHED.length] : SOLID[solid++ % SOLID.length],
      }));
      return { key, title, yLabel, traces };
    });
}
