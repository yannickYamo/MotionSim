// The cooling figure the tool offers where the chosen cooling's own box is left empty: the
// heatsink that holds itself at 60 °C, or the smallest board that keeps the junction under
// its limit, both from the loss at the design point. It is never put in the box by itself:
// the user takes it with one press, and the box then says it was sized by the tool until
// it is edited.

import { api, Refused } from "../api";
import type { CoolingOffer } from "../api";
import { schedule } from "../engine";
import { request, save, sizingKey } from "../state";
import { SUPPLY } from "../steps";
import { app, draw, res, ui, underTest } from "../store";

/** The box an offer is for, where the cooling chosen has one and it is empty. */
export function offerFigure(): CoolingOffer["figure"] | null {
  const c = app.state.conditions;
  const empty = (v: string) => String(v ?? "").trim() === "";
  if (c.cooling === "heatsink" && empty(c.rth_sink)) return "rth_sink";
  if (c.cooling === "board" && empty(c.board_area)) return "board_area";
  return null;
}

/** What an offer is worked out from: the motor, the conditions but the empty box, the part. */
function offerAsked(): { key: string; body: unknown } | null {
  const figure = offerFigure();
  const device = underTest();
  if (!figure || !device) return null;
  const body = { ...request(app.state), device };
  return { key: sizingKey(app.state, figure, device), body };
}

/** The offer for the inputs as they stand, asked for once, and the step drawn again when it
 *  comes. An answer for inputs that have since changed is dropped. */
export function offerNow(): CoolingOffer | Refused | "asking" | null {
  const asked = offerAsked();
  if (!asked) return null;
  if (res.offer?.key === asked.key) return res.offer.answer;
  res.offer = { key: asked.key, answer: "asking" };
  void api.cooling(asked.body).then(
    (answer) => landed(asked.key, answer),
    (e: unknown) =>
      landed(asked.key, e instanceof Refused ? e : new Refused(String((e as Error)?.message ?? e), "", "")),
  );
  return "asking";
}

function landed(key: string, answer: CoolingOffer | Refused): void {
  if (res.offer?.key !== key) return;
  res.offer = { key, answer };
  if (app.state.step === SUPPLY) draw.panel(true);
}

/** Take the figure offered: it goes in its box, marked as sized by the tool, and the
 *  keyboard stays on the box. */
export function useSized(): void {
  const offer = res.offer;
  const answer = offer?.answer;
  if (!offer || !answer || answer === "asking" || answer instanceof Refused || answer.value === null) return;
  put(answer.figure, answer.value, offer.key);
}

/** The figure the tool sized, in its box, with what it was sized from. */
function put(figure: CoolingOffer["figure"], value: number, key: string): void {
  const c = app.state.conditions;
  c[figure] = String(value);
  c.sized = figure;
  c.sizedFor = key;
  ui.resizing = null;
  ui.unsaved = !save(app.state);
  draw.panel(true);
  document.querySelector<HTMLElement>(`#f-conditions-${figure}`)?.focus();
  schedule();
}

/** Size the cooling again for the design point as it now stands, where it was sized for an
 *  earlier one: worked out as an empty box's offer is, and put in the box with one press. */
export async function resizeSized(): Promise<void> {
  const c = app.state.conditions;
  const figure = c.sized;
  const device = underTest();
  if (!figure || !device || (ui.resizing && "asking" in ui.resizing)) return;
  const conditions = { ...c, [figure]: "", sized: "" as const, sizedFor: "" };
  const key = sizingKey(app.state, figure, device);
  const body = { ...request({ ...app.state, conditions }), device };
  ui.resizing = { asking: true };
  draw.panel(true);
  document.querySelector<HTMLElement>(`#f-conditions-${figure}`)?.focus();
  let answer: CoolingOffer | null = null;
  try {
    answer = await api.cooling(body);
  } catch (e) {
    ui.resizing = { why: `it could not be sized again: ${(e as Error).message}` };
  }
  // Asked for inputs that have since moved, or for a box the user has since made their own.
  if (app.state.conditions.sized !== figure || sizingKey(app.state, figure, device) !== key) {
    ui.resizing = null;
    return;
  }
  if (answer && answer.value === null) ui.resizing = { why: answer.why ?? "it cannot be sized here" };
  if (answer && answer.value !== null) return put(figure, answer.value, key);
  if (app.state.step === SUPPLY) draw.panel(true);
}
