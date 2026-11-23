// A plot full screen, in a modal dialog over the page blurred behind it: drawn again at the
// size of the screen, zoomed about the pointer by the wheel or a pinch, moved by a drag, back
// to its first span on a double press or 0, read at the pointer by a crosshair, and saved as
// a PDF or a PNG image. What is plotted is handed in (Plottable): a switching event's edge, or a motion
// through minutes. Escape or Close shut it, and the keyboard goes back to where it was opened.

import { escape } from "../format";
import { icon } from "../icons";
import { timeAt } from "./reading";
import { keySpan, panBy, pinchFactor, wheelFactor, zoomAbout } from "./zoom";
import type { Span } from "./zoom";

/** What a plot is drawn with: where its plot area lies in the drawing. */
export interface Placed {
  box: { x: number; y: number; w: number; h: number };
}

/** Something that can be shown full screen: its words, its spans of time, how it is drawn
 *  and read at an instant, and how it is saved. */
export interface Plottable<D extends Placed = Placed> {
  title: string;
  said: string;
  /** The span shown now, the whole of it, and the span first shown. */
  span(): Span;
  whole(): Span;
  first(): Span;
  /** The narrowest span it may be zoomed to. */
  narrowest: number;
  set(v: Span): void;
  reset(): void;
  draw(v: Span, w: number, h: number): { svg: string; drawn: D };
  /** Where each dot of the crosshair sits up the drawing at t, and the line read beside it. */
  read(t: number, v: Span, drawn: D): { ys: number[]; text: string };
  pdf(v: Span): Promise<string>;
  /** Where the keyboard goes back to once it is shut. */
  back(): HTMLElement | null;
  /** What is open, for the page and its tests. */
  meta: unknown;
}

interface Open {
  p: Plottable;
  drawn: Placed | null;
  w: number;
  at: number | null;
}

let open: Open | null = null;
let watch: ResizeObserver | null = null;
let dialog: HTMLDialogElement | null = null;

const KEYS = "+ and − zoom, the arrows move, 0 goes back, Escape closes";

const plotEl = () => dialog?.querySelector<HTMLElement>("[data-full-plot]") ?? null;

function shell(): HTMLDialogElement {
  if (dialog?.isConnected) return dialog;
  dialog = document.createElement("dialog");
  dialog.className = "ev-full";
  dialog.setAttribute("aria-labelledby", "ev-full-h");
  dialog.setAttribute("aria-describedby", "ev-full-said");
  dialog.addEventListener("click", onClick);
  dialog.addEventListener("keydown", onKey);
  dialog.addEventListener("close", onClosed);
  dialog.addEventListener("wheel", onWheel, { passive: false });
  dialog.addEventListener("pointerdown", onDown);
  dialog.addEventListener("pointermove", onMove);
  dialog.addEventListener("pointerup", onUp);
  dialog.addEventListener("pointercancel", onUp);
  dialog.addEventListener("pointerleave", onLeave);
  dialog.addEventListener("dblclick", onDouble);
  document.body.append(dialog);
  return dialog;
}

/** Open a plot full screen. */
export function openPlot(p: Plottable): void {
  const d = shell();
  open = { p, drawn: null, w: 0, at: null };
  d.innerHTML =
    `<header class="ev-full-head"><div class="ev-full-title">` +
    `<h2 id="ev-full-h">${escape(p.title)}</h2>` +
    `<p id="ev-full-said" class="quiet small">${escape(p.said)}</p></div>` +
    `<div class="ev-full-actions">` +
    `<button type="button" class="ghost" data-full-reset>Reset zoom</button>` +
    `<button type="button" class="ghost" data-full-png>${icon("photo-down")}Export PNG</button>` +
    `<button type="button" class="ghost" data-full-pdf>${icon("download")}Export PDF</button>` +
    `</div><button type="button" class="close" data-full-close aria-label="Close">${icon("x")}</button>` +
    `</header>` +
    `<div class="ev-full-plot" tabindex="0" role="group" data-full-plot ` +
    `aria-label="${escape(p.title)}: ${KEYS}" aria-describedby="ev-full-read"></div>` +
    `<output class="ev-full-read quiet small" id="ev-full-read">Wheel or pinch to zoom about the pointer, ` +
    `drag to move, double-press or 0 to go back. Point at it to read every trace.</output>` +
    `<p class="ev-full-status quiet small" role="status" id="ev-full-status"></p>`;
  if (typeof d.showModal === "function") d.showModal();
  else d.setAttribute("open", "");
  // Drawn again whenever its place changes size: once laid out, on a turn of the phone, on a resize.
  watch?.disconnect();
  watch = typeof ResizeObserver === "function" ? new ResizeObserver(() => redraw()) : null;
  const el = plotEl();
  if (watch && el) watch.observe(el);
  else window.addEventListener("resize", redraw);
  redraw();
  el?.focus();
}

/** Shut the dialog: the keyboard goes back to where it was opened from. */
export function closePlot(): void {
  if (!dialog) return;
  if (typeof dialog.close === "function" && dialog.open) dialog.close();
  else onClosed();
}

function onClosed(): void {
  window.removeEventListener("resize", redraw);
  watch?.disconnect();
  watch = null;
  dialog?.removeAttribute("open");
  const was = open;
  open = null;
  down.clear();
  was?.p.back()?.focus();
}

/** Draw the plot again at the size it now has on the screen, at its span. */
function redraw(): void {
  const el = plotEl();
  if (!open || !el) return;
  const w = Math.max(Math.round(el.clientWidth), 240);
  const h = Math.max(Math.round(el.clientHeight), 180);
  const { svg, drawn } = open.p.draw(open.p.span(), w, h);
  el.innerHTML = svg;
  // The words above the plot are those of what is drawn now.
  const say = (id: string, text: string) => {
    const at = dialog?.querySelector(id);
    if (at && at.textContent !== text) at.textContent = text;
  };
  say("#ev-full-h", open.p.title);
  say("#ev-full-said", open.p.said);
  open.drawn = drawn;
  open.w = w;
  if (open.at !== null) cross(open.at);
}

function show(v: Span): void {
  if (!open) return;
  open.p.set(v);
  redraw();
}

const spanNow = (): { v: Span; all: Span; first: Span; n: number } | null =>
  open ? { v: open.p.span(), all: open.p.whole(), first: open.p.first(), n: open.p.narrowest } : null;

/** The instant under a point on the screen, and whether it is over the plot. */
function instant(clientX: number): { t: number; inside: boolean } | null {
  const s = spanNow();
  const svg = plotEl()?.querySelector("svg");
  if (!s || !open?.drawn || !svg) return null;
  return timeAt(clientX, svg.getBoundingClientRect(), s.v, open.drawn.box, open.w);
}

/** The crosshair at an instant, a dot on each trace, and every trace read beside the plot. */
function cross(t: number): void {
  const s = spanNow();
  const g = plotEl()?.querySelector<SVGGElement>(".ev-cross");
  const out = dialog?.querySelector("#ev-full-read");
  if (!s || !open?.drawn || !g || !out) return;
  const { box } = open.drawn;
  const x = box.x + ((t - s.v.t0) / (s.v.t1 - s.v.t0)) * box.w;
  g.setAttribute("transform", `translate(${x.toFixed(1)} 0)`);
  g.setAttribute("visibility", "visible");
  const { ys, text } = open.p.read(t, s.v, open.drawn);
  g.querySelectorAll("circle").forEach((dot, k) => {
    if (ys[k] !== undefined && Number.isFinite(ys[k])) dot.setAttribute("cy", ys[k].toFixed(1));
  });
  out.textContent = text;
}

function hideCross(): void {
  plotEl()?.querySelector(".ev-cross")?.setAttribute("visibility", "hidden");
}

function onWheel(e: WheelEvent): void {
  const s = spanNow();
  const at = instant(e.clientX);
  if (!s || !at || !(e.target as Element).closest?.("[data-full-plot]")) return;
  e.preventDefault();
  show(zoomAbout(s.v, at.t, wheelFactor(e.deltaY, e.deltaMode, e.ctrlKey), s.all, s.n));
}

/** The pointers down on the plot, where each was last, and where the first went down. */
const down = new Map<number, number>();
let pinchFrom = 0;
let from: { x: number; y: number } | null = null;

const spread = () => {
  const [a, b] = [...down.values()];
  return Math.abs(a - b);
};

function onDown(e: PointerEvent): void {
  if (!(e.target as Element).closest?.("[data-full-plot]")) return;
  down.set(e.pointerId, e.clientX);
  from = down.size === 1 ? { x: e.clientX, y: e.clientY } : null;
  plotEl()?.setPointerCapture?.(e.pointerId);
  if (down.size === 2) pinchFrom = spread();
}

function onMove(e: PointerEvent): void {
  const s = spanNow();
  const was = down.get(e.pointerId);
  if (s && was !== undefined && open?.drawn) {
    down.set(e.pointerId, e.clientX);
    const rect = plotEl()!.querySelector("svg")!.getBoundingClientRect();
    if (down.size === 1) {
      const dt = ((was - e.clientX) / ((rect.width * open.drawn.box.w) / open.w)) * (s.v.t1 - s.v.t0);
      if (dt !== 0) show(panBy(s.v, dt, s.all, s.n));
    } else {
      const now = spread();
      if (pinchFrom > 0 && now > 0) {
        const [a, b] = [...down.values()];
        const mid = timeAt((a + b) / 2, rect, s.v, open.drawn.box, open.w).t;
        show(zoomAbout(s.v, mid, pinchFactor(now, pinchFrom), s.all, s.n));
      }
      pinchFrom = now;
    }
  }
  if (e.pointerType === "touch" && down.size > 0 && !tapped(e)) return;
  const at = instant(e.clientX);
  if (!open || !at) return;
  if (!at.inside) return hideCross();
  open.at = at.t;
  cross(at.t);
}

/** A touch that has not moved past a few pixels: a tap, which reads the plot there. */
const tapped = (e: PointerEvent) => !!from && Math.hypot(e.clientX - from.x, e.clientY - from.y) < 4;

function onUp(e: PointerEvent): void {
  if (e.pointerType === "touch" && down.size === 1 && tapped(e)) {
    const at = instant(e.clientX);
    if (open && at?.inside) {
      open.at = at.t;
      cross(at.t);
    }
  }
  down.delete(e.pointerId);
  pinchFrom = down.size === 2 ? spread() : 0;
  if (!down.size) from = null;
}

function onLeave(e: PointerEvent): void {
  if (e.pointerType !== "touch" && !down.size) hideCross();
}

function onDouble(e: MouseEvent): void {
  if (!open || !(e.target as Element).closest?.("[data-full-plot]")) return;
  open.p.reset();
  redraw();
}

function onKey(e: KeyboardEvent): void {
  if (e.key === "Tab") return trap(e);
  if (!open || !(e.target as Element).closest?.("[data-full-plot]") || e.ctrlKey || e.metaKey || e.altKey) return;
  const s = spanNow();
  const next = s && keySpan(e.key, s.v, s.all, s.first, s.n);
  if (!next) return;
  e.preventDefault();
  show(next);
}

/** The keyboard stays inside the dialog: Tab from its last control goes to its first. */
function trap(e: KeyboardEvent): void {
  if (!dialog) return;
  const stops = [...dialog.querySelectorAll<HTMLElement>("button:not(:disabled), [tabindex='0']")];
  if (!stops.length) return;
  const [first, last] = [stops[0], stops[stops.length - 1]];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

function onClick(e: MouseEvent): void {
  const t = e.target as Element;
  if (t.closest?.("[data-full-close]")) return closePlot();
  if (t.closest?.("[data-full-reset]") && open) {
    open.p.reset();
    redraw();
    return;
  }
  const pdf = t.closest?.<HTMLButtonElement>("[data-full-pdf]");
  if (pdf) return void saveAsPdf(pdf);
  const png = t.closest?.<HTMLButtonElement>("[data-full-png]");
  if (png) void saveAsPng(png);
}

/** Export the plot as it is zoomed now, as an image; the button waits while it is made. */
async function saveAsPng(button: HTMLButtonElement): Promise<void> {
  const svg = plotEl()?.querySelector<SVGSVGElement>("svg");
  const status = dialog?.querySelector("#ev-full-status");
  if (!svg || !open || !status) return;
  const { title, said } = open.p;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  status.textContent = "Making the image…";
  try {
    const { savePng } = await import("../charts/png");
    status.textContent = `Saved as ${await savePng(svg, title, said)}.`;
  } catch (err) {
    status.textContent = `The image could not be made: ${String((err as Error)?.message ?? err)}. Try again.`;
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

/** Export the plot as it is zoomed now; the button waits while the PDF is made. */
async function saveAsPdf(button: HTMLButtonElement): Promise<void> {
  const s = spanNow();
  const status = dialog?.querySelector("#ev-full-status");
  if (!s || !open || !status) return;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  status.textContent = "Making the PDF…";
  try {
    const name = await open.p.pdf(s.v);
    status.textContent = `Saved as ${name}.`;
  } catch (err) {
    status.textContent = `The PDF could not be made: ${String((err as Error)?.message ?? err)}. Try again.`;
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}
