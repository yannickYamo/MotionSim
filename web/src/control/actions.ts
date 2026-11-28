// What the lab does when asked: take a scheme, change a figure of it, run a test and follow
// it as it comes, ask for the linear analysis. Each changes the store; the views draw it.

import { openingOf } from "./opening";
import { Unreachable, UNREACHABLE } from "../api/answers";
import { aborted, control, problemOf } from "./client";
import { stop } from "./play";
import { cursor, idleRun, lab } from "./store";
import type { LabState, Problem, Tab } from "./store";
import type { Block, Presets, Run, Scheme, Value } from "./types";
import { carry } from "./carry";
import { designOf } from "./request";
import type { ControlSaved } from "./carry";
import { outOfBounds } from "./problemwords";

const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

const KEPT = "motionsim.control.v1";

interface Remembered {
  open?: boolean;
  tab?: Tab;
  scenario?: string;
  fidelity?: string;
  learn?: boolean;
}

export function remembered(): Remembered {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEPT) ?? "{}");
    return typeof raw === "object" && raw !== null ? raw : {};
  } catch {
    return {};
  }
}

export function remember(change: Remembered): void {
  try {
    localStorage.setItem(KEPT, JSON.stringify({ ...remembered(), ...change }));
  } catch {
    /* it lasts this visit only */
  }
}

/** The scheme edited is no longer the one it started as. */
export const edited = (s: LabState): boolean => !!s.scheme && !same(s.scheme, s.tuned);

/** The lab opened on a design. On the design it was open on before, everything is as it was
 *  left. On another design (a new part, other conditions, a Reset) it starts from the scheme
 *  recommended for that design, as tuned for it: edits made on the design before are not
 *  carried. A setup opened brings its own scheme, edits and test, the edits only onto the
 *  design they were made on. */
export function begin(key: string, design: Record<string, unknown>, presets: Presets): void {
  const waiting = carry.take();
  if (waiting === "fresh") lab.reset();
  const s = lab.get();
  if (!waiting && s.designKey === key && s.presets) return;
  const hadRun = !!s.run.answer && !waiting;
  const saved = waiting && waiting !== "fresh" ? waiting : null;
  const start = saved ? fromSaved(saved, key, presets) : schemeFor(s, presets);
  lab.set({
    phase: "ready",
    problem: null,
    designKey: key,
    design,
    presets,
    ...start,
    ...settingsFor(s, presets, saved),
    learn: learning(s),
    ...(saved ? { figures: saved.figures, plant: saved.plant ?? {} } : {}),
    run: saved ? idleRun() : { ...s.run, stale: hadRun },
    before: saved ? null : s.before,
    plotted: null,
    pins: {},
    view: null,
    selected: null,
    loops: { status: "idle", answer: null, refused: null, fault: null },
    library: { ...s.library, status: "idle", sweep: null },
  });
  fitTest();
  askLoops(0);
  // What was run was of the design before: it is run again for the design as it now stands.
  if (hadRun) void runNow();
}

/** The scheme the lab opens on for a design it was not open on: the one recommended for it,
 *  as tuned for it. Said where edits of the design before are left behind. */
function schemeFor(s: LabState, presets: Presets): Pick<LabState, "scheme" | "tuned" | "said"> {
  const found = presets.schemes.find((x) => x.id === presets.chosen) ?? presets.schemes[0];
  const tuned = found ? copy(found) : null;
  const left = s.designKey && edited(s);
  const said = left
    ? `The design changed, so the lab starts again from ${tuned?.label ?? "the scheme recommended for it"}, as ` +
      "tuned for it. The edits made on the design before were not carried."
    : null;
  return { tuned, scheme: tuned && copy(tuned), said };
}

/** The scheme a setup carried: its own as tuned for this design, with its edits where they
 *  were made on this very design. */
function fromSaved(saved: ControlSaved, key: string, presets: Presets): Pick<LabState, "scheme" | "tuned" | "said"> {
  const found = presets.schemes.find((x) => x.id === saved.scheme);
  const base = found ?? presets.schemes.find((x) => x.id === presets.chosen) ?? presets.schemes[0];
  const tuned = base ? copy(base) : null;
  const edits = saved.edits as Scheme | null;
  const fits = !!edits && !!found && edits.id === found.id && saved.key === key;
  let said: string | null = null;
  if (fits) said = `The setup's edits to ${found.label} are carried: the scheme is as it was saved, not as tuned.`;
  else if (edits && found) said = `The setup's edits to ${found.label} were made on another design, and were left out.`;
  else if (saved.scheme && !found) said = "The scheme the setup names is not offered for this design.";
  return { tuned, scheme: fits ? copy(edits) : tuned && copy(tuned), said };
}

/** The test, the fidelity and the tab: as a setup carried them, as they were left in this
 *  visit, or in the last. */
function settingsFor(
  s: LabState,
  presets: Presets,
  saved: ControlSaved | null,
): Pick<LabState, "scenario" | "fidelity" | "tab"> {
  const kept = remembered();
  const scenario = saved?.scenario || (s.designKey ? s.scenario : kept.scenario);
  const fidelity = saved?.fidelity || (s.designKey ? s.fidelity : kept.fidelity);
  return {
    scenario: presets.scenarios.find((x) => x.kind === scenario)?.kind ?? presets.scenarios[0]?.kind ?? "hold",
    fidelity: presets.fidelities.find((f) => f === fidelity) ?? presets.fidelities[0] ?? "switched",
    tab: s.designKey ? s.tab : (kept.tab ?? "run"),
  };
}

/** Whether the lab teaches as it is pointed at: as it was left in this visit, or in the last. */
const learning = (s: LabState): boolean => (s.designKey ? s.learn : !!remembered().learn);

/** The tests a scheme takes: the engine's own list where it sends one; else those whose
 *  command the scheme's wiring takes (a torque step needs a scheme that is told a torque),
 *  less any the engine has refused for it. */
export function testsFor(s: LabState, scheme: Scheme | null = s.scheme): string[] {
  const all = s.presets?.scenarios ?? [];
  if (!scheme) return all.map((x) => x.kind);
  const listed = (scheme as { tests?: unknown }).tests;
  if (Array.isArray(listed) && listed.length) {
    const named = new Set(listed.map(String));
    const offered = all.filter((x) => named.has(x.kind)).map((x) => x.kind);
    if (offered.length) return offered;
  }
  const taken = new Set([...scheme.blocks.flatMap((b) => Object.values(b.inputs)), ...scheme.actuation.wires]);
  const refused = new Set(s.refusedTests[scheme.id] ?? []);
  const fits = all.filter((x) => (!x.needs || taken.has(x.needs)) && !refused.has(x.kind)).map((x) => x.kind);
  return fits.length ? fits : all.map((x) => x.kind);
}

/** The test in the lab is one the scheme takes: where it is not, the first that it does. */
export function fitTest(): void {
  const s = lab.get();
  const offered = testsFor(s);
  if (!offered.length || offered.includes(s.scenario)) return;
  lab.set({ scenario: offered[0], plotted: null, pins: {} });
}

/** Take another scheme: a preset as tuned for this design, or one that was kept. Where a test
 *  has been run, it is run again on the new scheme once the choosing has paused. */
export function takeScheme(scheme: Scheme): void {
  const s = lab.get();
  const tuned = s.presets?.schemes.find((x) => x.id === scheme.id) ?? scheme;
  lab.set({
    scheme: copy(scheme),
    tuned: copy(tuned),
    selected: null,
    run: { ...s.run, stale: !!s.run.answer, refused: null },
    plotted: null,
    pins: {},
    said: null,
  });
  fitTest();
  askLoops(0);
  rerunSoon();
}

let rerun: ReturnType<typeof setTimeout> | undefined;
let loopsTimer = 0;
let loopsAsked: AbortController | null = null;

const changed = (s: LabState, scheme: Scheme): Partial<LabState> => ({
  scheme,
  run: { ...s.run, stale: !!s.run.answer, refused: null },
  loops: { ...s.loops, refused: null },
});

/** Change one figure of one block. A figure past the bounds the engine holds it to is kept as
 *  typed and said at its field in words; nothing is asked of the engine with it. */
export function setParam(block: string, name: string, value: Value): void {
  const s = lab.get();
  if (!s.scheme) return;
  const scheme = copy(s.scheme);
  const b = scheme.blocks.find((x) => x.name === block);
  if (!b) return;
  b.params = { ...b.params, [name]: value };
  const field = `scheme.blocks.${block}.${name}`;
  const wrong = outOfBounds(
    field,
    s.presets?.blocks[b.kind]?.params.find((p) => p.name === name),
    value,
  );
  if (wrong) {
    clearTimeout(loopsTimer);
    clearTimeout(rerun);
    loopsAsked?.abort();
    lab.set({ ...changed(s, scheme), loops: { ...s.loops, status: "done", refused: wrong } });
    return;
  }
  lab.set(changed(s, scheme));
  // The loops answer a gain dragged within 400 ms: asked 180 ms after the last change.
  askLoops(180);
  rerunSoon();
}

/** Where a test has been run, a figure changed runs it again once the changing has paused:
 *  what the change costs is read without another press. */
export function rerunSoon(wait = 700): void {
  clearTimeout(rerun);
  if (!lab.get().run.answer) return;
  rerun = setTimeout(() => void runNow(), wait);
}

let frame = 0;
let next: (() => void) | null = null;

/** A figure dragged on its block: taken once a frame at most, however fast the pointer moves. */
export function nudge(block: string, name: string, value: Value): void {
  next = () => setParam(block, name, value);
  frame ||= requestAnimationFrame(() => {
    frame = 0;
    next?.();
    next = null;
  });
}

/** The figure a block's parameter had when the scheme was tuned for this design: the
 *  preset's, or where the preset leaves it out, the registry's default. Undefined for neither. */
export function tunedValue(s: LabState, block: string, name: string): Value | undefined {
  const b = s.tuned?.blocks.find((x) => x.name === block);
  const own = b?.params[name];
  if (own !== undefined) return own;
  const kind = s.scheme?.blocks.find((x) => x.name === block)?.kind ?? "";
  return s.presets?.blocks[kind]?.params.find((p) => p.name === name)?.default;
}

export function resetParam(block: string, name: string): void {
  const value = tunedValue(lab.get(), block, name);
  if (value !== undefined) setParam(block, name, value);
}

/** The kernel's stage, whose readings a block may take in another's place. */
const STAGE = "inverter";

/** The kinds a block could be replaced with: those that take no input the block has not
 *  got, and give every output the rest of the scheme takes from it. */
export function replacements(s: LabState, block: Block): string[] {
  if (!s.presets || !s.scheme) return [];
  const taken = [...s.scheme.blocks.flatMap((b) => Object.values(b.inputs)), ...s.scheme.actuation.wires]
    .filter((w) => w.startsWith(`${block.name}.`))
    .map((w) => w.slice(block.name.length + 1));
  const has = new Set(Object.keys(block.inputs));
  const stage = new Set(s.presets.sources.map((p) => p.name));
  return Object.values(s.presets.blocks)
    .filter((k) => k.kind !== block.kind)
    .filter((k) => k.inputs.every((i) => has.has(i.name) || stage.has(`${STAGE}.${i.name}`)))
    .filter((k) => taken.every((o) => k.outputs.some((p) => p.name === o)))
    .map((k) => k.kind);
}

/** Put a block of another kind in a block's place, wired as it was, with that kind's own
 *  starting figures. */
export function replaceBlock(name: string, kind: string): void {
  const s = lab.get();
  const to = s.presets?.blocks[kind];
  if (!s.scheme || !to) return;
  const scheme = copy(s.scheme);
  const b = scheme.blocks.find((x) => x.name === name);
  if (!b) return;
  b.kind = kind;
  // An input the block had keeps its wire; one it lacks takes the stage's own reading of that
  // name (a shunt's window, the DC link's current).
  b.inputs = Object.fromEntries(to.inputs.map((i) => [i.name, b.inputs[i.name] ?? `${STAGE}.${i.name}`]));
  b.params = {};
  b.sources = {};
  lab.set(changed(s, scheme));
  askLoops(0);
  rerunSoon();
}

/** A figure of the test as it is sent: a number where it reads as one, else as typed, for
 *  the engine to say what is wrong with it at its box. */
const sent = (raw: string): Value => (raw.trim() !== "" && Number.isFinite(Number(raw)) ? Number(raw) : raw);

/** The request a run is asked with: the design, the scheme as edited, the test. */
export function runRequest(s: LabState, more: Record<string, unknown> = {}): Record<string, unknown> {
  const typed = Object.entries(s.figures[s.scenario] ?? {}).filter(([, v]) => v.trim() !== "");
  return {
    ...designOf(s),
    scheme: s.scheme,
    scenario: { kind: s.scenario, ...Object.fromEntries(typed.map(([k, v]) => [k, sent(v)])) },
    fidelity: s.fidelity,
    // About twice the scope's width: a lab run is sent whole, a longer one thinned with what
    // it reached kept (report.series).
    points: SCOPE_POINTS,
    ...more,
  };
}

export const SCOPE_POINTS = 2400;

let running: AbortController | null = null;

function finished(answer: Run, note: string | null): void {
  // A run with an event (a trip, a step) opens on the stretch it changes, the cursor on its
  // largest phase current; any other is shown whole, the cursor where it was or at the end. It
  // draws itself in once (the scope's own), and is played only when Play is pressed.
  const open = openingOf(answer);
  lab.set({ run: { ...idleRun(), status: "done", answer, note }, ...(open ? { view: open.view } : {}) });
  cursor.t = open ? open.t : Math.min(cursor.t || Infinity, answer.series.t[answer.series.t.length - 1] ?? 0);
  cursor.again();
}

/** Take a run that was kept as the run in the lab: its scheme, its test and its figures, as
 *  they were kept. Its traces are the thinned ones, and it has no stretch point by point. */
export function takeRun(answer: Run, name: string): void {
  running?.abort();
  clearTimeout(rerun);
  const s = lab.get();
  const kind = String(answer.scenario?.kind ?? s.scenario);
  if (answer.scheme?.blocks) takeScheme(answer.scheme);
  clearTimeout(rerun);
  lab.set({
    scenario: s.presets?.scenarios.some((x) => x.kind === kind) ? kind : s.scenario,
    fidelity: s.presets?.fidelities.includes(answer.fidelity) ? answer.fidelity : s.fidelity,
    run: {
      ...idleRun(),
      status: "done",
      answer,
      note: `This is the run kept as ${name}, with its traces as they were thinned to keep it.`,
    },
    before: null,
    view: null,
    plotted: null,
    tab: "run",
  });
  cursor.t = Math.min(cursor.t || Infinity, answer.series.t[answer.series.t.length - 1] ?? 0);
  cursor.again();
}

function failed(e: unknown, earlier: Run | null): void {
  const refused = problemOf(e);
  const fault = refused
    ? null
    : e instanceof Unreachable
      ? UNREACHABLE
      : `The run did not finish: ${(e as Error).message}.`;
  // The run before stays on the page, said to be of the scheme before. A test the engine says
  // this scheme cannot take is not offered for it again.
  lab.set((s) => {
    const id = s.scheme?.id ?? "";
    const whole = refused && (refused.field === "scenario" || refused.field === "scenario.kind");
    const refusedTests =
      whole && id ? { ...s.refusedTests, [id]: [...(s.refusedTests[id] ?? []), s.scenario] } : s.refusedTests;
    return {
      refusedTests,
      run: { ...idleRun(), status: earlier ? "done" : "idle", answer: earlier, stale: !!earlier, refused, fault },
    };
  });
}

/** Run the test under the scheme as it stands, drawing what comes as it comes. A stream
 *  that drops on the way is asked again whole, and said to have been. */
export async function runNow(): Promise<void> {
  running?.abort();
  const mine = (running = new AbortController());
  const s = lab.get();
  const earlier = s.run.answer;
  const before = earlier && earlier.scenario.kind === s.scenario ? earlier : s.before;
  const body = runRequest(s);
  stop();
  lab.set({ run: { ...idleRun(), status: "running", answer: earlier }, before, view: null });
  const onProbe = (p: { progress: number; series: Run["series"] }) => {
    if (running !== mine) return;
    lab.set((now) => ({ run: { ...now.run, progress: p.progress, partial: p.series } }));
  };
  try {
    finished(await control.runStreamed(body, onProbe, mine.signal), null);
  } catch (e) {
    if (aborted(e) || running !== mine) return;
    if (problemOf(e) || e instanceof Unreachable) return failed(e, earlier);
    try {
      const said = "The run's progress was lost on the way, so it was asked again whole.";
      finished(await control.run(body, mine.signal), said);
    } catch (again) {
      if (!aborted(again) && running === mine) failed(again, earlier);
    }
  }
}

/** Stop whatever run is under way or waiting to start, and say none is: a run is about to be
 *  put in the lab from elsewhere (a comparison's). */
export function hush(): void {
  running?.abort();
  clearTimeout(rerun);
}

/** Stop a run under way: the engine stops at its next step, and the run before stays. */
export function cancelRun(): void {
  clearTimeout(rerun);
  running?.abort();
  running = null;
  const s = lab.get();
  if (s.run.status !== "running") return;
  lab.set({
    run: { ...idleRun(), status: s.run.answer ? "done" : "idle", answer: s.run.answer, stale: !!s.run.answer },
  });
}

/** Ask for the linear analysis of the scheme as it stands, a moment after the last change. */
export function askLoops(wait = 350): void {
  clearTimeout(loopsTimer);
  loopsTimer = window.setTimeout(() => void loopsNow(), wait);
}

async function loopsNow(): Promise<void> {
  loopsAsked?.abort();
  const mine = (loopsAsked = new AbortController());
  const s = lab.get();
  if (!s.scheme) return;
  lab.set({ loops: { ...s.loops, status: "asking" } });
  try {
    const answer = await control.loops({ ...designOf(s), scheme: s.scheme }, mine.signal);
    if (loopsAsked === mine) lab.set({ loops: { status: "done", answer, refused: null, fault: null } });
  } catch (e) {
    if (aborted(e) || loopsAsked !== mine) return;
    const refused = problemOf(e);
    const fault = refused ? null : (e as Error).message;
    lab.set((now) => ({ loops: { status: "done", answer: refused ? now.loops.answer : null, refused, fault } }));
  }
}

/** What the engine said is wrong with one figure, by the name it gives the figure. */
export function problemAt(s: LabState, field: string): Problem | null {
  for (const p of [s.run.refused, s.loops.refused]) if (p && p.field === field) return p;
  return null;
}

/** A refusal that names no figure the lab shows a box for: said above the run. */
export function problemAbove(s: LabState): Problem | null {
  const p = s.run.refused ?? s.loops.refused;
  if (!p) return null;
  const blocks = s.scheme?.blocks ?? [];
  const atParam = blocks.some((b) => Object.keys(b.params).some((n) => p.field === `scheme.blocks.${b.name}.${n}`));
  const kinds = s.presets?.scenarios.find((x) => x.kind === s.scenario)?.fields ?? [];
  const atFigure = p.field === "scenario.kind" || kinds.some((f) => p.field === `scenario.${f.name}`);
  return atParam || atFigure ? null : p;
}

export function setTab(tab: Tab): void {
  lab.set({ tab });
  remember({ tab });
}

/** Another test: the answer is marked as of the test before, and where one was run, the new
 *  test is run once the changing has paused. So are the changes below, wherever they are made:
 *  in the test's settings or on the reference block's inspector. */
export function setScenario(kind: string): void {
  lab.set((s) => ({
    scenario: kind,
    run: { ...s.run, refused: null, stale: !!s.run.answer },
    plotted: null,
    pins: {},
  }));
  remember({ scenario: kind });
  rerunSoon();
}

/** A figure of the test, kept as typed. */
export function setFigure(name: string, raw: string): void {
  lab.set((s) => ({
    figures: { ...s.figures, [s.scenario]: { ...s.figures[s.scenario], [name]: raw } },
    run: {
      ...s.run,
      refused: s.run.refused?.field === `scenario.${name}` ? null : s.run.refused,
      stale: !!s.run.answer,
    },
  }));
  rerunSoon();
}

/** A figure of the test back to the engine's own: no longer typed. */
export function resetFigure(name: string): void {
  lab.set((s) => {
    const own = { ...s.figures[s.scenario] };
    delete own[name];
    return { figures: { ...s.figures, [s.scenario]: own }, run: { ...s.run, stale: !!s.run.answer } };
  });
  rerunSoon();
}

export function setFidelity(fidelity: string): void {
  lab.set((s) => ({ fidelity, run: { ...s.run, stale: !!s.run.answer } }));
  remember({ fidelity });
  rerunSoon();
}

/** Draw the wires of one bus through time together, or take out again what the last press
 *  on it added: a trace drawn before the press (a usual one) stays. Where every line was
 *  already drawn and this press added none, they are all taken out. Says whether they are
 *  drawn now. */
export function pinWires(wires: string[], usual: string[]): boolean {
  const s = lab.get();
  const now = s.plotted ?? usual;
  const key = [...wires].sort().join(",");
  const added = s.pins[key];
  const pins = { ...s.pins };
  delete pins[key];
  if (added) {
    lab.set({ plotted: now.filter((w) => !added.includes(w)), pins });
    return false;
  }
  const missing = wires.filter((w) => !now.includes(w));
  if (!missing.length) {
    lab.set({ plotted: now.filter((w) => !wires.includes(w)), pins });
    return false;
  }
  lab.set({ plotted: [...now, ...missing], pins: { ...pins, [key]: missing } });
  return true;
}

/** Take these wires out of the scope, whoever drew them: a strip's own way out. */
export function unplot(wires: string[], usual: string[]): void {
  const s = lab.get();
  const now = s.plotted ?? usual;
  lab.set({ plotted: now.filter((w) => !wires.includes(w)) });
}

/** Whether a block's figures are no longer the ones the scheme was tuned with. */
export const blockEdited = (s: LabState, name: string): boolean => {
  const now = s.scheme?.blocks.find((b) => b.name === name);
  const was = s.tuned?.blocks.find((b) => b.name === name);
  return !!now && !!was && !same([now.kind, now.params], [was.kind, was.params]);
};

/** Draw a wire through time, or stop drawing it. */
export function togglePlotted(wire: string, usual: string[]): void {
  lab.set((s) => {
    const now = s.plotted ?? usual;
    return { plotted: now.includes(wire) ? now.filter((w) => w !== wire) : [...now, wire] };
  });
}

// A setup saved from the page carries the lab as it stands.
carry.register(() => {
  const s = lab.get();
  if (!s.scheme) return null;
  return {
    v: 1,
    key: s.designKey,
    scheme: s.scheme.id,
    edits: edited(s) ? copy(s.scheme) : null,
    scenario: s.scenario,
    figures: copy(s.figures),
    fidelity: s.fidelity,
    plant: copy(s.plant),
  };
});
