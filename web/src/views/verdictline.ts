// The verdict at the head of the results, over every tab: what the results are opened for,
// said first, in the one vocabulary of verdictwords.ts. Under it, what the verdict is on (an
// assumed drive, until the user has set or confirmed one) and the one thing to act on first.

import type { Candidate, Check } from "../api";
import { driveAssumed } from "../drive";
import { tick } from "../elapsed";
import { escape, num, sentence, tied } from "../format";
import { icon } from "../icons";
import { MOTOR } from "../steps";
import { app, focused, pending, res, verdictOf } from "../store";
import { verdictMarkup, verdictText, verdictWords } from "../verdictwords";
import type { VerdictPart, VerdictWords } from "../verdictwords";
import { frontEndActions } from "./frontend";
import { isAction, splitFinding } from "./html";
import { thumb } from "./thumb";

/** What a verdict comes to, counted: the design actions (the motion's own fail among them) and
 *  the notes. */
export function counted(c: Candidate): { actions: number; notes: number } {
  const motion = verdictOf(c).why ? 1 : 0;
  return {
    actions: c.checks.filter(isAction).length + motion + frontEndActions(),
    notes: c.checks.filter((x) => x.level !== "ok" && !isAction(x)).length,
  };
}

/** A part's verdict in the one vocabulary: its level as the motion left it, and its counts. */
export function wordsOf(c: Candidate): VerdictWords {
  const v = verdictOf(c);
  const { actions, notes } = counted(c);
  return verdictWords({ level: v.level, actions, notes, refused: v.motion === "refused" });
}

/** Where a verdict holds, said after it where it is not the whole motion: a fail over the
 *  motion, one at the design point, or a verdict of the design point alone. */
export function whereOf(c: Candidate): VerdictPart[] {
  const v = verdictOf(c);
  if (v.why) return [{ text: "over the motion", tone: "ink-2" }];
  if (c.level === "fail") return [{ text: "at the design point", tone: "ink-2" }];
  if (v.motion === "unworked") return [{ text: "at the design point", tone: "ink-2" }];
  return [];
}

/** The part that says the drive is the page's, not the user's, while it is. */
const ASSUMED: VerdictPart = { text: "on an assumed drive", tone: "ink-2" };

/** The verdict as it is said everywhere a part's verdict is said in words: the headline, the
 *  screen reader, the strip on a phone. */
export function verdictSaid(c: Candidate): string {
  const extra = [...whereOf(c), ...(driveAssumed(app.state) ? [ASSUMED] : [])];
  return verdictText(wordsOf(c), extra);
}

/** The verdict of one part in a few words: "Passes · 1 design action · 2 notes". */
export function headlineOf(only: Candidate): string {
  return verdictText(wordsOf(only), whereOf(only));
}

/** The drive the verdict is on, while it is assumed: the motor, the point and the load in one
 *  line of figures, said to be assumed, with the one press to set your own. */
function assumedRow(): string {
  const { state, setup } = app;
  if (!driveAssumed(state)) return "";
  const k = state.conditions;
  const motor = setup.motors[state.kind]?.label ?? state.kind;
  const load =
    res.presets?.list.find((p) => p.id === state.loadKind)?.label ?? res.suggestion?.data?.application?.label ?? "";
  const figures = [
    `Motor ${num(k.v_dc)} V ${escape(motor)}`,
    `${num(k.rpm)} rpm, ${num(k.torque)} N·m`,
    ...(load ? [`${escape(load.toLowerCase())} load`] : []),
  ].join(" · ");
  const go =
    `<button type="button" class="ghost set-drive" data-step="${MOTOR}">` +
    `Set your drive${icon("arrow-right")}</button>`;
  return `<div class="assumed-row"><p>${tied(figures)}: <b>assumed</b>, sized to the part.</p>${go}</div>`;
}

/** The one line under the headline: the first thing to act on, with its why and fix one press
 *  away; or what the verdict rests on where there is nothing to act on. */
function firstLine(c: Candidate): string {
  const v = verdictOf(c);
  const line = (tone: string, mark: string, text: string, fold = "") =>
    `<p class="first-line ${tone}">${icon(mark)}<span>${text}</span>` +
    (fold
      ? `<button type="button" class="link" data-open-finding="${escape(fold)}">Why, and how to fix it</button>`
      : "") +
    `</p>`;
  const said = (x: Check) => {
    const [first] = splitFinding(sentence(x.message));
    return `<b>${escape(sentence(x.topic))}</b> ${escape(first)}`;
  };
  if (v.why) return line("fail", "circle-x", `<b>Over the motion</b> ${escape(sentence(v.why))}`);
  const failed = c.checks.findIndex((x) => x.level === "fail");
  if (failed >= 0) return line("fail", "circle-x", said(c.checks[failed]), `fails-${c.id}-0`);
  if (c.level === "fail" && c.problem) return line("fail", "circle-x", escape(sentence(c.problem)));
  const actions = c.checks.filter((x) => x.level !== "fail" && isAction(x));
  if (actions.length) return line("caution", "alert-triangle", said(actions[0]), `acts-${c.id}-0`);
  if (v.motion === "unworked")
    return line("quiet", "info-circle", "The motion was not worked out: this verdict is of the design point alone.");
  if (v.motion === "followed") return line("quiet", "circle-check", "Holds over the whole motion.");
  return line("quiet", "circle-check", "Every check passes at the design point.");
}

/** The first verdict of the visit comes in just after the glows on the drawing; once. */
let verdictShown = false;

/** The place the verdict takes, held at its size from the first answer to the last, so that
 *  nothing under it moves when the verdict comes. */
const head = (inner: string, assumed: string, under: string) =>
  `<div class="verdict-head">${thumb()}${inner}${assumed}${under}</div>`;

/** While the answer is on its way: no verdict word (a verdict that could still change is not
 *  given), the time it has taken so far, and the lines under it held at their size. */
let workingSince = 0;

function working(said: string): string {
  workingSince ||= Date.now();
  const at = res.staleSince || workingSince;
  tick();
  const line =
    `<p class="verdict-line working" role="status"><span>${said}</span>` +
    `<span class="since-quiet"> · <span class="since" data-since="${at}">0 s</span></span></p>`;
  return head(line, assumedRow(), `<p class="first-line skeleton-line" aria-hidden="true"><span></span></p>`);
}

/** The headline: nothing while there is no part, a working state while the answer is on its
 *  way, and the verdict once it is final. */
export function verdictHead(): string {
  const proposal = res.proposal;
  if (!app.state.devices.length || res.fault || res.blocked) return "";
  if (pending() || !proposal) return working("Working out the verdict");
  if (!proposal.candidates.length) return "";
  const single = proposal.candidates.length === 1;
  const top = proposal.candidates[0];
  const shown = focused() ?? top;
  if (shown.result && verdictOf(shown).motion === "pending") return working("Following the motion for the verdict");
  // Among several parts the headline is the first in the ranking; the ranking's own sentence
  // opens the Verdict tab under it.
  workingSince = 0;
  const w = wordsOf(top);
  const extra = [...whereOf(top), ...(driveAssumed(app.state) ? [ASSUMED] : [])];
  const enters = verdictShown ? "" : " enters";
  verdictShown = true;
  const name = single ? "" : `<span class="v-name">${escape(top.name)}: </span>`;
  const line = `<p class="verdict-line ${w.tone}${enters}">${verdictMarkup(w, extra, "v-said", name)}</p>`;
  return head(line, assumedRow(), firstLine(top));
}
