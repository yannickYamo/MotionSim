// The what-if bar at the head of every results tab: pin the result as A, change one input, and
// every key figure says how far it moved from A. While the new answer is worked out, the
// figures' shapes stand in their places (Doherty), so the eye never waits on an empty panel.

import { escape } from "../format";
import { icon } from "../icons";
import { comparing } from "../compare";
import { changedSinceA, pin } from "../pin";
import { designNow, focused } from "../store";

/** The bar, once a result is pinned: A's name, what moved since, and the ways to pin the result
 *  now in its place or to unpin. */
export function whatIfBar(): string {
  const a = pin.a;
  const c = focused();
  // Before a pin, the press to pin is the next action at the foot of the results.
  if (!a || !c?.result) return "";
  const moved = changedSinceA();
  const same = designNow() === a.inputs;
  const mark = `<span class="pin-mark" aria-hidden="true">A</span>`;
  const name = `<span class="pin-name">${escape(a.name)}</span>`;
  const what = comparing()
    ? `<span class="pin-said quiet">set aside while things are compared below</span>`
    : same
      ? `<span class="pin-said quiet">change one input</span>`
      : `<span class="pin-said">${moved.lines.map((l) => `<span class="moved">${escape(l)}</span>`).join("")}` +
        `${moved.more ? `<span class="quiet">+${moved.more}</span>` : ""}</span>`;
  const again = same
    ? ""
    : `<button type="button" class="link" data-pin-a title="Make these figures the new A">` +
      `${icon("pin")}Pin this</button>`;
  const off =
    `<button type="button" class="icon-button" data-unpin aria-label="Unpin A" title="Unpin A">` +
    `${icon("x")}</button>`;
  return (
    `<div class="whatif is-pinned" role="group" aria-label="What-if against A">${mark}${name}` +
    `${what}<span class="whatif-tools">${again}${off}</span></div>`
  );
}

/** The verdict's shape while its answer is on its way: a headline bar and three figure cells. */
export function heroSkeleton(): string {
  const cell =
    `<div class="readout"><dt><span class="sk sk-label"></span></dt>` +
    `<dd><span class="sk sk-figure"></span></dd></div>`;
  return `<dl class="key-figures is-skeleton" aria-hidden="true">${cell.repeat(3)}</dl>`;
}
