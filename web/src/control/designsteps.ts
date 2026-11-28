// The figures of the design the lab may point at: set on the page's steps, not in the lab.

import { goTo } from "../actions";
import { LOAD, SUPPLY } from "../steps";

/** The figures of the design itself a lever may name, set on the page's steps, not in the lab. */
export const DESIGN_STEPS: Record<string, { words: string; step: number; field: string }> = {
  f_sw: { words: "Set the switching frequency · Supply and point", step: SUPPLY, field: "f-conditions-f_khz" },
  front_end: { words: "Change the front end · Supply and point", step: SUPPLY, field: "fe-change" },
  fe_link: { words: "The two controls, tied or not · Supply and point", step: SUPPLY, field: "f-conditions-fe_tie" },
  c_link: { words: "Set the link capacitance · Load", step: LOAD, field: "f-sink-c_link_uf" },
};

/** Close the lab and take the page to the step where a figure of the design is set, at its field. */
export function openDesign(param: string): void {
  const at = DESIGN_STEPS[param];
  if (!at) return;
  document.querySelector<HTMLDialogElement>("dialog.control-lab")?.close();
  goTo(at.step);
  window.requestAnimationFrame(() => {
    const el = document.getElementById(at.field);
    // A field under a fold: the fold opens for it.
    for (let fold = el?.closest("details"); fold; fold = fold.parentElement?.closest("details")) fold.open = true;
    el?.focus();
  });
}
