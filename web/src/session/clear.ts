// The bars that float at the foot of the screen (a newer build running, the agent's notice)
// never lie over a step's own actions: where one would, it is lifted to sit just above them.
// The step's actions move with the layout (a pane's foot on a desk, a bar pinned to the foot
// of a phone's screen, and nothing at all on some steps), so they are measured, not assumed.

const FEET = "#panel .actions";
const floating = ["#newer-build", "#agent-notice:not([hidden])"];

/** How far from the foot of the screen a bar must stand to clear the actions under it. */
function clearance(bar: HTMLElement): number {
  const box = bar.getBoundingClientRect();
  const high = window.innerHeight;
  let clear = 0;
  for (const foot of document.querySelectorAll<HTMLElement>(FEET)) {
    const r = foot.getBoundingClientRect();
    if (!r.width || !r.height || r.bottom <= 0 || r.top >= high) continue; // not on screen
    if (r.right <= box.left || r.left >= box.right) continue; // beside the bar, not under it
    clear = Math.max(clear, high - r.top);
  }
  return Math.ceil(clear);
}

/** Measure again, and set where the bars stand: `--foot-clear` on the page's root. */
export function lift(): void {
  queued = 0;
  const root = document.documentElement;
  const bars = floating.flatMap((s) => [...document.querySelectorAll<HTMLElement>(s)]);
  const clear = Math.max(0, ...bars.map(clearance));
  root.style.setProperty("--foot-clear", `${clear}px`);
  // The agent's notice goes above the newer build's bar, wherever that bar now stands.
  const newer = document.querySelector<HTMLElement>("#newer-build");
  const top = newer ? Math.ceil(window.innerHeight - newer.getBoundingClientRect().top) : 0;
  root.style.setProperty("--newer-top", `${top}px`);
}

let queued = 0;
let watching = false;

function soon(): void {
  if (queued) return;
  queued = requestAnimationFrame(lift);
}

/** Keep the floating bars clear of the actions from now on: on every resize, scroll and redraw. */
export function keepClear(): void {
  lift();
  if (watching) return;
  watching = true;
  addEventListener("resize", soon);
  addEventListener("scroll", soon, true);
  new MutationObserver(soon).observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["hidden"],
  });
}
