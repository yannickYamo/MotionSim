// The controls of a key setting: a figure as a large box with minus and plus either side,
// stepped by the arrow keys and scrubbed by dragging its name; a choice as a segmented switch.
// Each shows what it was tuned to, and offers the way back to it.

import { useEffect, useRef, useState } from "react";
import { sig } from "../format";
import { unitWords } from "./figures";
import { boxed, choiceWord, held, stepped, unbounded, whole } from "./keys";
import type { Value } from "./types";

/* The icons these controls draw, from the same Tabler set at the page's stroke. */
const PATHS = { minus: "M5 12h14", plus: "M12 5v14m-7-7h14", back: "M9 14l-4-4l4-4M5 10h11a4 4 0 1 1 0 8h-1" };
const Glyph = ({ d }: { d: string }) => (
  <svg className="icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
    <path fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.6" d={d} />
  </svg>
);

interface FigureProps {
  id: string;
  word?: string;
  label: string;
  unit: string;
  value: number | null;
  /** The figure it was tuned to, for the line under it and the way back. */
  tuned: Value | undefined;
  source?: string;
  low?: number | null;
  high?: number | null;
  name: string;
  problem?: string;
  /** Take a figure: at once from a step or a box, once a frame at most from a drag. */
  put: (v: number, dragged?: boolean) => void;
  reset: () => void;
}

/** The note under a key setting: what it was tuned to, and where that came from when it says
 *  so in a few words. */
interface NoteProps {
  id: string;
  tuned: string;
  unit: string;
  source?: string;
  /** What the value to go back to is called: tuned for a block, the engine's default for a test. */
  word?: string;
}

function Note({ id, tuned, unit, source, word = "Tuned" }: NoteProps) {
  const short = !!source && source.length <= 22;
  return (
    <span className="lab-key-note" id={`${id}-n`} title={source && !short ? `From ${source}` : undefined}>
      {word} {tuned}
      {unit && tuned !== "none" ? ` ${unit}` : ""}
      {short ? ` · ${source}` : ""}
    </span>
  );
}

/** The way back to the tuned value: its place is kept, so nothing moves when it shows. */
const Reset = ({ shown, label, act }: { shown: boolean; label: string; act: () => void }) => (
  <button
    type="button"
    className="lab-key-reset"
    hidden={!shown}
    aria-label={`Reset ${label} to its tuned value`}
    title="Back to the tuned value"
    onClick={act}
  >
    <Glyph d={PATHS.back} />
  </button>
);

const tunedWord = (t: Value | undefined): string =>
  t === undefined ? "" : typeof t === "number" ? (unbounded(t) ? "none" : boxed(t)) : choiceWord(String(t));

/** A figure's name, dragged sideways to scrub it: each pixel a little more than a hundredth. */
function ScrubName({ id, label, p }: { id: string; label: string; p: FigureProps }) {
  const drag = useRef<{ x: number; from: number } | null>(null);
  const { value, name, unit, low, high, put } = p;
  const able = value !== null && value !== 0 && !unbounded(value);
  return (
    <label
      htmlFor={id}
      className={`lab-key-name${able ? " is-scrub" : ""}`}
      title={able ? "Drag sideways to change" : undefined}
      onPointerDown={(e) => {
        if (!able || e.button !== 0) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        drag.current = { x: e.clientX, from: value };
      }}
      onPointerMove={(e) => {
        if (!drag.current) return;
        const v = drag.current.from * 1.012 ** (e.clientX - drag.current.x);
        put(held(whole(name, unit) ? Math.round(v) : Number(v.toPrecision(4)), low, high), true);
      }}
      onPointerUp={() => (drag.current = null)}
      onPointerCancel={() => (drag.current = null)}
    >
      {label}
    </label>
  );
}

/** Minus or plus beside the box: a pointer's way; the keyboard has the arrows on the box. */
const Step = ({ way, label, off, act }: { way: 1 | -1; label: string; off: boolean; act: (big: boolean) => void }) => (
  <button
    type="button"
    className="lab-key-step"
    aria-label={`${way > 0 ? "More" : "Less"} ${label}`}
    data-tip={`${way > 0 ? "More" : "Less"}: hold Shift for a larger step`}
    tabIndex={-1}
    disabled={off}
    onClick={(e) => act(e.shiftKey)}
  >
    <Glyph d={way > 0 ? PATHS.plus : PATHS.minus} />
  </button>
);

/** What the box says of itself to a screen reader. */
const spoken = (value: number | null, unit: string): string | undefined =>
  value === null ? undefined : unbounded(value) ? "none" : `${sig(value, 4)}${unit ? ` ${unit}` : ""}`;

/** The box as typed: kept while it is not a number, and following the figure when it changes
 *  from elsewhere (a step, a reset, another scheme). */
function useTyped(value: number | null): [string, (t: string) => void] {
  const [typed, setTyped] = useState(value === null ? "" : boxed(value));
  useEffect(() => {
    setTyped((now) => {
      if (value === null) return "";
      return Number(now) === value && now.trim() !== "" ? now : boxed(value);
    });
  }, [value]);
  return [typed, setTyped];
}

interface BoxProps {
  p: FigureProps;
  typed: string;
  wrong: string;
  type: (t: string) => void;
  step: (way: 1 | -1, big: boolean) => void;
}

/** The box itself, with its unit inside: typed into, or stepped with the arrow keys. */
function Box({ p, typed, wrong, type, step }: BoxProps) {
  const { id, value, unit, low, high, put } = p;
  const free = value === null || unbounded(value);
  return (
    <span className="lab-key-box">
      <input
        id={id}
        inputMode="decimal"
        autoComplete="off"
        spellCheck={false}
        role="spinbutton"
        value={typed}
        placeholder={value !== null && free ? "none" : ""}
        aria-valuenow={free ? undefined : value}
        aria-valuemin={low ?? undefined}
        aria-valuemax={high ?? undefined}
        aria-valuetext={spoken(value, unit)}
        aria-invalid={!!wrong || undefined}
        aria-describedby={`${id}-n${wrong ? ` ${id}-e` : ""}`}
        onChange={(e) => {
          type(e.target.value);
          const v = Number(e.target.value);
          if (e.target.value.trim() !== "" && Number.isFinite(v)) put(v);
        }}
        onKeyDown={(e) => {
          const way = e.key === "ArrowUp" ? 1 : e.key === "ArrowDown" ? -1 : 0;
          if (!way) return;
          e.preventDefault();
          step(way, e.shiftKey);
        }}
      />
      {unit ? <span className="lab-key-unit">{unitWords(unit)}</span> : null}
    </span>
  );
}

/** A figure as a large box: minus and plus beside it, the arrow keys on it, and its name
 *  dragged sideways to scrub it. */
export function KeyFigure(p: FigureProps) {
  const { id, label, unit, value, tuned, low, high, name, put } = p;
  const [typed, setTyped] = useTyped(value);
  const free = value === null || unbounded(value);
  const step = (way: 1 | -1, big = false) => {
    if (!free) put(held(stepped(value, way, big, name, unit), low, high));
  };
  const atLow = free || (low != null && value <= low);
  const atHigh = free || (high != null && value >= high);
  const changed = tuned !== undefined && value !== null && tuned !== value;
  const unread = typed.trim() !== "" && !Number.isFinite(Number(typed));
  const wrong = unread ? "A number is needed here; the last one read is still in use." : (p.problem ?? "");
  return (
    <div className={`lab-key${changed ? " is-changed" : ""}${wrong ? " is-wrong" : ""}`}>
      <div className="lab-key-head">
        <ScrubName id={id} label={label} p={p} />
        <Note id={id} tuned={tunedWord(tuned)} unit={unit} source={p.source} word={p.word} />
      </div>
      <div className="lab-key-control">
        <Step way={-1} label={label} off={atLow} act={(big) => step(-1, big)} />
        <Box p={p} typed={typed} wrong={wrong} type={setTyped} step={step} />
        <Step way={1} label={label} off={atHigh} act={(big) => step(1, big)} />
        <Reset shown={changed} label={label} act={p.reset} />
      </div>
      <Wrong id={id} said={wrong} />
    </div>
  );
}

const Wrong = ({ id, said }: { id: string; said?: string }) =>
  said ? (
    <p className="lab-key-wrong" id={`${id}-e`} role="alert">
      {said}
    </p>
  ) : null;

interface SegmentedProps {
  id: string;
  labelledBy: string;
  describedBy: string;
  className?: string;
  value: string;
  options: [string, string][];
  pick: (v: string) => void;
}

/** A few ways side by side, as radio buttons: one stop for Tab, the arrows move the choice. */
export function Segmented({ id, labelledBy, describedBy, className, value, options, pick }: SegmentedProps) {
  const ways = options.map(([o]) => o);
  return (
    <div
      className={`lab-key-segments${className ? ` ${className}` : ""}`}
      role="radiogroup"
      id={id}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      onKeyDown={(e) => {
        const way = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
        if (!way) return;
        e.preventDefault();
        const next = ways[(Math.max(0, ways.indexOf(value)) + way + ways.length) % ways.length];
        const group = e.currentTarget;
        pick(next);
        requestAnimationFrame(() => group.querySelector<HTMLElement>(`[data-value="${CSS.escape(next)}"]`)?.focus());
      }}
    >
      {options.map(([o, word]) => (
        <button
          key={o}
          type="button"
          role="radio"
          data-value={o}
          aria-checked={o === value}
          tabIndex={o === value || (!ways.includes(value) && o === ways[0]) ? 0 : -1}
          className={o === value ? "is-on" : ""}
          onClick={() => pick(o)}
        >
          {word}
        </button>
      ))}
    </div>
  );
}

interface ChoiceProps {
  id: string;
  word?: string;
  label: string;
  value: string;
  options: string[];
  tuned: Value | undefined;
  source?: string;
  problem?: string;
  pick: (v: string) => void;
  reset: () => void;
}

/** A choice as a segmented switch: four ways in sight, any more behind an Other… place. */
export function KeyChoice(p: ChoiceProps) {
  const { id, label, value, options, tuned } = p;
  const changed = tuned !== undefined && String(tuned) !== value;
  // Four ways in sight at most; the rarer ones behind a fifth place.
  const main = options.slice(0, 4);
  const rest = options.slice(4);
  return (
    <div className={`lab-key${changed ? " is-changed" : ""}${p.problem ? " is-wrong" : ""}`}>
      <div className="lab-key-head">
        <span className="lab-key-name" id={`${id}-l`}>
          {label}
        </span>
        <Note id={id} tuned={tunedWord(tuned)} unit="" source={p.source} word={p.word} />
      </div>
      <div className="lab-key-control">
        <Segmented
          id={id}
          labelledBy={`${id}-l`}
          describedBy={`${id}-n`}
          value={value}
          options={main.map((o) => [o, choiceWord(o)])}
          pick={p.pick}
        />
        {rest.length ? (
          <span className={`lab-key-box is-select${rest.includes(value) ? " is-on" : ""}`}>
            <select
              aria-label={`${label}: the other ways`}
              value={rest.includes(value) ? value : ""}
              onChange={(e) => e.target.value && p.pick(e.target.value)}
            >
              <option value="" disabled>
                Other…
              </option>
              {rest.map((o) => (
                <option key={o} value={o}>
                  {choiceWord(o)}
                </option>
              ))}
            </select>
          </span>
        ) : null}
        <Reset shown={changed} label={label} act={p.reset} />
      </div>
      <Wrong id={id} said={p.problem} />
    </div>
  );
}
