// A block's drawing in the inspector full screen: alive with the cursor of the run, over a strip
// of what the block puts out, so that pointing at the trace moves the drawing with it.

import type { Box } from "../charts/frame";
import type { Span } from "../eventplot/zoom";
import { escape } from "../format";
import { spanOf, slugOf, stripsDrawn, stripsRead } from "./fullgraphs";
import type { Scoped } from "./fullgraphs";
import { parts } from "./fullview";
import type { Graph, TimeDrawn } from "./fullview";
import { layoutOf } from "./layout";
import type { LNode } from "./layout";
import type { StripTrace } from "./plots";
import { unshown } from "./probes";
import { lab, tracesOf } from "./store";

type Back = () => HTMLElement | null;

/** The live drawing of the block in the inspector. */
const liveFace = () => document.querySelector<SVGSVGElement>(".lab-inspector .lab-animation svg.lab-face-svg");

/** The block the inspector is open on, as the diagram draws it. */
export function selectedNode(): LNode | null {
  const s = lab.get();
  if (!s.scheme || !s.presets || !s.selected) return null;
  const layout = layoutOf(s.scheme, s.presets.blocks, s.presets.sources);
  return layout.nodes.find((n) => n.id === s.selected) ?? null;
}

/** The drawing in its top part, scaled to fit; the strip of what it puts out under it. */
function faceOver(face: SVGSVGElement, sc: Scoped, title: string, v: Span, w: number, h: number): TimeDrawn {
  const fh = Math.round(h * 0.56);
  const p = parts(new XMLSerializer().serializeToString(liveFace() ?? face));
  const [vx, vy, vw, vh] = p.view;
  const k = Math.min(w / vw, (fh - 8) / vh);
  const [x, fw, fhh] = [((w - vw * k) / 2).toFixed(1), (vw * k).toFixed(1), (vh * k).toFixed(1)];
  const slot =
    `<svg data-face-slot x="${x}" y="0" width="${fw}" height="${fhh}" viewBox="${vx} ${vy} ${vw} ${vh}">` +
    `<g class="lab-face-svg">${p.inside}</g></svg>`;
  const strip = stripsDrawn(sc, [0], v, w, h - fh);
  const sp = parts(strip.svg);
  const box: Box = { ...strip.box, y: strip.box.y + fh };
  const under = `<svg x="0" y="${fh}" width="${w}" height="${sp.view[3]}" viewBox="0 0 ${w} ${sp.view[3]}">`;
  return {
    svg:
      `<svg class="chart" viewBox="0 0 ${w} ${h}" aria-label="${escape(title)}, over ${escape(sp.label)}">` +
      `${slot}${under}${sp.inside}</svg></svg>`,
    box,
    dots: strip.dots,
    at: (t) => strip.at(t).map((y) => (y === null ? null : y + fh)),
  };
}

/** A block's drawing full screen, alive with the cursor, over what it puts out through the run:
 *  pointed at, the trace moves the cursor and the drawing answers. */
export function faceGraph(back: Back): Graph | null {
  const face = liveFace();
  const node = selectedNode();
  if (!face || !node) return null;
  const series = tracesOf(lab.get());
  const outs = node.outputs.filter((o) => !unshown(o.wire) && series?.wires[o.wire]?.length);
  const title = `${node.title}: at the cursor`;
  const base = {
    title,
    file: `block-${slugOf(node.id)}`,
    back,
    heading: "The block",
    rows: [["Block", node.title]] as [string, string][],
  };
  const still = new XMLSerializer().serializeToString(face);
  if (!series || !outs.length) return { ...base, figures: () => [still] };
  const traced: StripTrace[] = outs
    .slice(0, 4)
    .map((o, k) => ({ name: o.wire, values: series.wires[o.wire], ink: k % 4, dash: 0 }));
  const sc: Scoped = {
    groups: [{ key: node.id, title: "What it puts out", yLabel: "", traces: [] }],
    traced: [traced],
    units: new Map(outs.map((o) => [o.wire, o.unit])),
    about: new Map(outs.map((o) => [o.wire, o.about])),
    series,
  };
  const whole = spanOf(series.t);
  return {
    ...base,
    time: {
      whole,
      cursor: true,
      draw: (v, w, h) => faceOver(face, sc, title, v, w, h),
      read: (t) => stripsRead(sc, [0], whole, t),
      // The drawing on the screen is the inspector's own, copied as it moves.
      drawn: (svg) => {
        const slot = svg.querySelector("[data-face-slot] > g");
        const live = liveFace();
        if (slot && live && slot.innerHTML !== live.innerHTML) slot.innerHTML = live.innerHTML;
      },
    },
  };
}
