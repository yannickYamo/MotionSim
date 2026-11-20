// The keyboard: Enter goes on or adds, the arrows move along the tabs, and Ctrl+S saves.

import { saveVariant } from "./columns";
import { addTyped } from "../actions/parts";
import { saveSetup } from "../actions/setup";
import { RESULTS, TABS } from "../steps";
import { app, ui } from "../store";
import { at } from "../views/html";
import { redrawNow } from "./typing";

/** In a menu the arrows move from item to item, round at the ends, Home and End to the first
 *  and the last; an item that cannot be chosen is passed over. */
function moveInMenu(e: KeyboardEvent, target: HTMLElement): boolean {
  const menu = target.closest<HTMLElement>("[role=menu]");
  if (!menu || !["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return false;
  const items = [...menu.querySelectorAll<HTMLButtonElement>("[role=menuitem]:not(:disabled)")];
  if (!items.length) return false;
  e.preventDefault();
  const now = items.indexOf(target as HTMLButtonElement);
  const key = e.key === "ArrowDown" ? "ArrowRight" : e.key === "ArrowUp" ? "ArrowLeft" : e.key;
  items[tabAfter(key, Math.max(now, 0), items.length) ?? 0].focus();
  return true;
}

/** Where a key takes the keyboard along a row of tabs: the arrows go round, Home and End to
 *  the ends. Null for a key that does not move along the row. */
export function tabAfter(key: string, now: number, count: number): number | null {
  if (key === "ArrowRight") return (now + 1) % count;
  if (key === "ArrowLeft") return (now + count - 1) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}

export function onKeydown(e: KeyboardEvent): void {
  const target = e.target as HTMLElement;
  // An Enter that ends the composing of characters (Japanese, Chinese, an accent) belongs to
  // the composing: it neither goes on nor adds.
  if (e.key === "Enter" && (e.isComposing || e.keyCode === 229)) return;
  if (e.key === "Enter" && enterGoesOn(target)) {
    e.preventDefault();
    at<HTMLButtonElement>("#panel .actions .primary[data-step]")?.click();
    return;
  }
  if (e.key === "Enter" && target.matches?.("input[data-variant]")) {
    e.preventDefault();
    saveVariant();
    return;
  }
  if (moveInMenu(e, target)) return;
  if (pressDrawn(e, target)) return;
  if (!typedEnter(e, target)) moveAlongTabs(e, target);
}

/** A spike of the loss chart is a button drawn in the chart: Enter and Space press it. */
function pressDrawn(e: KeyboardEvent, target: HTMLElement): boolean {
  if ((e.key !== "Enter" && e.key !== " ") || !target.matches?.("svg [data-event-show]")) return false;
  e.preventDefault();
  target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  return true;
}

/** Enter in a figure of the typed part adds the part, unless one is being added already. */
function typedEnter(e: KeyboardEvent, target: HTMLElement): boolean {
  if (e.key !== "Enter" || !target.matches?.("input[data-typed]") || ui.typedBusy) return false;
  e.preventDefault();
  void addTyped();
  return true;
}

/** An arrow, Home or End on a result tab moves to another tab, as a row of tabs does. */
function moveAlongTabs(e: KeyboardEvent, target: HTMLElement): void {
  const tab = target.closest<HTMLElement>("[role=tab]");
  if (!tab) return;
  const k = TABS.findIndex(([t]) => t === app.state.tab);
  const to = tabAfter(e.key, k, TABS.length);
  if (to === null) return;
  e.preventDefault();
  at(`#tab-${TABS[to][0]}`)?.click();
}

/** Ctrl or Cmd with S saves the setup, as it saves in any program: no other shortcut is taken. */
export function saveKey(e: KeyboardEvent): void {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.key.toLowerCase() !== "s") return;
  e.preventDefault();
  if (e.repeat) return; // held down: saved once

  void saveSetup();
}

/** Enter in a step's figure goes on to the next step, as a form's Enter does, while nothing
 *  on the step stands in the way: no figure that cannot be used, and a Next that can be pressed. */
function enterGoesOn(target: HTMLElement): boolean {
  if (!target.matches?.("#panel input[data-bind]:not([data-bind^='sweep.']):not([type=file])")) return false;
  redrawNow(); // what the box says of its figure is on the page before it is read
  if (app.state.step >= RESULTS) return false;
  if (document.querySelector('#panel [aria-invalid="true"], #panel .field.is-unread')) return false;
  const next = at<HTMLButtonElement>("#panel .actions .primary[data-step]");
  return !!next && !next.disabled;
}
