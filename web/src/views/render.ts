// Putting the views on the page: the frame, the panel of the open step, and the parts of
// it that follow the engine's answers.

import { api } from "../api";
import { escape } from "../format";
import { icon } from "../icons";
import { since, tick } from "../elapsed";
import { DEVICE, LOAD, MOTOR, RESULTS, STEPS, SUPPLY, TABS } from "../steps";
import { unusedEntries } from "../boxes";
import { app, draw, focused, pending, res, ui, verdictOf } from "../store";
import { renderDialogs, DIALOGS } from "./adding";
import { devicesPanel } from "./device";
import { $, followedNote, reduced, refusal, say, spinner, verdictWord, waiting } from "./html";
import { loadPanel, renderPreview } from "./load";
import { put } from "./morph";
import { fitBlock, motorPanel } from "./motor";
import { nextButton, renderRail } from "./rail";
import { notReady } from "./tabs/ready";
import { loadResults, resultsNow } from "./resultsload";
import { renderStage } from "./stage";
import { landOnColumn } from "./oncolumn";
import { supplyPanel } from "./supply";
import { verdictHead } from "./verdictline";

/** The ways to keep the results. The PDF is the one primary action once there is a verdict
 *  that passes or passes with a caution; the .md file sits beside it. */
function reportButtons(primary: boolean): string {
  // With no answer from the engine the figures on screen are from before: a report would set
  // them beside the inputs as they now stand, so none is written, and the notice says why.
  const off = res.fault ? 'disabled aria-describedby="fault"' : focused()?.result && !pending() ? "" : "disabled";
  const writing = ui.savingMd > 0;
  const md =
    `<button type="button" class="ghost" data-report-md ${writing ? 'disabled aria-busy="true"' : off} ` +
    `title="The whole design as a Markdown file: for your notes, or to hand to a coding agent">` +
    (writing ? `${spinner}Writing the .md report, ${since(ui.savingMd)}` : `${icon("file-text")}Save as .md`) +
    `</button>`;
  const pdf =
    `<button type="button" class="${primary ? "primary" : "ghost"}" data-report ${off} ` +
    `title="Opens the print dialog: choose Save as PDF">${icon("printer")}Print or save as PDF</button>`;
  return `<span class="save-as">${md}${pdf}</span>`;
}

/** The foot of the results: one primary action, the way back as a link, and the setup file. */
function resultsActions(): string {
  const { state } = app;
  const c = focused();
  const keep = `<button type="button" class="link" data-save-setup>${icon("device-floppy")}Save setup</button>`;
  if (!state.devices.length) {
    const choose = `<button type="button" class="primary" data-step="${DEVICE}">${icon("cpu")}Choose a device</button>`;
    return `<div class="actions results-actions"><span></span>${choose}</div>`;
  }
  const back = `<button type="button" class="link" data-step="${LOAD}">${icon("arrow-left")}Back to the load</button>`;
  // On a refusal the way to the step at fault is the primary action, in the tab above.
  const level = c?.result && !pending() && !res.blocked && !res.fault ? verdictOf(c).level : null;
  const primary = level === "ok" || level === "caution";
  const saved = ui.savedMd ? `<p class="quiet saved">${icon("circle-check")}Saved ${escape(ui.savedMd)}</p>` : "";
  // The way back and the setup file sit above the bar that holds the reports.
  const ways = `<p class="ways">${back}${keep}</p>`;
  return `${ways}<div class="actions results-actions">${reportButtons(primary)}</div>${saved}`;
}

const tryAgain = `${icon("rotate-clockwise")}Try again`;

function resultsPanel(): string {
  const { state } = app;
  // The results' own code comes apart from the page's: where it has not come yet, the panel
  // says so under its heading and is drawn again once it has.
  const results = resultsNow();
  if (!results && ui.resultsFailed) {
    const said =
      "<p><b>The results could not be fetched.</b> Their part of the page did not come; " +
      "check the connection, then try again.</p>";
    const again = `<button type="button" class="ghost" data-retry-results>${tryAgain}</button>`;
    const note = `<div class="fault" role="alert">${icon("info-circle")}<div>${said}<p>${again}</p></div></div>`;
    return `<h2 tabindex="-1">Results</h2>${note}`;
  }
  if (!results) {
    const redraw = () => {
      if (app.state.step !== RESULTS) return;
      // The keyboard on Try again, pressed while it was fetched, goes back to it when it fails.
      const onHeading = document.activeElement === document.querySelector("#panel h2");
      draw.panel(true);
      if (onHeading && ui.resultsFailed) document.querySelector<HTMLElement>("[data-retry-results]")?.focus();
    };
    void loadResults().then(redraw, () => {
      ui.resultsFailed = true;
      redraw();
    });
    return `<h2 tabindex="-1">Results</h2>${waiting("Opening the results.")}`;
  }
  // An answer for inputs that have since moved is not shown under them, on any tab.
  // With no answer from the engine, no verdict stands: the figures from before stay beside
  // the drawing, dimmed, and the tabs wait for an answer.
  const body = pending()
    ? waiting("Working out the results for the inputs as they now stand.", res.staleSince)
    : res.fault
      ? notReady()
      : results.TAB_BODY[state.tab]();
  const tab = ([t, name]: (typeof TABS)[number]) =>
    `<button type="button" role="tab" id="tab-${t}" aria-selected="${state.tab === t}" aria-controls="tab-body" ` +
    `tabindex="${state.tab === t ? 0 : -1}" data-tab="${t}">${name}</button>`;
  const tabs = `<div class="tabs" role="tablist" aria-label="Results">${TABS.map(tab).join("")}</div>`;
  const fault = ui.reportFault ? `<p class="help said-wrong" role="alert">${escape(ui.reportFault)}</p>` : "";
  // The verdict first, then the tabs that say why, then what is set beside the design.
  return `<h2 tabindex="-1">Results</h2>${verdictHead()}${tabs}
<div id="tab-body" role="tabpanel" aria-labelledby="tab-${state.tab}" tabindex="0">${body}</div>
${results.compareArea()}${resultsActions()}${fault}`;
}

/** A step whose starting figures come from the part, while the engine that works them out is
 *  still starting: its boxes are not shown with figures that are about to change. */
function startingPanel(k: number): string {
  const step = STEPS[k];
  const said =
    `The ${step.name.toLowerCase()} figures start from your part, and the engine that works them out ` +
    "is still starting in this browser. They are shown as soon as it has started.";
  const row = '<div class="skeleton-field"><span></span><span></span></div>';
  return (
    `<h2 tabindex="-1">${escape(step.name)}</h2><p class="lead">${said}</p>` +
    `<div class="skeleton" aria-hidden="true">${row.repeat(6)}</div>${nextButton(k)}`
  );
}

const PANELS = [devicesPanel, motorPanel, supplyPanel, loadPanel, resultsPanel];

/** The refusal is said above the form of any step that could hold the input at fault. */
const refusedHere = (): boolean =>
  !!res.blocked && app.state.step !== RESULTS && app.state.step >= MOTOR && app.state.reached >= SUPPLY;

/** No answer from the server or the engine: one notice, in its own neutral style. It says the
 *  figures are not worked out, never that the design cannot run; it keeps the last figures,
 *  dimmed and said to be from before; and it offers to try again. */
function faultBanner(): string {
  const kept = !!focused()?.result;
  const before = kept ? " The figures shown are from before, dimmed." : "";
  const retry = `<button type="button" class="ghost" data-retry>${icon("rotate-clockwise")}Try again</button>`;
  if (res.offline) {
    const said = `<p><b>Not worked out.</b> ${escape(res.fault!)} The page asks again by itself.${before}</p>`;
    return `<div class="fault" id="fault" role="alert">${icon("info-circle")}<div>${said}<p>${retry}</p></div></div>`;
  }
  const server = api.mode() === "server";
  const fix = server
    ? "Check that <code>motionsim serve</code> is still running."
    : "Trying again reloads the page to start it; your inputs are kept.";
  const said = `<p><b>Not worked out: the engine stopped.</b> ${escape(res.fault!)}${before}</p><p>${fix}</p>`;
  const again = server ? retry : retry.replace("data-retry", "data-retry-reload");
  return `<div class="fault" id="fault" role="alert">${icon("info-circle")}<div>${said}<p>${again}</p></div></div>`;
}

/** Said once to a screen reader, when it changes: the verdict, and a note that figures moved. */
export function announce(text: string): void {
  if (text === ui.announced) return;
  ui.announced = text;
  const region = document.querySelector("#announce");
  if (region) region.textContent = text;
}

/** On the results: each entry that was not used, with the figure in use in its place and
 *  the way back to its box. The verdict below is for the figure in use, not the one typed. */
function unusedBanner(): string {
  const list = unusedEntries();
  if (app.state.step !== RESULTS || !list.length) return "";
  const line = ({ path, step, note }: (typeof list)[number]) => {
    const name = note.label ?? path.split(".").pop()!.replace(/_/g, " ");
    const unit = note.unit ? ` ${note.unit}` : "";
    const used = note.inUse ? `${note.inUse}${unit} is in use` : "the box is left out";
    const go =
      `<button type="button" class="link" data-step="${step}" data-box="${escape(path)}">` +
      `Go to ${escape(name.toLowerCase())}</button>`;
    return `<li><b>${escape(name)}:</b> ${escape(note.raw)} was not used; ${escape(used)}. ${go}</li>`;
  };
  const said =
    `<p><b>${list.length === 1 ? "An entry was" : "Some entries were"} not used.</b> ` +
    `These results are for the figures in use.</p><ul class="plain small">${list.map(line).join("")}</ul>`;
  return `<div class="asking unused-entries" role="status">${icon("alert-triangle")}<div>${said}</div></div>`;
}

/** Another tab saved a newer setup: the choice between it and this one, with this tab not
 *  saving meanwhile. */
function otherTabBanner(): string {
  const said =
    "<p><b>This setup was changed in another tab.</b> This tab is not saving, so as not to write over it.</p>";
  const load = `${icon("rotate-clockwise")}Load the other tab's setup`;
  const buttons =
    `<p><button type="button" class="ghost" data-other-tab="load">${load}</button>` +
    `<button type="button" class="link" data-other-tab="keep">Keep this one</button></p>`;
  return `<div class="asking" role="alert">${icon("info-circle")}<div>${said}${buttons}</div></div>`;
}

function banner(): string {
  if (ui.otherTab) return otherTabBanner();
  if (res.fault) return faultBanner();
  const refused = refusedHere() ? refusal(res.blocked!) : "";
  // What the browser keeps is said beside the rest, never in its place: a refusal, a note on
  // a setup opened or a Try again would otherwise be hidden for the whole visit.
  return (
    keptBanner() +
    fetchBanner() +
    setupBanner() +
    unusedBanner() +
    refused +
    (app.state.step >= MOTOR ? followedNote() : "")
  );
}

/** What the browser did with what it keeps for the page: cleared it, or keeps none. */
function keptBanner(): string {
  const note = (said: string) => `<div class="asking" role="status">${icon("info-circle")}<div>${said}</div></div>`;
  if (ui.cleared)
    return note(
      "<p><b>What this browser kept from an earlier visit could not be shown, and was cleared.</b> " +
        "The page has started afresh.</p>",
    );
  if (ui.unsaved)
    return note("<p><b>This browser is not keeping what you enter.</b> The page works; a reload starts it afresh.</p>");
  return "";
}

/** The equations or the printed report whose code did not come, with Try again. */
function fetchBanner(): string {
  const f = ui.fetchFault;
  if (!f) return "";
  const again = `<button type="button" class="ghost" data-retry-fetch="${f.what}">${tryAgain}</button>`;
  const said = `<p>${escape(f.text)}</p><p>${again}</p>`;
  return `<div class="fault" role="alert">${icon("info-circle")}<div>${said}</div></div>`;
}

/** What opening a setup file came to, above whichever step is open, with a way to put it away. */
function setupBanner(): string {
  const note = ui.setupNote;
  if (!note) return "";
  const shut = `<button type="button" class="link" data-setup-note-shut>Hide this</button>`;
  const glyph = icon(note.bad ? "alert-triangle" : "circle-check");
  const said = `<p>${escape(note.text)} ${shut}</p>`;
  return `<div class="asking setup-note${note.bad ? " bad" : ""}">${glyph}<div>${said}</div></div>`;
}

/**
 * Draw the open step. `keepFocus`: the step is the one already on screen, so what has the
 * keyboard keeps it; otherwise the step is new, and its heading takes the keyboard.
 */
export function renderPanel(keepFocus = false): void {
  const { state } = app;
  const panel = $("#panel");
  const view = state.step === RESULTS ? `${state.step}/${state.tab}` : String(state.step);
  // Opened afresh, the results' code is fetched again where it did not come before.
  if (!keepFocus && state.step === RESULTS) ui.resultsFailed = false;
  const waitingForEngine = !!ui.starting && state.step >= MOTOR && state.step <= LOAD;
  const body = waitingForEngine ? startingPanel(state.step) : PANELS[state.step]();
  put(panel, `<div id="banner">${banner()}</div>${body}`, view);
  document.body.dataset.at = String(state.step);
  const tab = panel.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]');
  if (!keepFocus) tab?.scrollIntoView({ block: "nearest", inline: "nearest" });
  renderPreview();
  renderDialogs();
  if (!keepFocus) panel.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
  markStale();
  speak();
  showFollowed();
  landOnColumn();
}

/** The note that figures moved, with Keep and Put back, is brought into sight when it appears:
 *  on a phone it can be well above the box being looked at. */
let followedShown = false;
function showFollowed(): void {
  const el = document.querySelector<HTMLElement>("#followed");
  if (el && !followedShown) el.scrollIntoView({ block: "nearest", behavior: reduced() ? "auto" : "smooth" });
  followedShown = !!el;
}

/** What a screen reader is told: the verdict on the device on the drawing once it is that
 *  of the inputs as they stand, or that figures followed the device. Each is said once. */
function speak(): void {
  const f = ui.followed;
  if (f) {
    const n = f.changes.length;
    return announce(`${n} ${n === 1 ? "figure" : "figures"} you had not typed now start from ${f.device}.`);
  }
  // A verdict said for inputs that have since moved is taken back, silently, until the new
  // one. What a press said of itself (a part made the design, a column taken out) stays.
  if (pending()) {
    if (verdictSaid) announce("");
    verdictSaid = false;
    return;
  }
  const c = focused();
  const settled = app.state.step === RESULTS && c && !res.stale && !res.blocked && !res.fault && !res.waiting;
  if (!settled) return;
  const v = verdictOf(c);
  if (v.motion === "pending") return;
  announce(`${c.name}: ${verdictWord(v.level)}${v.motion === "unworked" ? " at the design point" : ""}.`);
  verdictSaid = true;
}

/** Whether what the live region holds is a verdict. */
let verdictSaid = false;

/** The figures on screen are marked while a new answer for them is on its way: they are
 *  those of the inputs as they were. */
let wasPending = false;

export function markStale(): void {
  // The moment the inputs move, what was drawn for them goes: drawn again as waiting.
  const now = pending();
  if (now !== wasPending) {
    wasPending = now;
    renderStage();
    if (app.state.step === RESULTS) renderPanel(true);
    renderRail();
  }
  document.body.toggleAttribute("data-pending", now);
  const stale = res.stale || res.loading.size > 0;
  // Said on the page itself too, for whatever watches it from outside to know it has settled.
  document.body.toggleAttribute("data-stale", stale);
  for (const id of ["readouts", "compare-table", "verdict-strip", "tab-body", "pwm", "switcher"]) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.setAttribute("aria-busy", String(stale));
    // Figures kept from before the engine stopped answering are dimmed as well.
    el.classList.toggle("is-stale", stale || !!res.fault);
  }
}

/** The engine has answered, or failed to: everything that shows an answer is drawn again. */
export function refreshOutputs(): void {
  renderStage();
  renderRail();
  renderPanel(true);
}

/** The note under the motor's figures, alone: the rest of the step is left as it is. */
function renderFit(): void {
  const box = document.querySelector<HTMLElement>("#motor-fit");
  if (box) put(box, fitBlock(), "fit");
}

/** The engine starting in this browser, said in the top bar from the first moment: which of
 *  its three stages it is at and how long it has taken so far, until it can answer. */
export function renderEngineStatus(): void {
  const el = document.querySelector<HTMLElement>("#engine-status");
  if (!el) return;
  if (!ui.starting) {
    // Started: the bar is left to the page, and the start is said once to a screen reader.
    if (!el.hidden) {
      el.hidden = true;
      say("The engine has started.");
    }
    return;
  }
  el.hidden = false;
  el.dataset.state = "starting";
  const doing = `${ui.starting.charAt(0).toLowerCase()}${ui.starting.slice(1)}`;
  const what = `Starting the engine, ${ui.startStage} of 3: ${doing}`;
  // Only the words are spoken: the seconds move on beside them, unspoken.
  const short = `<span class="short" aria-hidden="true">Engine ${ui.startStage}/3</span>`;
  const time = `<span class="quiet" aria-hidden="true">${since(ui.startAt)}</span>`;
  put(el, `${spinner}<span class="what">${escape(what)}</span>${short} ${time}`);
  tick();
}

/** The bar across the top and the dialog of equations, there from the first moment. */
export function topBar(): string {
  const about =
    "Results are estimates from what you bring (a datasheet, a device file or your own measurements), stated " +
    "assumptions and simplified models. They can be wrong. Check them against the manufacturer's data and " +
    "measure on real hardware before you rely on them.";
  const lead =
    "Every figure on this page comes from these equations and from the values read from your device. " +
    "Nothing else is fitted or tuned.";
  // The setup file is kept and opened from the bar, on every step.
  const files =
    `<div class="top-files">` +
    `<button type="button" class="top-button" data-save-setup aria-label="Save setup" ` +
    `title="Save everything entered as a file (Ctrl+S)">${icon("device-floppy")}<span>Save setup</span></button>` +
    `<label class="top-button" title="Open a setup file saved from this page">${icon("folder-open")}` +
    `<span class="top-label">Open setup</span>` +
    `<input type="file" class="sr" data-setup-file accept=".json,application/json"/></label></div>`;
  return (
    `<header class="top"><h1 class="brand">MotionSim</h1>` +
    `<span class="top-note">Datasheets as models for motor drives</span>` +
    `<p id="engine-status" class="engine-status" role="status" aria-live="polite" hidden></p>${files}` +
    `<button type="button" class="top-button" data-equations aria-label="The equations">` +
    `${icon("math-function")}<span>The equations</span></button>` +
    `<button type="button" class="top-button about-button" popovertarget="about" aria-label="Exploratory tool">` +
    `${icon("info-circle")}<span>Exploratory tool</span></button>` +
    `<div id="about" class="about" popover="auto"><p>${about}</p></div>` +
    `<button type="button" class="top-button reset" data-start-over ` +
    `title="Clear everything entered and start again">${icon("rotate-clockwise")}<span class="keep">Reset</span>` +
    `</button>` +
    // On a phone the setup file and Reset go into one menu, each with its words.
    `<button type="button" class="top-button more-button" popovertarget="top-more" ` +
    `aria-label="Setup file and reset">${icon("dots-vertical")}</button>` +
    `<div id="top-more" class="top-menu" popover="auto">` +
    `<button type="button" data-save-setup>${icon("device-floppy")}Save setup</button>` +
    `<label>${icon("folder-open")}Open setup` +
    `<input type="file" class="sr" data-setup-file accept=".json,application/json"/></label>` +
    `<button type="button" data-start-over>${icon("rotate-clockwise")}Reset: clear everything entered</button>` +
    `</div></header>\n` +
    `<dialog id="equations" aria-labelledby="equations-title"><div class="dialog-head">` +
    `<h2 id="equations-title">How the results are worked out</h2>` +
    `<button type="button" class="close" data-close-equations aria-label="Close the equations">${icon("x")}</button>` +
    `</div><p class="lead">${lead}</p><div id="equations-body"></div></dialog>\n`
  );
}

/** The steps, the drawing and the form. They are put on the page only once they can be drawn
 *  in full: an empty frame filled a moment later pushes everything below it down. */
export function frame(): string {
  const stage =
    `<main id="stage"><p id="verdict-strip" class="verdict-strip" aria-hidden="true"></p>` +
    `<div id="plate" class="plate" tabindex="0" role="group" aria-label="Power stage drawing"></div>` +
    `<p class="swipe-hint">${icon("arrow-right")}Slide the drawing sideways to see the motor.</p>` +
    `<div id="switcher" class="switcher"></div><dl id="readouts" class="readouts"></dl>` +
    `<section id="pwm" class="pwm-view" aria-label="Switching periods"></section></main>`;
  // One place speaks to a screen reader, and only when what it says changes: regions that
  // are redrawn as the user types would be read out again at every key.
  const spoken = `<p id="announce" class="sr-only" role="status" aria-live="polite"></p>`;
  const panel = `<section id="panel" aria-label="Current step"></section>`;
  return `<nav id="rail" aria-label="Steps"></nav>\n${stage}\n${panel}${spoken}\n${DIALOGS}`;
}

/** Let the engine side ask for redraws. */
export function connect(): void {
  draw.panel = renderPanel;
  draw.stage = renderStage;
  draw.rail = renderRail;
  draw.preview = renderPreview;
  draw.outputs = refreshOutputs;
  draw.fit = renderFit;
  draw.stale = markStale;
  draw.busy = (on) => {
    if (on) document.body.dataset.busy = "1";
    else delete document.body.dataset.busy;
    markStale();
  };
}
