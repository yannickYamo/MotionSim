// What the user does, and what the page does about it, wired to the page: what is typed,
// chosen, pressed, kept open, dropped, and the keys.

import { goTo } from "./actions";
import { addPart } from "./actions/parts";
import { followOtherTabs } from "./actions/setup";
import { onChange } from "./events/choosing";
import { dialogShut, menuToggled } from "./events/columns";
import { onKeydown, saveKey } from "./events/keys";
import { closeEquations, menusWithoutPopover } from "./events/menus";
import { onClick } from "./events/presses";
import { onInput, redrawNow } from "./events/typing";
import { app, ui } from "./store";
import { $ } from "./views/html";
import { drawnOpen } from "./views/morph";

/** The period drawing and the folds stay as the user left them, open or folded, through redraws. */
function onToggle(e: Event): void {
  const el = e.target as HTMLDetailsElement;
  if (el.classList?.contains("pwm-fold")) ui.pwmOpen = el.open;
  if (el.classList?.contains("typed")) ui.typedOpen = el.open;
  // A fold the user opened or shut (by a press, or the browser for them, as when it finds
  // text inside one) is remembered. One that a redraw opened or shut is as it was drawn.
  const id = el.dataset?.fold;
  if (!id || drawnOpen.get(el) === el.open) return;
  drawnOpen.set(el, el.open);
  ui.folds.set(id, el.open);
}

function onDrag(e: Event): void {
  const zone = (e.target as HTMLElement).closest("#drop");
  if (!zone) return;
  e.preventDefault();
  zone.classList.toggle("is-over", e.type === "dragover");
  const file = e.type === "drop" ? (e as DragEvent).dataTransfer?.files[0] : null;
  if (file) void addPart(file);
}

export function wire(): void {
  followOtherTabs();
  menusWithoutPopover();
  const page = $("#app");
  page.addEventListener("input", onInput);
  page.addEventListener("change", onChange);
  window.addEventListener("popstate", (e) => {
    const step = (e.state as { step?: number } | null)?.step;
    if (typeof step === "number" && step <= app.state.reached) goTo(step, true);
  });
  document.addEventListener("click", closeEquations);
  page.addEventListener("toggle", onToggle, true);
  page.addEventListener("toggle", menuToggled, true);
  page.addEventListener("close", dialogShut, true);
  page.addEventListener("click", onClick);
  page.addEventListener("keydown", onKeydown);
  page.addEventListener("focusout", (e) => {
    if ((e.target as HTMLElement).matches?.("input[data-bind]")) redrawNow();
  });
  document.addEventListener("keydown", saveKey);
  page.addEventListener("dragover", onDrag);
  page.addEventListener("drop", onDrag);
}
