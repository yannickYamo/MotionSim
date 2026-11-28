// Where each block of a scheme stands on the drawing, and how each wire runs: worked out from
// the scheme's own wiring, never from its name. It is set out as a control engineer draws it
// on paper. The path from the commands to the motor is one line, left to right; what senses
// the motor comes back along one line underneath, right to left. Signals that travel together
// are one bus; a signal that goes to several blocks is one trunk that branches at a dot. Wires
// run in the gaps between the columns and in the channels between the rows alone, so that none
// passes through a block. A kind of block the page has never seen is placed by its wiring.

import { BLOCK_H, type LEdge, type LNode, type Layout } from "./drawn";
import { blockNode, kernelNodes, placed, wayBack } from "./placing";
import {
  back as backSide,
  type GapLanes,
  Lanes,
  bundles,
  crossingsOf,
  frameOf,
  groupsOf,
  nearOf,
  netsOf,
  plans,
  route,
  same,
  sumsOf,
} from "./routing";
import { named } from "./naming";
import { unitsOf } from "./units";
import { widthOf } from "./symbols";
import type { Port, Presets, Scheme } from "./types";

export * from "./drawn";
export { blockOf } from "./placing";
export { busWords, wordOf } from "./routing";

/** The drawing of a scheme: its blocks placed and its wires run. The same scheme always
 *  gives the same drawing. */
export function layoutOf(scheme: Scheme, registry: Presets["blocks"], sources: Port[]): Layout {
  const bare = [...scheme.blocks.map((b) => blockNode(b, registry[b.kind], scheme)), ...kernelNodes(scheme, sources)];
  // A transform's outputs are in the unit of what goes into it, where the registry gives none.
  const given = new Map([
    ...sources.map((p) => [p.name, p.unit] as const),
    ...bare.flatMap((n) => n.outputs.map((o) => [o.wire, o.unit] as const)),
  ]);
  const units = unitsOf(scheme, registry, given);
  for (const n of bare) for (const o of n.outputs) if (!o.unit) o.unit = units.get(o.wire) ?? "";
  const at = placed(scheme, bare, registry);
  const back = wayBack(scheme, registry);
  const nodes: LNode[] = bare.map((n) => {
    const where = at.get(n.id)!;
    // A summing junction is drawn on the forward path alone.
    return { ...n, ...where, sum: n.sum && where.row === 0, x: 0, y: 0, w: widthOf(n.symbol), h: BLOCK_H, axis: 0 };
  });
  // Every block of a column is as wide as the widest: the drawing stands on a grid.
  for (const n of nodes) n.w = Math.max(...nodes.filter((m) => m.col === n.col).map((m) => widthOf(m.symbol)));
  const planned = plans(nodes, bundles(nodes, back));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const rowOf = (id: string) => byId.get(id)!.row;
  // The lanes of a side of a gap: first those that cross where the names of the row are
  // written (rising from the forward path, falling from the way back), then the rest.
  const rising = (p: (typeof planned)[number]) => p.way === "channel" && p.channel <= rowOf(p.edge.from);
  const order = (p: (typeof planned)[number]) => (rowOf(p.edge.from) > 0 ? (rising(p) ? 3 : 2) : rising(p) ? 0 : 1);
  const lanes: GapLanes = { all: new Lanes(), up: new Lanes(), down: new Lanes(), across: new Set() };
  const channels = new Lanes();
  for (const p of [...planned].sort((a, b) => order(a) - order(b))) {
    const fore = rowOf(p.edge.from) === 0;
    if (p.way === "straight") {
      if (!fore) lanes.across.add(p.gap);
      continue;
    }
    lanes.all.take(fore ? p.gap : backSide(p.gap), p.edge.from);
    if (order(p) === 0) lanes.up.take(p.gap, p.edge.from);
    if (order(p) === 2) lanes.down.take(backSide(p.gap), p.edge.from);
  }
  for (const p of planned) if (p.way === "channel") channels.take(p.channel, p.edge.from);
  const f = frameOf(nodes, lanes, channels);
  for (const n of nodes) {
    n.x = f.colX[n.col];
    n.y = f.rowY[n.row];
    n.axis = n.y + f.rowH[n.row] / 2;
  }
  const edges: LEdge[] = planned.map((p) => {
    const points = route(p, byId, f, lanes.all, channels).filter((q, i, all) => !i || !same(q, all[i - 1]));
    return { ...p.edge, points, label: null, tick: null };
  });
  // The order the keyboard goes through the blocks in: the forward path, then the way back.
  nodes.sort((a, b) => a.row - b.row || (a.row === 0 ? a.col - b.col : b.col - a.col));
  const groups = groupsOf(nodes, f);
  const sums = sumsOf(nodes, edges);
  named(edges, nodes, sums, groups, f, lanes);
  const nets = netsOf(edges);
  return {
    nodes,
    edges,
    nets,
    crossings: crossingsOf(nets),
    sums,
    groups,
    width: f.width,
    height: f.height,
    near: nearOf(nodes, edges),
  };
}

/** A wire's run as a path: square corners, a little rounded. */
export function pathOf(points: [number, number][], r = 5): string {
  let d = `M${points[0][0]} ${points[0][1]}`;
  for (let k = 1; k < points.length - 1; k++) {
    const [px, py] = points[k - 1];
    const [x, y] = points[k];
    const [nx, ny] = points[k + 1];
    const a = Math.min(r, Math.hypot(x - px, y - py) / 2);
    const b = Math.min(r, Math.hypot(nx - x, ny - y) / 2);
    const ax = x - Math.sign(x - px) * a;
    const ay = y - Math.sign(y - py) * a;
    const bx = x + Math.sign(nx - x) * b;
    const by = y + Math.sign(ny - y) * b;
    d += `L${ax} ${ay}Q${x} ${y} ${bx} ${by}`;
  }
  const [ex, ey] = points[points.length - 1];
  return `${d}L${ex} ${ey}`;
}
