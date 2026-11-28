// A part taken off the page, and the few seconds in which it can be put back as it was.

import { api, storedParts } from "../api";
import { partsMoved } from "../actions/reports";
import { partsHeld, save } from "../state";
import { app, draw, ui } from "../store";
import { at } from "../views/html";
import { partsChanged } from "./redraw";

/** How long a part taken off can be put back with a press. */
const UNDO_MS = 6000;

let undoTimer = 0;

/** No part is on offer to be put back: a whole new state is in place, or the offer ran out. */
export function resetUndo(): void {
  clearTimeout(undoTimer);
  undoTimer = 0;
  ui.forgotten = null;
}

export function forgetDevice(el: HTMLElement): void {
  const { state } = app;
  const id = el.dataset.forgetDevice!;
  const name = app.setup.devices.find((d) => d.id === id)?.name ?? id;
  const kept = storedParts().flatMap((part, at) => (part.id === id ? [{ part, at }] : []));
  const { focus, focusPicked } = state;
  ui.forgotten = { id, name, devices: [...state.devices], added: [...state.added], focus, focusPicked, kept };
  clearTimeout(undoTimer);
  undoTimer = window.setTimeout(() => {
    // The offer runs out: where the keyboard was on it, it stays on the step.
    const held = document.activeElement?.matches?.("[data-undo-forget]") ?? false;
    ui.forgotten = null;
    draw.panel(true);
    if (held) at<HTMLElement>("#panel h2")?.focus({ preventScroll: true });
  }, UNDO_MS);
  state.added = state.added.filter((d) => d !== id);
  state.devices = state.devices.filter((d) => d !== id);
  partsHeld(state); // the part ticked taken off: one left on the page is ticked in its place
  api.forget(id);
  partsMoved();
  if (ui.review?.id === id) ui.review = null;
  if (ui.reading?.outcome?.device.id === id) ui.reading = null;
  state.focusPicked = false;
  partsChanged();
  at<HTMLElement>("[data-undo-forget]")?.focus();
}

/** Put back the part just taken off, ticked as it was. */
export function undoForget(): void {
  const gone = ui.forgotten;
  if (!gone) return;
  clearTimeout(undoTimer);
  ui.forgotten = null;
  const { state } = app;
  state.devices = gone.devices;
  state.added = gone.added;
  state.focus = gone.focus;
  state.focusPicked = gone.focusPicked;
  for (const { part, at: where } of gone.kept) api.remember(part, where);
  partsMoved();
  save(state);
  partsChanged();
  at<HTMLElement>(`[data-forget-device="${CSS.escape(gone.id)}"]`)?.focus();
}
