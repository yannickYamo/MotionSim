// Talking to the engine: what is asked, when, and which answers are kept. Nothing here
// touches the page; what has to be redrawn is asked of `draw`.

import { api, Refused, Unreachable } from "./api";
import { deep, newState } from "./engine/deep";
import { stopFit } from "./engine/fit";
import { suggestFor } from "./engine/suggest";
import { latest } from "./guard";
import { request, save } from "./state";
import { app, chosenDevices, conditionsGiven, draw, invalidate, res, ui } from "./store";
import { plainRefusal } from "./wording";

let pending: AbortController | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
// The slower results wait on a timer of their own: a change of the map's range must not
// take the place of an answer that a design figure has just asked for.
let deepTimer: ReturnType<typeof setTimeout> | undefined;

/** From this moment the figures on screen are not those of the inputs, and are marked so. */
function markStale(): void {
  if (!res.stale) res.staleSince = Date.now();
  res.stale = true;
  draw.stale();
}

/** Work the answer out again, a moment after the last change. From this moment the figures
 *  on screen are marked as not yet those of the inputs. */
export function schedule(): void {
  ui.unsaved = !save(app.state);
  markStale();
  clearTimeout(timer);
  timer = setTimeout(() => void compute(), 240);
}

/** The slower results again, a moment after the map's own range stops changing. */
export function scheduleDeep(): void {
  clearTimeout(deepTimer);
  deepTimer = setTimeout(() => void deep(), 500);
}

/** Nothing that was worked out is an answer for the inputs as they stand. */
function dropAnswers(): void {
  res.stage = null;
  res.advice = null;
  res.proposal = null;
}

/** The part needs a figure the user has not given yet: nothing is asked of the engine, and
 *  the box that wants it says so. */
function needed(): Refused | null {
  const c = app.state.conditions;
  const empty = (text: string) => String(text ?? "").trim() === "";
  if (c.cooling === "heatsink" && empty(c.rth_sink)) {
    return new Refused("the heatsink's thermal resistance is needed", "give it under Cooling", "rth_sink");
  }
  if (c.cooling === "board" && empty(c.board_area)) {
    return new Refused("the board's area is needed", "give it under Cooling", "board_area");
  }
  return null;
}

/** A refusal for the junction-to-air figure while its box is still empty is not a fault in
 *  what was given: the figure has not been given yet, and is asked for at its box as the
 *  heatsink's is. A module is built to sit on a heatsink and its datasheet seldom has one:
 *  that is said plainly. */
function stillNeeded(refused: Refused): Refused | null {
  const c = app.state.conditions;
  const free = c.cooling === "none" || c.cooling === "board";
  if (refused.field !== "rth_ja" || !free || String(c.rth_ja ?? "").trim() !== "") return null;
  const module = chosenDevices().some((d) => d.positions > 1);
  if (module) {
    return new Refused(
      "a module is built to sit on a heatsink, and its datasheet seldom gives a figure from junction to air. " +
        "Give one under Cooling if you have it, or put the module on a heatsink",
      "give it under Cooling",
      "rth_ja",
    );
  }
  return new Refused("the thermal resistance from junction to air is needed", "give it under Cooling", "rth_ja");
}

interface PointAnswer {
  stage: typeof res.stage;
  advice: typeof res.advice;
  proposal: typeof res.proposal;
}

/** The design point, and each device at it. Nothing is stored here: the answer is handed
 *  back, and kept only if it is still the latest asked for. */
async function askPoint(signal: AbortSignal): Promise<PointAnswer> {
  const { state } = app;
  const req = request(state);
  const answer = await api.stage(req, signal);
  if (!conditionsGiven()) return { ...answer, proposal: null };
  return { ...answer, proposal: await api.proposal({ ...req, devices: state.devices }, signal) };
}

/** Take the answer for the design point, and put on the drawing the device the user chose
 *  where it was run, else the first that was. */
function keepPoint(answer: PointAnswer): void {
  const { state } = app;
  Object.assign(res, answer);
  const run = answer.proposal?.candidates ?? [];
  if (!answer.proposal) return;
  const stillThere = run.some((c) => c.id === state.focus && c.result);
  if (!state.focusPicked || !stillThere) state.focus = run.find((c) => c.result)?.id ?? null;
}

/**
 * Work out the design point for the inputs as they stand. The starting point for the
 * device under test is settled first, so that nothing is worked out for a motor that is
 * about to be changed. A failure leaves no earlier answer standing: what was on screen was
 * for other inputs.
 */
export async function compute(): Promise<void> {
  const current = latest("compute");
  markStale();
  pending?.abort();
  const mine = (pending = new AbortController());
  await suggestFor();
  if (!current()) return;
  res.fault = null;
  res.waiting = needed();
  try {
    const answer = res.waiting ? null : await askPoint(mine.signal);
    if (!current()) return;
    if (answer) keepPoint(answer);
    else dropAnswers();
    res.blocked = null;
  } catch (error) {
    if (!current() || mine.signal.aborted) return;
    // A refusal is an answer: what was worked out before goes. No answer at all says
    // nothing of the design, so the last figures stay, shown as from before.
    if (error instanceof Refused) dropAnswers();
    const asked = error instanceof Refused ? stillNeeded(error) : null;
    if (asked) {
      res.waiting = asked;
      res.blocked = null;
    } else if (error instanceof Refused) res.blocked = plainRefusal(error);
    else res.fault = (error as Error).message;
    res.offline = error instanceof Unreachable;
  }
  if (!res.fault) res.offline = false;
  askAgain();
  res.stale = false;
  invalidate("all");
  draw.outputs();
  if (res.fault) draw.panel(true);
  // With no engine answering, nothing more is asked of it until it answers again.
  else void deep();
}

/** How long to wait before asking a server that did not answer again: doubled each time
 *  it still does not, to half a minute. Coming back to the page asks at once. */
let backoff = 0;
let again: ReturnType<typeof setTimeout> | null = null;
let listening = false;

function askAgain(): void {
  if (again) clearTimeout(again);
  again = null;
  if (!res.offline) {
    backoff = 0;
    return;
  }
  backoff = Math.min(30000, backoff ? backoff * 2 : 2000);
  again = setTimeout(() => void compute(), backoff);
  if (listening || typeof window === "undefined") return;
  listening = true;
  const now = () => {
    if (res.offline) void compute();
  };
  window.addEventListener("focus", now);
  window.addEventListener("online", now);
}

/** A whole new state is put in place: every answer on its way for the one before is dropped
 *  when it comes, and what was about to be asked is not asked. */
export function dropInFlight(): void {
  newState();
  pending?.abort();
  pending = null;
  clearTimeout(timer);
  stopFit();
  for (const key of ["compute", "suggest", "presets", "fit", "review", "report", "print"]) latest(key);
  if (again) clearTimeout(again);
  again = null;
  backoff = 0;
  res.loading.clear();
  res.started.clear();
  draw.busy(false);
}
