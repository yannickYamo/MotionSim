// The largest load the device can drive: asked for by a press, since it takes a while.

import { api, NotWorkedOut, Refused } from "../api";
import type { Largest, Probe } from "../api";
import { startWaiting } from "../elapsed";
import { motionRequest, request } from "../state";
import { RESULTS } from "../steps";
import { app, designNow, draw, focused, res, stopLargest } from "../store";
import { at, say } from "../views/html";
import { trail } from "../views/largest";

/** A probe of the search finished: it goes on the trail, which is drawn again in place, so
 *  that nothing else on the page moves and the Cancel button keeps the focus. */
function probed(job: { probes: Probe[] }, p: Probe): void {
  if (res.biggestAsked !== job) return; // a search given up, or another asked since
  job.probes.push(p);
  const place = at("[data-largest-trail]");
  if (place) place.innerHTML = trail(job.probes);
}

/** Make the load heavier until something gives: asked for by a press, since it takes a while. */
export function findLargest(): void {
  const { state } = app;
  const c = focused();
  if (!c) return;
  res.biggestAsked?.stop.abort();
  const stop = new AbortController();
  const job = { at: startWaiting(), stop, probes: [] as Probe[] };
  res.biggestAsked = job;
  res.biggest = "working";
  draw.panel(true);
  const asked = `${designNow()}|${state.focus}`;
  const keep = (v: Largest | Refused) => {
    if (stop.signal.aborted) return; // cancelled: the button is back already
    res.biggestAsked = null;
    if (`${designNow()}|${state.focus}` === asked) {
      res.biggest = v;
      say(v instanceof Refused ? "The largest load could not be found." : "Found the largest load.");
    } else if (res.biggest === "working") res.biggest = null;
  };
  void api
    .largest({ ...request(state), device: c.id, ...motionRequest(state) }, (p) => probed(job, p), stop.signal)
    .then(
      (v) => keep(v),
      // No answer says nothing of the load: it is not worked out, never "cannot work".
      (e) => keep(e instanceof Refused ? e : new NotWorkedOut((e as Error).message)),
    )
    .then(() => {
      // Given up, the page was drawn again by Cancel: drawn once more, the stop it said would
      // be spoken over.
      if (stop.signal.aborted) return;
      if (state.step === RESULTS && state.tab === "limits") draw.panel(true);
    });
}

/** Stop the search for the largest load: it goes no further than the probe it is at, and the
 *  button to ask is back at once. */
export function cancelLargest(): void {
  stopLargest();
  draw.panel(true);
  at<HTMLElement>("[data-largest]")?.focus();
  say("Stopped looking for the largest load.");
}
