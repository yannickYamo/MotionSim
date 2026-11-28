// What the event's plots hold between redraws: the event drawn last, and the span of time
// each edge is zoomed to. A new answer keeps the zoom, held inside its own trace.

import type { EventEdge, SwitchingEvent } from "../api";
import { fit, refit } from "../charts/fit";
import { layout, pairPower, USUAL } from "./plot";
import type { Layout } from "./plot";
import { edgeSvgIn } from "./svg";
import type { Which } from "./svg";
import { clampSpan, firstSpan, whole } from "./zoom";
import type { Span } from "./zoom";

const spans = new Map<Which, Span>();

let current: SwitchingEvent | null = null;

/** The event drawn last, for the pointer and the keys to read. */
export const eventNow = () => current;
export const holdEvent = (ev: SwitchingEvent) => void (current = ev);

export const edgeOf = (ev: SwitchingEvent, which: Which): EventEdge => (which === "on" ? ev.turn_on : ev.turn_off);

/** The span an edge is shown over: the one the user zoomed to, kept inside the trace, else the first. */
export function spanOf(which: Which, e: EventEdge): Span {
  const held = spans.get(which);
  return held ? clampSpan(held, whole(e)) : firstSpan(e);
}

/** The layout each edge was drawn with last: what the pointer reads the drawing by. */
const layouts = new Map<Which, Layout>();
export const layoutOf = (which: Which): Layout => layouts.get(which) ?? USUAL;

/** The name an edge's drawing is fitted to its place by (charts/fit.ts). */
export const fitKey = (which: Which) => `ev-${which}`;

/** One edge's drawing over its span, laid out for the width it is shown at: its place is
 *  watched, and it is drawn again when that place has another width. */
export function plotSvg(ev: SwitchingEvent, which: Which): string {
  return fit(
    fitKey(which),
    (width) => {
      const now = current ?? ev;
      const e = edgeOf(now, which);
      const features = (now.signature?.features ?? []).filter((f) => f.edge === which);
      const lay = layout(width);
      layouts.set(which, lay);
      const drawing = { kind: now.kind, vMax: now.v_max, which, features, per: pairPower(now) };
      return edgeSvgIn(lay, e, spanOf(which, e), drawing);
    },
    USUAL.view.w,
  );
}

/** Show an edge over another span, and draw it again in place. */
export function setSpan(which: Which, v: Span): void {
  spans.set(which, v);
  if (current) refit(fitKey(which));
}

/** Nothing is held of an event: the design it was of is gone, and its zoom with it. */
export function forgetEvent(): void {
  spans.clear();
  current = null;
}

/** Back to the span first shown. */
export function resetSpan(which: Which): void {
  if (current) setSpan(which, firstSpan(edgeOf(current, which)));
}
