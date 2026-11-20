// The way from a check about one figure to its box: a figure the tool took for a typed part's
// box left empty, or a cooling it sized. The part's figures as they were typed are brought
// back, so that only the datasheet's figure is left to give.

import { save } from "../state";
import { DEVICE, SUPPLY } from "../steps";
import { app, draw, ui, underTest } from "../store";
import { boxOf } from "../typedkind";

/** The cooling figures a check may be about: their boxes are in the supply step. */
const COOLING = new Set(["rth_sink", "board_area"]);

/** Go to the box the check names, the keyboard in it, with the part's typed figures back in
 *  the form where it was typed in on this page. */
export function toFigure(field: string, device: string): void {
  const { state } = app;
  if (COOLING.has(field)) {
    state.step = SUPPLY;
    draw.panel();
    draw.rail();
    return focusBox(`#f-conditions-${field}`);
  }
  // A check of the motion is of the device under test: it names no part of its own.
  const kept = state.typedOf[device || (underTest() ?? "")];
  if (kept) {
    state.typed = { ...kept };
    ui.typedFrom = device || (underTest() ?? null);
  }
  ui.typedWrong = {};
  ui.typedRefused = null;
  ui.typedOpen = true;
  state.step = DEVICE;
  draw.panel();
  draw.rail();
  focusBox(`#t-${boxOf(field)}`);
}

/** The keyboard to a box, opening the fold it is in. */
function focusBox(selector: string): void {
  const box = document.querySelector<HTMLElement>(selector);
  if (!box) return;
  for (let fold = box.closest("details"); fold; fold = fold.parentElement?.closest("details") ?? null) fold.open = true;
  box.scrollIntoView({ block: "center" });
  box.focus();
}

/** The kind of part being typed in, picked: its figures are asked for, and what was typed
 *  for another kind is kept for it. What the page found wrong was of the other kind's boxes. */
export function pickTypedKind(el: HTMLInputElement): void {
  app.state.typed = { ...app.state.typed, kind: el.value };
  save(app.state);
  ui.typedWrong = {};
  ui.typedNotes = {};
  ui.typedRefused = null;
  ui.typedOpen = true;
  draw.panel(true);
  document.querySelector<HTMLElement>(`[data-typed-kind][value="${el.value}"]`)?.focus();
}
