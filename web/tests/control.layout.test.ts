// The diagram as a control engineer draws it, held to geometry: for every scheme the engine
// lists, signals that travel together are one bus, no wire runs through a block, and no name
// lies on a block or on another name. The schemes are the engine's own, recorded from it.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { BLOCK_H, CAPTION_PX, CHANNEL_LANE, INVERTER, layoutOf, MACHINE_R, MOTOR } from "../src/control/layout";
import type { Box, Layout } from "../src/control/layout";
import { pathOf } from "../src/control/path";
import { countBox, headOf, signBox } from "../src/control/naming";
import { LEAST, MOST } from "../src/control/diagram";
import { symbolOf } from "../src/control/symbols";
import type { Presets, Scheme } from "../src/control/types";
import allFile from "./fixtures/control-schemes-all.json";

const all = allFile as unknown as Pick<Presets, "schemes" | "blocks" | "sources">;
const drawn = (s: Scheme): Layout => layoutOf(s, all.blocks, all.sources);
const each = all.schemes.map((s) => [s.id, s] as const);
const css = readFileSync(new URL("../src/control/lab.css", import.meta.url), "utf8");

type Point = [number, number];
/** Whether a level or upright stretch goes through the inside of a box. */
const through = (a: Point, b: Point, box: Box): boolean => {
  const [x0, x1] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])];
  const [y0, y1] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
  return x1 > box.x + 0.5 && x0 < box.x + box.w - 0.5 && y1 > box.y + 0.5 && y0 < box.y + box.h - 0.5;
};
const overlap = (a: Box, b: Box): boolean => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

describe("the wiring of every scheme the engine lists", () => {
  it("has the schemes to hold to", () => {
    expect(all.schemes.length).toBeGreaterThanOrEqual(18);
  });

  it.each(each)("draws the three phases of %s as one bus of three", (_, s) => {
    const l = drawn(s);
    const toMotor = l.edges.filter((e) => e.from === INVERTER && e.to === MOTOR);
    expect(toMotor).toHaveLength(1);
    expect(toMotor[0].n).toBe(3);
    expect(toMotor[0].tick).not.toBeNull();
    // What reads the three phase currents reads them from one wire, marked with its count.
    for (const b of s.blocks) {
      const phases = Object.values(b.inputs).filter((w) => /^plant\.i_[abc]$/.test(w));
      if (phases.length < 3) continue;
      const into = l.edges.filter((e) => e.from === MOTOR && e.to === b.name && e.wires.includes("plant.i_a"));
      expect(into).toHaveLength(1);
      expect(into[0].wires).toEqual(expect.arrayContaining(phases));
      expect(into[0].n).toBe(3);
    }
    // No two runs join the same two blocks the same way.
    expect(new Set(l.edges.map((e) => e.id)).size).toBe(l.edges.length);
    // A stretch of a trunk is as thick as the lines that run in it.
    for (const net of l.nets) for (const seg of net.segs) expect(seg.n).toBeGreaterThanOrEqual(1);
  });

  it.each(each)("runs no wire of %s through a block", (_, s) => {
    const l = drawn(s);
    for (const e of l.edges) {
      const last = e.points.length - 2;
      e.points.slice(1).forEach((p, k) => {
        const q = e.points[k];
        expect(p[0] === q[0] || p[1] === q[1], `${e.id} runs square`).toBe(true);
        for (const n of l.nodes) {
          // The motor's own wires run on inside its box, level along its line, to its circle.
          const own = n.symbol.kind === "machine" && ((e.from === n.id && k === 0) || (e.to === n.id && k === last));
          if (own) expect(q[1] === n.axis && p[1] === n.axis, `${e.id} level into the motor`).toBe(true);
          else expect(through(q, p, n), `${e.id} through ${n.id}`).toBe(false);
        }
      });
    }
  });

  it.each(each)("lands every arrow of %s flush on the edge or the circle it points at", (_, s) => {
    const l = drawn(s);
    for (const e of l.edges) {
      const to = l.nodes.find((n) => n.id === e.to)!;
      const [x, y] = e.points[e.points.length - 1];
      const [px, py] = e.points[e.points.length - 2];
      // Square to the edge it lands on, with room for the head and some wire before it.
      expect(px === x || py === y, `${e.id} comes in square`).toBe(true);
      expect(Math.abs(x - px) + Math.abs(y - py), `${e.id} has room for its arrow`).toBeGreaterThanOrEqual(12);
      if (e.atSum) {
        const sum = l.sums.find((m) => m.node === e.to)!;
        expect(Math.hypot(x - sum.x, y - sum.y), `${e.id} on the circle`).toBe(sum.r);
        // From the left, from below or from above: the way it comes in is the way it points.
        const into = e.into === "side" ? px < x && y === sum.y : e.into === "bottom" ? py > y : py < y;
        expect(into && (e.into === "side" || x === sum.x), `${e.id} points at the centre`).toBe(true);
      } else if (to.symbol.kind === "machine") {
        expect([x, y]).toEqual([to.x + to.w / 2 - MACHINE_R, to.axis]);
        expect(px).toBeLessThan(x);
      } else if (e.into === "side") {
        expect(y, `${e.id} on the block's line`).toBe(to.axis);
        expect(x === to.x ? px < x : x === to.x + to.w && px > x, `${e.id} on the side it faces`).toBe(true);
      } else {
        expect(y, `${e.id} on the ${e.into}`).toBe(e.into === "top" ? to.y : to.y + to.h);
        expect(x > to.x && x < to.x + to.w).toBe(true);
        expect(e.into === "top" ? py < y : py > y).toBe(true);
      }
    }
    // A junction's error lands on its regulator's edge.
    for (const sum of l.sums) expect(sum.out).toBe(l.nodes.find((n) => n.id === sum.node)!.x);
  });

  it.each(each)("keeps every name, count and sign of %s clear of the arrows and the wires", (_, s) => {
    const l = drawn(s);
    const heads: Box[] = [
      ...l.edges.map((e) => headOf(e.points[e.points.length - 1], e.points[e.points.length - 2])),
      ...l.sums.map((m) => ({ x: m.out - 9, y: m.y - 5, w: 9, h: 10 })),
    ];
    const marks = [
      ...l.edges.filter((e) => e.label).map((e) => ({ id: `name of ${e.id}`, box: e.label as Box })),
      ...l.edges.filter((e) => e.tick).map((e) => ({ id: `count of ${e.id}`, box: countBox(e.tick!) })),
      ...l.sums.flatMap((m) => m.signs.map((x, k) => ({ id: `sign ${k} of ${m.node}`, box: signBox(x) }))),
    ];
    for (const m of marks) {
      for (const h of heads) expect(overlap(m.box, h), `${m.id} on an arrow`).toBe(false);
      if (m.id.startsWith("sign")) continue;
      for (const e of l.edges)
        e.points.slice(1).forEach((p, k) => {
          const q = e.points[k];
          expect(through(q, p, m.box), `${m.id} on the wire ${e.id}`).toBe(false);
        });
    }
    // A trunk branches well clear of every arrow's head.
    for (const net of l.nets)
      for (const d of net.dots)
        for (const h of heads) {
          const near = { x: h.x - 6, y: h.y - 6, w: h.w + 12, h: h.h + 12 };
          expect(
            overlap({ x: d.x - 3.4, y: d.y - 3.4, w: 6.8, h: 6.8 }, near),
            `a dot of ${net.from} by an arrow`,
          ).toBe(false);
        }
    // A sign stands clear of the names and of its own circle.
    for (const m of l.sums)
      for (const sign of m.signs) {
        const box = signBox(sign);
        expect(Math.hypot(sign.x - m.x, sign.y - 6 - m.y)).toBeGreaterThan(m.r + 4);
        for (const e of l.edges) {
          if (e.label) expect(overlap(box, e.label), `sign of ${m.node} on ${e.id}`).toBe(false);
          if (e.tick) expect(overlap(box, countBox(e.tick)), `sign of ${m.node} on the count of ${e.id}`).toBe(false);
        }
      }
  });

  it.each(each)("breaks a wire of %s where it crosses another without joining it", (_, s) => {
    const l = drawn(s);
    const found = new Set<string>();
    const strictly = (v: number, a: number, b: number) => v > Math.min(a, b) + 1 && v < Math.max(a, b) - 1;
    for (const up of l.nets)
      for (const a of up.segs.filter((x) => x.a[0] === x.b[0]))
        for (const other of l.nets.filter((n) => n !== up))
          for (const b of other.segs.filter((x) => x.a[1] === x.b[1]))
            if (strictly(a.a[0], b.a[0], b.b[0]) && strictly(b.a[1], a.a[1], a.b[1])) found.add(`${a.a[0]},${b.a[1]}`);
    expect(new Set(l.crossings.map((c) => `${c.x},${c.y}`))).toEqual(found);
    // A crossing is never where a trunk branches.
    const dots = new Set(l.nets.flatMap((n) => n.dots.map((d) => `${d.x},${d.y}`)));
    for (const c of l.crossings) expect(dots.has(`${c.x},${c.y}`)).toBe(false);
  });

  it.each(each)("ends every wire of %s on the block it goes to, with room for its arrow", (_, s) => {
    const l = drawn(s);
    for (const e of l.edges) {
      const to = l.nodes.find((n) => n.id === e.to)!;
      const [x, y] = e.points[e.points.length - 1];
      const [px, py] = e.points[e.points.length - 2];
      // On the edge of the block, or at its summing junction just before it.
      expect(x).toBeGreaterThanOrEqual(to.x - 60);
      expect(x).toBeLessThanOrEqual(to.x + to.w + 0.5);
      expect(y).toBeGreaterThanOrEqual(to.y - 0.5);
      expect(y).toBeLessThanOrEqual(to.y + to.h + 0.5);
      expect(Math.abs(x - px) + Math.abs(y - py), `${e.id} has a last stretch`).toBeGreaterThanOrEqual(8);
    }
  });

  it.each(each)("sets no name of %s on a block, a junction or another name", (_, s) => {
    const l = drawn(s);
    const names = l.edges.filter((e) => e.label).map((e) => ({ id: e.id, box: e.label as Box }));
    expect(names.length).toBeGreaterThan(l.edges.length / 2);
    names.forEach((a, i) => {
      for (const n of l.nodes) expect(overlap(a.box, n), `${a.id} on ${n.id}`).toBe(false);
      for (const sum of l.sums) {
        const circle = { x: sum.x - sum.r, y: sum.y - sum.r, w: 2 * sum.r, h: 2 * sum.r };
        expect(overlap(a.box, circle), `${a.id} on the junction of ${sum.node}`).toBe(false);
      }
      names.slice(i + 1).forEach((b) => expect(overlap(a.box, b.box), `${a.id} on ${b.id}`).toBe(false));
      expect(a.box.x >= 0 && a.box.x + a.box.w <= l.width && a.box.y >= 0 && a.box.y + a.box.h <= l.height).toBe(true);
    });
  });

  it.each(each)("draws a summing junction of %s with a sign for each wire into it", (_, s) => {
    const l = drawn(s);
    for (const sum of l.sums) {
      const into = l.edges.filter((e) => e.to === sum.node && e.atSum);
      expect(sum.signs).toHaveLength(into.length);
      expect(sum.signs.some((x) => x.text === "−")).toBe(true);
      expect(sum.signs.some((x) => x.text === "+")).toBe(true);
    }
  });

  it.each(each)("frames each loop of %s round its own blocks, its name clear of them", (_, s) => {
    const l = drawn(s);
    for (const g of l.groups) {
      expect(g.label.length).toBeGreaterThan(0);
      const inside = l.nodes.filter(
        (n) => n.x >= g.x && n.x + n.w <= g.x + g.w && n.y >= g.y && n.y + n.h <= g.y + g.h,
      );
      expect(inside.length).toBeGreaterThan(0);
      // The name has the head of the frame to itself: no block starts above its foot.
      for (const n of inside) expect(n.y).toBeGreaterThanOrEqual(g.y + 24);
    }
  });

  it.each(each)("is the same drawing of %s every time, and moves nothing for a figure", (_, s) => {
    const again = JSON.parse(JSON.stringify(s)) as Scheme;
    expect(drawn(again)).toEqual(drawn(s));
    for (const b of again.blocks)
      for (const k of Object.keys(b.params)) if (typeof b.params[k] === "number") b.params[k] = 1.5;
    expect(drawn(again).edges.map((e) => e.points)).toEqual(drawn(s).edges.map((e) => e.points));
  });
});

describe("the lit path", () => {
  it("is a wire alone with the two blocks it joins, when a wire is pointed at", () => {
    const l = drawn(all.schemes[0]);
    const e = l.edges[3];
    const lit = pathOf(l.edges, { edge: e.id });
    expect([...lit.wires]).toEqual([e.id]);
    expect([...lit.blocks].sort()).toEqual([e.from, e.to].sort());
  });

  it("is every wire up to the motor and down to it, when a block is pointed at", () => {
    const l = drawn(all.schemes[0]);
    const lit = pathOf(l.edges, { block: "speed" });
    expect(lit.blocks.has("speed") && lit.blocks.has(MOTOR) && lit.blocks.has("shaper")).toBe(true);
    for (const id of lit.wires) {
      const e = l.edges.find((x) => x.id === id)!;
      expect(lit.blocks.has(e.from) && lit.blocks.has(e.to)).toBe(true);
    }
  });
});

describe("the blocks as symbols on a grid", () => {
  it.each(each)("sets every block of %s at one height, each column at one width", (_, s) => {
    const l = drawn(s);
    for (const n of l.nodes) {
      expect(n.h).toBe(BLOCK_H);
      expect(new Set(l.nodes.filter((m) => m.col === n.col).map((m) => m.w)).size).toBe(1);
      // A block's short name fits inside it, at the size it is set in: half an em a letter.
      if (n.symbol.kind !== "title") expect(n.symbol.caption.length * CAPTION_PX * 0.5).toBeLessThan(n.w - 8);
    }
  });

  it.each(each)("names the wires of %s by their signals, as a control engineer writes them", (_, s) => {
    const l = drawn(s);
    const said = (e: (typeof l.edges)[number]) =>
      (e.label?.words ?? []).map((w) => `${w.text}${w.star ? "*" : ""}${w.sub}`).join(",");
    const between = (from: string, to: string) => l.edges.find((e) => e.from === from && e.to === to);
    expect(said(between(INVERTER, MOTOR)!)).toBe("vabc");
    for (const e of l.edges.filter((x) => x.label)) expect(said(e)).not.toMatch(/_|undefined/);
    if (s.blocks.some((b) => b.name === "current_ref")) {
      const ref = l.edges.find((e) => e.from === "current_ref" && e.label);
      if (ref) expect(said(ref)).toBe("i*dq");
    }
    const park = s.blocks.find((b) => b.kind === "park");
    const fromPark = park && l.edges.find((e) => e.from === park.name && e.label && e.n === 2);
    if (fromPark) expect(said(fromPark)).toBe("idq");
    const clarke = l.edges.find((e) => e.from === "clarke" && e.to === "park");
    if (clarke?.label) expect(said(clarke)).toBe("iαβ");
  });

  it("names the usual servo's wires ω*, T*, i*dq, v*dq, vαβ, d abc, v abc, i abc, iαβ, idq and θ", () => {
    const l = drawn(all.schemes.find((s) => s.id === "foc_servo")!);
    const names = l.edges.flatMap((e) => (e.label?.words ?? []).map((w) => `${w.text}${w.star ? "*" : ""}${w.sub}`));
    for (const n of ["ω*", "T*", "i*dq", "v*dq", "vαβ", "dabc", "vabc", "iabc", "iαβ", "idq", "θ"])
      expect(names, n).toContain(n);
  });

  it.each(each)("fits all of %s in a 1440 px window, its names never under the least size", (_, s) => {
    const l = drawn(s);
    const room = 1440 - 2 * 24 - 2;
    expect(room / (l.width * 1.02)).toBeGreaterThanOrEqual(LEAST);
  });

  it("reads the usual servo at 12 px or more once it is fitted to a 1440 px window", () => {
    const l = drawn(all.schemes.find((s) => s.id === "foc_servo")!);
    // The room the diagram has at 1440: the window less the lab's two 24 px gutters and the
    // canvas's hairlines; fitted with its 1 % of padding each side, as the canvas fits it.
    const room = 1440 - 2 * 24 - 2;
    const zoom = Math.min(1.15, room / (l.width * 1.02));
    expect(CAPTION_PX * zoom).toBeGreaterThanOrEqual(12);
    // The symbols themselves are larger than the names under them.
    expect(21 * zoom).toBeGreaterThan(16);
  });

  it("draws no live value, trace or gain on a block: only its symbol and its short name", () => {
    const s = all.schemes.find((x) => x.id === "foc_servo")!;
    for (const b of s.blocks) {
      const sym = symbolOf({
        role: "block",
        kind: b.kind,
        hint: all.blocks[b.kind]?.role ?? "",
        title: b.kind,
        known: true,
        block: b,
        inputs: Object.keys(b.inputs).map((port) => ({ port })),
        outputs: (all.blocks[b.kind]?.outputs ?? []).map((o) => ({ name: o.name })),
      });
      expect(Object.keys(sym).sort()).toEqual(expect.arrayContaining(["caption", "kind"]));
      expect(JSON.stringify(sym)).not.toMatch(/\d\.\d/);
    }
    expect(css).not.toMatch(/\.lab-port|\.lab-spark/);
  });

  /** The rules of the sheet that touch a selector. */
  const rulesOf = (name: string): string =>
    [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter(([, selector]) => selector.split(",").some((x) => x.trim().endsWith(name)))
      .map(([, , body]) => body)
      .join("\n");

  it("never cuts a title short: it wraps, with no ellipsis and no clamp of its lines", () => {
    const title = rulesOf(".lab-node-title");
    expect(title).toContain("overflow-wrap");
    expect(title).not.toMatch(/ellipsis|line-clamp|nowrap|overflow:\s*hidden/);
    expect(rulesOf(".lab-node-head")).not.toMatch(/ellipsis|line-clamp|overflow:\s*hidden/);
    expect(rulesOf(".lab-band span")).not.toMatch(/ellipsis|overflow:\s*hidden/);
  });
});

describe("motion kept down", () => {
  const from = css.indexOf("@media (prefers-reduced-motion: reduce)");
  const reduced = css.slice(from, css.indexOf("@media", from + 10));

  it("runs a mark along the lit path, and only by its dash offset", () => {
    expect(css).toMatch(/\.lab-wire\[data-path\] \.lab-flow \{[^}]*animation: lab-flow/);
    const frames = css.slice(
      css.indexOf("@keyframes lab-flow"),
      css.indexOf("}", css.indexOf("@keyframes lab-flow")) + 1,
    );
    expect(frames).toContain("stroke-dashoffset");
    expect(frames).not.toMatch(/width|height|top|left|margin|padding/);
  });

  it("leaves the path lit and runs nothing along it under reduced motion", () => {
    expect(reduced).toMatch(/\.lab-wire\[data-path\] \.lab-flow \{[^}]*animation: none/);
    expect(reduced).not.toMatch(/\.lab-lit/);
    expect(reduced).toMatch(/animation: none !important/);
  });
});

describe("the lists of the lab, opened", () => {
  const page = readFileSync(new URL("../src/style.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  /** The bodies of the rules whose selector is exactly this one, outside any media query. */
  const rule = (selector: string): string =>
    [...page.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter(([, s]) => s.trim() === selector)
      .map(([, , body]) => body)
      .join("\n");

  it("are drawn dark by the browser, their group names in the page's own inks", () => {
    // Every rule for the boxed list, taken together: one of them tells the browser it is dark.
    const lists = rule(".control select");
    expect(lists).toMatch(/color-scheme:\s*dark/);
    expect(lists).toMatch(/background-color:\s*var\(--surface\)/);
    const group = rule(".control select optgroup");
    expect(group).toMatch(/background:\s*var\(--raised\)/);
    expect(group).toMatch(/color:\s*var\(--ink-3\)/);
    expect(rule(".control select option")).toMatch(/color:\s*var\(--ink\)/);
  });
});

/** The drawing as it is fitted into the lab's canvas, pane px wide, in a window 900 px tall
 *  (diagram.tsx, Refit; lab.css, .lab-canvas): its scale, and where its corner stands. */
function fitted(l: Layout, pane: number) {
  const tall = l.height + 16;
  const height = Math.min(Math.max(tall * LEAST + 2, (pane * tall) / l.width), Math.min(0.62 * 900, tall * MOST + 2));
  const whole = Math.min(pane / l.width, height / tall) * 0.98;
  const zoom = Math.max(LEAST, Math.min(MOST, whole));
  const panned = zoom > whole * 1.02;
  const x = panned ? 0 : (pane - l.width * zoom) / 2;
  const y = panned ? 44 + Math.max(0, (height - tall * zoom) / 2) : (height - tall * zoom) / 2;
  return { zoom, x, y, height: panned ? height + 44 : height };
}

/** The canvas of the lab in a window 1440 px wide: the window less the lab's margins. */
const LAPTOP = 1392;

describe("the lines that come back from the motor", () => {
  /** The level stretches of every trunk, each with the block it comes from. */
  const levels = (l: Layout) =>
    l.nets.flatMap((net) =>
      net.segs
        .filter((s) => s.a[1] === s.b[1] && s.a[0] !== s.b[0])
        .map((s) => ({ from: net.from, y: s.a[1], x0: Math.min(s.a[0], s.b[0]), x1: Math.max(s.a[0], s.b[0]) })),
    );

  it.each(each)("run on lanes of %s about 12 px apart on a laptop, never bunched", (_, s) => {
    const l = drawn(s);
    const { zoom } = fitted(l, LAPTOP);
    const all = levels(l);
    let beside = 0;
    for (const a of all) {
      for (const b of all) {
        const along = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0);
        if (a.from === b.from || a.y === b.y || along <= 12) continue;
        beside++;
        const apart = Math.abs(a.y - b.y);
        expect(apart, `${a.from} and ${b.from}, in the drawing's units`).toBeGreaterThanOrEqual(CHANNEL_LANE);
        expect(apart * zoom, `${a.from} and ${b.from}, px on a laptop`).toBeGreaterThanOrEqual(10.5);
      }
    }
    // The cascaded schemes bring two lines or more back side by side: the case is held, not skipped.
    if (s.id === "foc_high_speed") {
      expect(beside).toBeGreaterThan(0);
      expect(CHANNEL_LANE * zoom).toBeGreaterThanOrEqual(11.5);
      expect(CHANNEL_LANE * zoom).toBeLessThanOrEqual(13.5);
    }
  });

  it.each(each)("stay clear of the zoom presses at the left of %s, and so does every block and name", (_, s) => {
    const l = drawn(s);
    const { zoom, x, y, height } = fitted(l, LAPTOP);
    // The presses stand in the canvas's lower left corner: 44 px wide, three and their gaps
    // tall, a step in from each edge (lab.css, .react-flow__controls). Six px are kept round them.
    const keep = { x: 0, y: height - 9 - 140 - 6, w: 9 + 44 + 6, h: 140 + 9 + 6 };
    const shown = (b: Box): Box => ({ x: b.x * zoom + x, y: b.y * zoom + y, w: b.w * zoom, h: b.h * zoom });
    for (const n of l.nodes) expect(overlap(shown(n), keep), `block ${n.id}`).toBe(false);
    for (const e of l.edges) {
      if (e.label) expect(overlap(shown(e.label), keep), `the name of ${e.id}`).toBe(false);
      e.points.slice(1).forEach((p, k) => {
        const q = e.points[k];
        const run = { x: Math.min(p[0], q[0]) - 1, y: Math.min(p[1], q[1]) - 1, w: Math.abs(p[0] - q[0]) + 2, h: 2 };
        run.h += Math.abs(p[1] - q[1]);
        expect(overlap(shown(run), keep), `wire ${e.id}`).toBe(false);
      });
    }
  });
});
