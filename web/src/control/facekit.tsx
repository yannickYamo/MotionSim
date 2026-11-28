// What the faces of the blocks are drawn with: the sheet they share, the marks found once
// and written to at every instant, an arrow, the two frames a vector is read against, and
// the words every face carries: each quantity by its symbol, its value at the cursor with
// its unit, and the scale it is drawn to.

import { useRef } from "react";
import type { Word } from "./drawn";
import { set } from "./follow";
import { faceGraph } from "./fullface";
import { openGraph } from "./fullview";
import type { LNode } from "./layout";
import { knownOf, signalWords } from "./probes";
import { angle, written } from "./series";
import { useLab } from "./store";
import type { Scheme } from "./types";
import { Icon } from "./ui";

export const puts = (n: LNode, names: string[]) => names.every((x) => n.outputs.some((o) => o.name === x));
export const takes = (n: LNode, names: string[]) => names.every((x) => n.inputs.some((i) => i.port === x));
export const outWire = (n: LNode, name: string) => n.outputs.find((o) => o.name === name)?.wire ?? "";
export const inWire = (n: LNode, port: string) => n.inputs.find((i) => i.port === port)?.wire ?? "";

/** The sheet: 200 units across, so that at the inspector's width a unit is about a pixel and a half. */
export const W = 200;
export const H = 150;
export const CX = W / 2;
export const CY = H / 2;
/** A face read on a circle sets it left, and its readouts in a column at the right. */
export const OX = 64;
export const OY = 76;
export const R = 50;
export const COL = 136;
export const DEG = 180 / Math.PI;

export interface FaceProps {
  node: LNode;
  scheme: Scheme;
}

export function Svg({
  children,
  hook,
  h = H,
}: {
  children: React.ReactNode;
  hook?: React.Ref<SVGSVGElement>;
  h?: number;
}) {
  return (
    <>
      <svg ref={hook} className="lab-face-svg can-open" viewBox={`0 0 ${W} ${h}`} aria-hidden="true" onClick={openFace}>
        {children}
      </svg>
      <button
        type="button"
        className="lab-face-open"
        aria-label="Open this drawing full screen, with what the block puts out through the run"
        title="Full screen"
        onClick={openFace}
      >
        <Icon name="maximize" />
      </button>
    </>
  );
}

/** The block's drawing full screen, from a press on it or on its button; the keyboard goes
 *  back to the button once it is shut. */
function openFace(e: React.MouseEvent<Element>): void {
  const button = e.currentTarget.closest(".lab-face")?.querySelector<HTMLElement>(".lab-face-open") ?? null;
  const g = faceGraph(() => (button?.isConnected ? button : null));
  if (g) openGraph(g);
}

/** The marks of a face, found once and kept: a face is written to sixty times a second. */
export function useMarks(): [React.RefObject<SVGSVGElement | null>, (name: string) => Element | null] {
  const svg = useRef<SVGSVGElement>(null);
  const kept = useRef(new Map<string, Element | null>());
  const mark = (name: string): Element | null => {
    const had = kept.current.get(name);
    if (had?.isConnected) return had;
    const found = svg.current?.querySelector(`[data-m="${name}"]`) ?? null;
    kept.current.set(name, found);
    return found;
  };
  return [svg, mark];
}

/** Write words into a mark, where it is there and they have changed. */
export function say(el: Element | null, words: string): void {
  if (el && el.textContent !== words) el.textContent = words;
}

/** An angle in radians as it is read: degrees within one turn, as everywhere in the lab. */
export const degrees = (rad: number | null): string => angle(rad);

/** A value with its unit as the faces write it. */
export const valued = (v: number | null, unit: string): string => written(v, unit);

/** The unit a wire is measured in: the run's, or before one, the engine's sources. */
export function useUnit(wire: string, fallback = ""): string {
  return useLab((s) => (wire ? knownOf(s).find((w) => w.name === wire)?.unit : "") || fallback);
}

/** A wire's symbol as an engineer writes it, with its unit. */
export function useWord(wire: string, fallback: Word, unit = ""): { word: Word; unit: string } {
  const known = useUnit(wire, unit);
  return { word: wire ? signalWords(wire, known) : fallback, unit: known };
}

/** A symbol in the math face: its letter, its subscript lowered, a star where it was asked for. */
export function Sym({
  word,
  x,
  y,
  anchor = "start",
  cls = "",
}: {
  word: Word;
  x: number;
  y: number;
  anchor?: "start" | "middle" | "end";
  cls?: string;
}) {
  return (
    <text className={`f-sym ${cls}`} x={x} y={y} textAnchor={anchor}>
      {word.text}
      {word.sub ? (
        <tspan className="f-sub" dy="2.6">
          {word.sub}
        </tspan>
      ) : null}
      {word.star ? <tspan dy={word.sub ? -5.2 : -2.6}>*</tspan> : null}
    </text>
  );
}

export const w = (text: string, sub = "", star = false): Word => ({ text, sub, star });

export interface Reading {
  word: Word;
  /** The mark its value is written into. */
  name: string;
}

/** The column of readouts at the right of a face: each symbol, and its value at the cursor. */
export function Reads({
  rows,
  x = COL,
  y = 22,
  step = 21,
}: {
  rows: Reading[];
  x?: number;
  y?: number;
  step?: number;
}) {
  return (
    <g className="f-reads">
      {rows.map((r, n) => (
        <g key={r.name}>
          <Sym word={r.word} x={x} y={y + n * step} />
          <text className="f-val" data-m={r.name} x={W - 2} y={y + n * step} textAnchor="end">
            –
          </text>
        </g>
      ))}
    </g>
  );
}

/** A quiet line of words on the sheet: the scale a face is drawn to, or what a mark is. */
export function Note({
  x,
  y,
  children,
  anchor = "start",
  name,
}: {
  x: number;
  y: number;
  children?: React.ReactNode;
  anchor?: "start" | "middle" | "end";
  name?: string;
}) {
  return (
    <text className="f-note" x={x} y={y} textAnchor={anchor} data-m={name}>
      {children}
    </text>
  );
}

/** An arrow from the middle of the face: its shaft, and its head turned the way it points. */
export function Arrow({ name, cls = "f-live" }: { name: string; cls?: string }) {
  return (
    <g className={`f-arrow ${cls}`}>
      <line data-m={name} />
      <path data-m={`${name}-head`} className="f-head" d="M-7 -3.2L0 0L-7 3.2z" />
    </g>
  );
}

export function point(
  mark: (name: string) => Element | null,
  name: string,
  x: number,
  y: number,
  x0 = 0,
  y0 = 0,
): void {
  set(mark(name), { x1: x0, y1: y0, x2: x, y2: y });
  const long = Math.hypot(x - x0, y - y0) > 5;
  set(mark(`${name}-head`), {
    transform: `translate(${x} ${y}) rotate(${Math.atan2(y - y0, x - x0) * DEG})`,
    visibility: long ? "visible" : "hidden",
  });
}

/** An arc of a circle about the middle, from one angle the short way to another: empty where
 *  there is nothing to show. */
export function arcOf(r: number, from: number, to: number, least = 0.01): string {
  let turn = to - from;
  turn -= 2 * Math.PI * Math.round(turn / (2 * Math.PI));
  if (Math.abs(turn) < least) return "";
  const [x0, y0] = [r * Math.cos(from), -r * Math.sin(from)];
  const [x1, y1] = [r * Math.cos(to), -r * Math.sin(to)];
  return `M${x0} ${y0}A${r} ${r} 0 0 ${turn > 0 ? 0 : 1} ${x1} ${y1}`;
}

export const AXES = `M${-R - 7} 0H${R + 7}M0 ${R + 7}V${-R - 7}`;

/** The stator's two axes, named. */
export function Stator() {
  return (
    <>
      <circle className="f-rule" r={R} />
      <path className="f-rule" d={AXES} />
      <Sym word={w("α")} x={R + 9} y={4} />
      <Sym word={w("β")} x={4} y={-R - 3} />
    </>
  );
}

/** The rotor's two axes, turned by the angle, named by letters that stay upright. */
export function Rotor({ quiet }: { quiet?: boolean }) {
  return (
    <>
      <g data-m="dq">
        <path className={quiet ? "f-quiet" : "f-mid"} d={`M${-R} 0H${R}M0 ${R}V${-R}`} />
      </g>
      <text className="f-sym" data-m="d-word">
        d
      </text>
      <text className="f-sym" data-m="q-word">
        q
      </text>
    </>
  );
}

export function turnRotor(mark: (name: string) => Element | null, th: number): void {
  set(mark("dq"), { transform: `rotate(${-th * DEG})` });
  const far = R + 8;
  set(mark("d-word"), { x: far * Math.cos(th) - 3, y: -far * Math.sin(th) + 4 });
  set(mark("q-word"), { x: -far * Math.sin(th) - 3, y: -far * Math.cos(th) + 4 });
}

/** The circle is a scale: the run's peak, with a little room round it. */
const circleIs = (most: number, unit: string) => `scale: circle = ${valued(most, unit)}`;

/** The circle's scale, written once for each run. */
export function ScaleText({ most, unit, words }: { most: number; unit: string; words?: string }) {
  const known = useLab((s) => !!s.run.answer);
  return (
    <text className="f-note" x={OX} y={OY + R + 18} textAnchor="middle">
      {words ?? (known ? circleIs(most, unit) : "circle = the run's peak")}
    </text>
  );
}
