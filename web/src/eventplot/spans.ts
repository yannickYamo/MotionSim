// What the event's plots hold between redraws: the event drawn last, and the span of time
// each edge is zoomed to. A new answer keeps the zoom, held inside its own trace.

import type { EventEdge, SwitchingEvent } from "../api";
import { edgeSvg } from "./svg";
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

/** One edge's drawing over its span. */
export function plotSvg(ev: SwitchingEvent, which: Which): string {
  const e = edgeOf(ev, which);
  const features = (ev.signature?.features ?? []).filter((f) => f.edge === which);
  return edgeSvg(e, spanOf(which, e), ev.kind, ev.v_max, which, features);
}

/** Show an edge over another span, and draw it again in place. */
export function setSpan(which: Which, v: Span): void {
  spans.set(which, v);
  const plot = document.querySelector(`[data-edge-plot="${which}"]`);
  if (current && plot) plot.innerHTML = plotSvg(current, which);
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
