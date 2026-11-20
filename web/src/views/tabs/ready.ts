import type { Candidate, Refused } from "../../api";
import { escape, sentence } from "../../format";
import { icon } from "../../icons";
import { STEPS, SUPPLY } from "../../steps";
import { app, blockedStep, focused, res } from "../../store";
import { asking, refusal, waiting } from "../html";

/** The engine's reason for refusing the design, and the button back to the step at fault. */
function wayBack(blocked: Refused): string {
  const at = blockedStep() < 0 ? SUPPLY : blockedStep();
  const label = `Go to ${escape(STEPS[at].name.toLowerCase())} to change it`;
  const button = `<button type="button" class="primary" data-step="${at}">${icon("arrow-left")}${label}</button>`;
  return `${refusal(blocked)}<p>${button}</p>`;
}

/** A device the engine could not run at this design point: why, and what would change that. */
function cannotRun(c: Candidate): string {
  const why = escape(sentence(c.problem ?? "it could not be run at this design point"));
  const said = `<p><b>${escape(c.name)} cannot be worked out here.</b> ${why}.</p>`;
  const fix = c.fix ? `<p class="fix">${escape(sentence(c.fix))}.</p>` : "";
  return `<div class="refusal" role="alert">${icon("ban")}<div>${said}${fix}</div></div>`;
}

/** Why there is nothing to show yet on a results tab: no device, a design that cannot run
 *  (with the reason and the way back to the step at fault), or an answer on its way. */
export function notReady(): string {
  if (!app.state.devices.length) {
    const said = "No device is chosen. Go back to step 1 and tick the part you want to test.";
    return `<p class="empty">${icon("cpu")}${said}</p>`;
  }
  if (res.waiting) {
    const label = `${icon("arrow-left")}Go to the cooling to give it`;
    const go = `<button type="button" class="ghost" data-step="${SUPPLY}" data-open-fold="cooling">${label}</button>`;
    return `${asking(res.waiting)}<p>${go}</p>`;
  }
  if (res.blocked) return wayBack(res.blocked);
  // No answer from the engine is said once, above the panel; here only that nothing is shown.
  if (res.fault) return `<p class="empty">Not worked out until the engine answers again.</p>`;
  const c = focused();
  if (res.proposal && c && !c.result) return cannotRun(c);
  return waiting("Working out the losses.", res.staleSince);
}
