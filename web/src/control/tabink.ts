// The underline of the lab's tabs: one mark, which slides from the tab left to the tab taken.
// Where the selected tab stands is measured and said to the strip as --ink-x, --ink-y and
// --ink-w (menus.css draws the mark from them); a strip that cannot be measured keeps the
// underline each tab draws for itself.

import { useLayoutEffect } from "react";

/** Where the mark goes under a tab: along its words, on the strip's own rule. */
export function inkOf(tab: HTMLElement): { x: number; y: number; w: number } | null {
  if (!tab.offsetWidth) return null;
  const pad = Number.parseFloat(getComputedStyle(tab).paddingLeft) || 0;
  return {
    x: tab.offsetLeft + pad,
    y: tab.offsetTop + tab.offsetHeight - 2,
    w: Math.max(0, tab.offsetWidth - 2 * pad),
  };
}

function measure(strip: HTMLElement): void {
  const tab = strip.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
  const ink = tab ? inkOf(tab) : null;
  strip.classList.toggle("has-ink", !!ink);
  if (!ink) return;
  strip.style.setProperty("--ink-x", `${ink.x}px`);
  strip.style.setProperty("--ink-y", `${ink.y}px`);
  strip.style.setProperty("--ink-w", `${ink.w}px`);
}

/** Keep the mark under the selected tab: as the tab changes (it slides), and as the strip is
 *  resized or its words take their face (it is put there, with no slide). */
export function useTabInk(strip: React.RefObject<HTMLElement | null>, selected: string): void {
  useLayoutEffect(() => {
    if (strip.current) measure(strip.current);
  }, [strip, selected]);
  useLayoutEffect(() => {
    const el = strip.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    // Only once it stands under its tab does a change of tab slide it.
    const live = requestAnimationFrame(() => el.classList.add("is-live"));
    const put = () => {
      el.classList.remove("is-live");
      measure(el);
      requestAnimationFrame(() => el.classList.add("is-live"));
    };
    const seen = new ResizeObserver(put);
    seen.observe(el);
    void document.fonts?.ready.then(put);
    return () => {
      cancelAnimationFrame(live);
      seen.disconnect();
    };
  }, [strip]);
}
