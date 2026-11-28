// The blocks of a scheme as they stand on the drawing: what each puts out and takes in, and
// which row and column it has. The path from the commands to the motor is one row, left to
// right; what senses the motor stands underneath, from under the motor leftwards.

import { GAIN, INVERTER, type LNode, MOTOR, type Output, REFERENCE, type Role } from "./drawn";
import { symbolOf } from "./symbols";
import type { Block, Kind, Port, Presets, Scheme } from "./types";

/** Wires the kernel drives that go to many blocks at once: named at the block, not drawn. */
export const AMBIENT = new Set(["plant.v_dc", "time.t", "const.zero"]);
export const SENSING = /observer|estimat|sens|sampl|encoder|resolver|pll/i;
/** The parts the registry names that stand under the forward path. */
export const BACK_HINTS = new Set(["sensing", "transform_feedback", "estimation", "supervisor"]);

export const blockOf = (wire: string): string => wire.split(".", 1)[0];
export const portOf = (wire: string): string => wire.slice(wire.indexOf(".") + 1);

/** The outputs of a block: as the registry lists them, or for a kind it does not know, the
 *  wires the rest of the scheme takes from it. */
export function outputsOf(block: Block, kind: Kind | undefined, scheme: Scheme): Output[] {
  const named = (p: Port): Output => ({ wire: `${block.name}.${p.name}`, name: p.name, unit: p.unit, about: p.about });
  if (kind) return kind.outputs.map(named);
  const used = new Set<string>();
  const taken = [...scheme.blocks.flatMap((b) => Object.values(b.inputs)), ...scheme.actuation.wires];
  for (const wire of taken) if (blockOf(wire) === block.name) used.add(wire);
  return [...used].map((wire) => ({ wire, name: portOf(wire), unit: "", about: "" }));
}

/** The wires of the kernel a scheme takes, as the outputs of the node that stands for them. */
export function kernelOutputs(prefix: string, scheme: Scheme, sources: Port[], always: string[]): Output[] {
  const taken = new Set(scheme.blocks.flatMap((b) => Object.values(b.inputs)));
  return sources
    .filter((s) => blockOf(s.name) === prefix && !AMBIENT.has(s.name) && (taken.has(s.name) || always.includes(s.name)))
    .map((s) => ({ wire: s.name, name: portOf(s.name), unit: s.unit, about: s.about }));
}

export type Placed = "row" | "col" | "x" | "y" | "w" | "h" | "axis";
export type Bare = Omit<LNode, Placed>;

/** A node with its symbol worked out from the rest of it. */
const drawnAs = (n: Omit<Bare, "symbol">): Bare => ({ ...n, symbol: symbolOf(n) });

export function blockNode(block: Block, kind: Kind | undefined, scheme: Scheme): Bare {
  const outputs = outputsOf(block, kind, scheme);
  const regulates = /regulator/.test(kind?.role ?? "") && outputs.some((o) => /^err/.test(o.name));
  return drawnAs({
    id: block.name,
    role: "block",
    kind: block.kind,
    hint: kind?.role ?? "",
    title: kind?.title ?? block.kind.replace(/_/g, " "),
    known: !!kind,
    loop: kind?.loop ?? "",
    sum: (!!kind?.loop && !!kind.linear) || regulates,
    block,
    gains: Object.keys(block.params)
      .filter((p) => GAIN.test(p) && typeof block.params[p] === "number")
      .slice(0, 4),
    inputs: Object.entries(block.inputs).map(([port, wire]) => ({ port, wire })),
    outputs,
  });
}

export function kernelNodes(scheme: Scheme, sources: Port[]): Bare[] {
  const kernel = (id: string, role: Role, title: string, outputs: Output[]): Omit<Bare, "symbol"> => ({
    id,
    role,
    kind: role,
    hint: "",
    title,
    known: true,
    loop: "",
    sum: false,
    block: null,
    gains: [],
    inputs: [],
    outputs,
  });
  const inverter = kernel(INVERTER, "inverter", "Inverter", []);
  inverter.inputs = scheme.actuation.wires.map((wire, k) => ({ port: "abc"[k] ?? String(k), wire }));
  const motor = kernel(MOTOR, "motor", "Motor and load", kernelOutputs(MOTOR, scheme, sources, ["plant.torque"]));
  motor.inputs = [{ port: "v", wire: `${INVERTER}.v` }];
  const reference = kernel(REFERENCE, "reference", "Commands", kernelOutputs(REFERENCE, scheme, sources, []));
  return [reference, inverter, motor].map(drawnAs);
}

/** Whether a block senses the motor: it reads a wire of the motor itself, or is named for it. */
export const senses = (b: Block): boolean =>
  Object.values(b.inputs).some((w) => blockOf(w) === MOTOR && !AMBIENT.has(w)) || SENSING.test(`${b.kind} ${b.name}`);

/** The blocks of the way back: those the registry says stand there; and of the kinds it says
 *  nothing of, those that sense the motor and those fed by the way back alone. */
export function wayBack(scheme: Scheme, registry: Presets["blocks"]): Set<string> {
  const hint = (b: Block) => registry[b.kind]?.role ?? "";
  const back = new Set(scheme.blocks.filter((b) => (hint(b) ? BACK_HINTS.has(hint(b)) : senses(b))).map((b) => b.name));
  for (let grew = true; grew;) {
    grew = false;
    for (const b of scheme.blocks) {
      const from = Object.values(b.inputs).filter((w) => !AMBIENT.has(w));
      if (back.has(b.name) || hint(b) || !from.length || !from.every((w) => back.has(blockOf(w)))) continue;
      back.add(b.name);
      grew = true;
    }
  }
  return back;
}

/** How far each block of a set stands from where its signals start: one more than the
 *  farthest block of the set that feeds it. A loop in the wiring is cut where it closes. */
export function depths(blocks: Block[], within: Set<string>): Map<string, number> {
  const byName = new Map(blocks.map((b) => [b.name, b]));
  const found = new Map<string, number>();
  const open = new Set<string>();
  const depth = (name: string): number => {
    if (found.has(name)) return found.get(name)!;
    if (open.has(name)) return 0;
    open.add(name);
    const feeders = Object.values(byName.get(name)!.inputs)
      .map(blockOf)
      .filter((n) => within.has(n) && n !== name);
    const d = 1 + Math.max(0, ...feeders.map(depth));
    open.delete(name);
    found.set(name, d);
    return d;
  };
  for (const b of blocks) if (within.has(b.name)) depth(b.name);
  return found;
}

/** The way back in the order it is drawn in, from the motor leftwards: its longest chain is
 *  kept block beside block, what else senses the motor stands before it, the rest after. */
export function backOrder(blocks: Block[], back: Set<string>): string[] {
  const depth = depths(blocks, back);
  const names = blocks.filter((b) => back.has(b.name)).map((b) => b.name);
  if (!names.length) return [];
  const byName = new Map(blocks.map((b) => [b.name, b]));
  const deepest = names.reduce((a, b) => (depth.get(b)! > depth.get(a)! ? b : a));
  const chain = [deepest];
  for (let at = deepest; depth.get(at)! > 1;) {
    const feeder = Object.values(byName.get(at)!.inputs)
      .map(blockOf)
      .find((n) => back.has(n) && depth.get(n) === depth.get(at)! - 1);
    if (!feeder) break;
    chain.unshift(feeder);
    at = feeder;
  }
  const on = new Set(chain);
  const off = names.filter((n) => !on.has(n));
  const first = off.filter((n) => depth.get(n) === 1);
  const rest = off.filter((n) => depth.get(n)! > 1).sort((a, b) => depth.get(a)! - depth.get(b)!);
  return [...first, ...chain, ...rest];
}

/** Each node's row and column. */
export function placed(
  scheme: Scheme,
  bare: Bare[],
  registry: Presets["blocks"],
): Map<string, { row: number; col: number }> {
  const back = wayBack(scheme, registry);
  const forward = new Set(scheme.blocks.filter((b) => !back.has(b.name)).map((b) => b.name));
  const fwd = depths(scheme.blocks, forward);
  const last = Math.max(0, ...fwd.values());
  const at = new Map<string, { row: number; col: number }>();
  at.set(REFERENCE, { row: 0, col: 0 });
  at.set(INVERTER, { row: 0, col: last + 1 });
  at.set(MOTOR, { row: 0, col: last + 2 });
  for (const [name, d] of fwd) at.set(name, { row: 0, col: d });
  spread(bare, at);
  // The way back stands under the forward path, from under the motor leftwards; where it is
  // longer than the forward path, it goes on in a row beneath.
  const motor = at.get(MOTOR)!.col;
  backOrder(scheme.blocks, back).forEach((name, k) => {
    at.set(name, { row: 1 + Math.floor(k / (motor + 1)), col: motor - (k % (motor + 1)) });
  });
  return at;
}

/** Forward blocks that came to the same column are set one after another, in the scheme's order. */
export function spread(bare: Bare[], at: Map<string, { row: number; col: number }>): void {
  const seen = new Set<number>();
  let shift = 0;
  const row0 = bare.filter((n) => at.has(n.id)).sort((a, b) => at.get(a.id)!.col - at.get(b.id)!.col);
  for (const n of row0) {
    const place = at.get(n.id)!;
    place.col += shift;
    while (seen.has(place.col)) {
      place.col += 1;
      shift += 1;
    }
    seen.add(place.col);
  }
}

/** Whether an input of a regulator is what is measured: it comes from the way back, in the
 *  unit of one of the regulator's references. */
export function measured(node: Bare, port: string, back: Set<string>): boolean {
  if (/ref/i.test(port)) return false;
  return back.has(blockOf(node.block?.inputs[port] ?? "")) && !/omega_e|theta|v_dc/.test(port);
}
