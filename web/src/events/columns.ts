// The + Add menu and the menu of each column: what is set beside the design, edited, made
// the design, or taken out, with a few seconds to put it back. One kind is compared at a
// time, and an addition that would clear what is there asks first, in the page.

import { motorLabel, series, sweepValues, withValues } from "../compare";
import { schedule } from "../engine";
import { itemOf } from "../engine/loads";
import { suggestFor } from "../engine/suggest";
import type { Field } from "../api";
import { shownAs, shownText } from "../motorentry";
import { readNumber } from "../parse";
import { save } from "../state";
import { MOST } from "../steps";
import { shown } from "../shown";
import type { Kind } from "../shown";
import { app, draw, invalidate, res, ui, underTest } from "../store";
import { drawVariant, motorOf, renderDialogs } from "../views/adding";
import { at, say } from "../views/html";
import { toColumn } from "../views/oncolumn";
import { dropOne, keepOwnLoad } from "./compare";
import { placeMenu } from "./menus";
import { redrawCompared } from "./redraw";

const KINDS: Record<string, Kind> = { device: "devices", load: "loads", motor: "motors", sweep: "sweep" };

/** How long a column taken out can be put back with a press. */
const UNDO_MS = 6000;
let undoTimer = 0;

/** Where the keyboard goes back to when a dialog or the question is done with. */
let from = "#add-button";

const backTo = (): void => (at<HTMLElement>(from) ?? at<HTMLElement>("#add-button") ?? at("#compare-title"))?.focus();

/** Dialogs shut by the page itself, which leave the keyboard where the page puts it. */
const shutQuietly = new WeakSet<Element>();

/** Nothing of the comparison of the state before stands on a fresh one: no question waiting
 *  on the user's word, no Undo, no small dialog open, no map asked for. */
export function resetColumns(): void {
  clearTimeout(undoTimer);
  undoTimer = 0;
  Object.assign(shown, { map: false, confirm: null, removed: null, editing: null, wrong: {}, readBefore: null });
  from = "#add-button";
  // Shut here, a dialog leaves the keyboard where the fresh state put it.
  for (const dialog of document.querySelectorAll<HTMLDialogElement>("dialog.add-dialog[open]")) {
    shutQuietly.add(dialog);
    dialog.close();
  }
}

/** Clear what is compared now: every part but the design's, the loads and motors set beside
 *  it, the values of a setting tried. The design itself is left as it is. */
function clearCompared(): void {
  const { state } = app;
  const lead = underTest();
  if (state.compare === "devices" && lead && state.devices.length > 1) {
    state.devices = [lead];
    if (state.focus !== lead) state.focusPicked = false;
    void suggestFor();
  }
  state.loadSet = [];
  state.motorSet = [];
  state.sweep = { ...state.sweep, values: "" };
  res.variants.clear();
  res.cycles.clear();
  invalidate("compared");
}

/** What comes of an item of the menu, once nothing that is there stands in its way. */
function goOn(to: Kind, preset?: string): void {
  const { state } = app;
  if (state.compare !== to && to !== "motors" && to !== "sweep") state.compare = to;
  if (to === "devices") return openDialog("#device-dialog");
  if (to === "loads") return addLoadKind(preset ?? "");
  shown.editing = to === "motors" ? { kind: "motor", id: null } : { kind: "sweep", key: state.sweep.key };
  openDialog("#variant-dialog");
}

/** A load of the five kinds, or the load of step 4 kept as it is now, set beside the design. */
function addLoadKind(preset: string): void {
  const { state } = app;
  if (series().length >= MOST) return;
  if (preset === "own") {
    keepOwnLoad();
    const own = state.loadSet.at(-1)!;
    say(`${own.label} is set beside the design.`);
    return toColumn(own.id);
  }
  const picked = res.presets?.list.find((p) => p.id === preset);
  if (!picked) return;
  state.loadSet.push(itemOf(picked));
  redrawCompared();
  say(`${picked.label} is set beside the design.`);
  // The keyboard goes to the new column, which is slid into sight: on a phone, + Add is at
  // the far end of a table that slides, and the column just added would be out of sight.
  toColumn(picked.id);
}

/** An item of the + Add menu. Where it is of another kind than what is compared, and
 *  something is compared, the user is asked first. */
export function addFromMenu(el: HTMLElement): void {
  const to = KINDS[el.dataset.adding ?? ""];
  if (!to) return;
  from = "#add-button";
  const preset = el.dataset.preset;
  if (app.state.compare !== to && series().length > 1) {
    shown.confirm = { to, preset };
    draw.panel(true);
    at("#confirm")?.focus();
    return;
  }
  goOn(to, preset);
}

/** The answer to the question: clear what is compared and go on, or keep it. */
export function settleSwitch(el: HTMLElement): void {
  const asked = shown.confirm;
  shown.confirm = null;
  if (!asked || el.dataset.switchNo !== undefined) {
    draw.panel(true);
    return backTo();
  }
  const parts = app.state.compare === "devices";
  clearCompared();
  app.state.compare = "devices";
  rework(parts);
  goOn(asked.to, asked.preset);
}

/** The parts compared when the device dialog was opened: one more on shutting it is the
 *  column the keyboard goes to. */
let devicesBefore: string[] = [];

function openDialog(id: string): void {
  shown.wrong = {};
  devicesBefore = [...app.state.devices];
  shown.readBefore = ui.reading;
  const dialog = at<HTMLDialogElement>(id);
  if (!dialog) return;
  if (!dialog.open) dialog.showModal();
  renderDialogs();
  drawVariant();
  dialog
    .querySelector<HTMLElement>("[data-variant], .device-routes input, .device-routes button, [data-dialog-close]")
    ?.focus();
}

/** A dialog shut by its button or by Escape: what it edited is let go, and the keyboard goes
 *  back to where it came from. */
export function dialogShut(e: Event): void {
  const dialog = e.target as HTMLElement;
  if (!dialog.matches?.(".add-dialog")) return;
  shown.editing = null;
  shown.wrong = {};
  if (shutQuietly.delete(dialog)) return;
  const brought = dialog.id === "device-dialog" ? app.state.devices.filter((d) => !devicesBefore.includes(d)) : [];
  if (brought.length) toColumn(brought[brought.length - 1]);
  else backTo();
}

export function shutDialog(el: HTMLElement): void {
  el.closest("dialog")?.close();
}

/** What a box of the small dialog holds, read as every box on the page reads a figure. */
function figureAt(path: string, unit = ""): number | null {
  const box = at<HTMLInputElement>(`#variant-dialog [data-variant="${path}"]`);
  const read = readNumber(box?.value ?? "", unit || undefined);
  if (read.ok) return read.value;
  shown.wrong[path] = read.empty ? "This figure is needed." : read.why;
  return null;
}

/** A figure of the motor in the dialog, typed in the terms step 2 shows it (line to line or
 *  per phase, mH or mΩ, Kv or Kt), as the engine takes it. */
function entryAt(kind: string, f: Field, was: string | number | undefined): number | null {
  const as = shownAs(kind, f.key, app.state.motorEntry, f.label, f.help);
  // A box left as it was shown keeps the figure it was shown from, unrounded.
  const text = at<HTMLInputElement>(`#variant-dialog [data-variant="motor.${f.key}"]`)?.value.trim();
  if (as && was !== undefined && was !== "" && text === String(shownText(as, was))) return Number(was);
  const typed = figureAt(`motor.${f.key}`, as?.unit ?? f.unit);
  if (typed === null || !as) return typed;
  const engine = as.engine(typed);
  if (typeof engine === "number") return Number(engine.toPrecision(12));
  shown.wrong[`motor.${f.key}`] = engine;
  return null;
}

/** The column the small dialog has just added, to take the keyboard to. */
let added: string | null = null;

/** The copy of the motor, with what was changed in it, kept as a column. */
function saveMotor(id: string | null): boolean {
  const { state, setup } = app;
  const kind = setup.motors[state.kind];
  const base = motorOf(id);
  const motor: Record<string, string | number> = { ...base.motor, type: state.kind };
  for (const f of kind.fields) {
    const box = at<HTMLInputElement>(`#variant-dialog [data-variant="motor.${f.key}"]`);
    if (!box) continue;
    if (f.options) motor[f.key] = box.value;
    else if (box.value.trim() !== "" || f.required) motor[f.key] = entryAt(state.kind, f, base.motor[f.key]) ?? 0;
  }
  const point = {
    v_dc: figureAt("point.v_dc", "V"),
    rpm: figureAt("point.rpm", "rpm"),
    torque: figureAt("point.torque", "N·m"),
  };
  if (Object.keys(shown.wrong).length) return false;
  const k = state.conditions;
  const conditions = {
    v_dc: point.v_dc,
    rpm: point.rpm,
    torque: point.torque,
    f_sw: k.f_khz * 1000,
    pwm: k.pwm || null,
  };
  const label = motorLabel({ motor, conditions });
  const kept = state.motorSet.find((m) => m.id === id);
  if (kept) Object.assign(kept, { label, motor, conditions });
  else {
    const made = `motor-${Date.now()}`;
    state.motorSet.push({ id: made, label, motor, conditions });
    added = made;
  }
  if (id) res.variants.delete(id);
  if (id) res.cycles.delete(id);
  state.compare = "motors";
  return true;
}

/** The setting tried, and its values. */
function saveSweep(key: string): boolean {
  const box = at<HTMLInputElement>('#variant-dialog [data-variant="sweep.values"]');
  const typed = box?.value.trim() ?? "";
  const { state } = app;
  if (typed === "") {
    state.sweep = { key, values: "" };
  } else {
    const read = withValues([], typed, key);
    if (!read.ok) shown.wrong["sweep.values"] = read.why;
    else if (read.values.length < 2) shown.wrong["sweep.values"] = "Give two values at least: one column each.";
    if (!read.ok || read.values.length < 2) return false;
    state.sweep = { key, values: read.values.join(", ") };
  }
  state.compare = "sweep";
  res.cycles.clear();
  return true;
}

/** Save what the small dialog holds; or, where a box cannot be read, say so at the box. */
export function saveVariant(): void {
  const editing = shown.editing;
  if (!editing) return;
  shown.wrong = {};
  added = null;
  const done = editing.kind === "motor" ? saveMotor(editing.id) : saveSweep(editing.key);
  if (!done) {
    drawVariant();
    at<HTMLElement>('#variant-dialog [aria-invalid="true"]')?.focus();
    return;
  }
  invalidate("compared");
  const made = added;
  // Shut with a column added, the dialog lets the keyboard go to it, not back to + Add.
  if (made) shutQuietly.add(at("#variant-dialog")!);
  at<HTMLDialogElement>("#variant-dialog")?.close();
  redrawCompared();
  if (made) toColumn(made);
  else backTo();
}

/** The setting chosen in the small dialog: its values box is drawn again in its unit. */
export function sweepKeyChosen(el: HTMLSelectElement): void {
  if (shown.editing?.kind !== "sweep") return;
  shown.editing = { kind: "sweep", key: el.value };
  drawVariant();
  at<HTMLElement>('#variant-dialog [data-variant="sweep.key"]')?.focus();
}

/** Edit a column: the copy of the motor, or the values of the setting tried. */
export function editColumn(el: HTMLElement): void {
  const key = el.dataset.colEdit!;
  const k = series().findIndex((x) => x.key === key);
  from = `#col-button-${k}`;
  const { state } = app;
  shown.editing = state.compare === "motors" ? { kind: "motor", id: key } : { kind: "sweep", key: state.sweep.key };
  openDialog("#variant-dialog");
}

/** Take a column out, and offer for a few seconds to put it back. Down to the design alone,
 *  nothing is compared any more. */
export function removeColumn(el: HTMLElement): void {
  const { state } = app;
  const key = el.dataset.colRemove!;
  const name = series().find((x) => x.key === key)?.name ?? "it";
  const { compare, devices, focus, focusPicked, loadSet, motorSet, sweep } = state;
  shown.removed = {
    name,
    compare,
    devices: [...devices],
    focus,
    focusPicked,
    loadSet: [...loadSet],
    motorSet: [...motorSet],
    sweep: { ...sweep },
  };
  clearTimeout(undoTimer);
  undoTimer = window.setTimeout(() => {
    const held = document.activeElement?.matches?.("[data-undo-column]") ?? false;
    shown.removed = null;
    draw.panel(true);
    if (held) backTo();
  }, UNDO_MS);
  dropOne(key, sweepValues());
  if (series().length < 2 && state.compare !== "devices") state.compare = "devices";
  rework(compare === "devices");
  say(`Took ${name} out of the table.`);
  from = "#add-button";
  at<HTMLElement>("[data-undo-column]")?.focus();
}

/** Drawn again after what is compared changed; worked out again where the parts changed,
 *  since each part's design point is worked out with the design's. */
function rework(parts: boolean): void {
  invalidate("compared");
  if (!parts) return redrawCompared();
  save(app.state);
  draw.panel(true);
  draw.stage();
  schedule();
}

/** Put back the column just taken out, and what was compared with it. */
export function undoColumn(): void {
  const gone = shown.removed;
  if (!gone) return;
  clearTimeout(undoTimer);
  shown.removed = null;
  const { state } = app;
  Object.assign(state, {
    compare: gone.compare,
    devices: gone.devices,
    focus: gone.focus,
    focusPicked: gone.focusPicked,
    loadSet: gone.loadSet,
    motorSet: gone.motorSet,
    sweep: gone.sweep,
  });
  if (gone.compare === "devices") void suggestFor();
  rework(gone.compare === "devices");
  say(`${gone.name} is back in the table.`);
  backTo();
}

/** A menu of the comparison opened or shut: it opens under its button, or over it where
 *  there is no room below, with the keyboard on its first item; its button says whether it
 *  is open. Shut, the browser gives the keyboard back to the button. */
export function menuToggled(e: Event): void {
  const menu = e.target as HTMLElement;
  if (!menu.matches?.(".menu[popover]")) return;
  const open = (e as ToggleEvent).newState === "open";
  const button = at<HTMLElement>(`[popovertarget="${menu.id}"]`);
  button?.setAttribute("aria-expanded", String(open));
  if (!open || !button) return;
  placeMenu(menu, button);
  menu.querySelector<HTMLElement>("[role=menuitem]:not(:disabled)")?.focus();
}
