// Presses are a table: the data attribute on what was pressed names its handler.

import { goTo } from "../actions";
import { resizeSized, useSized } from "../actions/cooling";
import { freeLink, holdLink, leaveTheMains, recommendedStage, suitSupply } from "../actions/frontend";
import { toFigure } from "../actions/figures";
import { addTyped, openReview } from "../actions/parts";
import { openEquations, printReport, retryFetch, saveDesign, saveMarkdown } from "../actions/reports";
import { clearEverything, keepEverything, saveSetup, settleOtherTab, startOver } from "../actions/setup";
import { compute, schedule } from "../engine";
import { deep } from "../engine/deep";
import { fitFor } from "../engine/fit";
import { applyPreset, loadFor, presetsFor } from "../engine/loads";
import { applicationNow, proposalFor, startingLoad } from "../engine/proposed";
import { suggestFor } from "../engine/suggest";
import { useBoardFigures } from "../board/reading";
import { dropLayout, openEvent, toEventBox, useEstimate, resetEdge } from "../eventask";
import { putBack } from "../follow";
import { openChat, wireChat } from "../chat/chat";
import { forgetKey, openSettings, saveKey } from "../settings/actions";
import { shown } from "../shown";
import { save } from "../state";
import type { State, Tab } from "../state";
import { DEVICE, MOST, RESULTS, SUPPLY, ZOOMS } from "../steps";
import { openLimitFull, openMotionFull, openPwmFull } from "../actions/fullscreen";
import { app, draw, invalidate, picked, redrawAll, res, shownMadeUp, ui } from "../store";
import { at, say } from "../views/html";
import { toColumn } from "../views/oncolumn";
import { openControl, fromRail } from "../control/entry";
import { firstRunShown } from "../views/firstrun";
import { choosePick, pickedId, taking, togglePick } from "./picker";
import { openFinding, toggleMoreRows, useThisLoad } from "./verdictpresses";
import { addFromMenu, editColumn, removeColumn, saveVariant, settleSwitch, shutDialog, undoColumn } from "./columns";
import { cancelLargest, findLargest } from "./largest";
import { shutMenu } from "./menus";
import { partsChanged } from "./redraw";
import { forgetDevice, undoForget } from "./undo";
import { pin, pinNow, unpin } from "../pin";
import { middleOf } from "../pasted";

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
    // The page may draw its charts again while the image is made: the drawing is the one that
    // stands by this button then, or by the button of the same name drawn in its place.
    const named = el.dataset.savePng ?? "";
    const drawn = () => {
      const all = [...document.querySelectorAll<HTMLElement>("[data-save-png]")];
      const at = el.isConnected ? el : all.find((b) => b.dataset.savePng === named);
      return at?.closest("[data-png-host], .ev-edge, #plate")?.querySelector<SVGSVGElement>("svg.chart, svg.schematic");
    };
    say(`Saved as ${await savePng(drawn, named || "Chart", el.dataset.under ?? "")}.`);
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
  applyPreset(startingLoad(again));
  res.cycles.clear();
  draw.panel(true);
  draw.preview();
  schedule();
}

/** The application's usual load in place of the one proposed for the part: the user's choice,
 *  kept as the design moves, until they ask for the proposal again. */
function useUsualLoad(): void {
  const { state } = app;
  const usual = loadFor(res.presets?.list ?? [], applicationNow());
  if (!usual) return;
  state.loadUsual = true;
  state.loadTouched = false;
  applyPreset(usual);
  res.cycles.clear();
  say("The usual load is in.");
  draw.panel(true);
  draw.preview();
  at<HTMLElement>("[data-proposed-load]")?.focus();
  schedule();
}

/** The load proposed for the part in place of what stands in step 4: the usual load or the
 *  user's own figures. */
function useProposedLoad(): void {
  const { state } = app;
  const p = proposalFor(applicationNow());
  if (!p) return;
  state.loadUsual = false;
  state.loadTouched = false;
  applyPreset(p.preset);
  res.cycles.clear();
  say("The load proposed for this part is in.");
  draw.panel(true);
  draw.preview();
  at<HTMLElement>("[data-usual-load]")?.focus();
  schedule();
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

// A part chosen in the list with none on the page yet is brought at once: the way on opens.
// On the first visit's question the list only selects: Try it beside it brings the part.
taking.chose = (made) => {
  if (made && !app.state.devices.length && !firstRunShown()) bringExample(made);
};

/** Bring the made-up part shown in the list's box: exactly that one, once. */
function addPicked(): void {
  const made = pickedId();
  if (!made || app.state.added.includes(made)) return;
  picked.id = "";
  bringExample(made);
}

/** Bring the made-up part, to try the tool with. */
function addExample(el: HTMLElement): void {
  bringExample(el.dataset.example || "example");
}

function bringExample(made: string): void {
  const { state } = app;
  state.devices = [...new Set([...state.devices, made])].slice(-MOST);
  state.added = [...new Set([...state.added, made])];
  save(state);
  partsChanged();
  (at(`[data-drop-device="${made}"]`) ?? at("#panel h2"))?.focus({ preventScroll: true });
}

/** The first visit's own part: the ways to bring it, and the compact table. */
function openYourPart(): void {
  ui.yourPart = true;
  draw.panel();
  at<HTMLElement>("#drop")?.focus({ preventScroll: true });
}

/** Back to the first visit's question. */
function firstBack(): void {
  ui.yourPart = false;
  draw.panel();
}

/** The first visit's made-up part, chosen in its list: brought onto step 1, from which the
 *  steps lead on one by one (motor, supply and point, load) to the results. */
function firstTry(): void {
  const made = pickedId();
  if (!made) return;
  ui.firstRun = false;
  ui.yourPart = false;
  picked.id = "";
  bringExample(made);
}

/** The figures typed in the compact table: a range in a box is read as its middle, and the part
 *  is built and brought onto step 1, from which the steps lead on to the results. */
async function quickAdd(): Promise<void> {
  const { state } = app;
  const notes: Record<string, string> = {};
  for (const [key, text] of Object.entries(state.typed)) {
    const mid = typeof text === "string" ? middleOf(text) : null;
    if (mid) {
      state.typed[key] = mid.text;
      notes[key] = mid.note;
    }
  }
  const before = state.devices.length;
  await addTyped();
  Object.assign(ui.typedNotes, notes);
  if (state.devices.length > before && !ui.typedRefused && !Object.keys(ui.typedWrong).length) {
    ui.firstRun = false;
    ui.yourPart = false;
    ui.pasted = "";
  }
  draw.panel(true);
}

/** Pin the result on the drawing as A: every key figure then says how far it moved from it. */
function pinA(): void {
  if (!pinNow()) return;
  say(`${pin.a!.name} pinned as A. Change one input to see each figure against it.`);
  draw.panel(true);
  draw.stage();
  at<HTMLElement>("[data-unpin]")?.focus();
}

function unpinA(): void {
  unpin();
  say("A unpinned.");
  draw.panel(true);
  draw.stage();
  at<HTMLElement>("[data-pin-a]")?.focus();
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
  const to = Number(el.dataset.step);
  // On from step 1 with no part on the page: the made-up part the list shows comes with it.
  if (app.state.step === DEVICE && to > DEVICE && !app.state.devices.length) {
    const made = shownMadeUp();
    if (made) bringExample(made);
  }
  goTo(to);
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
  ["boardUse", useBoardFigures],
  ["eventReset", (el) => resetEdge(el.dataset.eventReset as "on" | "off")],
  ["followed", settleFollowed],
  ["lead", startFromPart],
  ["equations", openEquations],
  ["settings", (el) => void openSettings(el)],
  ["chatOpen", (el) => (wireChat(), openChat(el))],
  ["settingsSave", () => void saveKey()],
  ["settingsForget", () => void forgetKey()],
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
  ["resetKeep", keepEverything],
  ["moreRows", toggleMoreRows],
  ["resetSure", clearEverything],
  ["dropMission", dropMission],
  ["report", () => void printReport()],
  ["reportMd", () => void saveMarkdown()],
  ["resizeLoad", resizeLoad],
  ["usualLoad", useUsualLoad],
  ["useLoad", useThisLoad],
  ["openFinding", (el) => openFinding(el.dataset.openFinding!)],
  ["proposedLoad", useProposedLoad],
  ["usualMotor", useUsualMotor],
  ["motionFull", (el) => void openMotionFull(el)],
  ["pwmFull", () => void openPwmFull()],
  ["limitFull", (el) => void openLimitFull(el)],
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
  ["holdLink", holdLink],
  ["freeLink", freeLink],
  ["recommendedStage", recommendedStage],
  ["leaveMains", leaveTheMains],
  ["suitSupply", suitSupply],
  ["resizeSized", () => void resizeSized()],
  ["pinA", pinA],
  [
    "recommend",
    () => {
      ui.recommend = !ui.recommend;
      draw.panel(true);
      at<HTMLElement>("[data-recommend]")?.focus();
    },
  ],
  ["yourPart", openYourPart],
  ["firstTry", firstTry],
  ["firstBack", firstBack],
  ["quickAdd", () => void quickAdd()],
  ["unpin", unpinA],
  ["example", addExample],
  ["exampleGo", addPicked],
  ["exampleOpen", togglePick],
  ["exampleChoose", choosePick],
  ["controlOpen", openControl],
  ["controlRail", fromRail],
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
