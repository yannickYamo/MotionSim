// A gain set on the block itself: dragged sideways on its figure, or stepped with the arrow
// keys. Each step is a share of the figure, as a gain is tuned: a twentieth, or a quarter
// with Shift held. The linear view follows as it changes; a test already run is run again
// once the changing has paused. A gain that is no longer the one the scheme was tuned with
// carries a dot that puts it back.

import { useLayoutEffect, useRef } from "react";
import { nudge, resetParam, tunedValue } from "./actions";
import { sig } from "../format";
import { calm } from "./play";
import { useLab } from "./store";

/** A figure's name as it is written: kp_d as Kp d. */
export const gainWord = (name: string): string => {
  // A gain of one axis is written as the engine's verdicts write it: Kp,q.
  const axis = /^(k[pi])_([dq])$/.exec(name);
  if (axis) return `K${axis[1][1]},${axis[2]}`;
  const words = name.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

const STEPS: Record<string, number> = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 };

/** The figure as it is shown: a jump (a reset, another scheme) is counted to over a moment,
 *  a step of a drag is shown at once. Under reduced motion every change is shown at once. */
function useCounted(value: number | null): React.RefObject<HTMLSpanElement | null> {
  const el = useRef<HTMLSpanElement>(null);
  const shown = useRef(value);
  useLayoutEffect(() => {
    const from = shown.current;
    shown.current = value;
    const put = (v: number) => {
      if (el.current) el.current.textContent = sig(v);
    };
    if (value === null) return;
    const jump = from !== null && from !== 0 && (value / from > 1.3 || value / from < 0.77);
    if (!jump || calm()) return put(value);
    put(from);
    const began = performance.now();
    let frame = requestAnimationFrame(function step(now) {
      const share = Math.min(1, (now - began) / 260);
      const eased = 1 - (1 - share) ** 3;
      put(from + (value - from) * eased);
      if (share < 1) frame = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return el;
}

type Span = React.PointerEvent<HTMLSpanElement>;

/** Dragging sideways on a figure: each pixel is a little more than a hundredth of it. */
function useScrub(value: number | null, put: (v: number) => void) {
  const drag = useRef<{ x: number; from: number } | null>(null);
  const end = (e: Span) => {
    drag.current = null;
    e.currentTarget.classList.remove("is-dragged");
  };
  return {
    onPointerDown: (e: Span) => {
      if (value === null) return;
      e.currentTarget.setPointerCapture(e.pointerId);
      drag.current = { x: e.clientX, from: value };
      e.currentTarget.classList.add("is-dragged");
    },
    onPointerMove: (e: Span) => {
      if (drag.current) put(drag.current.from * 1.012 ** (e.clientX - drag.current.x));
    },
    onPointerUp: end,
    onPointerCancel: end,
  };
}

/** The two arrows that say a figure is dragged sideways: shown when it is pointed at or reached. */
const ScrubHint = () => (
  <span className="lab-gain-scrub" aria-hidden="true">
    <svg viewBox="0 0 16 10" width="16" height="10">
      <path d="M5 1L1 5l4 4M11 1l4 4l-4 4" />
    </svg>
  </span>
);

/** The dot beside a changed figure, that puts it back as it was tuned. */
const Reset = ({ word, tuned, act }: { word: string; tuned: string; act: () => void }) => (
  <button
    type="button"
    className="lab-gain-reset nodrag nopan"
    tabIndex={-1}
    aria-label={`Put ${word} back to ${tuned}, as tuned`}
    title={`Changed: back to ${tuned}, as tuned`}
    onClick={act}
  />
);

export function Gain({ block, kind, name }: { block: string; kind: string; name: string }) {
  const value = useLab((s) => {
    const v = s.scheme?.blocks.find((b) => b.name === block)?.params[name];
    return typeof v === "number" ? v : null;
  });
  const tuned = useLab((s) => tunedValue(s, block, name));
  const bounds = useLab((s) => s.presets?.blocks[kind]?.params.find((p) => p.name === name));
  const figure = useCounted(value);
  const put = (v: number) => {
    const held = Math.min(bounds?.high ?? Infinity, Math.max(bounds?.low ?? -Infinity, v));
    if (Number.isFinite(held)) nudge(block, name, Number(held.toPrecision(6)));
  };
  const scrub = useScrub(value, put);
  if (value === null) return null;
  const changed = typeof tuned === "number" && tuned !== value;
  const key = (e: React.KeyboardEvent) => {
    const back = changed && (e.key === "Backspace" || e.key === "Delete");
    const way = STEPS[e.key];
    if (!back && !way) return;
    e.preventDefault();
    e.stopPropagation();
    if (back) resetParam(block, name);
    else put(value * (e.shiftKey ? 1.25 : 1.05) ** way);
  };
  const word = gainWord(name);
  const [first, ...rest] = word.split(" ");
  const back = changed ? ` Backspace puts it back to ${sig(tuned)}.` : "";
  return (
    <span className={`lab-gain-cell${changed ? " is-changed" : ""}`}>
      <span
        className="lab-gain nodrag nopan"
        role="spinbutton"
        tabIndex={0}
        aria-label={`${word} of ${block}${bounds?.unit ? `, in ${bounds.unit}` : ""}${changed ? ", changed" : ""}`}
        aria-valuenow={value}
        aria-valuemin={bounds?.low ?? undefined}
        aria-valuemax={bounds?.high ?? undefined}
        aria-valuetext={sig(value)}
        title={`${word}: drag sideways, or use the arrow keys (Shift for larger steps).${back}`}
        onKeyDown={key}
        {...scrub}
      >
        <span className="lab-gain-name">
          {first}
          {rest.length ? <sub>{rest.join(" ")}</sub> : null}
        </span>
        <ScrubHint />
        <span className="lab-gain-value" ref={figure}>
          {sig(value)}
        </span>
      </span>
      {changed ? <Reset word={`${word} of ${block}`} tuned={sig(tuned)} act={() => resetParam(block, name)} /> : null}
    </span>
  );
}
