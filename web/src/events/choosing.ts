// A choice from a list, a tick or a file: what follows from it depends on what was chosen.

import { pickTypedKind } from "../actions/figures";
import { addPart } from "../actions/parts";
import { addMission } from "../actions";
import { openSetup } from "../actions/setup";
import { schedule } from "../engine";
import { fitFor } from "../engine/fit";
import { applyPreset } from "../engine/loads";
import { settle } from "../follow";
import { suggestFor } from "../engine/suggest";
import { DEVICE, MOST } from "../steps";
import { setPath } from "../boxes";
import { save } from "../state";
import { app, draw, invalidate, res, ui, underTest } from "../store";
import { at, say } from "../views/html";
import { nextButton } from "../views/rail";
import { sweepKeyChosen } from "./columns";
import { shutMenu } from "./menus";
import { takeLayout } from "../eventask";

/** A kind of load picked from the list: it is sized to the motor, and is the load of step 4. */
function pickLoad(el: HTMLInputElement): void {
  const { state } = app;
  const picked = res.presets?.list.find((p) => p.id === el.value);
  if (!picked) return;
  state.loadTouched = false;
  state.loadPicked = picked.id;
  state.mission = null;
  ui.missionFault = null;
  applyPreset(picked);
  // Picked by the user, the application brings how its drive starts: sealed in a shell, a
  // compressor's motor has no sensor.
  if (["pmsm", "bldc", "synrm"].includes(state.kind) && picked.start) state.start.method = picked.start;
  state.loadSet = state.loadSet.filter((x) => x.id !== picked.id);
  res.cycles.clear();
  draw.panel(true);
  draw.preview();
  schedule();
  at(`[data-load][value="${picked.id}"]`)?.focus();
}

/** Another kind of motor, by the user's choice: it no longer follows the device. Its point
 *  is where its example starts for the device under test, with what the user typed for
 *  this kind before laid over. */
function pickKind(el: HTMLInputElement): void {
  const { state, setup } = app;
  state.kind = el.value;
  state.kindPicked = true;
  ui.followed = null;
  settle(state, setup, res.suggestion && res.suggestion.id === underTest() ? res.suggestion.data : null);
  state.map = { rpm_max: "", torque_max: "" };
  draw.stage(); // the drawing shows the kind of motor at once
  res.fit = null;
  draw.panel(true);
  at(`[data-kind][value="${state.kind}"]`)?.focus();
  fitFor(true);
  schedule();
}

/** How the motor's figures are given, switched: the boxes show the same motor the other way.
 *  Nothing the engine takes changes, so nothing is worked out again. What a box said of a
 *  figure typed the other way is taken away with it. */
function pickEntry(el: HTMLInputElement): void {
  const { state } = app;
  if (el.dataset.entry === "wiring") state.motorEntry.wiring = el.value === "phase" ? "phase" : "line";
  else state.motorEntry.constant = { ...state.motorEntry.constant, [state.kind]: el.value === "kt" ? "kt" : "kv" };
  for (const path of [...ui.notes.keys()]) if (path.startsWith(`motors.${state.kind}.`)) ui.notes.delete(path);
  save(state);
  draw.panel(true);
  at(`[data-entry="${el.dataset.entry}"][value="${el.value}"]`)?.focus();
}

/** The edge limit picked: the resistors the tool chooses, and all that follows from them, are worked out again. */
function pickEdgeLimit(el: HTMLInputElement): void {
  setPath("conditions.edge_limit", el.value, false);
  save(app.state);
  draw.panel(true);
  at(`[data-edge-limit][value="${el.value}"]`)?.focus();
  schedule();
}

/** A part ticked or unticked in the list. */
function tickDevice(el: HTMLInputElement): void {
  const { state } = app;
  const id = el.dataset.device!;
  if (el.checked && !state.devices.includes(id) && state.devices.length >= MOST) {
    // Five are compared at most: a sixth is not ticked, and the step says why.
    el.checked = false;
    at("#most-devices")?.remove();
    const why = "Five devices is the most at once: untick one to tick another.";
    const note = `<li class="quiet small" id="most-devices" role="alert">${why}</li>`;
    el.closest(".device")?.insertAdjacentHTML("afterend", note);
    return;
  }
  at("#most-devices")?.remove();
  state.devices = el.checked ? [...new Set([...state.devices, id])] : state.devices.filter((d) => d !== id);
  void suggestFor();
  if (state.focus === id && !el.checked) state.focusPicked = false;
  el.closest(".device")?.classList.toggle("is-on", el.checked);
  const foot = at("#panel .actions");
  if (foot) {
    at("#need-device")?.remove();
    foot.outerHTML = nextButton(DEVICE);
  }
  draw.rail();
  draw.stage();
  schedule();
}

/** A part ticked or unticked in the dialog that adds a device to compare: the design stays
 *  as it is, and the part is a column of the table, or is no longer one. */
function tickToCompare(el: HTMLInputElement): void {
  const { state } = app;
  const id = el.dataset.device!;
  const lead = underTest();
  if (el.checked && state.devices.length >= MOST) {
    el.checked = false;
    return say("Five devices is the most at once: untick one to tick another.");
  }
  // The design's own part is not taken out from here: it is the design.
  if (!el.checked && id === lead) {
    el.checked = true;
    return say("This is the part the design is started from: it stays.");
  }
  state.devices = el.checked ? [...new Set([...state.devices, id])] : state.devices.filter((d) => d !== id);
  state.compare = "devices";
  if (state.focus === id && !el.checked) state.focusPicked = false;
  invalidate("compared");
  void suggestFor();
  draw.panel(true);
  draw.stage();
  draw.rail();
  schedule();
}

/** A list bound to the state: what follows from the choice depends on which list it is. */
function pickOption(el: HTMLInputElement): void {
  const { state } = app;
  const bind = el.dataset.bind!;
  setPath(bind, el.value);
  if (bind.startsWith("motors.")) {
    draw.stage();
    fitFor();
  }
  if (bind === "conditions.cooling") {
    if (state.sweep.key === "t_sink") state.sweep.values = "";
    draw.panel(true);
    at('[data-bind="conditions.cooling"]')?.focus();
  }
  if (bind === "start.method") {
    res.cycle = null;
    draw.panel(true);
    at('[data-bind="start.method"]')?.focus();
  }
  schedule();
}

export function onChange(e: Event): void {
  const el = e.target as HTMLInputElement;
  const data = el.dataset;
  const file = el.files?.[0];
  if (el.matches("[data-load]")) return pickLoad(el);
  if (el.matches("[data-kind]")) return pickKind(el);
  if (el.matches("[data-typed-kind]")) return pickTypedKind(el);
  if (el.matches("[data-entry]")) return pickEntry(el);
  if (el.matches("[data-device]")) return el.closest("#device-dialog") ? tickToCompare(el) : tickDevice(el);
  if ((el.id === "part-file" || data.partFile !== undefined) && file) return void addPart(file);
  if (data.missionFile !== undefined && file) return void addMission(file);
  if (data.eventLayout !== undefined && file) {
    el.value = "";
    return void takeLayout(file);
  }
  changedOther(el, file);
}

/** A change to what is compared, a setup file chosen, or a choice in a list. */
function changedOther(el: HTMLInputElement, file: File | undefined): void {
  const data = el.dataset;
  if (el.matches("[data-edge-limit]")) return pickEdgeLimit(el);
  if (data.variant === "sweep.key") return sweepKeyChosen(el as unknown as HTMLSelectElement);
  if (data.setupFile !== undefined && file) {
    shutMenu(el.closest<HTMLElement>("[popover]"));
    el.value = "";
    return void openSetup(file);
  }
  if (el.tagName === "SELECT" && data.bind) pickOption(el);
}
