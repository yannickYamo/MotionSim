// The unit of a wire the engine gives none for: a transform (Clarke, Park and their inverses)
// carries whatever it is given into another frame, so what comes out is in the unit of what
// goes in. Read from the scheme's wiring, never from a block's name.

import type { Presets, Scheme, Wire } from "./types";

/** The ports of a frame's components: what a transform takes in and gives out. */
const FRAME = /^(a|b|c|alpha|beta|d|q)$/;

/** Every wire's unit, with those a transform carries filled in from what goes into it. */
export function unitsOf(scheme: Scheme | null, kinds: Presets["blocks"] | undefined, known: Map<string, string>) {
  const units = new Map(known);
  if (!scheme) return units;
  // A transform after a transform takes its unit once the one before it has one.
  for (let pass = 0; pass < 4 && scheme.blocks.some((b) => carried(b, kinds, units)); pass++);
  return units;
}

/** Fill in the units a block's frame outputs carry from its frame inputs; whether any was. */
function carried(b: Scheme["blocks"][number], kinds: Presets["blocks"] | undefined, units: Map<string, string>) {
  const given = Object.entries(b.inputs)
    .filter(([port]) => FRAME.test(port))
    .map(([, wire]) => units.get(wire) ?? "")
    .filter(Boolean);
  if (!given.length || new Set(given).size !== 1) return false;
  let more = false;
  for (const port of kinds?.[b.kind]?.outputs.map((o) => o.name) ?? []) {
    const wire = `${b.name}.${port}`;
    if (!FRAME.test(port) || units.get(wire)) continue;
    units.set(wire, given[0]);
    more = true;
  }
  return more;
}

/** The wires as they are known, each with its unit, a transform's filled in. */
export function withUnits(wires: Wire[], scheme: Scheme | null, kinds: Presets["blocks"] | undefined): Wire[] {
  const units = unitsOf(scheme, kinds, new Map(wires.map((w) => [w.name, w.unit])));
  return wires.map((w) => (w.unit ? w : { ...w, unit: units.get(w.name) ?? "" }));
}

/** In each unit, a swing finer than any drive reads of the quantity: a strip spans at least
 *  this much, so what the simulation's arithmetic leaves on a held value is drawn flat. */
const LEAST: Record<string, number> = { "rad/s": 0.1, rpm: 1, A: 0.01, "N·m": 0.01, V: 0.01, rad: 1e-3 };

export const leastSpan = (unit: string): number => LEAST[unit] ?? 0;
