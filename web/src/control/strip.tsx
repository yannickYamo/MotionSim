// One strip of the scope: the traces of one quantity through time, its legend beside it with
// each trace's name as an engineer writes it and its value at the cursor. The strip follows
// the cursor itself: its line, a dot on each trace, the values, and how far the traces are
// drawn while the run plays, written into the drawing once a frame at most.

import { useEffect, useMemo, useRef, useState } from "react";
import { togglePlotted, unplot } from "./actions";
import { stripsGraph } from "./fullgraphs";
import { openGraph } from "./fullview";
import type { Word } from "./drawn";
import type { Note } from "./findings";
import { calm, playing } from "./play";
import { stripPlot } from "./plots";
import { leastSpan } from "./units";
import type { StripAxes, StripTrace } from "./plots";
import { plainWords, signalWords } from "./probes";
import { reading } from "./figures";
import { valueAt, written } from "./series";
import { cursor, lab } from "./store";
import type { Run, Series } from "./types";
import { Icon } from "./ui";
import { usualWires } from "./wires";
import type { Group } from "./wires";

/** A signal's name as it is written on the diagram: the italic of mathematics, small letters
 *  under it, a star on what was asked for. */
export function MathName({ word }: { word: Word }) {
  const long = [...word.text].length > 2;
  return (
    <span className={`scope-name${long ? " is-word" : ""}`}>
      {word.text}
      {word.star ? <sup>*</sup> : null}
      {word.sub ? <sub>{word.sub}</sub> : null}
    </span>
  );
}

/** How wide a strip's plot is shown, in pixels: it is drawn at that size. */
export function useWidth(host: React.RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(720);
  useEffect(() => {
    const el = host.current;
    if (!el || typeof ResizeObserver !== "function") return;
    const seen = new ResizeObserver(() => {
      const plot = el.querySelector<HTMLElement>(".scope-plot");
      const w = Math.round(plot?.clientWidth || el.clientWidth);
      if (w > 0) setWidth((now) => (Math.abs(now - w) > 1 ? w : now));
    });
    seen.observe(el);
    return () => seen.disconnect();
  }, [host]);
  return width;
}

export interface StripProps {
  group: Group;
  traces: StripTrace[];
  units: Map<string, string>;
  about: Map<string, string>;
  from: number;
  to: number;
  width: number;
  /** The traces drawn, and the live ones the cursor reads, as the scope shows them. */
  series: Series;
  read: () => Series | null;
  last: boolean;
  first: boolean;
  step: Run["step"];
  on: boolean;
  /** What the run found on this strip, drawn as labelled regions. */
  notes?: Note[];
  /** The run whose arrival draws the traces in, once: null where nothing is to be drawn in. */
  fresh?: unknown;
}

/** The shared curve, cubic-bezier(0.2, 0, 0, 1) (--ease-out), as a function of time. */
export function easeOut(p: number): number {
  if (p <= 0) return 0;
  if (p >= 1) return 1;
  // Solve x(s) = p for the curve's parameter, then read y(s).
  const [x1, y1, x2, y2] = [0.2, 0, 0, 1];
  const at = (a: number, b: number, s: number) => 3 * a * s * (1 - s) ** 2 + 3 * b * s * s * (1 - s) + s ** 3;
  let lo = 0;
  let hi = 1;
  for (let n = 0; n < 24; n++) {
    const mid = (lo + hi) / 2;
    if (at(x1, x2, mid) < p) lo = mid;
    else hi = mid;
  }
  return at(y1, y2, (lo + hi) / 2);
}

/** How long the traces of a fresh run take to draw in, in ms: --dur-4, less a frame. */
export const DRAW_IN = 420;

/** The traces of a strip drawn in from the left, once, through the clip that playing uses. */
function drawIn(host: HTMLElement, width: number): void {
  const rect = host.querySelector(".scope-past-clip");
  if (!rect) return;
  host.classList.add("is-drawing");
  const from = performance.now();
  const step = (now: number) => {
    const p = Math.min(1, (now - from) / DRAW_IN);
    rect.setAttribute("width", String(width * easeOut(p)));
    if (p < 1) requestAnimationFrame(step);
    else host.classList.remove("is-drawing");
  };
  requestAnimationFrame(step);
}

/** What a strip's cursor reads from: each wire's unit, and the live traces. */
interface Reads {
  units: Map<string, string>;
  read: () => Series | null;
}

/** The marks of one strip that follow the cursor: its line, a dot on each trace, the value
 *  of each in its legend, and how far the traces are drawn while the run plays. */
function follow(host: HTMLElement, axes: StripAxes, traces: StripTrace[], reads: Reads, on: boolean) {
  const { units, read } = reads;
  const svg = host.querySelector(".scope-plot svg");
  const line = svg?.querySelector(".scope-cursor");
  const past = svg?.querySelector(".scope-past-clip");
  const dots = [...(svg?.querySelectorAll(".scope-dot") ?? [])];
  const when = svg?.querySelector(".scope-when");
  const values = [...host.querySelectorAll<HTMLElement>("[data-value]")];
  const shown = traces.filter((t) => !t.ghost);
  const { box, from, to, lo, hi } = axes;
  return (t: number) => {
    const s = read();
    const share = (t - from) / (to - from || 1);
    const inside = share >= 0 && share <= 1;
    const x = box.x + Math.min(1, Math.max(0, share)) * box.w;
    line?.setAttribute("visibility", inside ? "visible" : "hidden");
    if (inside) line?.setAttribute("d", `M${x.toFixed(1)} ${box.y - 4}V${box.y + box.h + 4}`);
    if (when) placeWhen(when, t, x, inside, box);
    // Played, the traces are drawn up to the cursor; at rest, whole.
    past?.setAttribute("width", String(on && playing() ? Math.max(0, x - box.x) : box.w));
    shown.forEach((tr, k) => {
      const v = s ? valueAt(s.t, s.wires[tr.name], t) : null;
      const dot = dots[k];
      const y = v === null ? null : box.y + box.h - ((v - lo) / (hi - lo || 1)) * box.h;
      const seen = inside && y !== null && y >= box.y - 4 && y <= box.y + box.h + 4;
      dot?.setAttribute("visibility", seen ? "visible" : "hidden");
      if (seen) {
        dot?.setAttribute("cx", x.toFixed(1));
        dot?.setAttribute("cy", y.toFixed(1));
      }
    });
    for (const el of values) {
      const wire = el.dataset.value!;
      el.textContent = readout(wire, s ? valueAt(s.t, s.wires[wire], t) : null, units.get(wire) ?? "", lo, hi);
    }
  };
}

/** The chip on the time axis under the cursor: the instant, kept inside the plot at its ends. */
function placeWhen(when: Element, t: number, x: number, inside: boolean, box: StripAxes["box"]): void {
  when.setAttribute("visibility", inside ? "visible" : "hidden");
  if (!inside) {
    when.parentElement?.querySelector("text.axis")?.setAttribute("opacity", "1");
    return;
  }
  const said = written(t, "s");
  const half = (said.length * 7 + 14) / 2;
  const at = Math.min(box.x + box.w - half, Math.max(box.x + half, x));
  const text = when.querySelector("text");
  const back = when.querySelector("rect");
  if (text) {
    text.textContent = said;
    text.setAttribute("x", at.toFixed(1));
  }
  back?.setAttribute("x", (at - half).toFixed(1));
  back?.setAttribute("width", (2 * half).toFixed(1));
  // At the axis's end the chip stands on the axis's own name ("time, ms"): the name gives way.
  const name = when.parentElement?.querySelector<SVGTextElement>("text.axis");
  name?.setAttribute("opacity", at + half > box.x + box.w - AXIS_NAME ? "0" : "1");
}

/** The room the time axis's name takes at its right end, px. */
const AXIS_NAME = 72;

/** The stage's safe state, as its wire carries it. */
const SAFE_WORDS: Record<number, string> = { 0: "switching", 1: "gates off", 2: "shorted" };

/** A trace's value at the cursor, read against its strip's span; the safe state in words. */
const readout = (wire: string, v: number | null, unit: string, lo: number, hi: number): string =>
  wire === "inverter.safe" && v !== null ? (SAFE_WORDS[Math.round(v)] ?? "–") : reading(v, unit, lo, hi);

/** A small sample of how a trace is drawn, beside its name. */
const Swatch = ({ ink, dash }: { ink: number; dash: number }) => (
  <svg className="scope-swatch" viewBox="0 0 18 8" width="18" height="8" aria-hidden="true">
    <path className={`scope-trace pr-${ink}${dash ? ` da-${dash}` : ""}`} d="M1 4H17" />
  </svg>
);

/** A strip's title as it is said after "the": "The stage once tripped" is "stage once tripped". */
const stripName = (title: string): string => title.toLowerCase().replace(/^the\s+/, "");

/** One trace of the legend: how it is drawn, its name, its value at the cursor, and the way
 *  to take it out. */
function Row({ trace, unit, said }: { trace: StripTrace; unit: string; said: string }) {
  const word = signalWords(trace.name, unit);
  return (
    <li data-wire={trace.name} title={said}>
      <Swatch ink={trace.ink} dash={trace.dash} />
      <MathName word={word} />
      <span className="scope-value lab-live" data-value={trace.name}>
        –
      </span>
      <button
        type="button"
        className="scope-remove"
        // A trace is taken out by keyboard from its wire on the diagram, or its strip from the
        // strip's own button: two dozen of these in the way between Play and the tabs is too many.
        tabIndex={-1}
        aria-label={`Take ${plainWords(word)}, ${said}, out of the scope`}
        title="Take it out"
        onClick={() => togglePlotted(trace.name, usualWires(lab.get()))}
      >
        <Icon name="x" />
      </button>
    </li>
  );
}

/** A strip's name and its traces, each with its value at the cursor and the way to take it out. */
function Legend({
  group,
  shown,
  units,
  about,
}: {
  group: Group;
  shown: StripTrace[];
  units: Map<string, string>;
  about: Map<string, string>;
}) {
  const unit = group.yLabel.includes(",") ? group.yLabel.slice(group.yLabel.lastIndexOf(",") + 1).trim() : "";
  return (
    <div className="scope-legend">
      <div className="scope-strip-head">
        <h4>{unit ? `${group.title}, ${unit}` : group.title}</h4>
        <button
          type="button"
          className="scope-full"
          aria-label={`Open the ${stripName(group.title)} strip full screen`}
          title="Full screen"
          onClick={(e) => {
            const opener = e.currentTarget;
            const g = stripsGraph(group.key, () => (opener.isConnected ? opener : null));
            if (g) openGraph(g);
          }}
        >
          <Icon name="maximize" />
        </button>
        <button
          type="button"
          className="scope-remove"
          aria-label={`Take the ${stripName(group.title)} strip out of the scope`}
          title="Take this strip out"
          onClick={() =>
            unplot(
              shown.map((t) => t.name),
              usualWires(lab.get()),
            )
          }
        >
          <Icon name="x" />
        </button>
      </div>
      <ul>
        {shown.map((t) => (
          <Row key={t.name} trace={t} unit={units.get(t.name) ?? ""} said={about.get(t.name) || t.name} />
        ))}
      </ul>
    </div>
  );
}

/** One strip of the scope: its legend, and its traces drawn at the size they are shown at. */
export function Strip({
  group,
  traces,
  units,
  about,
  from,
  to,
  width,
  series,
  read,
  last,
  first,
  step,
  on,
  notes,
  fresh,
}: StripProps) {
  const host = useRef<HTMLDivElement>(null);
  const narrow = width < 520;
  const drawn = useMemo(
    () =>
      stripPlot({
        title: group.title,
        t: series.t,
        traces: traces.map((tr) => ({ ...tr, said: about.get(tr.name) || undefined, unit: units.get(tr.name) })),
        from,
        to,
        width,
        // As tall as its legend beside it, so the two read as one row; on a phone, where the
        // legend stands over it, tall enough for three phases to be told apart.
        height: narrow ? 150 : Math.max(80, 14 + traces.filter((t) => !t.ghost).length * 32),
        axis: last,
        mark: step ? { t: step.t_step, label: first ? "step" : "" } : undefined,
        notes,
        least: leastSpan(units.get(traces.find((t) => !t.ghost)?.name ?? "") ?? ""),
      }),
    [group.title, series, traces, from, to, width, narrow, last, first, step, notes, units, about],
  );
  // A fresh run draws its traces in once; a redraw (a resize, a probe, the cursor) never does.
  const drawnFor = useRef<unknown>(null);
  useEffect(() => {
    if (!fresh || drawnFor.current === fresh || !host.current) return;
    drawnFor.current = fresh;
    if (!calm()) drawIn(host.current, drawn.axes.box.w);
  }, [fresh, drawn]);
  useEffect(
    () => (host.current ? cursor.follow(follow(host.current, drawn.axes, traces, { units, read }, on)) : undefined),
    [drawn, traces, units, read, on],
  );
  const shown = useMemo(() => traces.filter((t) => !t.ghost), [traces]);
  return (
    <section className="scope-strip" ref={host} aria-label={group.title} data-strip={group.key}>
      <Legend group={group} shown={shown} units={units} about={about} />
      <div className="scope-plot" dangerouslySetInnerHTML={{ __html: drawn.svg }} />
    </section>
  );
}
