// How the event's plots answer the hand: the wheel and a pinch zoom about the pointer, in
// proportion to how far they move, a drag moves along time, and a press (a click that has
// not moved past a few pixels) opens the plot under it full screen. The keys do the same
// from the keyboard, Enter opening it. Pointing reads every trace at that instant.
//
// A page scrolled past a plot is never caught by it: the wheel zooms only once the pointer
// has rested on the plot for a moment with the page still, and otherwise scrolls the page.

import { openFull } from "./full";
import { partAtY } from "./part";
import type { Part } from "./part";
import { setFlags } from "../charts/flag";
import { ranges, USUAL, valuesAt, yOf } from "./plot";
import type { Layout } from "./plot";
import { flagsAt, readingAt, timeAt } from "./reading";
import { edgeOf, eventNow, layoutOf, resetSpan, setSpan, spanOf } from "./spans";
import type { Which } from "./svg";
import { keySpan, firstSpan, panBy, pinchFactor, wheelFactor, whole, zoomAbout } from "./zoom";
import type { Span } from "./zoom";

export { readingAt } from "./reading";

/** How long the pointer rests on a plot, with the page still, before the wheel zooms it. */
export const DWELL_MS = 350;
/** A press that moves less than this, in pixels, is a press; more, a drag. */
export const CLICK_PX = 4;
/** How long a press waits for a second one, which goes back to the first span instead. */
export const DOUBLE_MS = 250;

/** The plot under an event, with its edge and what it shows now. */
interface Pointed {
  el: HTMLElement;
  which: Which;
  v: Span;
  all: Span;
  /** The layout the drawing under the pointer was made with. */
  lay: Layout;
}

function plotAt(target: EventTarget | null): Pointed | null {
  const el = (target as Element | null)?.closest?.<HTMLElement>("[data-edge-plot]");
  const ev = eventNow();
  if (!el || !ev) return null;
  const which = el.dataset.edgePlot as Which;
  const e = edgeOf(ev, which);
  return { el, which, v: spanOf(which, e), all: whole(e), lay: layoutOf(which) };
}

/** Where a point on the screen falls in time on a plot, and whether it is inside the plot. */
export const timeAtX = (clientX: number, rect: { left: number; width: number }, v: Span, lay: Layout = USUAL) =>
  timeAt(clientX, rect, v, lay.top, lay.view.w);

/** Which of an edge's two plots a point on the screen is over: the voltage and current
 *  above, the gate and power beneath, parted halfway across the gap between them. */
export function partAt(clientY: number, rect: { top: number; height: number }, lay: Layout = USUAL): Part {
  const y = ((clientY - rect.top) / rect.height) * lay.view.h;
  return partAtY(y, (lay.top.y + lay.top.h + lay.low.y) / 2);
}

const rectOf = (el: HTMLElement) => el.querySelector("svg")?.getBoundingClientRect() ?? el.getBoundingClientRect();

/** Whether the wheel may zoom: the pointer has rested on this plot for DWELL_MS and the
 *  page has not scrolled in that time. A pinch on a trackpad (the wheel with Ctrl) zooms at
 *  once: it is never a page's scroll. */
export function wheelZooms(now: number, restingSince: number | null, scrolledAt: number, pinch: boolean): boolean {
  if (pinch) return true;
  return restingSince !== null && now - restingSince >= DWELL_MS && now - scrolledAt >= DWELL_MS;
}

/** The plot the pointer rests on, since when, and when anything on the page last scrolled. */
let resting: { el: Element; since: number } | null = null;
let scrolledAt = -Infinity;

function onWheel(e: WheelEvent): void {
  const p = plotAt(e.target);
  if (!p) return;
  const since = resting?.el === p.el ? resting.since : null;
  if (!wheelZooms(e.timeStamp || performance.now(), since, scrolledAt, e.ctrlKey)) return;
  e.preventDefault();
  const { t } = timeAtX(e.clientX, rectOf(p.el), p.v, p.lay);
  setSpan(p.which, zoomAbout(p.v, t, wheelFactor(e.deltaY, e.deltaMode, e.ctrlKey), p.all));
}

function onScroll(e: Event): void {
  scrolledAt = e.timeStamp || performance.now();
  resting = null;
}

/** The pointers down on a plot, where each was last; where the first went down, and whether
 *  it has moved far enough to be a drag. */
const down = new Map<number, number>();
let pinchFrom = 0;
let press: { x: number; y: number; dragged: boolean; pinched: boolean } | null = null;
let pending = 0;

function onDown(e: PointerEvent): void {
  const p = plotAt(e.target);
  if (!p || (e.pointerType === "mouse" && e.button !== 0)) return;
  down.set(e.pointerId, e.clientX);
  if (down.size === 1) press = { x: e.clientX, y: e.clientY, dragged: false, pinched: false };
  p.el.setPointerCapture?.(e.pointerId);
  if (down.size === 2) {
    pinchFrom = spread();
    if (press) press.pinched = true;
  }
}

const spread = () => {
  const [a, b] = [...down.values()];
  return Math.abs(a - b);
};

function onMove(e: PointerEvent): void {
  const p = plotAt(e.target);
  if (!p) {
    resting = null;
    return;
  }
  if (resting?.el !== p.el) resting = { el: p.el, since: e.timeStamp || performance.now() };
  const was = down.get(e.pointerId);
  if (was !== undefined) moved(p, e, was);
  readAt(p, e.clientX);
}

/** A drag moves along time once it has gone past a press; two pointers moving apart or
 *  together zoom about their middle. */
function moved(p: Pointed, e: PointerEvent, was: number): void {
  if (press && !press.dragged && Math.hypot(e.clientX - press.x, e.clientY - press.y) >= CLICK_PX) {
    press.dragged = true;
  }
  if (down.size === 1 && !press?.dragged) return;
  down.set(e.pointerId, e.clientX);
  const rect = rectOf(p.el);
  if (down.size === 1) {
    const dt = ((was - e.clientX) / ((rect.width * p.lay.top.w) / p.lay.view.w)) * (p.v.t1 - p.v.t0);
    setSpan(p.which, panBy(p.v, dt, p.all));
    return;
  }
  const now = spread();
  if (pinchFrom > 0 && now > 0) {
    const [a, b] = [...down.values()];
    setSpan(p.which, zoomAbout(p.v, timeAtX((a + b) / 2, rect, p.v, p.lay).t, pinchFactor(now, pinchFrom), p.all));
  }
  pinchFrom = now;
}

/** Whether a press let go is a press: one pointer, never a pinch, moved under CLICK_PX. */
export const isPress = (from: { x: number; y: number }, x: number, y: number, dragged: boolean, pinched: boolean) =>
  !dragged && !pinched && Math.hypot(x - from.x, y - from.y) < CLICK_PX;

function onUp(e: PointerEvent): void {
  const p = plotAt(e.target);
  const last = down.size === 1 && down.has(e.pointerId);
  down.delete(e.pointerId);
  pinchFrom = down.size === 2 ? spread() : 0;
  if (!last || !press) return;
  const was = press;
  press = null;
  if (!p || e.type === "pointercancel" || !isPress(was, e.clientX, e.clientY, was.dragged, was.pinched)) return;
  // A press opens the plot full screen, unless a second press follows, which goes back.
  const part = partAt(was.y, rectOf(p.el), p.lay);
  const which = p.which;
  clearTimeout(pending);
  pending = window.setTimeout(() => openFull(which, part), DOUBLE_MS);
}

/** Each trace at the instant pointed at: said under the plot, and shown on it by a hairline, a
 *  dot on each trace and a flag of each value. */
function readAt(p: Pointed, clientX: number): void {
  const ev = eventNow()!;
  const { t, inside } = timeAtX(clientX, rectOf(p.el), p.v, p.lay);
  const cross = p.el.querySelector<SVGGElement>(".ev-cross");
  const out = document.getElementById(`ev-read-${p.which}`);
  if (!cross || !out || !inside) return void cross?.setAttribute("visibility", "hidden");
  const { top, low } = p.lay;
  const e = edgeOf(ev, p.which);
  const x = top.x + ((t - p.v.t0) / (p.v.t1 - p.v.t0)) * top.w;
  cross.setAttribute("transform", `translate(${x.toFixed(1)} 0)`);
  cross.setAttribute("visibility", "visible");
  // The dots and the flags, in the order they were drawn: voltage, current, gate, power.
  const r = ranges(e, p.v, ev.v_max);
  const at = valuesAt(e, t);
  const ys = [
    yOf(top, r.top[0])(at.v_ds),
    yOf(top, r.top[1])(at.i),
    yOf(low, r.low[0])(at.v_gs),
    yOf(low, r.low[1])(at.p),
  ];
  cross.querySelectorAll("circle.ev-dot").forEach((dot, k) => dot.setAttribute("cy", ys[k].toFixed(1)));
  const said = flagsAt(e, t);
  setFlags(
    [...cross.querySelectorAll(".plot-flag")],
    ys.map((y, k) => ({ y, text: said[k], box: k < 2 ? top : low })),
    x,
  );
  out.textContent = readingAt(ev.kind, e, t, p.v);
}

function onKey(e: KeyboardEvent): void {
  const p = plotAt(e.target);
  if (!p || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    openFull(p.which, "vi");
    return;
  }
  const next = keySpan(e.key, p.v, p.all, firstSpan(edgeOf(eventNow()!, p.which)));
  if (!next) return;
  e.preventDefault();
  setSpan(p.which, next);
}

function onDouble(e: MouseEvent): void {
  const p = plotAt(e.target);
  if (!p) return;
  clearTimeout(pending);
  resetSpan(p.which);
}

/** The buttons beside an edge that open one of its plots full screen. */
function onOpen(e: MouseEvent): void {
  const b = (e.target as Element | null)?.closest?.<HTMLElement>("[data-full-open]");
  if (!b) return;
  const [which, part] = (b.dataset.fullOpen ?? "on:vi").split(":") as [Which, Part];
  openFull(which, part);
}

let wired = false;

/** Listen once, on the document, so the plots answer however often they are drawn again. */
export function wirePlots(): void {
  if (wired || typeof document === "undefined") return;
  wired = true;
  document.addEventListener("wheel", onWheel, { passive: false });
  document.addEventListener("scroll", onScroll, { passive: true, capture: true });
  document.addEventListener("pointerdown", onDown);
  document.addEventListener("pointermove", onMove);
  document.addEventListener("pointerup", onUp);
  document.addEventListener("pointercancel", onUp);
  document.addEventListener("keydown", onKey);
  document.addEventListener("dblclick", onDouble);
  document.addEventListener("click", onOpen);
}
