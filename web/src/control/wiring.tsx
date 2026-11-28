// The wires of the diagram, drawn as one layer over the blocks' plane: each trunk in its
// stretches, a dot where it branches; and on each wire its arrow, its name in the italic of
// mathematics, and the slash and count of a bus as Simulink marks one. Every wire is a probe, as
// in Simulink: pointed at, its note says what it carries at the cursor; pressed (or reached by the
// keyboard and pressed), it is drawn in the scope, or is no longer, and carries a dot in the ink of
// its trace while it is. What a wire carries is read in its note and in the scope's legend, never
// written on the drawing, where it would fall on the names and the blocks. Summing junctions are
// drawn here too: a circle, a sign beside each wire that comes into it.

import { backToBlock, nextWire } from "./rover";
import { memo, useRef } from "react";
import { useFollow } from "./follow";
import { written } from "./series";
import { pinWires } from "./actions";
import { pathOf } from "./layout";
import type { Layout, LEdge, LNet, LSum } from "./layout";
import { light } from "./path";
import { inksOf, plainWords, probesOf, signalWords } from "./probes";
import { hideTip, placeTip, showTip } from "./probetip";
import { lab, useLab } from "./store";
import { usualWires } from "./wires";

type Pt = [number, number];
const line = (points: Pt[]): string => points.map(([x, y], k) => `${k ? "L" : "M"}${x} ${y}`).join("");
const keyOf = (p: Pt): string => `${p[0]},${p[1]}`;
/** A point moved along a stretch towards another, by so much. */
const toward = (p: Pt, q: Pt, by: number): Pt => [
  p[0] + Math.sign(q[0] - p[0]) * by,
  p[1] + Math.sign(q[1] - p[1]) * by,
];
const lengthOf = (p: Pt, q: Pt): number => Math.abs(p[0] - q[0]) + Math.abs(p[1] - q[1]);
/** How round a wire's bends are drawn. */
const BEND = 5;
/** How far a wire stops short of its arrow's point: its end hides under the arrow. */
const UNDER_HEAD = 4;
/** A wire's run as it is drawn: a little rounded at its bends, stopping under its arrow. */
const runOf = (points: Pt[]): string =>
  pathOf([...points.slice(0, -1), toward(points[points.length - 1], points[points.length - 2], UNDER_HEAD)], BEND);

/** The stretches of a trunk as they are drawn: each cut back where it turns into the next, a
 *  little curve joining the two, and stopped under the point of an arrow it ends at. */
function strokesOf(net: LNet, tips: Set<string>): { d: string; n: number; edges: string[] }[] {
  const ends = new Map<string, LNet["segs"]>();
  for (const s of net.segs) for (const p of [s.a, s.b]) ends.set(keyOf(p), [...(ends.get(keyOf(p)) ?? []), s]);
  const dots = new Set(net.dots.map((d) => keyOf([d.x, d.y])));
  const upright = (s: LNet["segs"][number]) => s.a[0] === s.b[0];
  const bend = (p: Pt) => {
    const at = ends.get(keyOf(p))!;
    return at.length === 2 && !dots.has(keyOf(p)) && upright(at[0]) !== upright(at[1]);
  };
  const other = (s: LNet["segs"][number], p: Pt): Pt => (keyOf(s.a) === keyOf(p) ? s.b : s.a);
  const out = net.segs.map((s) => {
    const cut = (p: Pt) =>
      bend(p)
        ? Math.min(BEND, lengthOf(s.a, s.b) / 2)
        : tips.has(keyOf(p))
          ? Math.min(UNDER_HEAD, lengthOf(s.a, s.b))
          : 0;
    return { d: line([toward(s.a, s.b, cut(s.a)), toward(s.b, s.a, cut(s.b))]), n: s.n, edges: s.edges };
  });
  for (const [k, at] of ends) {
    const p = k.split(",").map(Number) as Pt;
    if (!bend(p)) continue;
    const [s, t] = at;
    const r = Math.min(BEND, lengthOf(s.a, s.b) / 2, lengthOf(t.a, t.b) / 2);
    const [p0, p1] = [toward(p, other(s, p), r), toward(p, other(t, p), r)];
    out.push({
      d: `M${p0[0]} ${p0[1]}Q${p[0]} ${p[1]} ${p1[0]} ${p1[1]}`,
      n: Math.min(s.n, t.n),
      edges: s.edges.filter((e) => t.edges.includes(e)),
    });
  }
  return out;
}

/** The name of a wire, on a ground of its own (the canvas's, or a loop's where it lies in one)
 *  so that nothing runs through its letters. */
function Name({ edge, onBand }: { edge: LEdge; onBand: boolean }) {
  const l = edge.label!;
  const x = l.x + l.w / 2;
  return (
    <g className={`lab-name${onBand ? " is-on-band" : ""}`} aria-hidden="true">
      <rect x={l.x + 1} y={l.y + 1} width={l.w - 2} height={l.h - 2} rx="3" />
      <text x={x} y={l.y + l.h - 5.5} textAnchor="middle">
        {l.words.map((w, k) => (
          <tspan key={k}>
            {k ? ", " : ""}
            {w.text}
            {w.star ? (
              <tspan className="lab-sub" dy="-6">
                *
              </tspan>
            ) : null}
            {w.sub ? (
              <tspan className="lab-sub" dy={w.star ? 9 : 3} dx={w.star ? -4.5 : 0}>
                {w.sub}
              </tspan>
            ) : null}
            {w.sub || w.star ? <tspan dy={w.sub ? -3 : 6}>{"\u200b"}</tspan> : null}
          </tspan>
        ))}
      </text>
    </g>
  );
}

/** The mark of a bus: a stroke across it, and how many lines it stands for. */
function Tick({ edge }: { edge: LEdge }) {
  const t = edge.tick!;
  return (
    <g className="lab-tick" aria-hidden="true">
      <path
        d={t.upright ? `M${t.x - 5} ${t.y + 4}L${t.x + 5} ${t.y - 4}` : `M${t.x - 4} ${t.y + 5}L${t.x + 4} ${t.y - 5}`}
      />
      <text
        x={t.upright ? (t.flip ? t.x - 8 : t.x + 8) : t.x + 6}
        y={t.upright ? t.y + 4 : t.flip ? t.y - 6 : t.y + 15}
        textAnchor={t.upright && t.flip ? "end" : "start"}
      >
        {edge.n}
      </text>
    </g>
  );
}

/** The length of the wire's run under its name, less what its ends take (an arrow's head, a
 *  junction's ring): the room a reading written there has. */
export function runRoom(edge: LEdge): number {
  const l = edge.label;
  if (!l) return 0;
  const mid = l.x + l.w / 2;
  let room = 0;
  for (let k = 1; k < edge.points.length; k++) {
    const [a, b] = [edge.points[k - 1], edge.points[k]];
    if (a[1] === b[1] && Math.min(a[0], b[0]) <= mid && mid <= Math.max(a[0], b[0])) {
      room = Math.max(room, Math.abs(b[0] - a[0]));
    }
  }
  return room ? Math.max(0, room - 16) : l.w + 24;
}

/** What a probed wire carries at the cursor, written under its name: it follows the cursor,
 *  so it moves as the run is played, without anything being drawn again by React. */
function Value({ edge, units }: { edge: LEdge; units: Map<string, string> }) {
  const el = useRef<SVGTextElement>(null);
  const l = edge.label!;
  const shown = edge.wires.slice(0, 2);
  const room = runRoom(edge);
  useFollow(
    (read) => {
      const text = el.current;
      if (!text) return;
      text.textContent = shown.map((w) => written(read(w), units.get(w) ?? "", 3)).join(", ");
      // A reading wider than its wire's own run would lie over the blocks and the junction at
      // its ends: it is not drawn there (the scope's legend and the probe's tip still say it).
      const wide = typeof text.getComputedTextLength === "function" ? text.getComputedTextLength() : 0;
      text.style.visibility = wide > room ? "hidden" : "";
    },
    [shown.join(","), room],
  );
  return (
    <text ref={el} className="lab-value" x={l.x + l.w / 2} y={l.y + l.h + 12} textAnchor="middle" aria-hidden="true" />
  );
}

/** An arrow's head, its point at the origin: it lands flush on the edge it points at. */
const HEAD = "M-9 -4.5L0 0L-9 4.5z";

/** Say something once to whoever listens to the lab. */
const say = (el: Element, words: string): void => {
  const said = el.closest(".control-lab, .lab")?.querySelector(".lab-said");
  if (said) said.textContent = words;
};

/** Room, in px, left before a wire's head: its arrow, or the junction it meets. */
const HEAD_ROOM = 14;

/** Where a probed wire carries its dot, in the ink of its trace: just after its name, level
 *  with it (over the name it hid a mark or a star), or over the middle of its last run where it
 *  has no name. */
function Badge({ edge, inks }: { edge: LEdge; inks: string }) {
  const marks = inks.split(",").slice(0, 3);
  const l = edge.label;
  const [a, b] = [edge.points[edge.points.length - 2], edge.points[edge.points.length - 1]];
  const level = a[1] === b[1];
  // After the name where the dots end clear of the wire's head; else centred above the name.
  const span = (marks.length - 1) * 8;
  const after = !!l && (!level || l.x + l.w + 6 + span + 3.6 <= Math.max(a[0], b[0]) - HEAD_ROOM);
  const x = l ? (after ? l.x + l.w + 6 : l.x + l.w / 2 - span / 2) : (a[0] + b[0]) / 2 + (level ? 0 : 8);
  const y = l ? (after ? l.y + l.h / 2 : l.y - 6) : (a[1] + b[1]) / 2 - (level ? 8 : 0);
  return (
    <g className="lab-probe" aria-hidden="true">
      {marks.map((m, k) => (
        <circle key={k} className={m ? `pr-${m.split(".")[0]}` : "pr-none"} cx={x + k * 8} cy={y} r="3.6" />
      ))}
    </g>
  );
}

interface HitProps {
  edge: LEdge;
  /** The blocks it runs between, as they are titled. */
  between: [string, string];
  d: string;
  pinned: boolean;
  named: string;
  units: Map<string, string>;
  onPress: (el: Element) => void;
}

/** What is pressed of a wire: a broad stroke along it, reached by the keyboard too. */
function Hit({ edge, between, d, pinned, named, units, onPress }: HitProps) {
  return (
    <path
      className="lab-hit"
      d={d}
      tabIndex={-1}
      role="button"
      aria-pressed={pinned}
      aria-label={`${named}, from ${between[0]} to ${between[1]}. ${pinned ? "In the scope" : "Not in the scope"}.`}
      onClick={(e) => onPress(e.currentTarget)}
      onKeyDown={(e) => {
        // Reached from its block by W: W goes on round, Escape or an arrow goes back.
        if (nextWire(e) || backToBlock(e)) return;
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault();
        onPress(e.currentTarget);
      }}
      onPointerEnter={(e) => {
        light({ edge: edge.id });
        showTip(edge, units, pinned, e.clientX, e.clientY);
      }}
      onPointerMove={(e) => placeTip(e.clientX, e.clientY)}
      onPointerLeave={() => {
        light(null);
        hideTip();
      }}
      onFocus={(e) => {
        light({ edge: edge.id });
        const r = e.currentTarget.getBoundingClientRect();
        showTip(edge, units, pinned, r.left + r.width / 2, r.top + r.height / 2);
      }}
      onBlur={() => {
        light(null);
        hideTip();
      }}
    />
  );
}

/** A wire pressed: its lines drawn in the scope, or taken out, and said. */
function probe(el: Element, edge: LEdge, named: string): void {
  const series = lab.get().run.answer?.series.wires;
  const drawable = edge.wires.filter((w) => !series || series[w]);
  if (!drawable.length) return say(el, "This wire has no trace of its own to draw.");
  const now = pinWires(drawable, usualWires(lab.get()));
  say(el, `${named}: ${now ? "drawn in the scope" : "taken out of the scope"}.`);
  hideTip();
}

/** One wire: lit along its whole run when its path is, with its arrow where it comes in. A
 *  probe: pressed, it is drawn in the scope, or is no longer. */
const Wire = memo(function Wire({
  edge,
  onBand,
  units,
  titles,
  delay,
}: {
  edge: LEdge;
  onBand: boolean;
  units: Map<string, string>;
  titles: Map<string, string>;
  /** When the pulse that runs along the drawing as it opens reaches this wire, in ms. */
  delay: number;
}) {
  const ran = useLab((s) => !!s.run.answer);
  const on = useLab((s) => s.selected !== null && (s.selected === edge.from || s.selected === edge.to));
  const pinned = useLab((s) => {
    const drawn = probesOf(s);
    return edge.wires.every((w) => drawn.includes(w));
  });
  const inks = useLab((s) => {
    const map = inksOf(s);
    return edge.wires.map((w) => (map.get(w) ? `${map.get(w)!.ink}.${map.get(w)!.dash}` : "")).join(",");
  });
  const [x, y] = edge.points[edge.points.length - 1];
  const [px, py] = edge.points[edge.points.length - 2];
  const turn = (Math.atan2(y - py, x - px) * 180) / Math.PI;
  const d = runOf(edge.points);
  const named = edge.wires.map((w) => plainWords(signalWords(w, units.get(w) ?? ""))).join(", ");
  const press = (el: Element) => probe(el, edge, named);
  const marks = [on && "is-on", edge.back && "is-back", edge.n > 1 && "is-bus", pinned && "is-pinned"];
  return (
    <g
      className={["lab-wire", ...marks.filter(Boolean)].join(" ")}
      data-edge={edge.id}
      data-wire-from={edge.from}
      data-wire-to={edge.to}
    >
      <path className="lab-lit" d={d} aria-hidden="true" />
      <path className="lab-flow" d={d} aria-hidden="true" />
      <path className="lab-pulse" d={d} pathLength={100} style={{ animationDelay: `${delay}ms` }} aria-hidden="true" />
      <path className="lab-arrow" d={HEAD} transform={`translate(${x} ${y}) rotate(${turn})`} aria-hidden="true" />
      {edge.tick ? <Tick edge={edge} /> : null}
      {edge.label ? <Name edge={edge} onBand={onBand} /> : null}
      {pinned ? <Badge edge={edge} inks={inks} /> : null}
      {pinned && ran && edge.label ? <Value edge={edge} units={units} /> : null}
      <Hit
        edge={edge}
        between={[titles.get(edge.from) ?? edge.from, titles.get(edge.to) ?? edge.to]}
        d={d}
        pinned={pinned}
        named={named}
        units={units}
        onPress={press}
      />
    </g>
  );
});

/** The unit of every wire the drawing names, kept while the drawing is the same. */
const unitsMemo = new WeakMap<Layout, Map<string, string>>();
function unitsOf(layout: Layout): Map<string, string> {
  let units = unitsMemo.get(layout);
  if (!units) {
    units = new Map(layout.nodes.flatMap((n) => n.outputs.map((o) => [o.wire, o.unit] as const)));
    unitsMemo.set(layout, units);
  }
  return units;
}

/** A summing junction as it is drawn on paper: a circle, the signs beside what comes in, and
 *  the error going on into the regulator. */
function Sum({ sum }: { sum: LSum }) {
  return (
    <g className="lab-sum" data-sum={sum.node} aria-hidden="true">
      <path className="lab-sum-out" d={`M${sum.x + sum.r} ${sum.y}H${sum.out - UNDER_HEAD}`} />
      <path className="lab-arrow" d={HEAD} transform={`translate(${sum.out} ${sum.y})`} />
      <circle cx={sum.x} cy={sum.y} r={sum.r} />
      {sum.signs.map((s, k) => (
        <text key={k} x={s.x} y={s.y} textAnchor="middle">
          {s.text}
        </text>
      ))}
    </g>
  );
}

/** When the opening pulse reaches a wire: along the forward path from left to right in the
 *  first 560 ms, then back along the feedback from right to left, done by 1 s. */
export function pulseDelay(edge: LEdge, width: number): number {
  const x = Math.min(...edge.points.map((p) => p[0])) / (width || 1);
  return Math.round(edge.back ? 560 + (1 - x) * 440 : x * 560);
}

/** The trunks as drawn: their stretches, the dots where they branch, the gaps where they cross. */
function Nets({ layout, tips }: { layout: Layout; tips: Set<string> }) {
  return (
    <g className="lab-nets" aria-hidden="true">
      {layout.nets.flatMap((net) =>
        strokesOf(net, tips).map((s) => (
          <path
            key={`${net.from}-${s.d}`}
            className={`lab-seg${s.n > 1 ? " is-bus" : ""}`}
            data-edges={s.edges.join(" ")}
            d={s.d}
          />
        )),
      )}
      {layout.nets.flatMap((net) =>
        net.dots.map((p) => (
          <circle
            key={`${net.from}-${p.x}-${p.y}`}
            className="lab-dot"
            data-edges={p.edges.join(" ")}
            cx={p.x}
            cy={p.y}
            r="3.4"
          />
        )),
      )}
      {/* A crossing is not a junction: the level wire is broken where the upright one goes on. */}
      {layout.crossings.map((c) => (
        <g key={`cross-${c.x}-${c.y}`} className="lab-cross">
          <path className="lab-cross-gap" d={`M${c.x - 5} ${c.y}H${c.x + 5}`} />
          <path
            className={`lab-seg${c.n > 1 ? " is-bus" : ""}`}
            data-edges={c.edges.join(" ")}
            d={`M${c.x} ${c.y - 7}V${c.y + 7}`}
          />
        </g>
      ))}
    </g>
  );
}

export const Wiring = memo(function Wiring({ layout }: { layout: Layout }) {
  const units = unitsOf(layout);
  const titles = new Map(layout.nodes.map((n) => [n.id, n.title]));
  const tips = new Set(layout.edges.map((e) => keyOf(e.points[e.points.length - 1])));
  const within = (b: { x: number; y: number; w: number; h: number }) =>
    layout.groups.some((g) => b.x >= g.x && b.y >= g.y && b.x + b.w <= g.x + g.w && b.y + b.h <= g.y + g.h);
  return (
    <svg
      className="lab-wiring"
      width={layout.width}
      height={layout.height}
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      role="group"
      aria-label="The wires: each is a probe, pressed to draw it in the scope. W from a block reaches its wires"
    >
      <Nets layout={layout} tips={tips} />
      {layout.edges.map((e) => (
        <Wire
          key={e.id}
          edge={e}
          onBand={!!e.label && within(e.label)}
          units={units}
          titles={titles}
          delay={pulseDelay(e, layout.width)}
        />
      ))}
      {layout.sums.map((s) => (
        <Sum key={s.node} sum={s} />
      ))}
    </svg>
  );
});
