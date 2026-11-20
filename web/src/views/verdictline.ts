// The verdict in one line, at the head of the results, over every tab: what the results are
// opened for, said first, in the colour of its state.

import type { Candidate } from "../api";
import { escape } from "../format";
import { icon } from "../icons";
import { app, pending, res, verdictOf } from "../store";
import { levelClass, VERDICT_ICON } from "./html";

/** The verdict in one clause, where one device alone is under test. What comes after the
 *  clause is said on the Verdict tab, under the line. */
export function headlineOf(only: Candidate): string {
  const v = verdictOf(only);
  if (v.why) return `${only.name} passes at the design point, but not over the motion`;
  if (only.level === "ok") return `${only.name} passes every check at this design point`;
  if (only.level === "caution") return `${only.name} can do this, with cautions to read`;
  if (only.level === "undecided") return `${only.name} is not decided by this data`;
  return `${only.name} does not pass at this design point`;
}

/** The first verdict of the visit comes in just after the glows on the drawing; once. */
let verdictShown = false;

/** The line itself: nothing while there is no verdict for the inputs as they stand. */
export function verdictHead(): string {
  const proposal = res.proposal;
  if (!app.state.devices.length || !proposal?.candidates.length || pending() || res.fault || res.blocked) return "";
  const single = proposal.candidates.length === 1;
  const top = proposal.candidates[0];
  const level = single ? verdictOf(top).level : top.level;
  const text = single ? headlineOf(top) : (proposal.explain[0] ?? "").replace(/\.$/, "");
  const enters = verdictShown ? "" : " enters";
  verdictShown = true;
  const mark = icon(VERDICT_ICON[level] ?? "alert-triangle");
  return `<p class="verdict-line ${levelClass(level)}${enters}">${mark}<span>${escape(text)}.</span></p>`;
}
