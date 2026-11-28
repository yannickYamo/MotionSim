// What a comparison gives the lab: a scheme taken from it with its run, and the run of the
// scheme already in the lab, which needs no second run.

import { askLoops, fitTest, hush } from "./actions";
import { compareKey } from "./compare";
import { cursor, idleRun, lab } from "./store";
import type { Run, Scheme } from "./types";

/** Take a scheme with its run already made (a comparison's): the run is the lab's at once,
 *  with nothing run again. The run before stays to be compared with where it was of this test. */
export function adopt(scheme: Scheme, answer: Run): void {
  hush();
  const s = lab.get();
  const tuned = s.presets?.schemes.find((x) => x.id === scheme.id) ?? scheme;
  const earlier = s.run.answer;
  lab.set({
    scheme: copy(scheme),
    tuned: copy(tuned),
    selected: null,
    run: { ...idleRun(), status: "done", answer },
    before: earlier && earlier.scenario.kind === s.scenario ? earlier : s.before,
    plotted: null,
    pins: {},
    said: null,
    view: null,
  });
  fitTest();
  askLoops(0);
  cursor.t = answer.series.t[answer.series.t.length - 1] ?? 0;
  cursor.again();
}

const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

/** The comparison's run of the scheme in the lab, as tuned, on the lab's test, is the lab's own
 *  run where it has none: chosen and kept, it is not run a second time, nor said not to have run. */
export function intoLab(scheme: Scheme, run: Run, key: string): void {
  const s = lab.get();
  const same = s.scheme && JSON.stringify(s.scheme) === JSON.stringify(scheme);
  if (!same || s.run.answer || s.run.status !== "idle" || compareKey(s) !== key) return;
  lab.set({ run: { ...idleRun(), status: "done", answer: run } });
  cursor.t = run.series.t[run.series.t.length - 1] ?? 0;
  cursor.again();
}
