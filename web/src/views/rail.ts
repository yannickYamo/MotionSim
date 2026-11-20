// The steps down the side, and the bar at the foot of each step that leads to the next.

import { icon } from "../icons";
import { DEVICE, LOAD, RESULTS, STEPS, SUPPLY } from "../steps";
import { degrees, watts } from "../format";
import { unusedEntries } from "../boxes";
import { app, blockedStep, conditionsGiven, focused, pending, res, verdictOf } from "../store";
import { put } from "./morph";
import { $, verdictWord } from "./html";

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

export function renderRail(): void {
  put($("#rail"), `<ol>${STEPS.map(station).join("")}</ol>`);
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
  return `${verdictWord(verdictOf(c).level)} · ${degrees(r.tj_peak)} · ${watts(r.loss)}`;
}

/** Say the figures again in the bar, where it is on the page. */
export function renderBarStatus(): void {
  const el = document.querySelector<HTMLElement>("#panel .bar-status");
  if (el) el.textContent = barStatus();
}

export function nextButton(k: number): string {
  const back =
    k > 0
      ? `<button type="button" class="ghost" data-step="${k - 1}">${icon("arrow-left")}Back</button>`
      : "<span></span>";
  const stuck = k === DEVICE && !app.state.devices.length;
  // With no answer from the engine there are no results to see: the way to them waits for it.
  const unanswered = !!res.fault && k >= DEVICE;
  const label = k === LOAD ? "See the results" : `Next: ${STEPS[k + 1].name.toLowerCase()}`;
  const need = stuck
    ? 'disabled aria-describedby="need-device"'
    : unanswered && k === LOAD
      ? 'disabled aria-describedby="fault"'
      : "";
  const face = `${label}${icon("arrow-right")}`;
  const next = `<button type="button" class="primary" data-step="${k + 1}" ${need}>${face}</button>`;
  const why = stuck ? '<p class="quiet need" id="need-device">Tick a device, or add one, to go on.</p>' : "";
  // With a part chosen, the results are one press away: every other step starts sized to it.
  const skip =
    k === DEVICE && !stuck
      ? `<button type="button" class="ghost" data-step="${RESULTS}" data-skip ` +
        (unanswered ? 'disabled aria-describedby="fault" ' : "") +
        `aria-label="See the results with these settings"><span class="long">See the results with these settings` +
        `</span><span class="short" aria-hidden="true">See the results</span></button>`
      : "";
  const forward = skip ? `<span class="forward">${skip}${next}</span>` : next;
  const status = k > DEVICE ? `<p class="bar-status" aria-hidden="true">${barStatus()}</p>` : "";
  return `<div class="actions${skip ? " has-skip" : ""}">${status}${back}${forward}</div>${why}`;
}
