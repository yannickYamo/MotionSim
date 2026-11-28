// The library of explorations and the store of kept work: what is asked of the engine for
// them, and what a press on one of them does to the lab.

import { aborted, control, Missing } from "./client";
import { runNow, setParam, setTab, takeRun, takeScheme } from "./actions";
import { designOf } from "./request";
import { lab } from "./store";
import type { Exploration, Kept, Run, Scheme, Sweep, Variant } from "./types";

const copy = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

/** Ask what explorations there are for this design, once for each design. */
export async function openLibrary(): Promise<void> {
  const s = lab.get();
  if (s.library.status !== "idle") return;
  lab.set({ library: { ...s.library, status: "asking" } });
  try {
    const found = await control.explorations(designOf(s));
    const list = found.explorations ?? [];
    lab.set((now) => ({ library: { ...now.library, status: "done", list, words: found.reads ?? {} } }));
  } catch (e) {
    const missing = e instanceof Missing;
    const problem = missing ? null : (e as Error).message;
    lab.set((now) => ({ library: { ...now.library, status: missing ? "missing" : "fault", problem } }));
  }
}

let sweeping: AbortController | null = null;

/** A step of a sweep as it comes: the variant just worked out, under the name the engine
 *  gives it. */
const variantOf = (probe: unknown): Variant | null => {
  const p = (probe && typeof probe === "object" ? probe : {}) as { result?: unknown; variant?: unknown };
  const found = [p.result, p.variant, probe].find((v) => v && typeof v === "object" && "label" in v);
  return (found as Variant | undefined) ?? null;
};

/** Run an exploration: one run for each value it varies, each shown as it is worked out. */
export async function runSweep(x: Exploration): Promise<void> {
  sweeping?.abort();
  const mine = (sweeping = new AbortController());
  const s = lab.get();
  const begun: Sweep = { vary: x.vary, variants: [], baseline: null, said: [] };
  lab.set({ library: { ...s.library, open: x.id, sweep: begun, running: true, done: 0, problem: null } });
  // The exploration is the engine's own: its name is all the engine needs beside the design.
  const body = { ...designOf(s), exploration: x.id };
  const onProbe = (probe: unknown) => {
    const v = variantOf(probe);
    if (!v || sweeping !== mine) return;
    lab.set((now) => {
      const sweep = now.library.sweep ?? begun;
      const next = { ...sweep, variants: [...sweep.variants, v] };
      return { library: { ...now.library, sweep: next, done: next.variants.length } };
    });
  };
  try {
    const sweep = await control.sweep(body, onProbe, mine.signal);
    if (sweeping === mine) lab.set((now) => ({ library: { ...now.library, sweep, running: false } }));
  } catch (e) {
    if (aborted(e) || sweeping !== mine) return;
    const problem =
      e instanceof Missing ? "This build of the engine cannot run explorations yet." : (e as Error).message;
    lab.set((now) => ({ library: { ...now.library, running: false, problem } }));
  }
}

export function cancelSweep(): void {
  sweeping?.abort();
  sweeping = null;
  lab.set((s) => ({ library: { ...s.library, running: false } }));
}

/** The scheme an exploration starts from: a preset by its name, or a scheme written out. */
function schemeOf(given: string | Scheme | undefined): Scheme | null {
  const s = lab.get();
  if (typeof given === "string") return s.presets?.schemes.find((x) => x.id === given) ?? null;
  return given ?? s.scheme;
}

/** Where in the lab a varied figure lives, if the lab holds it: a figure of a block, or of the test. */
const placeOf = (path: string): { block?: [string, string]; figure?: string } => {
  const parts = path.replace(/^scheme\./, "").split(".");
  if (parts[0] === "blocks" && parts.length === 3) return { block: [parts[1], parts[2]] };
  return parts[0] === "scenario" && parts.length === 2 ? { figure: parts[1] } : {};
};

/** Whether a variant can be taken into the lab: its scheme is one the lab has, and what was
 *  varied is a figure of a block or of the test, or the scheme itself. */
export function opens(x: Exploration, v: Variant): boolean {
  if (!schemeOf(v.scheme ?? x.scheme)) return false;
  const place = placeOf(x.vary.path);
  return x.vary.path === "scheme" || !!place.block || !!place.figure;
}

/** Take one variant of an exploration into the lab: its scheme, the value it varied, its
 *  test, and run it there. */
export function openVariant(x: Exploration, v: Variant): void {
  const scheme = schemeOf(v.scheme ?? x.scheme);
  if (scheme) takeScheme(scheme);
  const place = placeOf(x.vary.path);
  if (place.block && v.value !== undefined) setParam(place.block[0], place.block[1], v.value);
  const { kind, ...figures } = x.scenario;
  const typed = Object.fromEntries(Object.entries(figures).map(([k, f]) => [k, String(f)]));
  if (place.figure && v.value !== undefined) typed[place.figure] = String(v.value);
  lab.set((s) => ({
    scenario: typeof kind === "string" ? kind : s.scenario,
    figures: typeof kind === "string" ? { ...s.figures, [kind]: typed } : s.figures,
    fidelity: x.fidelity || s.fidelity,
  }));
  setTab("run");
  void runNow();
}

/** A name as the store takes one for a document: letters, digits and dashes. */
export const idOf = (name: string): string =>
  name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[^a-z0-9]+/, "")
    .slice(0, 60) || "unnamed";

async function listed(said: string | null = null): Promise<void> {
  try {
    const [schemes, runs] = await Promise.all([control.kept("control-scheme"), control.kept("control-run")]);
    lab.set({ kept: { schemes, runs, status: "done", said } });
  } catch (e) {
    lab.set((s) => ({ kept: { ...s.kept, status: "fault", said: (e as Error).message } }));
  }
}

export const openKept = (): Promise<void> => listed(lab.get().kept.said);

/** A run as it is kept: its figures whole, its traces thinned and its point-by-point stretch
 *  left out, so that it stays within what one document may be. */
export function trimmed(run: Run): Run {
  const every = Math.max(1, Math.ceil(run.series.t.length / 250));
  const thin = (a: number[]) => a.filter((_, k) => k % every === 0);
  const wires = Object.fromEntries(Object.entries(run.series.wires).map(([k, v]) => [k, thin(v)]));
  const thermalEvery = Math.max(1, Math.ceil(run.thermal.t.length / 250));
  const cool = (a: number[]) => a.filter((_, k) => k % thermalEvery === 0);
  const kept = copy({ ...run, waveform: null, series: { t: thin(run.series.t), wires } });
  kept.thermal = { ...run.thermal, t: cool(run.thermal.t), tj_from_start: cool(run.thermal.tj_from_start) };
  delete (kept as unknown as Record<string, unknown>).switches;
  return kept;
}

async function kept(work: () => Promise<unknown>, said: string): Promise<void> {
  try {
    await work();
    await listed(said);
  } catch (e) {
    lab.set((s) => ({ kept: { ...s.kept, said: `Not done: ${(e as Error).message}.` } }));
  }
}

export function keepScheme(name: string): Promise<void> {
  const scheme = lab.get().scheme;
  if (!scheme) return Promise.resolve();
  return kept(() => control.keep("control-scheme", idOf(name), { name, scheme }), `The scheme is kept as ${name}.`);
}

export function keepRun(name: string): Promise<void> {
  const run = lab.get().run.answer;
  if (!run) return Promise.resolve();
  return kept(
    () => control.keep("control-run", idOf(name), { name, run: trimmed(run) }),
    `The run is kept as ${name}.`,
  );
}

export const dropKept = (kind: string, item: Kept): Promise<void> =>
  kept(() => control.drop(kind, item.id), `${item.name || item.id} is no longer kept.`);

export async function bringScheme(item: Kept): Promise<void> {
  await kept(
    async () => {
      const doc = await control.bring<{ scheme: Scheme }>("control-scheme", item.id);
      if (!doc.scheme?.blocks) throw new Error("what is kept under that name is not a scheme");
      takeScheme(doc.scheme);
    },
    `${item.name || item.id} is the scheme in the lab now.`,
  );
}

/** A kept run comes back as the run to compare with: the A of an A/B. */
export async function bringRun(item: Kept): Promise<void> {
  await kept(
    async () => {
      const doc = await control.bring<{ run: Run }>("control-run", item.id);
      if (!doc.run?.series) throw new Error("what is kept under that name is not a run");
      lab.set({ held: { name: item.name || item.id, run: doc.run } });
    },
    `${item.name || item.id} is held as run A: the next runs are set beside it.`,
  );
}

/** A kept run comes back as the run in the lab: its scheme, its test and its figures. */
export async function openRun(item: Kept): Promise<void> {
  const name = item.name || item.id;
  await kept(async () => {
    const doc = await control.bring<{ run: Run }>("control-run", item.id);
    if (!doc.run?.series) throw new Error("what is kept under that name is not a run");
    takeRun(doc.run, name);
  }, `${name} is open as the run, under Run and cost.`);
}

/** The scheme as a file of JSON, handed to the browser to save. */
export function exportScheme(): void {
  const scheme = lab.get().scheme;
  if (!scheme) return;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([JSON.stringify(scheme, null, 2)], { type: "application/json" }));
  link.download = `motionsim-scheme-${idOf(scheme.id)}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 4000);
}
