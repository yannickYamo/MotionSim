// The scheme as it is saved: its block diagram drawn as the lab draws it (its loops, its
// blocks' symbols, its wires with their names and its summing junctions), in the print inks,
// and the table of every block's figures: its value with its unit, whether it is as tuned or
// was changed, and where it came from. Made off the screen from the scheme itself, so it is
// the same whatever is zoomed or open in the lab.

import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { tunedValue } from "./actions";
import { BLOCK_H } from "./drawn";
import { gainWord } from "./gain";
import { layoutOf } from "./layout";
import type { Layout } from "./layout";
import { written } from "./series";
import { lab } from "./store";
import { Symbol } from "./symbol";
import type { LabState } from "./store";
import type { Scheme, Value } from "./types";
import { worded } from "./ui";
import { Wiring } from "./wiring";
import { forPaper, holder, rgbaOf, printInk } from "./pdfkit";
import type { Target } from "./pdfkit";

export interface ParamRow {
  block: string;
  name: string;
  value: string;
  state: string;
  source: string;
}

function valueWords(v: Value | undefined, unit: string): string {
  if (v === undefined) return "–";
  if (typeof v === "number") return written(v, unit);
  if (typeof v === "boolean") return v ? "on" : "off";
  return worded(String(v));
}

type Kind = NonNullable<LabState["presets"]>["blocks"][string];
type Block = NonNullable<LabState["scheme"]>["blocks"][number];

/** Whether a figure is as tuned, was changed (and from what), or is the scheme's own. */
function stateOf(tuned: Value | undefined, value: Value | undefined, unit: string): string {
  if (tuned === undefined) return "set here";
  return tuned === value ? "as tuned" : `changed, tuned ${valueWords(tuned, unit)}`;
}

/** One block's figures: those its kind describes, then any more it carries. */
function blockRows(s: LabState, b: Block, kind: Kind | undefined): ParamRow[] {
  const described = kind?.params ?? [];
  const extra = Object.keys(b.params).filter((n) => !described.some((p) => p.name === n));
  return [...described.map((p) => p.name), ...extra].map((name) => {
    const p = described.find((x) => x.name === name);
    const unit = p?.unit ?? "";
    const value = b.params[name] ?? p?.value;
    return {
      block: kind?.title ?? worded(b.kind),
      name: gainWord(name),
      value: valueWords(value, unit),
      state: stateOf(tunedValue(s, b.name, name), value, unit),
      source: b.sources?.[name] || p?.source || (p?.about ?? ""),
    };
  });
}

/** Every block's figures, block by block in the scheme's order: what each is, its value with its
 *  unit, as tuned or changed (and from what), and where it came from. */
/** How often a scheme of duties is updated against its carrier, in words. */
export function updateWords(t: Scheme["timing"]): string {
  if (t.update === "multi") return `${t.per_carrier ?? 4} times a carrier period`;
  if (t.update === "every") return `once every ${t.carriers ?? 2} carrier periods`;
  if (t.update === "double") return "twice a carrier period";
  return "once a carrier period";
}

export function paramRows(s: LabState = lab.get()): ParamRow[] {
  const scheme = s.scheme;
  if (!scheme) return [];
  const kinds = s.presets?.blocks ?? {};
  const rows = scheme.blocks.flatMap((b) => blockRows(s, b, kinds[b.kind]));
  const t = scheme.timing;
  rows.push({
    block: "Timing",
    name: "Control update",
    value: t.f_control ? written(t.f_control, "Hz") : updateWords(t),
    state: "as tuned",
    source: `${worded(t.update)} update${t.delay ? ", with one period of delay" : ""}`,
  });
  return rows;
}

const NS = "http://www.w3.org/2000/svg";

/** The scheme drawn as the lab draws it, off the screen: its loops, wires and blocks. */
function Drawn({ layout }: { layout: Layout }) {
  return (
    <>
      {layout.groups.map((g) => (
        <div
          key={g.loop}
          className="lab-band"
          data-band
          style={{ position: "absolute", left: g.x, top: g.y, width: g.w, height: g.h }}
        >
          <span>{g.label}</span>
        </div>
      ))}
      <Wiring layout={layout} />
      {layout.nodes.map((n) => (
        <div
          key={n.id}
          className={`lab-node is-${n.role} is-${n.symbol.kind}`}
          data-block={n.id}
          style={{ position: "absolute", left: n.x, top: n.y, width: n.w, height: BLOCK_H }}
        >
          <Symbol node={n} />
        </div>
      ))}
    </>
  );
}

const inkOr = (css: string, or: string) => {
  const c = rgbaOf(css);
  return c ? printInk(c) : or;
};

/** A loop: a soft region round its blocks, named at its head. */
function bandMarks(band: HTMLElement, g: Layout["groups"][number], target: Target): Element[] {
  const st = getComputedStyle(band);
  const rect = document.createElementNS(NS, "rect");
  const r = parseFloat(st.borderTopLeftRadius) || 12;
  for (const [k, v] of Object.entries({ x: g.x, y: g.y, width: g.w, height: g.h, rx: r }))
    rect.setAttribute(k, String(v));
  rect.setAttribute("fill", inkOr(st.backgroundColor, "none"));
  rect.setAttribute("stroke", parseFloat(st.borderTopWidth) > 0 ? inkOr(st.borderTopColor, "none") : "none");
  const ss = getComputedStyle(band.querySelector("span") ?? band);
  const size = parseFloat(ss.fontSize) || 12;
  const word = document.createElementNS(NS, "text");
  word.setAttribute("x", String(g.x + (parseFloat(st.paddingLeft) || 12)));
  word.setAttribute("y", String(g.y + size + (parseFloat(st.paddingTop) || 6)));
  word.setAttribute("font-size", String(size));
  word.setAttribute("fill", inkOr(ss.color, "#45413a"));
  word.setAttribute("font-family", target === "pdf" ? "helvetica" : "'Funnel Sans', Helvetica, Arial, sans-serif");
  word.textContent = g.label;
  return [rect, word];
}

/** The drawing off the screen gathered into one SVG, in the inks of the file. */
function gathered(hold: HTMLElement, layout: Layout, target: Target): SVGSVGElement {
  const out = document.createElementNS(NS, "svg");
  out.setAttribute("viewBox", `0 0 ${layout.width} ${layout.height}`);
  out.setAttribute("width", String(layout.width));
  out.setAttribute("height", String(layout.height));
  hold.querySelectorAll<HTMLElement>("[data-band]").forEach((band, k) => {
    const g = layout.groups[k];
    if (g) out.append(...bandMarks(band, g, target));
  });
  const wiring = hold.querySelector<SVGSVGElement>("svg.lab-wiring");
  if (wiring) {
    const w = forPaper(wiring, target);
    w.setAttribute("x", "0");
    w.setAttribute("y", "0");
    out.append(w);
  }
  for (const n of layout.nodes) {
    const sym = hold.querySelector<SVGSVGElement>(`[data-block="${CSS.escape(n.id)}"] svg.lab-sym`);
    if (!sym) continue;
    const c = forPaper(sym, target);
    for (const [k, v] of Object.entries({ x: n.x, y: n.y, width: n.w, height: BLOCK_H })) c.setAttribute(k, String(v));
    c.setAttribute("overflow", "visible");
    out.append(c);
  }
  return out;
}

/** The scheme's drawing, in its own units: its width and height, and its marks for a file. */
export function schemeDrawing(target: Target): { svg: SVGSVGElement; w: number; h: number } | null {
  const s = lab.get();
  if (!s.scheme || !s.presets) return null;
  const layout: Layout = layoutOf(s.scheme, s.presets.blocks, s.presets.sources);
  const hold = holder("lab-diagram");
  hold.style.width = `${layout.width}px`;
  hold.style.height = `${layout.height}px`;
  const root = createRoot(hold);
  try {
    flushSync(() => root.render(<Drawn layout={layout} />));
    return { svg: gathered(hold, layout, target), w: layout.width, h: layout.height };
  } finally {
    root.unmount();
    hold.remove();
  }
}
