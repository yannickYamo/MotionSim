// The steps down the side, and the bar at the foot of each step that leads to the next.

import { icon } from "../icons";
import { DEVICE, LOAD, RESULTS, STEPS, SUPPLY } from "../steps";
import { degrees, escape, watts } from "../format";
import { unusedEntries } from "../boxes";
import { app, blockedStep, conditionsGiven, focused, pending, res, shownMadeUp } from "../store";
import { put } from "./morph";
import { $ } from "./html";
import { verdictToken } from "../verdictwords";
import { wordsOf } from "./verdictline";
import { controlStatus } from "../control/entry";
import type { LabState } from "../control/entry";

function stepState(k: number): string {
  const { state } = app;
  if (k === blockedStep()) return "blocked";
  // A step with an entry that was not used is not done: the figure before it is in use.
  if (unusedEntries().some((x) => x.step === k)) return "unused";
  if (k === DEVICE && state.reached > DEVICE && !state.devices.length) return "blocked";
  const none = !pending() && res.proposal && !res.proposal.candidates.some((c) => c.result);
  if (k === RESULTS && state.reached >= RESULTS && none) return "blocked";
  // Three states: the step open now, a step opened before, and one not opened yet. A step
  // passed over on the way to the results is not opened, and is never ticked.
  return k !== state.step && state.visited.includes(k) ? "done" : "todo";
}

/** The step open now waits on the user before anything can be worked out: no part chosen
 *  yet, or a figure the cooling needs. Only then is the station marked as the next action. */
function needsAction(k: number): boolean {
  if (k === DEVICE) return !app.state.devices.length;
  return k === SUPPLY && !!res.waiting;
}

/** A step's state, said for a screen reader. */
function saidOf(st: string, current: boolean): string {
  if (st === "blocked") return "needs a change";
  if (st === "unused") return "an entry was not used";
  if (current) return "current step";
  return st === "done" ? "opened before" : "not opened yet";
}

/** The mark in a step's station. */
function glyphOf(st: string, current: boolean, own: string): string {
  if (st === "blocked" || st === "unused") return icon("alert-triangle");
  return icon(st === "done" && !current ? "check" : own);
}

/** The line under a step's name. */
function aboutOf(st: string, k: number, own: string): string {
  if (st === "blocked") return k === DEVICE ? "Choose a part" : "Needs a change";
  return st === "unused" ? "An entry was not used" : own;
}

/** One step of the rail: its station, its name, and its state said for a screen reader. */
function station(s: (typeof STEPS)[number], k: number): string {
  const st = stepState(k);
  const current = k === app.state.step;
  const mark = `<span class="station">${glyphOf(st, current, s.icon)}</span>`;
  const text =
    `<span class="step-text"><span class="step-name"><span class="step-number">${k + 1}</span>${s.name}</span>` +
    `<span class="step-about">${aboutOf(st, k, s.about)}</span></span>`;
  const button =
    `<button type="button" data-step="${k}" aria-describedby="step-${k}-state" title="${s.name}" ` +
    `${current ? 'aria-current="step"' : ""}>${mark}${text}</button>`;
  const said = `<span class="sr" id="step-${k}-state">${saidOf(st, current)}</span>`;
  const cls = st === "unused" ? "blocked unused" : st;
  const marked = current && needsAction(k) ? " needs-action" : "";
  return `<li class="${cls}${current ? " is-current" : ""}${marked}">${button}${said}</li>`;
}

/** What the control lab's panel says of where it stands, and what a press does from there. */
const LAB_WORDS: Record<LabState, [string, string]> = {
  local: ["Runs on your own machine", "runs on your own machine: start MotionSim there"],
  "no-part": ["Needs a part first", "needs a part first: pressed, it leads to step 1"],
  waiting: ["Press to open", "pressed, it opens over the results, once the scheme for this design is chosen there"],
  choosing: ["Choosing…", "choosing a scheme for this design; pressed, it opens once one is chosen"],
  unreachable: ["Not available now", "not available now: the results say why"],
  ready: ["Ready", "ready: opens the control lab"],
};

/** The control lab, under the five steps and set apart from them by a rule: a project of its
 *  own on the same design, so not numbered and not a station of the route. It says where it
 *  stands (greyed until there is a part to control) and opens the lab, or leads to it. */
function labPanel(): string {
  const { state, scheme } = controlStatus();
  const [word, said] = LAB_WORDS[state];
  // The panel says only where it stands; the scheme it is ready on is in its tooltip and its
  // description for a screen reader, never in a visible line that runs long.
  const on = state === "ready" && scheme ? escape(scheme) : "";
  const title = on ? `Control lab: ${on}` : "Control lab";
  const button =
    `<button type="button" class="lab-entry" data-control-rail data-state="${state}" ` +
    `aria-describedby="lab-entry-said" title="${title}">` +
    `<span class="lab-entry-mark">${icon("route")}</span>` +
    `<span class="lab-entry-text"><span class="lab-entry-name">Control lab` +
    `<span class="lab-entry-go" aria-hidden="true">${icon("arrow-right")}</span></span>` +
    `<span class="lab-entry-state">${word}</span></span></button>`;
  const sr = `<span class="sr" id="lab-entry-said">${said}${on ? ` on ${on}` : ""}</span>`;
  const cls = `rail-lab${state === "ready" ? " is-ready" : ""}${state === "no-part" ? " is-idle" : ""}`;
  return `<div class="${cls}">${button}${sr}</div>`;
}

export function renderRail(): void {
  put($("#rail"), `<ol>${STEPS.map(station).join("")}</ol>${labPanel()}`);
}

/** What the figures say now, in a few words, for the bar at the foot of a phone's screen,
 *  where the drawing and its readouts are out of sight above the form. Shown on a phone only,
 *  and kept from screen readers: the readouts say the same. */
export function barStatus(): string {
  if (!app.state.devices.length || !conditionsGiven()) return "";
  if (pending()) return "Working…";
  const c = focused();
  const r = c?.result;
  if (!c || !r || res.fault || res.blocked) return "";
  return `${verdictToken(wordsOf(c))} · ${degrees(r.tj_peak)} · ${watts(r.loss)}`;
}

/** The same words as the bar sets them, on a phone's one row: a figure stays with its unit and
 *  a dot with the words before it, so the line turns only between two of its parts. */
export const barWords = (): string => barStatus().replace(/ · /g, "\u00a0· ").replace(/(\d) /g, "$1\u00a0");

/** Say the figures again in the bar, where it is on the page. */
export function renderBarStatus(): void {
  const el = document.querySelector<HTMLElement>("#panel .bar-status");
  if (el) el.textContent = barWords();
}

/** Why the way on from step k cannot be taken yet, with the id it is said under; null where it can. */
function holdBack(k: number): { id: string; said: string; next: boolean } | null {
  if (k === DEVICE && !app.state.devices.length && !shownMadeUp())
    return { id: "need-device", said: "Bring a part, or try a made-up one, to go on.", next: true };
  // With no answer from the engine there are no results to see: the way to them waits for it.
  if (res.fault && k === LOAD)
    return { id: "need-answer", said: "Not worked out yet: see the note at the top of this step.", next: true };
  return null;
}

const backButton = (k: number): string =>
  k > 0
    ? `<button type="button" class="ghost" data-step="${k - 1}">${icon("arrow-left")}Back</button>`
    : "<span></span>";

/** The press to the next step. */
function stepOn(k: number, off: string): string {
  const label = k === LOAD ? "See the results" : `Next: ${STEPS[k + 1].name.toLowerCase()}`;
  const face = `${label}${icon("arrow-right")}`;
  return `<button type="button" class="primary" data-step="${k + 1}" ${off}>${face}</button>`;
}

/** What a held press carries: disabled, and described by the line saying why. */
const offOf = (held: { id: string } | null | undefined): string =>
  held ? `disabled aria-describedby="${held.id}${held.id === "need-answer" ? " fault" : ""}"` : "";

export function nextButton(k: number): string {
  const back = backButton(k);
  // Every part, made-up or the user's own, is walked through the steps in turn: the results
  // are reached from the load's step, never from the part's.
  const held = holdBack(k);
  const next = stepOn(k, held?.next ? offOf(held) : "");
  // A way on that cannot be taken says why beside it, in the bar itself: never only to a screen reader.
  const why = held ? `<p class="need" id="${held.id}">${held.said}</p>` : "";
  const status = k > DEVICE && !why ? `<p class="bar-status" aria-hidden="true">${barWords()}</p>` : "";
  return `<div class="actions${why ? " has-need" : ""}">${status}${back}${why}${next}</div>`;
}
