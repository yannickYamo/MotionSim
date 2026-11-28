// The load the part under test can carry, proposed for the design as it stands: asked of the
// engine once a design's loads are known, put in as the load of step 4 while the user has not
// put in their own, and the load the user does put in set against it.

import { api, NotWorkedOut, Refused } from "../api";
import type { Cycle, LoadPreset, LoadProposal, Probe } from "../api";
import { startWaiting } from "../elapsed";
import { motionRequest, request, save } from "../state";
import { LOAD, RESULTS } from "../steps";
import { app, draw, focused, invalidate, pending, res, underTest } from "../store";
import { refusalOf } from "../wording";
import { deep } from "./deep";

/** The proposal for one design: on its way with its probes so far, or come back. */
export interface Proposed {
  key: string;
  application: string;
  at: number;
  probes: Probe[];
  answer: LoadProposal | Refused | null;
  stop: AbortController;
}

/** The proposal asked for last, and the motion of the user's own load set against it. */
export const proposed = {
  now: null as Proposed | null,
  /** The user's own load followed through its motion, to say how it stands to the proposal. */
  feedback: null as { key: string; cycle: Cycle | Refused | null } | null,
};

/** Where the block that says the proposal is drawn again in place, set by the view. */
export const drawProposal = { block: (): void => undefined };

/** What the proposal is asked with: the design, the part under test and the application,
 *  never the load itself, which is what it proposes. */
function asked(application: string): Record<string, unknown> | null {
  const { state } = app;
  const device = underTest();
  if (!device || !application || state.mission) return null;
  const { heatsink, c_link, precharge, start, repeats } = motionRequest(state);
  return { ...request(state), device, application, heatsink, c_link, precharge, start, repeats };
}

const keyOf = (body: Record<string, unknown>): string => JSON.stringify(body);

/** The proposal come back for the design as it stands and this application, or null. */
export function proposalFor(application: string): LoadProposal | null {
  const body = asked(application);
  const now = proposed.now;
  if (!body || !now || now.key !== keyOf(body)) return null;
  return now.answer instanceof Refused ? null : now.answer;
}

/** The application the load of step 4 is of: the kind its figures were last sized as, else the
 *  one the proposal was last asked for (a load of the user's own figures from the start). */
export const applicationNow = (): string => app.state.loadKind || proposed.now?.application || "";

/** The proposal of the design as it stands, whatever it came to: on its way, refused, or come. */
export function proposalNow(): Proposed | null {
  const body = asked(applicationNow());
  const now = proposed.now;
  return body && now && now.key === keyOf(body) ? now : null;
}

/** The load step 4 starts on for this application: the one proposed for the part where it
 *  has come and the user has not asked for the usual one, else the usual one. */
export const startingLoad = (usual: LoadPreset): LoadPreset =>
  (!app.state.loadUsual && proposalFor(usual.id)?.preset) || usual;

/** Whether the load of step 4 is the proposal as it came, untouched. */
export function isProposed(): boolean {
  const { state } = app;
  return !state.loadTouched && !state.loadUsual && !state.mission && !!proposalFor(applicationNow());
}

/** Put the proposal in as the load of step 4, where nothing of the user's own stands there. */
function putIn(answer: LoadProposal, put: (p: LoadPreset) => void): void {
  const { state } = app;
  if (state.loadTouched || state.loadUsual || state.mission || state.loadKind !== answer.application) return;
  put(answer.preset);
  invalidate("motion");
  save(state);
  if (state.step === LOAD) {
    draw.panel(true);
    draw.preview();
  }
  if (state.step === RESULTS) {
    draw.panel(true);
    draw.stage();
    void deep();
  }
}

/** Whether the verdict on the results is in, with what the open results ask for after it:
 *  the proposal's search is many motions followed one after another, and on the one engine
 *  it would take its time from the verdict's (measured: a 7 s verdict took 23 s beside it). */
export function verdictIn(): boolean {
  if (app.state.step !== RESULTS || res.blocked || res.fault) return true;
  // The design point first: until it has come, the verdict is not in.
  if (pending() || !res.proposal) return false;
  if (!focused()?.result) return true;
  return res.cycle !== null && res.loading.size === 0;
}

/** Resolves once the verdict is in (verdictIn), or at once when the search is stopped. */
function afterVerdict(stop: AbortSignal): Promise<void> {
  return new Promise((done) => {
    const look = () => (stop.aborted || verdictIn() ? done() : void setTimeout(look, 200));
    look();
  });
}

/** Ask for the proposal for the design as it stands, once for each design: the answer comes
 *  step by step, each step drawn in place, and is put in where the load is still not the
 *  user's own. `put` makes a preset the load of step 4. */
export async function propose(application: string, put: (p: LoadPreset) => void): Promise<void> {
  const body = asked(application);
  if (!body) return;
  const key = keyOf(body);
  // Asked once for a design; one the engine could not work out is asked again at the next change.
  if (proposed.now?.key === key && !(proposed.now.answer instanceof NotWorkedOut)) return;
  proposed.now?.stop.abort();
  const job: Proposed = { key, application, at: startWaiting(), probes: [], answer: null, stop: new AbortController() };
  proposed.now = job;
  drawProposal.block();
  // The verdict first: the search waits for it, and starts the moment it is in.
  await afterVerdict(job.stop.signal);
  if (proposed.now !== job || job.stop.signal.aborted) return;
  let answer: LoadProposal | Refused;
  try {
    answer = await api.loadProposal(
      body,
      (p) => {
        if (proposed.now !== job) return;
        job.probes.push(p);
        drawProposal.block();
      },
      job.stop.signal,
    );
  } catch (e) {
    if (job.stop.signal.aborted || proposed.now !== job) return;
    // An engine that could not work it out leaves the usual load standing, and says why.
    answer = refusalOf(e, (message) => new NotWorkedOut(message));
  }
  if (proposed.now !== job) return;
  job.answer = answer;
  if (!(answer instanceof Refused)) putIn(answer, put);
  drawProposal.block();
  // The results say how the load stands to the proposal: drawn again with it.
  if (app.state.step === RESULTS) draw.panel(true);
  // A load of the user's own already in place is set against it now it has come.
  void feedbackFor();
}

/** The user's own load followed through its motion, while they are on step 4, so that the
 *  step can say how it stands to the proposal. The same request the results ask, so they
 *  find it already worked out. */
export async function feedbackFor(): Promise<void> {
  const { state } = app;
  const device = underTest();
  if (state.step !== LOAD || !state.loadTouched || state.mission || !device) return;
  if (!proposalFor(applicationNow())) return;
  const body = { ...request(state), device, ...motionRequest(state) };
  const key = JSON.stringify(body);
  if (proposed.feedback?.key === key) return;
  const mine = { key, cycle: null as Cycle | Refused | null };
  proposed.feedback = mine;
  drawProposal.block();
  let got: Cycle | Refused;
  try {
    got = await api.cycle(body);
  } catch (e) {
    got = refusalOf(e, (message) => new NotWorkedOut(message));
  }
  if (proposed.feedback !== mine) return;
  mine.cycle = got;
  drawProposal.block();
}

/** The motion of the user's own load, where it is for the load as it stands now. */
export function feedbackNow(): Cycle | Refused | null | undefined {
  const { state } = app;
  const device = underTest();
  const f = proposed.feedback;
  if (!f || !device) return undefined;
  return f.key === JSON.stringify({ ...request(state), device, ...motionRequest(state) }) ? f.cycle : undefined;
}

/** Nothing proposed is kept: a whole new state is put in place. */
export function forgetProposal(): void {
  proposed.now?.stop.abort();
  proposed.now = null;
  proposed.feedback = null;
}
