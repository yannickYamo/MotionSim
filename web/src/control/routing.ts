// How each wire runs on the drawing. Signals that travel together are one bus; a signal that
// goes to several blocks is one trunk that branches at a dot. Wires run in the gaps between
// the columns and in the channels between the rows alone, so that none passes through a block.

import {
  BAND_HEAD,
  CHANNEL_LANE,
  ENTRY,
  INVERTER,
  LANE,
  type LCross,
  type LEdge,
  type LGroup,
  type LNet,
  type LNode,
  type LSeg,
  type LSum,
  type Layout,
  MACHINE_R,
  PAD,
  SUM_OUT,
  SUM_R,
  SUM_ROOM,
  type Word,
} from "./drawn";
import { AMBIENT, blockOf, measured } from "./placing";

export const GREEK: Record<string, string> = { theta: "θ", omega: "ω", alpha: "α", beta: "β", speed: "ω", torque: "T" };
const AXES = /^(a|b|c|d|q|alpha|beta)$/;
const axis = (name: string): string => GREEK[name] ?? name;

/** A signal's name as it is written on a wire, as a control engineer writes it: i with dq
 *  small under it for the currents in the rotor's frame, ω* for the speed asked for. The
 *  letter of a pair of axes is read from its unit, or, without one, from where it runs: the
 *  way back carries currents, the way forward voltages. */
export function wordOf(port: string, unit = "", star = false, back = false): Word {
  const pair = /^([ivds])_(a|b|c|d|q|alpha|beta)$/.exec(port);
  if (pair) return { text: pair[1], sub: axis(pair[2]), star: star && pair[1] !== "s" };
  if (AXES.test(port)) return { text: letterOf(unit, back), sub: axis(port), star };
  if (port === "ref") return { text: unit === "N·m" ? "T" : unit === "A" ? "i" : "ω", sub: "", star: true };
  return plainWord(port, star);
}

/** The letter of a pair of axes: v for volts, i for amperes; without a unit, by the way it runs. */
const letterOf = (unit: string, back: boolean): string => (unit === "V" ? "v" : unit === "A" || back ? "i" : "v");

/** Any other name: a Greek letter for what is one, with what follows its last stroke small. */
function plainWord(port: string, star: boolean): Word {
  const cut = port.lastIndexOf("_");
  const base = cut > 0 ? port.slice(0, cut) : port;
  const sub = cut > 0 ? port.slice(cut + 1) : "";
  if (GREEK[base] && sub.length <= 2) return { text: GREEK[base], sub, star };
  if (GREEK[port]) return { text: GREEK[port], sub: "", star };
  if (sub.length > 3 || base.length > 2) return { text: port.replace(/_/g, " "), sub: "", star: false };
  return { text: base, sub, star };
}

/** The name of the signals that travel together: i_a, i_b and i_c are i abc; d and q are dq. */
export function busWords(words: Word[]): Word[] {
  if (words.length < 2) return words;
  const star = words.every((w) => w.star);
  const same = words.every((w) => w.text === words[0].text);
  if (same && words.every((w) => [...w.sub].length === 1))
    return [{ text: words[0].text, sub: words.map((w) => w.sub).join(""), star }];
  if (words.every((w) => !w.sub && w.text.length === 1))
    return [{ text: words.map((w) => w.text).join(""), sub: "", star }];
  return words.length > 2 ? [words[0], { text: `+${words.length - 1}`, sub: "", star: false }] : words;
}

/** How wide a name is, at the size it is set on the drawing (16 px italic, its small letters
 *  at 0.72 of that), with a little room either side. */
export const wordsWidth = (words: Word[]): number =>
  6 +
  words.reduce((w, x) => w + [...x.text].length * 9 + [...x.sub].length * 6.5 + (x.star ? 6 : 0), 0) +
  (words.length - 1) * 8;

export type Way = "straight" | "ell" | "channel";

/** A wire's run, before its lanes have places. */
export interface Plan {
  edge: Omit<LEdge, "points" | "label" | "tick">;
  way: Way;
  /** The gap (left of this column) its upright runs in. */
  gap: number;
  channel: number;
  /** Which of the target's inputs on that side this is, and of how many. */
  nth: number;
  of: number;
}

export const flow = (n: { row: number }): 1 | -1 => (n.row === 0 ? 1 : -1);

/** Lanes handed out one to a trunk: every wire that leaves one block shares its lane. */
export class Lanes {
  private held = new Map<number, string[]>();
  take(where: number, net: string): void {
    const lanes = this.held.get(where) ?? [];
    this.held.set(where, lanes);
    if (!lanes.includes(net)) lanes.push(net);
  }
  of(where: number, net: string): number {
    return Math.max(0, (this.held.get(where) ?? []).indexOf(net));
  }
  count(where: number): number {
    return this.held.get(where)?.length ?? 0;
  }
}

/** One more wire in a bundle: a line more, unless the bundle already carries that wire. */
function joined(had: Plan["edge"], input: { wire: string; port: string }): void {
  if (!had.wires.includes(input.wire)) had.wires.push(input.wire);
  had.ports.push(input.port);
  had.n = had.wires.length;
}

/** The wires into each block, those from one block that come in together bundled into one. */
export function bundles(nodes: LNode[], back: Set<string>): Plan["edge"][] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const out = new Map<string, Plan["edge"]>();
  for (const to of nodes) {
    for (const input of to.inputs) {
      const from = byId.get(blockOf(input.wire));
      if (AMBIENT.has(input.wire) || !from || from.id === to.id) continue;
      const minus = to.sum && measured(to, input.port, back);
      const atSum = to.sum && (minus || /ref/i.test(input.port));
      const id = `${from.id}>${to.id}${atSum ? (minus ? ":minus" : ":plus") : ""}`;
      const had = out.get(id);
      if (had) {
        joined(had, input);
        continue;
      }
      out.set(id, {
        id,
        wire: input.wire,
        wires: [input.wire],
        ports: [input.port],
        // The three phase voltages are one wire in the scheme, and three lines on the drawing.
        n: input.wire === `${INVERTER}.v` ? 3 : 1,
        from: from.id,
        to: to.id,
        port: input.port,
        back: from.row > 0 || to.row > 0,
        minus,
        atSum,
        into: "side",
      });
    }
  }
  return [...out.values()];
}

/** How each bundle runs: straight to the next block of its row, round the end of the row to the
 *  first block of the row beneath, or by a gap and a channel to the top or the foot of its block. */
export function plans(nodes: LNode[], edges: Plan["edge"][]): Plan[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const sideTaken = new Set<string>();
  const lastOfRow = (n: LNode) => !nodes.some((m) => m.row === n.row && m.col > n.col);
  const out: Plan[] = edges.map((edge) => {
    const from = byId.get(edge.from)!;
    const to = byId.get(edge.to)!;
    const gap = flow(from) > 0 ? from.col + 1 : from.col;
    const free = !sideTaken.has(to.id);
    const beside = from.row === to.row && to.col === from.col + flow(from) && (!to.sum || edge.atSum);
    const round = from.row === 0 && to.row > 0 && to.col <= from.col && lastOfRow(to);
    if (free && (beside || round)) {
      sideTaken.add(to.id);
      return { edge, way: beside ? "straight" : "ell", gap, channel: 0, nth: 0, of: 1 };
    }
    edge.into = from.row > to.row ? "bottom" : "top";
    return { edge, way: "channel", gap, channel: from.row > to.row ? to.row + 1 : to.row, nth: 0, of: 1 };
  });
  // The wires into one side of a block are set along it in the order they come from, left to right.
  const sides = new Map<string, Plan[]>();
  for (const p of out) {
    if (p.way !== "channel" || p.edge.atSum) continue;
    const key = `${p.edge.to}|${p.edge.into}`;
    sides.set(key, [...(sides.get(key) ?? []), p]);
  }
  for (const list of sides.values()) {
    list.sort((a, b) => byId.get(a.edge.from)!.col - byId.get(b.edge.from)!.col || (a.edge.id < b.edge.id ? -1 : 1));
    list.forEach((p, k) => Object.assign(p, { nth: k, of: list.length }));
  }
  return out;
}

export const SUM_X = SUM_R + SUM_OUT;
/** Room in a gap for the name of a wire that crosses it, and its arrow under the name. */
export const NAME_ROOM = 40;

/** How much of a gap its lanes take, from its left edge. */
export const lanesWidth = (count: number): number => (count ? PAD + LANE * (count - 1) + 8 : 2);

export interface Frame {
  /** How many columns there are: the gap after the last has this number. */
  cols: number;
  colX: number[];
  gapX: number[];
  rowY: number[];
  rowH: number[];
  channelY: number[];
  width: number;
  height: number;
}

/** The lanes of the gaps. Each block's lanes stand by it, as its wires leave it: the forward
 *  path's from the left of a gap, the way back's from its right (kept under `back(gap)`).
 *  `up` holds the forward path's lanes that rise through where its names are written, over
 *  its wires, first of their side; `down` the way back's that fall through where its names are
 *  written, under its wires, first of theirs; `across` the gaps a wire of the way back crosses
 *  straight, from one block to the next. */
export interface GapLanes {
  all: Lanes;
  up: Lanes;
  down: Lanes;
  across: Set<number>;
}

/** Where the lanes of the way back in a gap are kept, apart from the forward path's. */
export const back = (gap: number): number => -1 - gap;

/** How wide a gap is: room for its lanes, the forward path's and the way back's side by side,
 *  and for what each row asks of it. On the forward path, the lanes that rise through its
 *  names, then the name of the wire that crosses it, then a summing junction; on the way back,
 *  the name, then the lanes that fall through it. The last gap holds the forward path's lanes
 *  as they turn down past the motor, and the count of a bus beside them. */
function gapWidth(nodes: LNode[], g: number, cols: number, l: GapLanes): number {
  const [left, right] = [l.all.count(g), l.all.count(back(g))];
  if (g === 0) return PAD + lanesWidth(Math.max(left, right));
  if (g === cols) return left ? PAD + LANE * (left - 1) + 20 : PAD;
  const sum = nodes.some((n) => n.col === g && n.sum) ? SUM_ROOM : 0;
  return Math.max(
    lanesWidth(left) + lanesWidth(right),
    lanesWidth(left) + sum,
    lanesWidth(l.up.count(g)) + NAME_ROOM + sum,
    l.across.has(g) ? lanesWidth(l.down.count(back(g))) + NAME_ROOM : 0,
  );
}

export function frameOf(nodes: LNode[], l: GapLanes, channels: Lanes): Frame {
  const rows = Math.max(...nodes.map((n) => n.row)) + 1;
  const cols = Math.max(...nodes.map((n) => n.col)) + 1;
  const gapX: number[] = [];
  const colX: number[] = [];
  let x = 0;
  for (let g = 0; g <= cols; g++) {
    gapX.push(x);
    x += gapWidth(nodes, g, cols, l);
    if (g === cols) break;
    colX.push(x);
    x += Math.max(...nodes.filter((n) => n.col === g).map((n) => n.w));
  }
  const rowH = Array.from({ length: rows }, (_, r) => Math.max(...nodes.filter((n) => n.row === r).map((n) => n.h)));
  const rowY: number[] = [];
  const channelY: number[] = [];
  let y = 0;
  for (let r = 0; r <= rows; r++) {
    channelY.push(y);
    const lanes = channels.count(r);
    // The channel above the forward path also holds the names of the loops.
    if (r === 0) y += lanes ? PAD + CHANNEL_LANE * lanes + ENTRY : PAD + BAND_HEAD;
    else if (r === rows) y += PAD;
    else y += lanes ? 2 * ENTRY + CHANNEL_LANE * (lanes - 1) : 2 * PAD;
    if (r === rows) break;
    rowY.push(y);
    y += rowH[r];
  }
  return { cols, colX, gapX, rowY, rowH, channelY, width: x, height: y };
}

/** Where the summing junction of a regulator stands: on its row's line, before the block. */
export const sumOf = (n: LNode): [number, number] => [n.x - SUM_X, n.axis];

export function route(
  plan: Plan,
  nodes: Map<string, LNode>,
  f: Frame,
  gaps: Lanes,
  channels: Lanes,
): [number, number][] {
  const from = nodes.get(plan.edge.from)!;
  const to = nodes.get(plan.edge.to)!;
  // The motor's wires come to its circle, not to the box round it.
  const inset = (n: LNode) => (n.symbol.kind === "machine" ? n.w / 2 - MACHINE_R : 0);
  const start: [number, number] = [flow(from) > 0 ? from.x + from.w - inset(from) : from.x + inset(from), from.axis];
  const [sx, sy] = sumOf(to);
  const side: [number, number] =
    flow(to) > 0 ? (plan.edge.atSum ? [sx - SUM_R, sy] : [to.x + inset(to), to.axis]) : [to.x + to.w, to.axis];
  if (plan.way === "straight") return [start, side];
  // A lane stands by the block whose wires run in it: right of it on the forward path, left of
  // it on the way back.
  const up =
    flow(from) > 0
      ? f.gapX[plan.gap] + PAD + LANE * gaps.of(plan.gap, from.id)
      : f.colX[plan.gap] - PAD - LANE * gaps.of(back(plan.gap), from.id);
  if (plan.way === "ell") return [start, [up, start[1]], [up, to.axis], [to.x + to.w, to.axis]];
  const first = plan.channel === 0 ? PAD : ENTRY;
  const cy = f.channelY[plan.channel] + first + CHANNEL_LANE * channels.of(plan.channel, from.id);
  const top = plan.edge.into === "top";
  const end: [number, number] = plan.edge.atSum
    ? [sx, top ? sy - SUM_R : sy + SUM_R]
    : [to.x + (to.w * (plan.nth + 1)) / (plan.of + 1), top ? to.y : to.y + to.h];
  return [start, [up, start[1]], [up, cy], [end[0], cy], end];
}

export const same = (a: [number, number], b: [number, number]): boolean => a[0] === b[0] && a[1] === b[1];
export const key = (p: [number, number]): string => `${p[0]},${p[1]}`;

/** Whether a point lies on a stretch, between its ends. */
export function within(p: [number, number], a: [number, number], b: [number, number]): boolean {
  if (same(p, a) || same(p, b)) return false;
  if (a[0] === b[0]) return p[0] === a[0] && p[1] > Math.min(a[1], b[1]) && p[1] < Math.max(a[1], b[1]);
  return p[1] === a[1] && p[0] > Math.min(a[0], b[0]) && p[0] < Math.max(a[0], b[0]);
}

/** The trunks: for each block, the wires that leave it cut where one turns off from another,
 *  each stretch knowing which signals travel in it; and a dot wherever three stretches meet. */
export function netsOf(edges: LEdge[]): LNet[] {
  const bySource = new Map<string, LEdge[]>();
  for (const e of edges) bySource.set(e.from, [...(bySource.get(e.from) ?? []), e]);
  return [...bySource.entries()].map(([from, list]) => {
    const corners = list.flatMap((e) => e.points);
    const segs = new Map<string, LSeg & { wires: Set<string> }>();
    for (const e of list) {
      for (let k = 1; k < e.points.length; k++) {
        const [a, b] = [e.points[k - 1], e.points[k]];
        const cuts = corners.filter((p) => within(p, a, b));
        const along = (p: [number, number]) => Math.abs(p[0] - a[0]) + Math.abs(p[1] - a[1]);
        const stops = [a, ...cuts.sort((p, q) => along(p) - along(q)), b].filter(
          (p, i, all) => !i || !same(p, all[i - 1]),
        );
        for (let s = 1; s < stops.length; s++) {
          const [p, q] = [stops[s - 1], stops[s]];
          const id = key(p) < key(q) ? `${key(p)}|${key(q)}` : `${key(q)}|${key(p)}`;
          const seg = segs.get(id) ?? { a: p, b: q, n: 0, edges: [], wires: new Set<string>() };
          segs.set(id, seg);
          e.wires.forEach((w) => seg.wires.add(w));
          seg.edges.push(e.id);
          seg.n = Math.max(seg.n, seg.wires.size, e.n);
        }
      }
    }
    const met = new Map<string, { at: [number, number]; ends: Set<string>; edges: Set<string> }>();
    for (const s of segs.values()) {
      for (const [p, q] of [
        [s.a, s.b],
        [s.b, s.a],
      ] as const) {
        const m = met.get(key(p)) ?? { at: p, ends: new Set<string>(), edges: new Set<string>() };
        met.set(key(p), m);
        m.ends.add(key(q));
        s.edges.forEach((id) => m.edges.add(id));
      }
    }
    const dots = [...met.values()]
      .filter((m) => m.ends.size > 2)
      .map((m) => ({ x: m.at[0], y: m.at[1], edges: [...m.edges] }));
    return { from, segs: [...segs.values()].map(({ a, b, n, edges: on }) => ({ a, b, n, edges: on })), dots };
  });
}

/** The summing junctions, each with a sign beside every wire that comes into it, as a control
 *  engineer writes them: under the arrow that comes in from the left, right of one that comes
 *  in from below or above. */
export function sumsOf(nodes: LNode[], edges: LEdge[]): LSum[] {
  return nodes
    .filter((n) => n.sum)
    .map((n) => {
      const [x, y] = sumOf(n);
      const signs = edges
        .filter((e) => e.to === n.id && e.atSum)
        .map((e) => {
          const text = e.minus ? ("−" as const) : ("+" as const);
          if (e.into === "bottom") return { text, x: x + 11, y: y + SUM_R + 15 };
          if (e.into === "top") return { text, x: x + 11, y: y - SUM_R - 4 };
          return { text, x: x - SUM_R - 6, y: y + 18 };
        });
      return { node: n.id, x, y, r: SUM_R, out: n.x, signs };
    });
}

/** Where a wire of one trunk crosses a wire of another without joining it. */
export function crossingsOf(nets: LNet[]): LCross[] {
  const out = new Map<string, LCross>();
  const between = (v: number, p: number, q: number) => v > Math.min(p, q) + 1 && v < Math.max(p, q) - 1;
  const uprights = nets.flatMap((net) =>
    net.segs.filter((s) => s.a[0] === s.b[0] && s.a[1] !== s.b[1]).map((s) => ({ net, s })),
  );
  const levels = nets.flatMap((net) =>
    net.segs.filter((s) => s.a[1] === s.b[1] && s.a[0] !== s.b[0]).map((s) => ({ net, s })),
  );
  for (const { net, s } of uprights) {
    const [x] = s.a;
    for (const { s: t } of levels.filter((m) => m.net !== net && between(x, m.s.a[0], m.s.b[0]))) {
      const y = t.a[1];
      if (between(y, s.a[1], s.b[1])) out.set(key([x, y]), { x, y, n: s.n, edges: s.edges });
    }
  }
  return [...out.values()];
}

/** A loop's name, from what its regulator is: a current regulator closes a current loop, direct
 *  torque control a torque and flux loop (it has no current regulator). The engine's own word
 *  for the loop is the last resort. */
export function loopName(loop: string, members: LNode[]): string {
  const regulator = [...members].reverse().find((n) => n.loop === loop);
  const title = regulator?.title ?? "";
  const params = Object.keys(regulator?.block?.params ?? {});
  if (/\bspeed\b/i.test(title)) return "Speed loop";
  if (/\btorque\b/i.test(title))
    return /direct torque/i.test(title) || params.some((p) => /flux/.test(p)) ? "Torque and flux loop" : "Torque loop";
  if (/\bcurrent\b/i.test(title)) return "Current loop";
  if (/\bposition\b/i.test(title)) return "Position loop";
  return `${loop.charAt(0).toUpperCase()}${loop.slice(1).replace(/_/g, " ")} loop`;
}

/** The loops, each as the stretch of the forward path it takes in: the speed loop up to its
 *  regulator, the inner loop from there to its own, each named by what its regulator is. */
export function groupsOf(nodes: LNode[], f: Frame): LGroup[] {
  const row0 = nodes.filter((n) => n.row === 0 && n.role === "block").sort((a, b) => a.col - b.col);
  const out: LGroup[] = [];
  let start = 0;
  for (const loop of ["speed", "current"]) {
    const end = row0.map((n) => n.loop).lastIndexOf(loop);
    if (end < start) continue;
    const members = row0.slice(start, end + 1);
    // Round its blocks, and a summing junction before the first with the sign under its arrow.
    const x = members[0].x - (members[0].sum ? SUM_ROOM + 12 : 0) - 6;
    const last = members[members.length - 1];
    const right = last.x + last.w + 6;
    out.push({
      loop,
      label: loopName(loop, members),
      x,
      y: f.rowY[0] - BAND_HEAD,
      w: right - x,
      h: f.rowH[0] + BAND_HEAD + 6,
    });
    start = end + 1;
  }
  return out;
}

/** The block the arrow keys reach from each: along its wires left and right, and to the
 *  nearest block of the row above or below. */
export function nearOf(nodes: LNode[], edges: LEdge[]): Layout["near"] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const near: Layout["near"] = {};
  const closest = (n: LNode, row: number) =>
    nodes.filter((m) => m.row === row).sort((a, b) => Math.abs(a.col - n.col) - Math.abs(b.col - n.col))[0]?.id;
  for (const n of nodes) {
    const fed = edges.filter((e) => e.to === n.id).map((e) => byId.get(e.from)!);
    const feeds = edges.filter((e) => e.from === n.id).map((e) => byId.get(e.to)!);
    const sameRow = (list: LNode[]) => list.find((m) => m.row === n.row)?.id ?? list[0]?.id;
    const before = sameRow(fed);
    const after = sameRow(feeds);
    near[n.id] = {
      left: flow(n) > 0 ? before : after,
      right: flow(n) > 0 ? after : before,
      up: closest(n, n.row - 1),
      down: closest(n, n.row + 1),
    };
  }
  return near;
}
