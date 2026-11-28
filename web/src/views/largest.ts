// How much heavier the load of step 4 could be: the button to ask, the search as it closes
// in, probe by probe, with the way to stop it, and the answer.

import { Refused } from "../api";
import type { Probe } from "../api";
import { degrees, escape, num, ratio, sentence } from "../format";
import { icon } from "../icons";
import { res } from "../store";
import { refusal, waiting } from "./html";

/** A scale as the page says it: "1.6×". */
const times = (k: number) => `${ratio(k)}×`;

/** What one probe came to, in a few words: it passes, it runs too hot, or something else gives. */
export function probeWords(p: Probe): string {
  const at = p.full ? `${times(p.scale)} worked out in full` : times(p.scale);
  if (p.passes) return `${at} … passes`;
  if (p.peak != null && p.tj_max != null && p.peak > p.tj_max) return `${at} … ${degrees(p.peak)}, too hot`;
  return `${at} … does not pass`;
}

/** Where the answer lies once a probe is counted: between two scales, under the load as it
 *  is, or past the last that passed. */
export function boundsWords(p: Probe): string {
  if (p.low <= 0) return `under ${times(p.high)}`;
  // Still doubling: every scale tried so far has passed.
  const doubling = p.passes && !p.full && p.low >= 1 && p.scale === p.low && p.high === 2 * p.low;
  if (doubling) return `more than ${times(p.low)}`;
  return `between ${times(p.low)} and ${times(p.high)}`;
}

/** The probes so far, each said as it finished, and where the answer lies now. */
export function trail(probes: Probe[]): string {
  const last = probes.at(-1);
  if (!last) return "";
  const said = [...probes.map(probeWords), boundsWords(last)].join(" · ");
  return `<p class="largest-trail small">Tried ${escape(said)}.</p>`;
}

/** The search on its way: how long it has looked, the probes so far, and the way to stop it.
 *  The trail is drawn in place as each probe finishes, and is not read out one probe at a
 *  time: a screen reader hears that the search is under way, and its answer. */
function working(): string {
  const asked = res.biggestAsked;
  const cancel = `<button type="button" class="ghost" data-cancel-largest>${icon("x")}Cancel</button>`;
  const said = waiting("Making the load heavier until something gives.", asked?.at);
  return (
    `<div class="largest-working">${said}${cancel}</div>` +
    `<div data-largest-trail>${trail(asked?.probes ?? [])}</div>`
  );
}

/** How much heavier the load of step 4 could be: the button to ask, the search, or the answer. */
export function largestLoad(): string {
  const biggest = res.biggest;
  if (biggest === "working") return working();
  if (biggest instanceof Refused) return refusal(biggest);
  if (!biggest) {
    return `<p><button type="button" class="ghost" data-largest>${icon("plus")}Find the largest load</button></p>`;
  }
  const k = num(biggest.scale, 2);
  if (biggest.scale < 1) {
    const said =
      `The load of step 4 is already too much: it would have to be ${k} times what it is. ` +
      `${escape(sentence(biggest.why))}.`;
    return `<p class="fact warn">${icon("alert-triangle")}<span>${said}</span></p>`;
  }
  if (biggest.open) {
    const said =
      `The load could be more than ${k} times heavier and still pass every check: ` +
      "something other than this device will limit it first.";
    return `<p class="fact">${icon("circle-check")}<span>${said}</span></p>`;
  }
  const said =
    `The load of step 4 could be <b>${k} times</b> as heavy ` +
    "(its inertia, friction, steady torque and mass together) before a check fails. " +
    `What gives first: ${escape(sentence(biggest.why))}.`;
  return `<p class="fact">${icon("circle-check")}<span>${said}</span></p>`;
}
