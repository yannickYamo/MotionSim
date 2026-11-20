// The slower results: the motion, the map, what to build and what the device can drive,
// worked out only for the tab that is open, and for each thing compared.

import { api, NotWorkedOut, Refused } from "../api";
import { requestOf, series } from "../compare";
import type { Series } from "../compare";
import { startWaiting } from "../elapsed";
import { motionRequest, request } from "../state";
import { RESULTS } from "../steps";
import { shown } from "../shown";
import { app, designNow, draw, focused, invalidate, res } from "../store";
import { refusalOf } from "../wording";

/** The answers asked for again by a later pass while an earlier asking was still out. */
const askedAgain = new Set<string>();

/** Counts the states put in place whole (Reset, Open setup): an answer asked for under an
 *  earlier count is for a state that is no longer on the page, whatever its inputs. */
let generation = 0;

/** A whole new state is put in place: no answer asked for under the one before is kept, and
 *  none of it is owed. */
export function newState(): void {
  generation++;
  askedAgain.clear();
}

/** One pass of the slower results: it is for the inputs and the device it began with. Once
 *  either has moved on it asks for nothing more: what it would ask with (the device, the
 *  request) is no longer what is wanted. */
function passOf() {
  const begun = { inputs: designNow(), focus: app.state.focus, at: generation };
  const still = (key: string) =>
    begun.at === generation &&
    designNow() === begun.inputs &&
    ((app.state.compare === "devices" && key.includes(":")) || app.state.focus === begun.focus);
  return async <T>(key: string, call: () => Promise<T>, store: (v: T | Refused) => void): Promise<void> => {
    // Only the results are redrawn by a slow answer: if the user has moved to another
    // step meanwhile, that step is theirs and is left as it is.
    if (app.state.step !== RESULTS || !still(key)) return;
    if (res.loading.has(key)) {
      askedAgain.add(key);
      return;
    }
    res.loading.add(key);
    res.started.set(key, startWaiting());
    draw.busy(true);
    draw.panel(true);
    // In a comparison of devices each answer is one device's own; anywhere else it is
    // the answer for the device on the drawing.
    let got: T | Refused;
    try {
      got = await call();
    } catch (e) {
      got = refusalOf(e, (message) => new NotWorkedOut(message));
    }
    // Asked for a state no longer on the page: nothing of it is the page's any more.
    if (begun.at !== generation) return;
    if (still(key)) store(got);
    res.loading.delete(key);
    res.started.delete(key);
    if (!res.loading.size) draw.busy(false);
    // The readouts and the verdict above the drawing read the motion too: they are redrawn
    // with the panel, or they keep what they said before it came.
    if (app.state.step === RESULTS) {
      draw.panel(true);
      draw.stage();
    }
    // An answer that came back for inputs since changed is not shown, and one asked for
    // again while this was out is owed. The pass is made once more after every answer: it
    // works out only what is still missing, and so cannot leave something out for good.
    askedAgain.delete(key);
    void deep();
  };
}

type Run = ReturnType<typeof passOf>;

/** The top of the map: the user's own, or twice the design point. */
function mapRange(n: number) {
  const { state } = app;
  const c = state.conditions;
  return {
    rpm_max: Number(state.map.rpm_max) || c.rpm * 2,
    torque_max: Number(state.map.torque_max) || c.torque * 2,
    n,
  };
}

/** The motion of one thing compared: its own load, or the page's with what differs laid over. */
function motionOf(x: Series) {
  const { state } = app;
  // A heatsink temperature being tried is also where that column's heatsink starts from.
  const tried = x.over?.conditions?.t_sink;
  const as = tried != null ? { ...state, conditions: { ...state.conditions, t_sink: Number(tried) } } : state;
  if (!x.item) return motionRequest(as);
  return motionRequest({
    ...state,
    load: x.item.load,
    segments: x.item.segments,
    phases: x.item.phases ?? null,
    mission: x.item.mission ?? null,
  });
}

/** Each thing compared through its motion. Returns false when the user has left the results. */
async function comparedCycles(run: Run, list: Series[], shownId: string): Promise<boolean> {
  const { state } = app;
  for (const x of list) {
    if (state.step !== RESULTS) return false;
    if (res.cycles.has(x.key) || !x.candidate) continue;
    const ask = () => api.cycle({ ...requestOf(x), device: x.candidate!.id, ...motionOf(x) });
    await run(`cycle:${x.key}`, ask, (v) => {
      res.cycles.set(x.key, v);
    });
    if (state.compare === "loads") draw.stage();
  }
  // The device on the drawing as it is now: it may have changed while the motions were asked for,
  // and the motion of the one it was must not be shown under the one it is.
  const onDrawing = focused()?.id ?? shownId;
  const mine = res.cycles.get(state.compare === "devices" ? onDrawing : state.compare === "sweep" ? "" : "now");
  if (mine && res.cycle !== mine) {
    res.cycle = mine;
    // The readouts say the motion's hottest junction beside the design point's: they are
    // drawn again with it, as a reload would draw them.
    draw.stage();
    if (state.step === RESULTS) draw.panel(true);
  }
  return true;
}

/** The results of the open tab for the device on the drawing alone. */
async function tabResults(run: Run, req: ReturnType<typeof request> & { device: string }): Promise<void> {
  const { state } = app;
  const cycle = () => api.cycle({ ...req, ...motionRequest(state) });
  // The motion is followed whatever tab is open: the verdict on the device rests on it too.
  if (res.cycle === null) await run("cycle", cycle, (v) => (res.cycle = v));
  if (state.tab === "losses" && shown.map && res.grid === null) {
    await run(
      "map",
      () => api.map({ ...req, ...mapRange(8) }),
      (v) => (res.grid = v),
    );
  }
  if (state.tab === "limits" && res.advised === null) {
    const air = state.sink.t_ambient;
    const t_ambient = air === "" || Number.isNaN(Number(air)) ? 40 : Number(air);
    const ask = () => api.recommend({ ...req, t_ambient }).then((x) => x.items);
    await run("recommend", ask, (v) => (res.advised = v));
  }
  if (state.tab === "limits" && res.capable === null) {
    await run(
      "capability",
      () => api.capability(req),
      (v) => (res.capable = v),
    );
  }
}

/** The map of each device compared is shown: under the losses, once the map is asked for. */
const mapsCompared = (): boolean => app.state.compare === "devices" && app.state.tab === "losses" && shown.map;

/** The slower results, worked out only for the tab that is open. */
export async function deep(): Promise<void> {
  const { state } = app;
  const c = focused();
  if (state.step !== RESULTS || !c?.result || res.blocked) return;
  const req = { ...request(state), device: c.id };
  // Whatever was worked out for other inputs is not an answer for these.
  // What is compared beside the design is not one of its inputs: changing only that keeps
  // the design's own results, its map among them, and works out only what is compared.
  if (designNow() !== res.resultsOf) {
    invalidate("deep");
    res.resultsOf = designNow();
  }
  const run = passOf();
  // What is compared: each one's motion, and for devices each one's map.
  const list = series();
  const wide = list.length > 1;
  if (wide && !(await comparedVariants(run, list, c.id))) return;
  if (wide && (state.compare === "loads" || state.tab === "motion")) {
    if (!(await comparedCycles(run, list, c.id))) return;
  }
  if (wide && mapsCompared()) {
    await comparedMaps(run, list);
    return;
  }
  await tabResults(run, req);
}

/** The design point of each thing compared that changes an input. Returns false when the user
 *  has left the results. */
async function comparedVariants(run: Run, list: Series[], device: string): Promise<boolean> {
  for (const x of list) {
    if (!x.over || res.variants.has(x.key)) continue;
    if (app.state.step !== RESULTS) return false;
    const ask = () => api.proposal({ ...requestOf(x), devices: [device] }).then((p) => p.candidates[0]);
    await run(`variant:${x.key}`, ask, (v) => {
      res.variants.set(x.key, v);
    });
    draw.stage();
  }
  return true;
}

/** The map of each device compared, until the user leaves the results. */
async function comparedMaps(run: Run, list: Series[]): Promise<void> {
  const { state } = app;
  for (const x of list) {
    if (state.step !== RESULTS) return;
    if (res.grids.has(x.key)) continue;
    const ask = () => api.map({ ...request(state), device: x.key, ...mapRange(6) });
    await run(`map:${x.key}`, ask, (v) => {
      res.grids.set(x.key, v);
    });
  }
}
