// A finding taken to where it is seen: its strip of the scope (probed first if it is not), the
// loop of the Laplace lens it was read on, or the cost and the junction through the run. What
// it points at is lit for a moment; nothing else moves.

import { setTab, togglePlotted } from "./actions";
import type { Target } from "./findings";
import { calm } from "./play";
import { lab } from "./store";
import { usualWires } from "./wires";

type Loop = "current_q" | "speed";

/** The loop the Laplace lens is asked to show, for the lens to take when it opens. */
let askedLoop: Loop | null = null;
const listeners = new Set<(loop: Loop) => void>();

export const loopAsked = (): Loop | null => askedLoop;

/** Follow the loop asked for while the lens is open. */
export function onLoopAsked(act: (loop: Loop) => void): () => void {
  listeners.add(act);
  return () => listeners.delete(act);
}

const bring = (el: Element | null | undefined) =>
  el?.scrollIntoView?.({ block: "nearest", behavior: calm() ? "auto" : "smooth" });

/** Light a mark for a moment: the eye finds it, and it goes back to how it was. */
function light(els: Element[]): void {
  for (const el of els) {
    el.classList.remove("is-pointed");
    // A reflow between, so that pointing twice lights it twice.
    void (el as HTMLElement).getBoundingClientRect?.();
    el.classList.add("is-pointed");
    window.setTimeout(() => el.classList.remove("is-pointed"), 1600);
  }
}

/** Take a finding to where it is seen. */
export function pointAt(target: Target): void {
  if (target.kind === "laplace") {
    askedLoop = target.loop;
    listeners.forEach((l) => l(target.loop));
    setTab("laplace");
    window.requestAnimationFrame(() => bring(document.getElementById("lab-tab-body")));
    return;
  }
  if (target.kind === "cost") {
    setTab("run");
    window.requestAnimationFrame(() => {
      const more = document.querySelector<HTMLDetailsElement>(".lab-cost-view .lab-more");
      if (more) more.open = true;
      const plot = document.querySelector(".lab-cost-view .lab-thermal") ?? document.querySelector(".lab-cost-view");
      bring(plot);
      if (plot) light([plot]);
    });
    return;
  }
  const find = () => document.querySelector(`.scope-strip[data-strip="${CSS.escape(target.group)}"]`);
  if (!find()) {
    const s = lab.get();
    const probed = s.plotted ?? usualWires(s);
    if (!probed.includes(target.wire)) togglePlotted(target.wire, usualWires(s));
  }
  // The strip is drawn on the next frame where it was just probed.
  window.requestAnimationFrame(() =>
    window.requestAnimationFrame(() => {
      const strip = find();
      if (!strip) return;
      bring(strip);
      const marks = [...strip.querySelectorAll(`[data-note="${CSS.escape(target.note)}"]`)];
      light(marks.length ? marks : [strip]);
    }),
  );
}
