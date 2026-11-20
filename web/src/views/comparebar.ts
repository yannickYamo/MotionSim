// Under the tabs of the results: what is set beside the design, one column each, with the
// way to add one more and, where adding it would clear what is there, the question first.

import { comparing, series } from "../compare";
import { escape } from "../format";
import { icon } from "../icons";
import { shown } from "../shown";
import type { Kind } from "../shown";
import { app, focused, pending, res, ui } from "../store";
import { addMenu } from "./columns";
import { compareTable, onDevice } from "./comparison";
import { at } from "./html";
import { put } from "./morph";
import { landOnColumn } from "./oncolumn";

/** What is compared, in a few words, as the question and the heading say it. */
export const KIND_WORDS: Record<Kind, string> = {
  devices: "devices",
  loads: "loads",
  motors: "motors",
  sweep: "values of a setting",
};

/** The question asked before an addition clears what is compared: in the page, not a dialog
 *  of the browser, and the answer is the user's. */
function confirmBlock(): string {
  const to = shown.confirm?.to;
  if (!to) return "";
  const now = app.state.compare;
  const n = series().length - 1;
  const said =
    `<p id="confirm-said"><b>Compare ${KIND_WORDS[to]} instead?</b> One kind is compared at a time: this takes ` +
    `the ${n === 1 ? "one" : n} ${n === 1 ? KIND_WORDS[now].replace(/s\b/, "") : KIND_WORDS[now]} beside the ` +
    "design out of the table.</p>";
  const buttons =
    `<p class="confirm-buttons"><button type="button" class="ghost" data-switch-yes>${icon("check")}` +
    `Take them out, compare ${KIND_WORDS[to]}</button>` +
    `<button type="button" class="link" data-switch-no>Keep the ${KIND_WORDS[now]}</button></p>`;
  const attrs = 'id="confirm" role="group" aria-labelledby="confirm-said" tabindex="-1"';
  return `<div class="confirm" ${attrs}>${said}${buttons}</div>`;
}

/** A column just taken out, with the few seconds in which it can be put back. */
function undoNote(): string {
  const gone = shown.removed;
  if (!gone) return "";
  const undo = `<button type="button" class="link" data-undo-column>Undo</button>`;
  return `<p class="undo-note" role="status">Took ${escape(gone.name)} out of the table. ${undo}</p>`;
}

/** A part being read to compare, said under the table while the dialog is shut. */
function readingNote(): string {
  const reading = ui.reading;
  if (app.state.compare !== "devices" || !reading || reading.outcome || reading.refused) return "";
  return `<p class="quiet small">Adding ${escape(reading.name)}…</p>`;
}

/** What the columns stand on, by what is compared. */
function saidOf(mode: Kind): string {
  return {
    devices: "Up to five devices, each on the motor and load you set.",
    loads: `Up to five loads, each on ${onDevice()}.`,
    motors: `Up to five motors, each at its own design point, on ${onDevice()}.`,
    sweep: `One setting at up to five values, everything else as you set it, on ${onDevice()}.`,
  }[mode];
}

/** The table can be shown: there is a result for the inputs as they stand, and something
 *  beside it. */
const tableShown = (): boolean =>
  comparing() && !!focused()?.result && !pending() && !res.blocked && !res.fault && app.state.reached >= 3;

/** What the area holds: the heading, the question, the table or the way to start one. */
export function compareInner(): string {
  const mode = app.state.compare;
  const many = tableShown();
  const head = many
    ? `<h3 id="compare-title" tabindex="-1">Compared: ${KIND_WORDS[mode]}</h3>` +
      `<p class="quiet small">${saidOf(mode)}</p>`
    : `<h3 id="compare-title" tabindex="-1">Compare</h3>`;
  const start = many
    ? ""
    : `<div class="compare-start"><p class="quiet">Set another device, another load, this motor with a change, ` +
      `or a setting at several values beside the design: one kind at a time.</p>${addMenu()}</div>`;
  const table = `<div id="compare-table" class="compare-table">${many ? compareTable() : ""}</div>`;
  return `${head}${confirmBlock()}${start}${table}${readingNote()}${undoNote()}`;
}

/** The area under the tabs, on the results. */
export function compareArea(): string {
  if (!app.state.devices.length || res.fault || res.blocked) return "";
  return `<section id="compare-area" class="compare-area" aria-labelledby="compare-title">${compareInner()}</section>`;
}

/** The area alone drawn again, as the answers for the columns come in. */
export function renderCompareArea(): void {
  const el = at("#compare-area");
  if (el) put(el, compareInner(), "compare");
  landOnColumn();
}
