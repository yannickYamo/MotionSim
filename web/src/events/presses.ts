// Presses are a table: the data attribute on what was pressed names its handler.

import { goTo } from "../actions";
import { notRefused } from "../api";
import { resizeSized, useSized } from "../actions/cooling";
import { toFigure } from "../actions/figures";
import { addTyped, openReview } from "../actions/parts";
import { openEquations, printReport, retryFetch, saveDesign, saveMarkdown } from "../actions/reports";
import { saveSetup, settleOtherTab, startOver } from "../actions/setup";
import { compute, schedule } from "../engine";
import { deep } from "../engine/deep";
import { fitFor } from "../engine/fit";
import { applyPreset, loadFor, presetsFor } from "../engine/loads";
import { suggestFor } from "../engine/suggest";
import { dropLayout, openEvent, toEventBox, useEstimate, resetEdge } from "../eventask";
import { putBack } from "../follow";
import { shown } from "../shown";
import { save } from "../state";
import type { State, Tab } from "../state";
import { MOST, RESULTS, SUPPLY, ZOOMS } from "../steps";
import { app, draw, focused, invalidate, redrawAll, res, ui } from "../store";
import { at, say } from "../views/html";
import { toColumn } from "../views/oncolumn";
import { loadResults } from "../views/resultsload";
import { addFromMenu, editColumn, removeColumn, saveVariant, settleSwitch, shutDialog, undoColumn } from "./columns";
import { cancelLargest, findLargest } from "./largest";
import { shutMenu } from "./menus";
import { partsChanged } from "./redraw";
import { forgetDevice, undoForget } from "./undo";

type Press = (el: HTMLElement) => void;

/** Save the drawing a button stands on as a PNG image, and say that it was, or why not. The
 *  button waits while the image is made. */
async function savePngOf(el: HTMLElement): Promise<void> {
  const host = el.closest("[data-png-host], .ev-edge, #plate");
  const svg = host?.querySelector<SVGSVGElement>("svg.chart, svg.schematic");
  if (!svg || el.getAttribute("aria-busy")) return;
  el.setAttribute("aria-busy", "true");
  try {
    const { savePng } = await import("../charts/png");
    say(`Saved as ${await savePng(svg, el.dataset.savePng || "Chart", el.dataset.under ?? "")}.`);
  } catch (err) {
    say(`The image could not be made: ${String((err as Error)?.message ?? err)}.`);
  } finally {
    el.removeAttribute("aria-busy");
  }
}

function zoom(el: HTMLElement): void {
  const { state } = app;
  const now = ZOOMS.indexOf(state.pwmPeriods);
  const next = (now < 0 ? 2 : now) + (el.dataset.zoom === "in" ? -1 : 1);
  state.pwmPeriods = ZOOMS[Math.min(Math.max(next, 0), ZOOMS.length - 1)];
  save(state);
  draw.stage();
  at(`[data-zoom="${el.dataset.zoom}"]:not(:disabled), [data-zoom]:not(:disabled)`)?.focus();
}

function dropMission(): void {
  const { state } = app;
  state.mission = null;
  state.loadTouched = state.loadTouchedBefore;
  ui.missionFault = null;
  invalidate("motion");
  save(state);
  draw.panel(true);
  schedule();
}

/** Size the load to the motor again. A load of a kind this motor is not offered gives way
 *  to the usual one for it. */
function resizeLoad(): void {
  const { state } = app;
  const again = loadFor(res.presets?.list ?? [], state.loadKind);
  if (!again) return;
  state.loadTouched = false;
  applyPreset(again);
  res.cycles.clear();
  draw.panel(true);
  draw.preview();
  schedule();
}

/** A chart of the motion full screen, its code coming with the results' own. */
async function openMotionFull(el: HTMLElement): Promise<void> {
  const cycle = notRefused(res.cycle);
  if (!cycle) return;
  const { openMotion } = await loadResults();
  const name = focused()?.name ?? "the device";
  openMotion(cycle, el.dataset.motionFull as "tj" | "rpm" | "torque" | "i_peak", name);
}

/** The motor an application usually has, put in where the user has not typed their own: its
 *  kind, each of its figures not typed, and the design point where that was not typed. */
function useUsualMotor(el: HTMLElement): void {
  const { state } = app;
  const p = res.presets?.list.find((x) => x.id === el.dataset.usualMotor);
  if (!p?.motor) return;
  const m = p.motor;
  const own = state.motorOwn[m.kind] ?? [];
  const values = { ...(state.motors[m.kind] ?? {}) };
  for (const [k, v] of Object.entries(m.values)) if (k !== "type" && !own.includes(k)) values[k] = v;
  state.motors = { ...state.motors, [m.kind]: values };
  state.kind = m.kind;
  state.kindPicked = true;
  const typed = state.pointOf[m.kind] ?? {};
  if (typed.rpm === undefined) state.conditions.rpm = m.point.rpm;
  if (typed.torque === undefined) state.conditions.torque = m.point.torque;
  state.loadPicked = p.id;
  state.loadTouched = false;
  res.fit = null;
  invalidate("motion");
  save(state);
  say("The motor this application usually has is in, where you had not typed your own.");
  draw.stage();
  draw.panel(true);
  void presetsFor();
  fitFor(true);
  schedule();
}

function setMapSide(el: HTMLElement): void {
  const { state } = app;
  state.mapAt = el.dataset.mapAt as "motor" | "load";
  save(state);
  draw.panel(true);
  at(`[data-map-at="${state.mapAt}"]`)?.focus();
}

/** Bring the made-up part, to try the tool with. */
function addExample(el: HTMLElement): void {
  const { state } = app;
  const made = el.dataset.example || "example";
  state.devices = [...new Set([...state.devices, made])].slice(-MOST);
  state.added = [...new Set([...state.added, made])];
  save(state);
  partsChanged();
  (at(`[data-drop-device="${made}"]`) ?? at("#panel h2"))?.focus({ preventScroll: true });
}

/** The map under the losses, shown or put away: solved once it is shown. */
function showMap(el: HTMLElement): void {
  shown.map = el.dataset.showMap === "show";
  draw.panel(true);
  at<HTMLElement>("[data-show-map]")?.focus();
  void deep();
}

function openTab(el: HTMLElement): void {
  const { state } = app;
  state.tab = el.dataset.tab as Tab;
  save(state);
  draw.panel(true);
  at(`#tab-${state.tab}`)?.focus();
  void deep();
}

/** Put another device on the drawing: it stays the user's choice from then on. */
function setFocus(el: HTMLElement): void {
  const { state } = app;
  state.focusPicked = true;
  if (state.focus === el.dataset.focus) return;
  state.focus = el.dataset.focus!;
  res.cycle = res.grid = res.advised = null;
  res.capable = null;
  res.biggest = null;
  if (state.compare !== "devices") invalidate("compared");
  save(state);
  draw.stage();
  if (!el.matches("summary")) draw.panel(true);
  void deep();
}

function setMetric(el: HTMLElement): void {
  app.state.metric = el.dataset.metric as State["metric"];
  save(app.state);
  draw.panel(true);
}

/** The stretches of the motion changed in number: the load is the user's own from then on. */
function stretchesChanged(): void {
  app.state.loadTouched = true;
  app.state.phases = null; // the stretches as they now stand, no longer a duty's phases
  save(app.state);
  draw.panel(true);
  draw.preview();
  schedule();
}

function addStretch(): void {
  const { segments } = app.state;
  const last = segments[segments.length - 1];
  segments.push({ duration: 1, speed_start: last?.speed_end ?? 0, speed_end: last?.speed_end ?? 0 });
  stretchesChanged();
}

function removeStretch(el: HTMLElement): void {
  app.state.segments.splice(Number(el.dataset.remove), 1);
  stretchesChanged();
}

/** The note that figures followed the device under test: put away, or the figures put back
 *  where they were, which makes them the user's own. */
function settleFollowed(el: HTMLElement): void {
  const { state, setup } = app;
  if (el.dataset.followed === "back") {
    for (const change of [...(ui.followed?.changes ?? [])].reverse()) putBack(state, setup, change);
    res.fit = null;
    fitFor(true);
  }
  ui.followed = null;
  draw.panel(true);
  draw.stage();
  at("#panel h2")?.focus({ preventScroll: true });
  schedule();
}

/** Start the design from another part: the figures the user has not typed move to where
 *  that part starts them, and the note at the fields says what moved and how to put it back. */
function startFromPart(el: HTMLElement): void {
  const { state } = app;
  const id = el.dataset.lead!;
  if (!state.devices.includes(id)) return;
  state.lead = id;
  res.suggestion = null;
  save(state);
  const name = app.setup.devices.find((d) => d.id === id)?.name ?? "That part";
  void suggestFor().then(redrawAll);
  schedule();
  // The keyboard goes to the new design's column, once the table is drawn again with it; on
  // the first step, to the part in the list.
  draw.panel(true);
  if (state.step === RESULTS) toColumn(id);
  else at(`#panel [data-device="${CSS.escape(id)}"]`)?.focus();
  say(`${name} is now the design: its results are worked out again.`);
}

/** A press that moves to a step may first open a fold on it, or take the keyboard to a box. */
function toStep(el: HTMLElement): void {
  goTo(Number(el.dataset.step));
  const box = el.dataset.box;
  if (box) {
    const input = at<HTMLInputElement>(`[data-bind="${CSS.escape(box)}"]`);
    input?.scrollIntoView({ block: "center" });
    input?.focus();
  }
}

/** To the edge limit on step 3, from the event's line that says the limit set a resistor:
 *  the keyboard on the limit in use. */
function toEdgeLimit(): void {
  ui.folds.set("gate", true); // the limit is in the gate drive's fold
  goTo(SUPPLY);
  const fold = at<HTMLDetailsElement>('details[data-fold="gate"]');
  if (fold) fold.open = true;
  const input = at<HTMLInputElement>("[data-edge-limit]:checked");
  input?.closest("fieldset")?.scrollIntoView({ block: "center" });
  input?.focus();
}

/** Fetch the results' code again: the step says it is opening them, with the keyboard on its
 *  heading until they come, or on Try again where they do not. */
function retryResults(): void {
  ui.resultsFailed = false;
  draw.panel(true);
  at("#panel h2")?.focus({ preventScroll: true });
}

/** Each press by the data attribute that names it, in the order they are tried: the first
 *  that the pressed element carries is the one that answers. */
const PRESSES: [string, Press][] = [
  ["zoom", zoom],
  ["savePng", (el) => void savePngOf(el)],
  ["eventShow", (el) => openEvent((el.dataset.eventShow as "on" | "off") || null)],
  ["eventBox", (el) => toEventBox(el.dataset.eventBox!)],
  ["edgeLimitGo", toEdgeLimit],
  ["eventUse", (el) => useEstimate(el.dataset.eventUse!)],
  ["eventLayoutDrop", dropLayout],
  ["eventReset", (el) => resetEdge(el.dataset.eventReset as "on" | "off")],
  ["followed", settleFollowed],
  ["lead", startFromPart],
  ["equations", openEquations],
  ["saveSetup", saveSetup],
  ["undoForget", undoForget],
  ["cancelLargest", cancelLargest],
  ["retryReload", () => location.reload()],
  ["retryResults", retryResults],
  ["retryFetch", (el) => retryFetch(el.dataset.retryFetch!)],
  [
    "retry",
    () => {
      say("Asking again.");
      void compute();
    },
  ],
  [
    "setupNoteShut",
    () => {
      ui.setupNote = null;
      draw.panel(true);
    },
  ],
  ["saveDesign", saveDesign],
  ["otherTab", settleOtherTab],
  ["largest", findLargest],
  ["forgetDevice", forgetDevice],
  ["startOver", startOver],
  ["dropMission", dropMission],
  ["report", () => void printReport()],
  ["reportMd", () => void saveMarkdown()],
  ["resizeLoad", resizeLoad],
  ["usualMotor", useUsualMotor],
  ["motionFull", (el) => void openMotionFull(el)],
  ["mapAt", setMapSide],
  ["adding", addFromMenu],
  ["colEdit", editColumn],
  ["colRemove", removeColumn],
  ["undoColumn", undoColumn],
  ["switchYes", settleSwitch],
  ["switchNo", settleSwitch],
  ["variantSave", saveVariant],
  ["dialogClose", shutDialog],
  ["showMap", showMap],
  ["review", (el) => void openReview(el.dataset.review!)],
  ["addTyped", () => void addTyped()],
  ["toFigure", (el) => toFigure(el.dataset.toFigure!, el.dataset.figureOf ?? "")],
  ["useSized", useSized],
  ["resizeSized", () => void resizeSized()],
  ["example", addExample],
  ["step", toStep],
  ["tab", openTab],
  ["focus", setFocus],
  ["metric", setMetric],
  ["add", addStretch],
  ["remove", removeStretch],
];

const kebab = (key: string) => key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

const PRESSABLE = PRESSES.map(([key]) => `[data-${kebab(key)}]`).join(",");

export function onClick(e: Event): void {
  const el = (e.target as HTMLElement).closest<HTMLElement>(PRESSABLE);
  if (!el) return;
  const press = PRESSES.find(([key]) => el.dataset[key] !== undefined);
  if (!press) return;
  if (press[0] === "step" && el.dataset.openFold) ui.folds.set(el.dataset.openFold, true);
  // A choice made from a menu closes the menu.
  shutMenu(el.closest<HTMLElement>("[popover]"));
  press[1](el);
}
