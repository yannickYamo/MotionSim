// The lab as the session shared with a coding agent reads and writes it. Fetched with the lab's
// own code: until the lab is first opened, what the session holds of it waits in carry.ts.
//
// The page writes what a setup carries of the lab, the wires probed, and a summary of the last
// run (with the run itself, thinned, kept as session-run/last for the agent to read). What the
// agent writes is put in place in the lab as it stands: its scheme as tuned for this design
// with the agent's edits, its test, figures and fidelity, its probes, and a run it made.

import { designOfPage } from "./entry";
import { askLoops } from "./actions";
import { carry, goLive, readSaved } from "./carry";
import type { LabDoc, LastRun } from "./carry";
import { control } from "./client";
import { trimmed } from "./libactions";
import { cursor, idleRun, lab } from "./store";
import type { LabState } from "./store";
import type { Run, Scheme } from "./types";

const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

let lastRun: LastRun | null = null;
/** The run put in place from the session, and the last run seen finished: a run of the page's
 *  own is one that is neither. */
let fromSession: Run | null = null;
let seen: Run | null = null;

/** What a run comes to, in the few words the session keeps of it. */
export function summaryOf(run: Run, source: LastRun["source"]): LastRun {
  return {
    id: "last",
    source,
    at: Date.now() / 1000,
    scheme: run.scheme?.id ?? "",
    scenario: String(run.scenario?.kind ?? ""),
    fidelity: run.fidelity,
    level: run.level,
    summary: run.verdict?.summary ?? "",
    findings: (run.verdict?.findings ?? []).slice(0, 8).map((f) => ({
      id: f.id,
      topic: f.topic,
      tag: f.tag,
      said: f.said,
    })),
  };
}

export function read(): LabDoc | null {
  const saved = carry.saved();
  if (!saved) return null;
  return { ...saved, plotted: lab.get().plotted, last_run: lastRun };
}

/** A run of the page's own has finished: its summary goes to the session, the run to the store. */
function ranHere(): void {
  const s = lab.get();
  const answer = s.run.status === "done" ? s.run.answer : null;
  if (!answer || answer === seen) return;
  seen = answer;
  if (answer === fromSession || s.run.note?.startsWith("This is the run kept")) return;
  lastRun = summaryOf(answer, "page");
  void control.keep("session-run", "last", { name: "last run", run: trimmed(answer) }).catch(() => undefined);
}

/** The run the agent made, brought from the store and shown as the lab's run. */
async function showRun(said: LastRun): Promise<void> {
  let run: Run;
  try {
    run = (await control.bring<{ run: Run }>("session-run", "last")).run;
  } catch {
    return;
  }
  if (!run?.series) return;
  fromSession = seen = run;
  const note = `Run by your agent${said.summary ? `: ${said.summary}` : "."}`;
  // Shown where the user is looking: the tab, the stretch of time and the block chosen stay theirs.
  lab.set({ run: { ...idleRun(), status: "done", answer: run, note } });
  cursor.t = Math.min(cursor.t || Infinity, run.series.t[run.series.t.length - 1] ?? 0);
  cursor.again();
}

/** The scheme the agent left: the preset by its id as tuned for this design, with its edits. */
function schemeOf(s: LabState, doc: LabDoc): Partial<LabState> | null {
  const found = s.presets?.schemes.find((x) => x.id === doc.scheme);
  if (!found) return null;
  const edits = doc.edits && (doc.edits as Scheme).id === found.id ? (doc.edits as Scheme) : null;
  const scheme = copy(edits ?? found);
  if (same(scheme, s.scheme) && s.tuned?.id === found.id) return null;
  const run = { ...s.run, stale: !!s.run.answer, refused: null };
  // The block the user has open stays open where the scheme still has it.
  const selected = scheme.blocks.some((b) => b.name === s.selected) ? s.selected : null;
  return { scheme, tuned: copy(found), selected, pins: {}, run };
}

/** The test, its figures, the fidelity and the probes the agent left, where they differ. */
function testOf(s: LabState, doc: LabDoc): Partial<LabState> {
  const presets = s.presets!;
  const change: Partial<LabState> = {};
  const offered = presets.scenarios.some((x) => x.kind === doc.scenario);
  if (doc.scenario && doc.scenario !== s.scenario && offered) change.scenario = doc.scenario;
  if (doc.figures && !same(doc.figures, s.figures)) change.figures = copy(doc.figures);
  const fidelity = doc.fidelity && presets.fidelities.includes(doc.fidelity) ? doc.fidelity : s.fidelity;
  if (fidelity !== s.fidelity) change.fidelity = fidelity;
  if ("plotted" in doc && !same(doc.plotted ?? null, s.plotted)) change.plotted = doc.plotted ?? null;
  return change;
}

/** What the agent wrote, put in place in the lab as it stands. */
export function adopt(doc: LabDoc): void {
  const s = lab.get();
  if (!s.presets) {
    if (readSaved(doc)) carry.open({ ...doc, key: designOfPage().key });
    return;
  }
  const scheme = schemeOf(s, doc);
  const change = { ...scheme, ...testOf(s, doc) };
  if (Object.keys(change).length) lab.set(change);
  if (scheme) askLoops(0);
  const run = doc.last_run ?? null;
  const newer = !!run && run.at !== lastRun?.at;
  lastRun = run;
  if (newer && run.source === "agent") void showRun(run);
}

goLive({ read, subscribe: (heard) => lab.subscribe(() => (ranHere(), heard())), adopt });
