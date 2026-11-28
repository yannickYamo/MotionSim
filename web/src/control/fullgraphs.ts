// Every graph of the lab as the full-screen viewer takes it (fullview.ts): the scope's strips,
// one or all of them; the ripple and the legs' states; the junction through the run; the
// Laplace lens's gain and phase, its step and its poles; an exploration's curves; a block's
// drawing in the inspector with what it puts out through time. Each is drawn again at the
// size of the screen from the same figures the lab drew it from, by the lab's own helpers.

import { FULL } from "../charts/frame";
import { along, figures } from "../charts/scale";
import type { Span } from "../eventplot/zoom";
import { escape, sig } from "../format";
import { gainPlot, phasePlot, poleZeroMap } from "./bode";
import type { Simulated } from "./bode";
import { cut, statesPlot, STRIP_FOOT, stripPlot, timePlot, timeUnit, valueTicks } from "./plots";
import { LINE } from "./stripnotes";
import type { StripTrace, TimePlot, Trace } from "./plots";
import { inked, knownOf, plainWords, probesOf, signalWords, stripsOf, tracedOf } from "./probes";
import { shaftRun, shaftSeries, shaftWires } from "./scopeview";
import { valueAt, written } from "./series";
import { lab, tracesOf } from "./store";
import type { Loop, Run, Series } from "./types";
import { keyRow, lettering, parts, testSaid } from "./fullview";
import type { Graph, Key, TimeDrawn, TimeGraph } from "./fullview";
import type { Group } from "./wires";

type Back = () => HTMLElement | null;

/** An instant as it is read: in the unit the span shown reads best in. */
export function when(t: number, v: Span): string {
  const { unit, k } = timeUnit(v.t1 - v.t0);
  return `${sig(t * k, 4)} ${unit}`;
}

export const spanOf = (t: number[]): Span => ({ t0: t[0] ?? 0, t1: t[t.length - 1] ?? 1 });

/** A drawing that is not through time, as it stands. */
export function stillGraph(title: string, svgs: string[], back: Back, more: Partial<Graph> = {}): Graph {
  return { title, file: slugOf(title), figures: () => svgs, back, ...more };
}

export const slugOf = (title: string) =>
  title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60) || "graph";

/* ---------- Plots through time, drawn on the lab's own frame ---------- */

/** Where a value falls up a plot of the full frame, on the ticks its traces are drawn to. */
function rise(p: TimePlot, v: Span): (y: number) => number {
  const parts2 = p.traces.map((tr) => cut(tr.t ?? p.t, tr.values, v.t0, v.t1));
  const yt = valueTicks([...parts2.flatMap(([, x]) => figures(x)), ...(p.rating ? [p.rating] : [])]);
  const { box } = FULL;
  return (y) => box.y + box.h - along(y, yt[0], yt[yt.length - 1]) * box.h;
}

/** A plot through time on the full frame (the ripple, the junction, a step), at any span. */
export function timePlotGraph(
  p: TimePlot,
  back: Back,
  opts: { keys?: Key[]; units?: string; cursor?: boolean; rows?: [string, string][]; note?: string; heading?: string },
): Graph {
  const whole = { t0: p.from, t1: p.to };
  const unit = opts.units ?? "";
  const time: TimeGraph = {
    whole,
    cursor: opts.cursor ?? true,
    draw: (v): TimeDrawn => {
      const made = timePlot({ ...p, from: v.t0, to: v.t1 });
      const sy = rise(p, v);
      return {
        svg: made.svg,
        box: made.time.box,
        dots: p.traces.map((tr) => `series ${tr.cls}`),
        at: (t) =>
          p.traces.map((tr) => {
            const y = valueAt(tr.t ?? p.t, tr.values as number[], t);
            return y === null ? null : sy(y);
          }),
      };
    },
    read: (t) =>
      `At ${when(t, whole)}: ` +
      p.traces.map((tr) => `${tr.name} ${written(valueAt(tr.t ?? p.t, tr.values as number[], t), unit)}`).join(", "),
  };
  return {
    title: p.title,
    file: slugOf(p.title),
    keys: opts.keys ?? (p.traces.length > 1 ? p.traces.map((tr) => ({ label: tr.name, cls: `series ${tr.cls}` })) : []),
    rows: opts.rows,
    heading: opts.heading,
    note: opts.note,
    back,
    time,
  };
}

/** The phase currents of the ripple, every point. */
export function rippleGraph(run: Run, from: number, to: number, back: Back): Graph {
  const w = run.waveform!;
  const traces: Trace[] = [
    { name: "phase a", values: w.i_a, cls: "s1" },
    { name: "phase b", values: w.i_b, cls: "s4" },
    { name: "phase c", values: w.i_c, cls: "s5" },
  ];
  const g = timePlotGraph(
    { title: "Phase currents with their ripple", yLabel: "phase current, A", t: w.t, traces, from: w.from, to: w.to },
    back,
    { units: "A", note: "The last stretch of the run, kept point by point: not thinned." },
  );
  g.time!.first = { t0: from, t1: to };
  return g;
}

/** Which way each leg is switched through the ripple's stretch. */
export function statesGraph(run: Run, from: number, to: number, back: Back): Graph {
  const w = run.waveform!;
  const rows = ["a", "b", "c"].map((p) => ({ name: p, values: w[`s_${p}` as "s_a"] }));
  const whole = { t0: w.from, t1: w.to };
  return {
    title: "The legs' states",
    file: "legs-states",
    note: "Each leg is up while its high side is on.",
    back,
    time: {
      whole,
      first: { t0: from, t1: to },
      cursor: true,
      draw: (v) => {
        const made = statesPlot(w.t, rows, v.t0, v.t1);
        return {
          svg: made.svg,
          box: made.time.box,
          dots: rows.map(() => "series s0"),
          at: (t) =>
            rows.map((r, n) => {
              const base = made.time.box.y + 22 * (n + 1);
              return base - ((valueAt(w.t, r.values, t) ?? 0) > 0.5 ? 14 : 0);
            }),
        };
      },
      read: (t) =>
        `At ${when(t, whole)}: ` +
        rows
          .map((r) => `leg ${r.name} ${(valueAt(w.t, r.values, t) ?? 0) > 0.5 ? "high side on" : "low side on"}`)
          .join(", "),
    },
  };
}

/** The hottest junction through the run, under its rating where that is near. */
export function thermalGraph(run: Run, back: Back): Graph {
  const t = run.thermal.t;
  const tj = run.thermal.tj_from_start;
  const rating = run.losses.tj_max;
  const near = rating !== undefined && Math.max(...figures(tj)) > rating * 0.8 ? rating : undefined;
  return timePlotGraph(
    {
      title: "Junction temperature of the hottest switch",
      yLabel: "junction temperature, °C",
      t,
      traces: [{ name: "junction", values: tj, cls: "s0" }],
      from: t[0] ?? 0,
      to: t[t.length - 1] ?? 1,
      rating: near,
    },
    back,
    {
      units: "°C",
      heading: "Through the run",
      rows: [
        ["Hottest junction", `${sig(run.losses.tj_peak)} °C`],
        ["Run without end, it settles", `${sig(run.thermal.settled_low)} to ${sig(run.thermal.settled_high)} °C`],
        ["Swing", `${sig(run.thermal.swing)} K`],
      ],
      note: "The hottest junction from the start of the run.",
    },
  );
}

/* ---------- The Laplace lens ---------- */

const hz = (f: number | null): string => (f === null ? "–" : f >= 1000 ? `${sig(f / 1000)} kHz` : `${sig(f)} Hz`);

/** The loop's headline figures, for its printed page. */
export function marginRows(loop: Loop): [string, string][] {
  const m = loop.margins;
  return [
    ["Bandwidth", hz(loop.bandwidth_hz)],
    ["Phase margin", m.phase_deg === null ? "–" : `${sig(m.phase_deg)}°`],
    ["Gain margin", m.gain_db === null ? "–" : `${sig(m.gain_db)} dB`],
    ["Crossover", hz(m.crossover_hz)],
  ];
}

export const BODE_KEYS: Key[] = [
  { label: "open loop", cls: "series s1" },
  { label: "closed loop", cls: "series s3 lab-closed" },
];

/** The gain and the phase of a loop, one above the other. */
export function bodeGraph(loop: Loop, back: Back): Graph {
  return stillGraph(`Gain and phase of the ${loop.name}`, [gainPlot(loop), phasePlot(loop)], back, {
    file: `bode-${slugOf(loop.name)}`,
    keys: BODE_KEYS,
    heading: "The loop",
    rows: marginRows(loop),
  });
}

export const POLE_KEYS: Key[] = [
  { label: "pole", cls: "lab-pole", shape: "cross" },
  { label: "zero", cls: "lab-zero", shape: "ring" },
  { label: "|z| = 1", cls: "lab-unit", shape: "ring" },
];

export function poleGraph(loop: Loop, back: Back): Graph {
  const out = loop.poles.filter((p) => !p.stable).length;
  return stillGraph(`Poles and zeros of the ${loop.name}`, [poleZeroMap(loop)], back, {
    file: `poles-${slugOf(loop.name)}`,
    keys: POLE_KEYS,
    heading: "Poles of the closed loop",
    rows: loop.poles
      .slice(0, 8)
      .map((p, n) => [
        `Pole ${n + 1}`,
        `${sig(p.re, 4)} ${p.im < 0 ? "−" : "+"} ${sig(Math.abs(p.im), 4)}j, ${p.stable ? "inside" : "outside"}`,
      ]),
    note: out
      ? `${out} of the poles lie outside the unit circle: the loop does not settle.`
      : "Every pole lies inside the unit circle: the loop settles.",
  });
}

/** The step a loop's linear model predicts, with the simulated one over it, at any span. */
export function stepGraph(loop: Loop, simulated: Simulated | null, back: Back): Graph {
  const last = Math.max(loop.step.t[loop.step.t.length - 1] ?? 0, 0) || 1;
  const end = Math.min(last, (loop.step.settling_time ?? last) * (simulated ? 8 : 4) || last);
  const traces: Trace[] = [
    { name: "predicted", values: loop.step.y, t: loop.step.t, cls: "s3" },
    ...(simulated ? [{ name: "simulated", values: simulated.y, t: simulated.t, cls: "s1" }] : []),
  ];
  const p = loop.step;
  const g = timePlotGraph(
    {
      title: `Predicted step of the ${loop.name}`,
      yLabel: "share of the step",
      t: loop.step.t,
      traces,
      from: 0,
      to: last,
    },
    back,
    {
      cursor: false,
      keys: [
        { label: "predicted by the linear model", cls: "series s3" },
        ...(simulated ? [{ label: "simulated, switched", cls: "series s1" }] : []),
      ],
      heading: "The step it predicts",
      rows: [
        ["Overshoot", p.overshoot === null ? "–" : `${sig(p.overshoot * 100)} %`],
        ["Rise time", p.rise_time === null ? "–" : written(p.rise_time, "s")],
        ["Settling time", p.settling_time === null ? "–" : written(p.settling_time, "s")],
      ],
      note: "Time is counted from the instant of the step; 1 is the whole of the step.",
    },
  );
  g.time!.first = { t0: 0, t1: end };
  return g;
}

/* ---------- The scope ---------- */

export interface Scoped {
  groups: Group[];
  traced: StripTrace[][];
  units: Map<string, string>;
  about: Map<string, string>;
  series: Series;
}

/** The scope's strips as it draws them now, run A's traces under this run's where one is held. */
export function scopeNow(): Scoped | null {
  const s = lab.get();
  const raw = tracesOf(s);
  if (!raw?.t.length) return null;
  // As the scope itself reads the run: the shaft's speeds in rpm.
  const series = shaftSeries(raw, knownOf(s));
  const known = shaftWires(knownOf(s));
  const groups = stripsOf(probesOf(s), known, series, s.scenario);
  const inks = inked(groups);
  const run = s.run.answer;
  const held = s.held;
  const other = held && run && held.run !== run && held.run.scenario.kind === run.scenario.kind ? held.run : null;
  const ghost = other && shaftRun(other);
  const traced = tracedOf(groups, inks, ghost, series);
  return {
    groups,
    traced,
    units: new Map(known.map((w) => [w.name, w.unit])),
    about: new Map(known.map((w) => [w.name, w.about])),
    series,
  };
}

const traceCls = (t: StripTrace) =>
  t.ghost ? "scope-ghost" : `scope-trace pr-${t.ink}${t.dash ? ` da-${t.dash}` : ""}`;

/** The key of a strip: each trace's sample, its name as it is written, what it is. */
export function stripKeys(traces: StripTrace[], units: Map<string, string>, about: Map<string, string>): Key[] {
  return traces.map((t) =>
    t.ghost
      ? { label: t.name.replace(/^.*, /, ""), cls: traceCls(t) }
      : { label: about.get(t.name) || "", word: signalWords(t.name, units.get(t.name) ?? ""), cls: traceCls(t) },
  );
}

const HEAD = 24;

interface StripDrawn {
  markup: string;
  /** Where the next strip starts, and the top and bottom of this one's plot. */
  next: number;
  top: number;
  bottom: number;
}

/** A strip's name, as its axis says it: its title and unit. */
const stripName = (g: Group) => {
  const unit = g.yLabel.includes(",") ? g.yLabel.slice(g.yLabel.lastIndexOf(",") + 1).trim() : "";
  return unit ? `${g.title}, ${unit}` : g.title;
};

/** One strip at y, under its name and key, with the dots the crosshair puts on its traces. */
interface StripAt {
  /** Which of the scope's strips, and whether it is the first or the last drawn. */
  k: number;
  first: boolean;
  last: boolean;
  /** Its plot's height, and where it starts. */
  ph: number;
  y: number;
}

function oneStrip(sc: Scoped, { k, first, last, ph, y }: StripAt, v: Span, w: number) {
  const g = sc.groups[k];
  const traces = sc.traced[k];
  const step = lab.get().run.answer?.step ?? null;
  const made = stripPlot({
    title: g.title,
    t: sc.series.t,
    traces,
    from: v.t0,
    to: v.t1,
    width: w,
    height: ph,
    axis: last,
    mark: step ? { t: step.t_step, label: first ? "step" : "" } : undefined,
  });
  const p = parts(made.svg);
  const at = y + HEAD;
  const { box, lo, hi, height } = made.axes;
  const places = traces
    .filter((x) => !x.ghost)
    .map((tr) => ({
      dot: `scope-dot pr-${tr.ink}`,
      place: (t: number) => {
        const val = valueAt(tr.t ?? sc.series.t, tr.values as number[], t);
        return val === null ? null : at + box.y + box.h - ((val - lo) / (hi - lo || 1)) * box.h;
      },
    }));
  const named = stripName(g);
  const clear = box.x + [...named].length * lettering.px * 0.6 + 16;
  const keys = keyRow(stripKeys(traces, sc.units, sc.about), w, y + 16, clear);
  const cls = escape(p.cls.replace(/\bchart\b/, "").trim());
  const markup =
    `<text class="lab-full-strip" x="${box.x}" y="${y + 16}">${escape(named)}</text>${keys}` +
    `<svg x="0" y="${at}" width="${w}" height="${height}" viewBox="0 0 ${w} ${height}">` +
    `<g class="${cls}">${p.inside}</g></svg>`;
  const drawn: StripDrawn = { markup, next: at + height + 8, top: at + box.y, bottom: at + box.y + box.h };
  return { drawn, places };
}

/** Strips set one above another at w by h, each under its name and key, the time under the last. */
export function stripsDrawn(sc: Scoped, only: number[], v: Span, w: number, h: number): TimeDrawn {
  const n = only.length;
  // The first strip names the step in a line over its plot, which takes that line's height.
  const named = lab.get().run.answer?.step ? LINE : 0;
  const ph = Math.max(36, (h - n * (HEAD + 16) - (STRIP_FOOT - 8) - named) / n);
  let y = 0;
  let top = 0;
  let bottom = 0;
  const body: string[] = [];
  const marks: { dot: string; place: (t: number) => number | null }[] = [];
  only.forEach((k, m) => {
    const { drawn, places } = oneStrip(sc, { k, first: m === 0, last: m === n - 1, ph, y }, v, w);
    if (m === 0) top = drawn.top;
    bottom = drawn.bottom;
    body.push(drawn.markup);
    marks.push(...places);
    y = drawn.next;
  });
  const label = escape(only.map((k) => sc.groups[k].title).join(", "));
  return {
    svg:
      `<svg class="chart" viewBox="0 0 ${w} ${Math.max(h, y)}" aria-label="The scope: ${label}">` +
      `${body.join("")}</svg>`,
    box: { x: 60, y: top, w: Math.max(40, w - 68), h: bottom - top },
    dots: marks.map((x) => x.dot),
    at: (t) => marks.map((x) => x.place(t)),
  };
}

/** What every trace of the strips reads at an instant. */
export function stripsRead(sc: Scoped, only: number[], v: Span, t: number): string {
  const said = only.flatMap((k) =>
    sc.traced[k]
      .filter((x) => !x.ghost)
      .map((tr) => {
        const unit = sc.units.get(tr.name) ?? "";
        const value = valueAt(tr.t ?? sc.series.t, tr.values as number[], t);
        return `${plainWords(signalWords(tr.name, unit))} ${written(value, unit)}`;
      }),
  );
  return `At ${when(t, v)}: ${said.join(", ")}`;
}

/** The scope's strips full screen: the one named, or every one where none is. */
export function stripsGraph(key: string | null, back: Back): Graph | null {
  const sc = scopeNow();
  if (!sc || !sc.groups.length) return null;
  const one = key === null ? -1 : sc.groups.findIndex((g) => g.key === key);
  const only = one < 0 ? sc.groups.map((_, k) => k) : [one];
  const whole = spanOf(sc.series.t);
  const view = lab.get().view;
  const g = one < 0 ? null : sc.groups[one];
  const test = testSaid();
  return {
    title: g ? `Scope: ${g.title.toLowerCase()}` : "Scope: every strip",
    file: g ? `scope-${slugOf(g.title)}` : "scope",
    keys: [],
    heading: "The run",
    rows: [
      ...(test ? [["Test", test] as [string, string]] : []),
      ["Lasts", when(whole.t1 - whole.t0, whole)],
      ["Strips", String(only.length)],
    ],
    note: "What was asked for is dashed in the ink of what answers it.",
    back,
    time: {
      whole,
      first: view ? { t0: view[0], t1: view[1] } : whole,
      cursor: true,
      draw: (v, w, h) => stripsDrawn(sc, only, v, w, h),
      read: (t) => stripsRead(sc, only, whole, t),
    },
    more:
      sc.groups.length > 1
        ? {
            label: g ? "All strips" : "First strip alone",
            graph: () => stripsGraph(g ? null : sc.groups[0].key, back)!,
          }
        : undefined,
  };
}

/** The scope's strips for the printed report: every one, through the whole run. */
export function scopePrinted(w: number, h: number): { svg: string; keys: Key[] } | null {
  const sc = scopeNow();
  if (!sc || !sc.groups.length) return null;
  const only = sc.groups.map((_, k) => k);
  const drawn = stripsDrawn(sc, only, spanOf(sc.series.t), w, h);
  return { svg: drawn.svg, keys: [] };
}
