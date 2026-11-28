// The linear view of a loop, drawn: its gain and phase against frequency with the margins
// marked where they are read, its poles and zeros against the unit circle, and the answer to
// a step it predicts. All of it is the engine's; only the drawing is done here.

import { frame, FULL, line, nextId, plotRect } from "../charts/frame";
import type { Box, Scale } from "../charts/frame";
import { along, figures, scale, ticks } from "../charts/scale";
import { escape, minus, sig } from "../format";
import { timeUnit, valueTicks } from "./plots";
import { placeNote } from "./bodenotes";
import type { Around, Point } from "./bodenotes";
import type { Loop, Polynomials } from "./types";

const eachDecade = (lo: number, hi: number): number[] => {
  const out: number[] = [];
  for (let e = Math.ceil(Math.log10(lo) - 1e-9); 10 ** e <= hi * (1 + 1e-9); e++) out.push(10 ** e);
  return out;
};

/** A decade as it is said: 0.01, 1, 100, 1k, 10k; never padded to the smallest's decimals. */
const decadeName = (v: number): string =>
  v >= 1000 ? `${Number((v / 1000).toPrecision(1))}k` : `${Number(v.toPrecision(1))}`;

/** The inspector's frame: narrow, so that drawn in its column its words read near their own size. */
const SMALL = { view: "0 0 320 196", box: { x: 46, y: 20, w: 258, h: 128 } };

/** Ticks a quarter turn apart, or half a turn where there would be too many. */
function turns(lo: number, hi: number): number[] {
  const step = hi - lo > 540 ? 180 : 90;
  const out: number[] = [];
  for (let v = Math.floor(lo / step) * step; v <= Math.ceil(hi / step) * step; v += step) out.push(v);
  return out.length > 1 ? out : [out[0] - step, out[0]];
}

interface Axes {
  box: Box;
  sx: Scale;
  sy: Scale;
  yt: number[];
}

function axes(f: number[], values: number[], phase: boolean, small: boolean): Axes {
  const { box } = small ? SMALL : FULL;
  const lo = Math.log10(f[0]);
  const hi = Math.log10(f[f.length - 1]);
  const sx: Scale = (v) => box.x + along(Math.log10(v), lo, hi) * box.w;
  const held = figures(values);
  const yt = phase ? turns(Math.min(...held, -180), Math.max(...held, 0)) : scale([...held, 0], 5);
  const a = yt[0];
  const b = yt[yt.length - 1];
  return { box, sx, sy: (v) => box.y + box.h - along(v, a, b) * box.h, yt };
}

/** A margin to mark: where it is read, the line it is measured from, the value there, its words. */
interface Mark {
  hz: number | null;
  from: number;
  to: number | null;
  label: string;
}

/** A mark as it stands on the plot: its upright, and the stretch it is read across. */
interface Stood {
  x: number;
  y0: number;
  y1: number;
  hz: number;
  label: string;
}

function stood(a: Axes, m: Mark): Stood | null {
  if (m.hz === null || m.to === null || !Number.isFinite(m.hz) || !Number.isFinite(m.to)) return null;
  const x = a.sx(m.hz);
  if (!(x >= a.box.x && x <= a.box.x + a.box.w)) return null;
  return { x, y0: a.sy(m.from), y1: a.sy(m.to), hz: m.hz, label: m.label };
}

/** The margins, each drawn where it is read: a dot on the curve, a bar to the line it is
 *  measured from, and its figure in words set clear of the curves, tied to it by a short leader. */
function margins(a: Axes, marks: Mark[], curves: Point[][]): string {
  const all = marks.map((m) => stood(a, m)).filter((m): m is Stood => m !== null);
  const band = (m: Stood): Box => ({ x: m.x - 14, y: Math.min(m.y0, m.y1), w: 28, h: Math.abs(m.y0 - m.y1) });
  const around: Around = {
    plot: a.box,
    curves,
    uprights: all.map((m) => m.x),
    taken: all.map(band).filter((b) => b.h > 1),
  };
  return all.map((m) => margin(a, m, band(m), around)).join("");
}

function margin(a: Axes, m: Stood, band: Box, around: Around): string {
  // The margin as a region: the stretch it is read across, shaded where it is read.
  const region =
    band.h > 1
      ? `<rect class="lab-region-band" x="${band.x}" y="${band.y.toFixed(1)}" width="28" ` +
        `height="${band.h.toFixed(1)}"/>`
      : "";
  const drawn =
    `<path class="lab-mark" d="M${m.x} ${a.box.y}v${a.box.h}"/>${region}` +
    `<path class="lab-bar" d="M${m.x} ${m.y0}V${m.y1}"/>` +
    `<circle class="lab-dot" cx="${m.x}" cy="${m.y1}" r="3.2" data-mark-hz="${m.hz}"/>`;
  if (!m.label) return drawn;
  // A margin with a stretch is named from the middle of its bar; a crossing, from its dot.
  const long = band.h > 12;
  const note = placeNote([m.x, long ? (m.y0 + m.y1) / 2 : m.y1], m.label, around, long ? 2 : 5);
  around.taken.push(note.box);
  const [p, q] = note.leader;
  const leader = `M${p[0].toFixed(1)} ${p[1].toFixed(1)}L${q[0].toFixed(1)} ${q[1].toFixed(1)}`;
  return (
    `${drawn}<path class="lab-leader" d="${leader}"/>` +
    `<text class="tick lab-note" x="${(note.box.x + 4).toFixed(1)}" y="${(note.box.y + 12).toFixed(1)}" ` +
    `data-margin>${escape(m.label)}</text>`
  );
}

const hz = (f: number | null): string => (f === null ? "–" : f >= 1000 ? `${sig(f / 1000)} kHz` : `${sig(f)} Hz`);

function bode(loop: Loop, phase: boolean, small = false): string {
  const b = loop.bode;
  const open = phase ? b.open_deg : b.open_db;
  const closed = phase ? b.closed_deg : b.closed_db;
  const a = axes(b.f, [...open, ...closed], phase, small);
  const m = loop.margins;
  const ref = phase ? -180 : 0;
  // The curves as they are drawn, and the line the margins are measured from: what a figure
  // is kept clear of.
  const drawn = (ys: number[]): Point[] =>
    b.f.flatMap((f, k) => (Number.isFinite(ys[k]) ? [[a.sx(f), a.sy(ys[k])] as Point] : []));
  const level: Point[] = [
    [a.box.x, a.sy(ref)],
    [a.box.x + a.box.w, a.sy(ref)],
  ];
  const phaseMark = { hz: m.crossover_hz, from: -180, to: m.phase_deg === null ? null : -180 + m.phase_deg };
  const marks = margins(
    a,
    phase
      ? [{ ...phaseMark, label: `phase margin ${minus(sig(m.phase_deg))}°` }]
      : [
          // Small, the crossover's figure is the bandwidth said over the plot: its mark alone is drawn.
          { hz: m.crossover_hz, from: 0, to: 0, label: small ? "" : `crossover ${hz(m.crossover_hz)}` },
          {
            hz: m.phase_crossover_hz,
            from: 0,
            to: m.gain_db === null ? null : -m.gain_db,
            label: `gain margin ${minus(sig(m.gain_db))} dB`,
          },
        ],
    [drawn(open), drawn(closed), level],
  );
  const what = phase ? "Phase" : "Gain";
  const clip = nextId("lab-clip");
  const decades = eachDecade(b.f[0], b.f[b.f.length - 1]);
  const said =
    `${what} of the ${loop.name} against frequency, open and closed. Crossover at ${hz(m.crossover_hz)}, ` +
    `phase margin ${minus(sig(m.phase_deg))} degrees, gain margin ${minus(sig(m.gain_db))} dB.`;
  return (
    `<svg class="chart" viewBox="${(small ? SMALL : FULL).view}" role="img" aria-label="${escape(said)}">` +
    frame(a, decades, a.yt, "frequency, Hz", phase ? "phase, °" : "gain, dB", decades.map(decadeName)) +
    `<path class="zero" d="M${a.box.x} ${a.sy(ref)}h${a.box.w}"/>` +
    `<clipPath id="${clip}"><rect x="${a.box.x}" y="${a.box.y}" width="${a.box.w}" height="${a.box.h}"/></clipPath>` +
    `<g clip-path="url(#${clip})"><path class="series s3 lab-closed" d="${line(b.f, closed, a.sx, a.sy)}"/>` +
    `<path class="series s1" d="${line(b.f, open, a.sx, a.sy)}"/></g>${marks}</svg>`
  );
}

export const gainPlot = (loop: Loop, small = false): string => bode(loop, false, small);
export const phasePlot = (loop: Loop): string => bode(loop, true);

const count = (n: number, noun: string): string => `${n} ${noun}${n === 1 ? "" : "s"}`;

/** How near z = 1 poles and zeros crowd into one mark at the circle's scale. */
const NEAR = 0.01;
/** How near a zero lies to a pole for the two to cancel. */
const CANCELS = 1e-6;

/** The poles and zeros within `NEAR` of z = 1, and how many pairs of them cancel. */
function nearOne(loop: Loop) {
  const at = (p: { re: number; im: number }) => Math.hypot(p.re - 1, p.im) < NEAR;
  const poles = loop.poles.filter(at);
  const zeros = loop.zeros.filter(at);
  if (poles.length + zeros.length < 2) return null;
  const free = [...zeros];
  let pairs = 0;
  for (const p of poles) {
    const k = free.findIndex((z) => Math.hypot(z.re - p.re, z.im - p.im) < CANCELS);
    if (k >= 0) {
      free.splice(k, 1);
      pairs++;
    }
  }
  const pairWord = `${pairs} pair${pairs === 1 ? "" : "s"}`;
  return {
    poles: poles.length,
    zeros: zeros.length,
    written: pairs ? `; ${pairWord} ${pairs === 1 ? "cancels" : "cancel"}` : "",
    spoken: pairs ? `, ${pairWord} cancelling` : "",
  };
}

/** The closed loop's poles (crosses) and zeros (rings) against the unit circle: inside it,
 *  the loop settles. */
export function poleZeroMap(loop: Loop): string {
  const box = { x: 48, y: 20, w: 240, h: 240 };
  const all = [...loop.poles, ...loop.zeros];
  const reach = Math.max(1.25, ...all.map((p) => Math.hypot(p.re, p.im) * 1.1));
  const sx: Scale = (v) => box.x + along(v, -reach, reach) * box.w;
  const sy: Scale = (v) => box.y + box.h - along(v, -reach, reach) * box.h;
  const t = ticks(-Math.floor(reach), Math.floor(reach), 2);
  const cross = (p: { re: number; im: number; stable: boolean }) => {
    const x = sx(p.re);
    const y = sy(p.im);
    return `<path class="lab-pole${p.stable ? "" : " out"}" d="M${x - 4} ${y - 4}l8 8m0 -8l-8 8"/>`;
  };
  const ring = (p: { re: number; im: number }) => `<circle class="lab-zero" cx="${sx(p.re)}" cy="${sy(p.im)}" r="4"/>`;
  const out = loop.poles.filter((p) => !p.stable).length;
  const crowd = nearOne(loop);
  const said =
    `Poles and zeros of the closed ${loop.name} in the z plane: ${count(loop.poles.length, "pole")}, ` +
    `${count(loop.zeros.length, "zero")}; ` +
    (out
      ? `${out} outside the unit circle, so the loop does not settle.`
      : "every pole of this linear model inside the unit circle.") +
    (crowd ? ` ${crowd.poles} poles and ${crowd.zeros} zeros lie within ${NEAR} of z = 1${crowd.spoken}.` : "");
  // At the scale of the circle they are one mark: what lies there is said beside it.
  // In the figures' face the note is too long for one line left of the mark: what cancels goes
  // on a line of its own under the count.
  const noteX = sx(1) - 6;
  const [counted, cancels] = crowd ? [crowd.written.slice(0, 1), crowd.written.slice(1)] : ["", ""];
  const near = crowd
    ? `<text class="tick lab-note" x="${noteX}" y="${sy(0) - (cancels ? 24 : 10)}" text-anchor="end">` +
      `near z = 1: ${count(crowd.poles, "pole")}, ${count(crowd.zeros, "zero")}${counted}` +
      (cancels ? `<tspan x="${noteX}" dy="14">${cancels}</tspan>` : "") +
      `</text>`
    : "";
  return (
    `<svg class="chart small" viewBox="0 0 310 304" role="img" aria-label="${escape(said)}">` +
    frame({ box, sx, sy }, t, t, "real", "imaginary") +
    `<path class="zero" d="M${box.x} ${sy(0)}h${box.w}M${sx(0)} ${box.y}v${box.h}"/>` +
    `<circle class="lab-unit" cx="${sx(0)}" cy="${sy(0)}" r="${sx(1) - sx(0)}"/>` +
    `${loop.zeros.map(ring).join("")}${loop.poles.map(cross).join("")}${near}${plotRect(box)}</svg>`
  );
}

/** What was simulated, as the share of the step it has made, from the instant of the step. */
export interface Simulated {
  t: number[];
  y: number[];
}

/** What a predicted step is judged by, where it is read: the overshoot as a band over the
 *  target, the settling as the stretch up to the instant it stays, that instant ticked. */
/** When a loop's predicted step settles, in words: its time, or that it does not. */
export function settlesWords(loop: Loop): string {
  if (!loop.stable) return "does not settle";
  const t = loop.step.settling_time;
  if (t === null) return "not within the stretch drawn";
  const { unit, k } = timeUnit(t);
  return `${sig(t * k)} ${unit}`;
}

function stepMarks(
  loop: Loop,
  at: { box: Box; sx: Scale; sy: Scale; k: number; unit: string; end: number; top: number },
): string {
  const { box, sx, sy, k, end } = at;
  let marks = "";
  if (!loop.stable) {
    // A pole outside the unit circle: the step grows without end, and is said to.
    const words = `<text class="tick warn" x="${box.x + 6}" y="${box.y + 14}">does not settle</text>`;
    return `<g class="lab-region tone-fail" data-note="unstable">${words}</g>`;
  }
  const over = loop.step.overshoot;
  if (over !== null && over > 1e-3 && 1 + over <= at.top) {
    const y = sy(1 + over);
    const h = Math.max(1.5, sy(1) - y).toFixed(1);
    const rect = `<rect x="${box.x}" y="${y.toFixed(1)}" width="${box.w}" height="${h}"/>`;
    const words =
      `<text class="tick lab-region-label" x="${box.x + box.w - 4}" y="${(y - 4).toFixed(1)}" ` +
      `text-anchor="end">overshoot ${sig(over * 100)} %</text>`;
    marks += `<g class="lab-region tone-note" data-note="overshoot">${rect}${words}</g>`;
  }
  const settle = loop.step.settling_time;
  if (settle === null || settle <= 0 || settle > end) return marks;
  const x = sx(settle * k);
  const flip = x > box.x + box.w - 110;
  const region =
    `<rect x="${box.x}" y="${box.y}" width="${(x - box.x).toFixed(1)}" height="${box.h}"/>` +
    `<path d="M${x.toFixed(1)} ${box.y}v${box.h}"/>`;
  const words =
    `<text class="tick lab-region-label" x="${(flip ? x - 5 : x + 5).toFixed(1)}" y="${box.y + box.h - 6}" ` +
    `text-anchor="${flip ? "end" : "start"}">settles ${settlesWords(loop)}</text>`;
  return `${marks}<g class="lab-region tone-good" data-note="settling">${region}${words}</g>`;
}

/** The answer to a unit step the linear model predicts, with the simulated one over it
 *  where a run has made that step. */
export function stepPlot(loop: Loop, simulated: Simulated | null, small = false): string {
  const { view, box } = small ? SMALL : FULL;
  // The model's answer is given long after it has settled: the stretch drawn is the settling, four times over.
  const last = Math.max(loop.step.t[loop.step.t.length - 1] ?? 0, 0) || 1;
  const end = Math.min(last, (loop.step.settling_time ?? last) * (simulated ? 8 : 4) || last);
  const { unit, k } = timeUnit(end);
  const sx: Scale = (v) => box.x + along(v, 0, end * k) * box.w;
  const sim = simulated ? simulated.t.map((t, n) => (t <= end ? simulated.y[n] : null)) : [];
  const shown = loop.step.t.filter((t) => t <= end);
  const yt = valueTicks([...loop.step.y, ...figures(sim), 0, 1]);
  const a = yt[0];
  const b = yt[yt.length - 1];
  const sy: Scale = (v) => box.y + box.h - along(v, a, b) * box.h;
  const drawn = simulated
    ? `<path class="series s1" d="${line(
        simulated.t.map((t) => t * k),
        sim,
        sx,
        sy,
      )}"/>`
    : "";
  const marks = stepMarks(loop, { box, sx, sy, k, unit, end, top: b });
  const said =
    `The answer of the ${loop.name} to a unit step, as the linear model predicts it` +
    (simulated ? ", with the simulated answer over it." : ".");
  return (
    `<svg class="chart" viewBox="${view}" role="img" aria-label="${escape(said)}">` +
    frame({ box, sx, sy }, ticks(0, end * k, 5), yt, `time after the step, ${unit}`, "share of the step") +
    marks +
    `<path class="zero" d="M${box.x} ${sy(1)}h${box.w}"/>` +
    `<path class="series s3" d="${line(
      shown.map((t) => t * k),
      loop.step.y,
      sx,
      sy,
    )}"/>${drawn}</svg>`
  );
}

/** A polynomial in z as LaTeX, highest power first, to four figures. */
function polynomial(c: number[]): string {
  const n = c.length - 1;
  const terms = c
    .map((v, k) => {
      if (v === 0) return "";
      const power = n - k;
      const z = power === 0 ? "" : power === 1 ? "z" : `z^{${power}}`;
      const size = Math.abs(v);
      const figure = size === 1 && z ? "" : sig(size, 4);
      return `${v < 0 ? "-" : "+"}${figure}${figure && z ? "\\," : ""}${z}`;
    })
    .filter(Boolean)
    .join(" ");
  return terms.replace(/^\+/, "") || "0";
}

/** A transfer function as LaTeX, from its two polynomials. */
export const transferTex = (name: string, p: Polynomials): string =>
  `${name}(z) = \\frac{${polynomial(p.num)}}{${polynomial(p.den)}}`;
