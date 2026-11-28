// The load proposed for the part, as step 4 and the results say it: what it is and what stops
// it going further while it is the load; the way back to the usual load; and, once the user
// puts in a load of their own, how that load stands to the proposal.

import { NotWorkedOut, Refused } from "../api";
import type { Cycle, LoadProposal } from "../api";
import { applicationNow, feedbackNow, isProposed, proposalFor, proposalNow } from "../engine/proposed";
import { degrees, escape, num, ratio, sentence } from "../format";
import { icon } from "../icons";
import { app, res } from "../store";
import { driveAssumed } from "../drive";
import { refusal, waiting } from "./html";

/** A scale as the page says it: "1.6×". */
const times = (k: number) => `${ratio(k)}×`;

/** Where a junction gets to and how far that is from its rating, the distance taken from the
 *  top of the band the thermal assumptions span, as the proposal is held to it: "79 °C (up to
 *  95 °C across the thermal assumptions), 80 K under its 175 °C rating". The distance is the
 *  difference of the figures written, so the two always add up. */
export function junctionSaid(peak: number, top: number, rating: number): { text: string; room: number } {
  const [p, t, r] = [peak, Math.max(top, peak), rating].map((x) => Math.round(x));
  const spread = t - p >= 1 ? ` (up to ${degrees(t)} across the thermal assumptions)` : "";
  const room = r - t;
  const side = room >= 0 ? `${room} K under` : `${-room} K over`;
  return { text: `${degrees(p)}${spread}, ${side} its ${degrees(r)} rating`, room };
}

/** What stops the proposal going further, and where its junction stands: "limited by the
 *  motor's current limit, with the junction peaking at 79 °C (up to 95 °C across the thermal
 *  assumptions), 80 K under its 175 °C rating". */
export function limitedBy(p: LoadProposal): string {
  const f = p.figures;
  const margin = `the junction peaking at ${junctionSaid(f.tj_peak, f.tj_top, f.tj_max).text}`;
  if (p.open || p.binding.limit === "none") return `nothing on this drive limits it within 16 times, with ${margin}`;
  return `limited by ${p.binding.words}, with ${margin}`;
}

/** What the proposed load asks, in one line of figures. */
function figuresLine(p: LoadProposal): string {
  const f = p.figures;
  const current = f.i_peak != null ? `, ${num(f.i_peak)} A peak in a switch` : "";
  return (
    `<p class="quiet small proposed-figures">Up to ${num(f.peak_torque)} N·m at the motor ` +
    `(${num(f.rms_torque)} N·m rms) and ${num(f.top_rpm)} rpm${current}.</p>`
  );
}

/** Why this load and not a heavier one, folded away: the engine's own sentence. */
function whyFold(p: LoadProposal): string {
  return (
    `<details class="more" data-fold="proposed-why"><summary>${icon("info-circle")}Why this load` +
    `<span class="quiet">the heaviest that passes, with a margin</span></summary>` +
    `<p class="small">${escape(p.why)}</p></details>`
  );
}

/** The proposal while it is on its way: word at once, with how long it has looked and how
 *  far it has got. The page stays usable meanwhile: the usual load stands until it comes. */
function working(at: number, probes: { scale: number; passes: boolean }[]): string {
  const label = labelOf();
  const said = waiting(`Finding how much of this ${label} load the part carries.`, at);
  const last = probes.at(-1);
  const so = last
    ? `<p class="quiet small proposed-trail" aria-hidden="true">Tried ${probes.length}: ` +
      `${escape(probes.map((p) => `${times(p.scale)} ${p.passes ? "passes" : "does not"}`).join(" · "))}.</p>`
    : "";
  return `${said}${so}`;
}

/** The application's name as the list of loads says it, in lower case. */
function labelOf(): string {
  const id = proposalNow()?.application;
  return (res.presets?.list.find((p) => p.id === id)?.label ?? "").toLowerCase();
}

/** The proposal in place as the load: what it is, what limits it, and the way to the usual load. */
function inPlace(p: LoadProposal): string {
  const head =
    `<p class="fact proposed-line">${icon("weight")}<span><span class="tag">proposal in use</span> ` +
    `<b>${escape(p.label)}, ${times(p.scale)} the usual load</b>, ${escape(limitedBy(p))}.</span></p>`;
  const usual =
    `<button type="button" class="ghost" data-usual-load>${icon("arrow-back-up")}` +
    `Back to your duty: the usual load</button>`;
  return `${head}${figuresLine(p)}${whyFold(p)}<p>${usual}</p>`;
}

/** The one press back to the proposal, from the usual load or the user's own. */
const toProposal = (p: LoadProposal) =>
  `<button type="button" class="ghost" data-proposed-load>${icon("weight")}Use ${times(p.scale)}</button>`;

/** The usual load in place, by the user's choice: the proposal said beside it, one press away. */
function usualInPlace(p: LoadProposal): string {
  const said = `<b>This part carries up to ${times(p.scale)}</b> this load, ${escape(limitedBy(p))}.`;
  return (
    `<div class="offer"><p class="fact">${icon("weight")}<span><span class="tag">proposal</span> ${said}</span></p>` +
    `${toProposal(p)}</div>`
  );
}

/** The peak torque a motion asks of the motor. */
const peakTorque = (c: Cycle): number => c.torque.reduce((m, t) => Math.max(m, Math.abs(t)), 0);

/** How a load of the user's own stands to the proposal: its torque against the proposal's,
 *  where its junction gets to and how far that is from the rating, and the first check that
 *  fails. Its level is the gravest of those. */
export function against(p: LoadProposal, c: Cycle): { level: "ok" | "caution" | "fail"; text: string } {
  const junction = junctionAgainst(p, c);
  return { level: junction.level, text: `${torqueAgainst(p, c)}: ${junction.text}` };
}

/** The torque of a load against the proposal's: by its peak, or by its rms where the peaks
 *  are the same (a heavier inertia on a motion whose peak is a steady hold). */
function torqueAgainst(p: LoadProposal, c: Cycle): string {
  const peak = peakTorque(c) / p.figures.peak_torque - 1;
  const rms = Number(c.summary.rms_torque) / p.figures.rms_torque - 1;
  const [ratio, what] = Math.abs(peak) >= 0.01 ? [peak, "torque"] : [rms, "rms torque"];
  const share = Math.round(Math.abs(ratio) * 100);
  if (share < 1) return "The proposal's torque";
  return ratio > 0 ? `+${share}% ${what} over the proposal` : `${share}% less ${what} than the proposal`;
}

/** Where the junction of a load gets to against its rating and the proposal's margin, and
 *  the first check that fails: the level is the gravest of those. */
function junctionAgainst(p: LoadProposal, c: Cycle): { level: "ok" | "caution" | "fail"; text: string } {
  const s = c.summary;
  const peak = Number(s.peak);
  const said = junctionSaid(peak, Number(s.peak_top ?? s.peak), Number(s.tj_max));
  const failed =
    c.checks.find((x) => x.level === "fail" && x.topic === "motion") ?? c.checks.find((x) => x.level === "fail");
  const tight = said.room < p.margin.wanted;
  const level = failed || said.room < 0 ? "fail" : tight ? "caution" : "ok";
  const tail = failed
    ? `. Does not pass: ${failed.message}`
    : tight
      ? `, inside the ${Math.round(p.margin.wanted)} K margin`
      : "";
  return { level, text: `the junction reaches ${said.text}${tail}.` };
}

const LEVEL_ICON = { ok: "circle-check", caution: "alert-triangle", fail: "circle-x" } as const;

/** The user's own load set against the proposal, once its motion has been followed. */
function ownAgainst(p: LoadProposal): string {
  const c = feedbackNow();
  const button = toProposal(p);
  const base =
    `<p class="quiet small">Proposed for this part: ${times(p.scale)} the usual load, ` +
    `${escape(limitedBy(p))}.</p>`;
  if (c === undefined || c === null) {
    return `${waiting("Setting your load against the proposal.")}${base}<p>${button}</p>`;
  }
  if (c instanceof Refused) {
    return `${refusal(c)}${base}<p>${button}</p>`;
  }
  const said = against(p, c);
  const cls = said.level === "ok" ? "fact fits" : said.level === "caution" ? "fact warn" : "fact warn fails";
  return (
    `<p class="${cls} proposed-against" role="status">${icon(LEVEL_ICON[said.level])}` +
    `<span>${escape(said.text)}</span></p>${base}<p>${button}</p>`
  );
}

/** Step 4's word on the proposal: on its way, in place, the usual load in its place, the
 *  user's own load set against it, or why there is none. Nothing while none is asked for. */
export function proposalBlock(): string {
  const { state } = app;
  if (state.mission) return "";
  const now = proposalNow();
  if (!now) return "";
  if (now.answer === null) return working(now.at, now.probes);
  if (now.answer instanceof NotWorkedOut) {
    return (
      `<p class="fact warn">${icon("alert-triangle")}<span>The load this part can carry could not be worked ` +
      `out: ${escape(sentence(now.answer.reason))}. The usual load stands; it is asked again at your next change.` +
      `</span></p>`
    );
  }
  if (now.answer instanceof Refused) {
    // The engine's own reason opens with the same words: they are said once.
    const reason = sentence(now.answer.reason);
    const lead = /^no load of this kind passes/i.test(reason) ? "" : "No load of this kind passes on this design: ";
    return (
      `<p class="fact warn">${icon("alert-triangle")}<span>${lead}` +
      `${escape(reason)}. The usual load stands, to look at.</span></p>`
    );
  }
  const p = now.answer;
  if (isProposed()) return inPlace(p);
  if (state.loadTouched) return ownAgainst(p);
  return usualInPlace(p);
}

/** The results' word on the load: the proposal for the part and what limits it, or how the
 *  load in use stands to it. Nothing where no proposal has come for this design. */
export function resultsLoadLine(cycle: Cycle | null): string {
  const { state } = app;
  if (state.mission) return "";
  const p = proposalFor(applicationNow());
  if (!p) return "";
  if (isProposed()) {
    return (
      `<p class="fact proposed-line">${icon("weight")}<span>The load is the one proposed for this part: ` +
      `${times(p.scale)} the usual ${escape(p.label.toLowerCase())} load, ${escape(limitedBy(p))}.</span></p>`
    );
  }
  if (state.loadUsual && !state.loadTouched) {
    return (
      `<p class="fact">${icon("weight")}<span>${driveAssumed(state) ? "Assumed duty" : "Your duty"}: ` +
      `the usual ${escape(p.label.toLowerCase())} load. ` +
      `This part carries up to ${times(p.scale)}, ${escape(limitedBy(p))}.</span></p>`
    );
  }
  if (!cycle) return "";
  const said = against(p, cycle);
  const cls = said.level === "ok" ? "fact fits" : "fact warn";
  return `<p class="${cls}">${icon(LEVEL_ICON[said.level])}<span>Your load. ${escape(said.text)}</span></p>`;
}

/** The block drawn again in place, as the proposal's search closes in and when it comes. */
export function redrawProposal(): void {
  const box = document.querySelector<HTMLElement>("#load-proposal");
  if (box) box.innerHTML = proposalBlock();
}
