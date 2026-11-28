// What is typed into a box, kept as it is typed, and drawn again once the typing pauses.

import { schedule, scheduleDeep } from "../engine";
import { fitFor } from "../engine/fit";
import { save } from "../state";
import { setPath } from "../boxes";
import { eventTyped, geometryTyped } from "../eventask";
import { app, draw, focused, res, ui } from "../store";

/** A figure of the part being typed in: kept as typed, and a refusal about it taken away. */
function typedInput(el: HTMLInputElement): void {
  const key = el.dataset.typed!;
  app.state.typed[key] = el.value;
  save(app.state);
  delete ui.typedNotes[key];
  el.closest(".field")?.querySelector(`#t-${key}-c`)?.remove();
  if (ui.typedRefused?.field !== key && !(key in ui.typedWrong)) return;
  if (ui.typedRefused?.field === key) ui.typedRefused = null;
  delete ui.typedWrong[key];
  const box = el.closest(".field");
  box?.classList.remove("is-wrong");
  box?.querySelector(".said-wrong")?.remove();
  el.removeAttribute("aria-invalid");
}

/** While a figure is being typed, the step and the drawing are drawn again once the typing
 *  pauses, not at every key: a key paints at once, and the box being typed in is left alone. */
const TYPING_PAUSE_MS = 160;

let typingTimer = 0;

let typedMotor = false;

function redrawSoon(motor: boolean): void {
  typedMotor ||= motor;
  document.body.toggleAttribute("data-typing", true);
  clearTimeout(typingTimer);
  typingTimer = window.setTimeout(redrawNow, TYPING_PAUSE_MS);
}

/** Draw now what the typing put off: before Enter is acted on, and when the box is left. */
export function redrawNow(): void {
  document.body.removeAttribute("data-typing");
  if (!typingTimer) return;
  clearTimeout(typingTimer);
  typingTimer = 0;
  if (typedMotor) draw.stage();
  typedMotor = false;
  draw.panel(true);
}

/** A figure typed that is not used is kept with the box's own name and unit, for the results
 *  to say which entry was not used. */
function nameUnused(el: HTMLInputElement, bind: string): void {
  const note = ui.notes.get(bind);
  if (!note?.unused) return;
  note.label = document.querySelector(`label[for="${el.id}"]`)?.textContent?.trim() || undefined;
  note.unit = el.parentElement?.querySelector(".unit")?.textContent?.trim() || undefined;
  draw.rail();
}

/** What was typed into a box bound to the state. The step is drawn again in place once the
 *  typing pauses, so that what the box says of its figure, and everything said from it,
 *  follows what was typed. */
export function onInput(e: Event): void {
  const el = e.target as HTMLInputElement;
  if (el.dataset.typed) return typedInput(el);
  if (el.dataset.geo) return geometryTyped(el);
  const bind = el.dataset.bind;
  // A list or a set of choices is taken when it changes: see the change handler.
  if (!bind || el.tagName === "SELECT" || el.type === "radio") return;
  if (bind.startsWith("sweep.")) return; // taken when the field is left: see the change handler
  // A figure only the switching event uses: the design is not worked out again for it.
  if (bind.startsWith("event.")) return eventTyped(el, focused());
  // The box's unit, so that a figure may be typed with it or with a prefix: "120 µH".
  const unit = el.dataset.unit ?? el.parentElement?.querySelector(".unit")?.textContent?.trim();
  setPath(bind, el.value, true, unit);
  nameUnused(el, bind);
  // The drawing and the fit follow the motor's figures as they are typed.
  if (bind.startsWith("motors.")) fitFor();
  if (bind.startsWith("map.")) {
    res.grid = null;
    scheduleDeep();
    ui.unsaved = !save(app.state);
    return;
  }
  redrawSoon(bind.startsWith("motors."));
  schedule();
}
