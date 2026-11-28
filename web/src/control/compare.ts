// Schemes set side by side: the one recommended for the design and the alternatives that
// differ from it the most, each run as tuned on the same design and the same test, read
// figure by figure, the best of each row marked, and one line that says which to choose and
// why, in the figures themselves. Every figure is the engine's: nothing here models anything.

import { written } from "./figures";
import { sig } from "../format";
import { control, aborted, problemOf } from "./client";
import { runRequest, testsFor } from "./actions";
import { intoLab } from "./taking";
export { adopt } from "./taking";
import { toneOf } from "./findings";
import { lab } from "./store";
import type { Compared, LabState } from "./store";
import type { Presets, Run, Scheme } from "./types";
import { Unreachable, UNREACHABLE } from "../api/answers";

/** The most schemes a comparison holds: the recommended one and four others at most. */
export const MOST = 5;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** What a comparison was run on: change any of it, and the comparison is of before. */
export const compareKey = (s: LabState): string =>
  JSON.stringify([s.designKey, s.scenario, s.figures[s.scenario] ?? {}, s.fidelity]);

/** The parts of a scheme that make it another way of doing the work: how the rotor's angle is
 *  known, which current regulator, how often it is updated, whether it has a speed loop. */
function traitsOf(scheme: Scheme, presets: Presets) {
  const kinds = scheme.blocks.map((b) => b.kind);
  const sensor = kinds.find((k) => k.startsWith("observer_")) ?? (kinds.includes("position_sensing") ? "sensor" : "");
  const regulator = kinds.find((k) => presets.blocks[k]?.role === "inner_regulator") ?? "";
  return {
    sensored: sensor === "sensor",
    sensor,
    regulator,
    update: scheme.timing.update,
    speed: kinds.includes("speed_pi") || kinds.includes("speed_adrc"),
    shape: kinds.join(","),
  };
}

/** The alternatives to set beside the scheme recommended: those that take the same test and
 *  answer the same command (a speed, or a torque), chosen to differ from it the most: another
 *  way of knowing the angle in the same class, the other class (a sensor or none), another
 *  current regulator, then whatever is left with a wiring of its own; three at most. */
export function alternativesFor(presets: Presets, from: string, test: string, many = 3): string[] {
  const first = presets.schemes.find((s) => s.id === from);
  if (!first) return [];
  const own = traitsOf(first, presets);
  const takes = (s: Scheme) => !s.tests?.length || s.tests.includes(test);
  const pool = presets.schemes
    .filter((s) => s.id !== from && takes(s) && !s.aside)
    .map((s) => ({ id: s.id, t: traitsOf(s, presets) }))
    .filter((x) => x.t.speed === own.speed);
  const picked: typeof pool = [];
  const take = (ok: (x: (typeof pool)[number]) => boolean) => {
    const found = pool.find((x) => !picked.includes(x) && ok(x));
    if (found && picked.length < many) picked.push(found);
  };
  take((x) => x.t.sensored === own.sensored && x.t.sensor !== own.sensor);
  take((x) => x.t.sensored !== own.sensored);
  take((x) => [own, ...picked.map((p) => p.t)].every((t) => t.regulator !== x.t.regulator));
  const shapes = () => new Set([own.shape + own.update, ...picked.map((p) => p.t.shape + p.t.update)]);
  for (const x of pool) if (picked.length < many && !shapes().has(x.t.shape + x.t.update)) picked.push(x);
  for (const x of pool) if (picked.length < many && !picked.includes(x)) picked.push(x);
  return picked.map((x) => x.id);
}

/** The speed loop's bandwidth where the regulator is given one (active disturbance rejection). */
const givenBand = (scheme: Scheme | undefined): number | null =>
  num(scheme?.blocks.find((b) => b.kind === "speed_adrc")?.params.bandwidth);

/** The schemes a comparison starts with: the recommended one, the one in the lab where that is
 *  another, then the alternatives to the recommended one. Only schemes that take the test. */
export function startingIds(s: LabState): string[] {
  const presets = s.presets;
  if (!presets) return [];
  const takes = (id: string) => {
    const scheme = presets.schemes.find((x) => x.id === id);
    return !!scheme && testsFor(s, scheme).includes(s.scenario);
  };
  const lead = takes(presets.chosen) ? presets.chosen : (s.scheme?.id ?? presets.chosen);
  const ids = [lead];
  if (s.scheme && s.scheme.id !== lead && takes(s.scheme.id)) ids.push(s.scheme.id);
  for (const id of alternativesFor(presets, lead, s.scenario, 4 - ids.length)) if (!ids.includes(id)) ids.push(id);
  return ids.slice(0, 4);
}

/** A row of the comparison: its symbol, what it is in words, which way is better, and how a
 *  run gives it. */
export interface Row {
  id: string;
  symbol: string;
  words: string;
  better: "high" | "low" | null;
  read: (run: Run, scheme: Scheme | undefined, presets: Presets) => number | null;
  show: (v: number) => string;
  /** How the best of the row is said in the line that chooses: "the lowest device loss". */
  best?: string;
  /** How far apart two figures must be to tell them apart: a share of the best, or an amount
   *  in the row's own unit (a margin in degrees). Closer than that, they are a tie. */
  within?: { share?: number; amount?: number };
}

const quality = (run: Run) => (run.quality ?? {}) as Record<string, Record<string, unknown> | undefined>;
const loop = (run: Run, name: string) =>
  ((quality(run).loops ?? {}) as Record<string, Record<string, unknown> | undefined>)[name] ?? {};
const ripple = (run: Run): Record<string, unknown> =>
  quality(run).ripple ?? (run as { ripple?: Record<string, unknown> }).ripple ?? {};
const hz = (f: number) => (f >= 1000 ? `${sig(f / 1000)} kHz` : `${sig(f)} Hz`);
const time = (t: number) => (t < 1 ? `${sig(t * 1e3)} ms` : `${sig(t)} s`);

/** The junction at its worst: the top of the assumptions' spread where the engine sends it. */
const junction = (run: Run): number | null => {
  const tj = quality(run).tj ?? {};
  return num(tj.high) ?? num(tj.peak) ?? num(run.losses?.tj_peak);
};

/** rad/s, a swing of speed under which two figures are one: a thousandth of a radian a second is
 *  well under what any drive reads of its shaft, the simulation's arithmetic and no more. */
const SPEED_DUST = 1e-3;

export const ROWS: Row[] = [
  {
    id: "pm",
    symbol: "PM",
    words: "phase margin, current loop",
    better: "high",
    read: (r) => num(loop(r, "current").phase_deg),
    show: (v) => `${sig(v)}°`,
    best: "the widest phase margin",
    within: { amount: 2 },
  },
  {
    id: "bw",
    symbol: "f_bw",
    words: "bandwidth, current loop",
    better: "high",
    read: (r) => num(loop(r, "current").bandwidth_hz),
    show: hz,
    best: "the fastest current loop",
  },
  {
    id: "bw_speed",
    symbol: "f_bw,ω",
    words: "bandwidth, speed loop",
    better: "high",
    // A regulator with no linear loop to read it from is given its bandwidth: that is the figure.
    read: (r, scheme) => num(loop(r, "speed").bandwidth_hz) ?? givenBand(scheme),
    show: hz,
    best: "the fastest speed loop",
  },
  {
    id: "settle",
    symbol: "t_s",
    words: "settling after the step",
    better: "low",
    read: (r) => num(r.step?.kind === "disturbance" ? r.step?.recovery_time : r.step?.settling_time),
    show: time,
    best: "the quickest settling",
  },
  {
    id: "thd",
    symbol: "THD",
    words: "of the phase current",
    better: "low",
    read: (r) => num(ripple(r).thd) ?? num(r.channels?.thd),
    show: (v) => `${sig(v * 100)} %`,
    best: "the cleanest current",
  },
  {
    id: "ripple",
    symbol: "ΔT",
    words: "torque ripple, pk-pk",
    better: "low",
    read: (r) => num(ripple(r).torque_pp) ?? num(r.channels?.torque_ripple_pp),
    show: (v) => `${sig(v)} N·m`,
    best: "the least torque ripple",
  },
  {
    id: "speed_swing",
    symbol: "Δω",
    words: "speed swing within a turn, pk-pk",
    better: "low",
    read: (r) => num(r.channels?.speed_ripple_pp),
    show: (v) => written(v, "rad/s", 3),
    best: "the smoothest shaft",
    within: { amount: SPEED_DUST },
  },
  {
    id: "shaft_swing",
    symbol: "Δω_ml",
    words: "shaft swing, motor against load, pk-pk",
    better: "low",
    read: (r) => {
      const v = num(r.channels?.shaft_swing_pp);
      return v === null || v === 0 ? null : v;
    },
    show: (v) => written(v, "rad/s", 3),
    best: "the quietest shaft",
    within: { amount: SPEED_DUST },
  },
  {
    id: "misread",
    symbol: "Δî",
    words: "current as read, off the true one, rms",
    better: "low",
    read: (r) => num(r.channels?.read_error_rms),
    show: (v) => `${sig(v)} A`,
    best: "the truest reading",
  },
  {
    id: "torque",
    symbol: "T",
    words: "torque delivered, mean",
    better: null,
    read: (r) => num(ripple(r).torque_mean),
    show: (v) => `${sig(v)} N·m`,
  },
  {
    id: "loss",
    symbol: "P_loss",
    words: "device loss",
    better: "low",
    read: (r) => num((quality(r).loss ?? {}).total) ?? num(r.losses?.loss),
    show: (v) => `${sig(v)} W`,
    best: "the lowest device loss",
  },
  {
    id: "tj",
    symbol: "Tj",
    words: "junction at its worst",
    better: "low",
    read: junction,
    show: (v) => `${sig(v)} °C`,
    best: "the coolest junction",
    within: { amount: 1 },
  },
  {
    id: "complexity",
    symbol: "Blocks",
    words: "control law, its blocks",
    better: "low",
    read: (_r, scheme) => (scheme ? scheme.blocks.length : null),
    show: (v) => String(v),
    best: "the fewest blocks",
    within: { amount: 0.5 },
  },
  {
    id: "rate",
    symbol: "f_c",
    words: "control rate",
    better: null,
    read: (r) => num(r.timing?.f_control),
    show: hz,
  },
];

/** The rows with a figure for at least one scheme: a hold has no step to settle from. */
export const rowsShown = (runs: (Run | null)[], schemes: (Scheme | undefined)[], presets: Presets): Row[] =>
  ROWS.filter((row) => runs.some((r, k) => r && row.read(r, schemes[k], presets) !== null));

/** The place of the best figure of a row, where there is one best: two figures at least, and
 *  the best told apart from every other figure by more than the row's tolerance (3 % of the best
 *  by default). Where another figure comes within that tolerance, no figure is the best and none
 *  is marked: "lowest" is never said of a figure another column beats or matches. */
export function bestOf(values: (number | null)[], better: Row["better"], within: Row["within"] = {}): number[] {
  const have = values.filter((v): v is number => v !== null);
  if (!better || have.length < 2) return [];
  const top = better === "high" ? Math.max(...have) : Math.min(...have);
  const gap = within.amount ?? Math.abs(top) * (within.share ?? 0.03);
  const near = values.flatMap((v, k) => (v !== null && Math.abs(v - top) <= gap ? [k] : []));
  return near.length === 1 ? near : [];
}

/** The best of a row among the schemes that pass: a ruled-out scheme's figure is no one's to
 *  beat, and where none passes, none is marked. */
export function bestPassing(
  values: (number | null)[],
  runs: (Run | null)[],
  better: Row["better"],
  within: Row["within"] = {},
): number[] {
  const passing = values.map((v, k) => (runs[k] && !standingOf(runs[k]).fails ? v : null));
  return bestOf(passing, better, within);
}

/** How a scheme is told, what its rotor's angle comes from. */
export function sensorOf(scheme: Scheme, presets: Presets): { needs: boolean; words: string } {
  const t = traitsOf(scheme, presets);
  if (t.sensored) return { needs: true, words: "Rotor sensor" };
  if (!t.sensor) return { needs: false, words: "–" };
  const title = presets.blocks[t.sensor]?.title ?? "an observer";
  return { needs: false, words: `None: ${title.charAt(0).toLowerCase()}${title.slice(1)}` };
}

/** A scheme's name short enough for a sentence: what its brackets say where that names it,
 *  else its label without them. */
export function shortName(label: string): string {
  // "Joint servo: speed and current control along an S-curve" is the joint servo.
  const named = /^([^:()]{4,32}):\s/.exec(label);
  if (named) return named[1];
  const m = /^(.*?)\s*\((.+)\)\s*$/.exec(label);
  if (!m) return label;
  const inner = m[2].replace(/^(a|an|the)\s+/i, "");
  const name = inner.length >= 12 ? inner : m[1];
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/** What a run's verdict comes to, counted: what fails, what to change (among it the design
 *  actions: what would make a result that holds better, the engine's lightest grade), the notes. */
export function standingOf(run: Run): { fails: number; changes: number; actions: number; notes: number } {
  const findings = run.verdict?.findings ?? [];
  const tones = findings.map(toneOf);
  const failed = run.checks?.some((c) => c.level === "fail") ?? false;
  return {
    fails: tones.filter((t) => t === "fail").length + (failed && !tones.includes("fail") ? 1 : 0),
    changes: tones.filter((t) => t === "improve").length,
    actions: findings.filter((f) => toneOf(f) === "improve" && f.severity <= 1).length,
    notes: tones.filter((t) => t === "note").length,
  };
}

export interface Choice {
  /** The place of the scheme chosen among those compared, or -1 for none run yet. */
  at: number;
  /** The line that says it, in figures. */
  said: string;
  /** Whether the chosen one passes. */
  passes: boolean;
}

/** The rows that make a scheme better to choose, not only different: what it costs (loss, the
 *  junction), the current it makes, its margin, how it settles and its torque ripple. A wider
 *  bandwidth or fewer blocks is shown and marked, but is not by itself a reason to change. */
const DECIDING = ["loss", "tj", "thd", "pm", "settle", "ripple"];

/** Which scheme to choose and why, from the figures alone.
 *  - Only a scheme with nothing failing, that delivers the torque the others do (within 5 %),
 *    can be chosen; and where the scheme recommended needs no rotor sensor (the application has
 *    none), neither can one that needs a sensor.
 *  - The verdict's level first: a scheme that passes is always chosen over one with anything to
 *    change, whatever its figures; then the fewest to change.
 *  - Among those, the one best on the most deciding rows; the first (the recommended one) where
 *    it is a tie, so the recommendation stands unless the figures say otherwise.
 *  - The line names up to two rows it is the one best on (beyond the tie tolerance), each with its
 *    figure and the best of the others, and says when it needs no sensor that another needs.
 *  - Where none that can be chosen passes, it says so and which comes closest; and where a scheme
 *    that passes was left out (it needs a sensor, or delivers less torque), it names it and why. */
export function choose(
  names: string[],
  runs: (Run | null)[],
  schemes: (Scheme | undefined)[],
  presets: Presets,
): Choice {
  const f = figuresOf(runs, schemes, presets);
  if (!f.done.length) return { at: -1, said: "", passes: false };
  const ranked = [...f.able].sort(
    (a, b) =>
      f.level(a) - f.level(b) ||
      f.standing[a]!.changes - f.standing[b]!.changes ||
      f.deciding(b) - f.deciding(a) ||
      a - b,
  );
  return !ranked.length || !f.passing(ranked[0]) ? noneSaid(names, f, ranked[0]) : chosenSaid(names, f, ranked[0]);
}

/** What the line that chooses is read from: the figures of each row, the best of each, and the
 *  standing of each scheme, with which of them can be chosen at all. */
function figuresOf(runs: (Run | null)[], schemes: (Scheme | undefined)[], presets: Presets) {
  const done = runs.map((r, k) => (r ? k : -1)).filter((k) => k >= 0);
  const rows = rowsShown(runs, schemes, presets);
  const values = rows.map((row) => runs.map((r, k) => (r ? row.read(r, schemes[k], presets) : null)));
  const bests = rows.map((row, n) => bestOf(values[n], row.better, row.within));
  const torque = ROWS.find((r) => r.id === "torque")!;
  const delivered = runs.map((r, k) => (r ? torque.read(r, schemes[k], presets) : null));
  const most = Math.max(0, ...delivered.map((t) => Math.abs(t ?? 0)));
  const standing = runs.map((r) => (r ? standingOf(r) : null));
  const sensors = schemes.map((s) => (s ? sensorOf(s, presets).needs : false));
  const sealed = !!schemes[0] && !sensors[0];
  const short = (k: number) => most > 0 && delivered[k] !== null && Math.abs(delivered[k] ?? 0) < most * 0.95;
  const passing = (k: number) => standing[k]!.fails === 0 && standing[k]!.changes === 0;
  const able = done.filter((k) => standing[k]!.fails === 0 && !short(k) && !(sealed && sensors[k]));
  const deciding = (k: number) => rows.filter((r, n) => DECIDING.includes(r.id) && bests[n].includes(k)).length;
  const level = (k: number) => (passing(k) ? 0 : 1);
  return { runs, schemes, done, rows, values, bests, standing, sensors, sealed, short, passing, able, deciding, level };
}
type Figures = ReturnType<typeof figuresOf>;

/** None that can be chosen passes: which comes closest, and the one that passes but was left
 *  out, with why. Never "because it passes" of a scheme with anything to change. */
function noneSaid(names: string[], f: Figures, best: number | undefined): Choice {
  const near =
    best ??
    [...f.done].sort(
      (a, b) => f.standing[a]!.fails - f.standing[b]!.fails || f.standing[a]!.changes - f.standing[b]!.changes || a - b,
    )[0];
  const { fails, changes } = f.standing[near]!;
  const owed = [fails ? `${fails} failing` : "", changes ? `${changes} to change` : ""].filter(Boolean).join(" and ");
  const without = f.sealed && f.done.some((k) => f.passing(k) && f.sensors[k]) ? " without a rotor sensor" : "";
  const leftOut = f.done
    .filter((k) => f.passing(k) && !f.able.includes(k))
    .map((k) => ` ${names[k]} passes, but ${f.short(k) ? "delivers less torque" : "needs a rotor sensor"}.`)[0];
  return {
    at: near,
    passes: false,
    said: `None passes as tuned${without}: closest is ${names[near]}, with ${owed}.${leftOut ?? ""}`,
  };
}

/** The scheme chosen passes: the rows it is the one best on, each against the best of the others. */
function chosenSaid(names: string[], f: Figures, at: number): Choice {
  const ORDER = [...DECIDING, "bw", "bw_speed", "complexity"];
  const won = ORDER.map((id) => f.rows.findIndex((r) => r.id === id))
    .filter((n) => n >= 0 && f.bests[n].includes(at))
    .slice(0, 2)
    .map((n) => {
      const row = f.rows[n];
      const others = f.values[n].filter((v, k): v is number => v !== null && k !== at);
      const next = others.length ? (row.better === "high" ? Math.max(...others) : Math.min(...others)) : null;
      return `${row.best} (${row.show(f.values[n][at]!)}${next === null ? "" : ` against ${row.show(next)}`})`;
    });
  const noSensor = f.schemes[at] && !f.sensors[at] && f.sensors.some((x, k) => x && f.runs[k]);
  const reasons = [...won, ...(noSensor ? ["no rotor sensor"] : [])];
  const name = names[at];
  const alone = f.done.length > 1 && f.done.every((k) => k === at || !f.passing(k));
  // Where a scheme not chosen is the one best on a deciding row, "no other is better" is said
  // only of those that pass.
  const beaten = f.rows.some((r, n) => DECIDING.includes(r.id) && f.bests[n].some((k) => k !== at));
  const others = beaten ? "no other that passes" : "no other scheme here";
  const said = alone
    ? `Choose ${name} because it is the only one here that passes${reasons.length ? `, with ${list(reasons)}` : ""}.`
    : reasons.length
      ? `Choose ${name} because it passes with ${list(reasons)}.`
      : `Choose ${name} because it passes and ${others} is better on loss, Tj, THD or margin.`;
  return { at, said, passes: true };
}

const list = (parts: string[]): string =>
  parts.length <= 1 ? (parts[0] ?? "") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;

let asked: AbortController | null = null;

/** Run each scheme as tuned on the lab's design and test, all at once: the engine serves each
 *  request on its own thread. Each column fills as its run comes; one refused or lost does not
 *  stop the others. */
export async function compareNow(ids: string[] = startingIds(lab.get())): Promise<void> {
  asked?.abort();
  const mine = (asked = new AbortController());
  const s = lab.get();
  const presets = s.presets;
  if (!presets || !ids.length) return;
  const key = compareKey(s);
  const running: Compared = { status: "running", run: null, refused: null, fault: null };
  lab.set({ compare: { key, ids, items: Object.fromEntries(ids.map((id) => [id, running])) } });
  const put = (id: string, item: Compared) => {
    if (asked !== mine) return;
    lab.set((now) => (now.compare ? { compare: { ...now.compare, items: { ...now.compare.items, [id]: item } } } : {}));
  };
  await Promise.all(
    ids.map(async (id) => {
      const scheme = presets.schemes.find((x) => x.id === id);
      if (!scheme)
        return put(id, { ...running, status: "fault", fault: "This scheme is not offered for this design." });
      try {
        const run = await control.run(runRequest({ ...s, scheme }), mine.signal);
        put(id, { status: "done", run, refused: null, fault: null });
        if (asked === mine) intoLab(scheme, run, key);
      } catch (e) {
        if (aborted(e)) return;
        const refused = problemOf(e);
        put(id, {
          status: refused ? "refused" : "fault",
          run: null,
          refused,
          fault: refused ? null : e instanceof Unreachable ? UNREACHABLE : (e as Error).message,
        });
      }
    }),
  );
}

/** Add a scheme to the comparison, run at once; or take one out. */
export function addCompared(id: string): void {
  const now = lab.get().compare;
  if (!now || now.ids.includes(id) || now.ids.length >= MOST) return;
  const s = lab.get();
  const scheme = s.presets?.schemes.find((x) => x.id === id);
  if (!scheme) return;
  lab.set({
    compare: {
      ...now,
      ids: [...now.ids, id],
      items: { ...now.items, [id]: { status: "running", run: null, refused: null, fault: null } },
    },
  });
  control
    .run(runRequest({ ...s, scheme }))
    .then((run) => {
      const c = lab.get().compare;
      if (c?.key === now.key && c.ids.includes(id))
        lab.set({
          compare: { ...c, items: { ...c.items, [id]: { status: "done", run, refused: null, fault: null } } },
        });
    })
    .catch((e: unknown) => {
      const c = lab.get().compare;
      const refused = problemOf(e);
      if (c?.key === now.key && c.ids.includes(id))
        lab.set({
          compare: {
            ...c,
            items: {
              ...c.items,
              [id]: { status: refused ? "refused" : "fault", run: null, refused, fault: refused ? null : String(e) },
            },
          },
        });
    });
}

export function dropCompared(id: string): void {
  const now = lab.get().compare;
  if (!now || now.ids.length <= 2) return;
  lab.set({ compare: { ...now, ids: now.ids.filter((x) => x !== id) } });
}

/** Stop the comparison under way: the lab was shut. */
export function stopCompare(): void {
  asked?.abort();
  asked = null;
}
