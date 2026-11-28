// Drawings made at the size they are shown. A graph whose drawing is scaled to its place has
// words that grow and shrink with it; one drawn for the width it has keeps its figures at their
// own size on a desk and on a phone alike. A graph names itself and hands over how it is drawn
// for a width; its place on the page is watched, and it is drawn again when that place comes
// onto the page at another width or changes width (the window, the column beside it, a phone
// turned). The page's own redraws use the width last seen, so nothing jumps between the two.

/** How a graph is drawn for the width it is shown at, in pixels. */
export type Draw = (width: number) => string;

const draws = new Map<string, Draw>();
const widths = new Map<string, number>();
const usuals = new Map<string, number>();

/** The width a graph is drawn at where its place has not been seen yet. */
export const USUAL_WIDTH = 640;

/** The width a graph was last seen at, or `usual` where it has not been seen. */
export const fitWidth = (key: string, usual = usuals.get(key) ?? USUAL_WIDTH): number => widths.get(key) ?? usual;

/** The room an element has across for its drawing: its width less its own padding. */
function roomIn(el: HTMLElement): number {
  const style = getComputedStyle(el);
  const pad = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
  return Math.round(el.clientWidth - pad);
}

/** Draw a graph again in its place, at the width that place has now. */
export function refit(key: string): void {
  if (typeof document === "undefined") return;
  const draw = draws.get(key);
  const el = document.querySelector<HTMLElement>(`[data-fit="${key}"]`);
  if (!draw || !el) return;
  const room = roomIn(el);
  if (room > 0) widths.set(key, room);
  el.innerHTML = draw(fitWidth(key));
}

let sizes: ResizeObserver | null = null;
let watching = false;
const watched = new WeakSet<Element>();

function seen(entries: ResizeObserverEntry[]): void {
  for (const entry of entries) {
    const el = entry.target as HTMLElement;
    const key = el.dataset.fit;
    if (!key || !el.isConnected || !draws.has(key)) continue;
    const room = roomIn(el);
    if (room > 0 && Math.abs(room - (widths.get(key) ?? -1)) > 1) refit(key);
  }
}

/** Watch every place a fitted graph stands in, those that come onto the page later included. */
function watch(): void {
  if (watching || typeof document === "undefined" || typeof ResizeObserver !== "function") return;
  watching = true;
  sizes = new ResizeObserver(seen);
  const look = () =>
    document.querySelectorAll("[data-fit]").forEach((el) => {
      if (watched.has(el)) return;
      watched.add(el);
      sizes?.observe(el);
    });
  look();
  if (typeof MutationObserver === "function" && document.body) {
    new MutationObserver(look).observe(document.body, { childList: true, subtree: true });
  }
}

/** Name a graph and say how it is drawn; its drawing at the width last seen comes back. */
export function fit(key: string, draw: Draw, usual = USUAL_WIDTH): string {
  draws.set(key, draw);
  usuals.set(key, usual);
  watch();
  return draw(fitWidth(key, usual));
}

/** A fitted graph in the element that is its place. */
export const fitted = (key: string, draw: Draw, usual = USUAL_WIDTH): string =>
  `<div class="plot-fit" data-fit="${key}">${fit(key, draw, usual)}</div>`;

/** Forget what was seen: for the tests, which draw the same graphs at widths of their own. */
export function forgetFits(): void {
  draws.clear();
  widths.clear();
  usuals.clear();
}
