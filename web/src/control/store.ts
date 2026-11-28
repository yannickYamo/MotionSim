// What the lab holds: the scheme being edited, the test and its run, the linear analysis,
// the library. One store outside React, so that it outlasts the lab being shut and opened,
// and a second, far smaller one for the time cursor, which moves sixty times a second and
// is read straight by the marks that follow it, without drawing anything again.

import { useSyncExternalStore } from "react";
import type { Exploration, Kept, Loops, Plant, Presets, ReadWords, Run, Scheme, Series, Sweep } from "./types";

export interface Problem {
  reason: string;
  fix: string;
  /** The figure at fault, as the engine names it: `scheme.blocks.current.kp_q`. */
  field: string;
}

export type Tab = "run" | "compare" | "laplace" | "library" | "kept";

/** One scheme of a comparison: its run on the design and test of the lab, as it comes. */
export interface Compared {
  status: "running" | "done" | "refused" | "fault";
  run: Run | null;
  refused: Problem | null;
  fault: string | null;
}

/** Schemes run side by side on the same design and test: what each was run on (its key), the
 *  schemes in their order (the one recommended first), and each one's answer. */
export interface Comparison {
  key: string;
  ids: string[];
  items: Record<string, Compared>;
}

export interface RunState {
  status: "idle" | "running" | "done";
  progress: number;
  /** What has come of a run under way. */
  partial: Series | null;
  answer: Run | null;
  refused: Problem | null;
  fault: string | null;
  /** Something said beside the answer: that its progress was lost on the way, say. */
  note: string | null;
  /** The answer is of a design or a scheme that has since been changed. */
  stale: boolean;
}

export interface LabState {
  phase: "loading" | "ready" | "refused" | "fault";
  problem: Problem | null;
  designKey: string;
  design: Record<string, unknown>;
  presets: Presets | null;
  /** The scheme as edited, and the preset or kept scheme it started as. */
  scheme: Scheme | null;
  tuned: Scheme | null;
  selected: string | null;
  scenario: string;
  /** The test's figures as typed, by test; a figure not typed takes the engine's own. */
  figures: Record<string, Record<string, string>>;
  fidelity: string;
  /** The motor and load as simulated, where they differ from the controller's own model. */
  plant: Plant;
  run: RunState;
  /** The run before this one, for every figure to read as a difference. */
  before: Run | null;
  /** A run set aside to compare the next ones with: the A of an A/B. */
  held: { name: string; run: Run } | null;
  /** The wires probed: drawn in the scope through time; null for the test's usual ones. */
  plotted: string[] | null;
  /** What each press on a wire of several lines added to the scope, by its lines: a second
   *  press takes out those alone, never a trace that was drawn before it. */
  pins: Record<string, string[]>;
  /** The tests the engine refused for a scheme, by the scheme's id: not offered again. */
  refusedTests: Record<string, string[]>;
  /** Something said once of the lab as it opened: a scheme carried, or started afresh. */
  said: string | null;
  /** The stretch of time the scope shows; null for all of it. */
  view: [number, number] | null;
  loops: { status: "idle" | "asking" | "done"; answer: Loops | null; refused: Problem | null; fault: string | null };
  tab: Tab;
  library: {
    status: "idle" | "asking" | "done" | "missing" | "fault";
    list: Exploration[];
    /** The engine's own words for the figures the sweeps read. */
    words: ReadWords;
    open: string | null;
    sweep: Sweep | null;
    running: boolean;
    done: number;
    problem: string | null;
  };
  kept: { schemes: Kept[]; runs: Kept[]; status: "idle" | "asking" | "done" | "fault"; said: string | null };
  /** The schemes compared on this design and test, or null before any comparison is asked. */
  compare: Comparison | null;
  /** Learning: each block says what it does as it is pointed at, and its theory opens first. */
  learn: boolean;
}

export const idleRun = (): RunState => ({
  status: "idle",
  progress: 0,
  partial: null,
  answer: null,
  refused: null,
  fault: null,
  note: null,
  stale: false,
});

export const fresh = (): LabState => ({
  phase: "loading",
  problem: null,
  designKey: "",
  design: {},
  presets: null,
  scheme: null,
  tuned: null,
  selected: null,
  scenario: "hold",
  figures: {},
  fidelity: "switched",
  plant: {},
  run: idleRun(),
  before: null,
  held: null,
  plotted: null,
  pins: {},
  refusedTests: {},
  said: null,
  view: null,
  loops: { status: "idle", answer: null, refused: null, fault: null },
  tab: "run",
  library: { status: "idle", list: [], words: {}, open: null, sweep: null, running: false, done: 0, problem: null },
  kept: { schemes: [], runs: [], status: "idle", said: null },
  compare: null,
  learn: false,
});

type Listener = () => void;

let state = fresh();
const listeners = new Set<Listener>();

export const lab = {
  get: (): LabState => state,
  set(change: Partial<LabState> | ((s: LabState) => Partial<LabState>)): void {
    state = { ...state, ...(typeof change === "function" ? change(state) : change) };
    listeners.forEach((l) => l());
  },
  subscribe(l: Listener): () => void {
    listeners.add(l);
    return () => listeners.delete(l);
  },
  reset(): void {
    state = fresh();
    listeners.forEach((l) => l());
  },
};

/** A part of what the lab holds; the part is drawn again only when it is another. What is
 *  picked has to be a value held in the store itself, never one made on the way. */
export function useLab<T>(pick: (s: LabState) => T): T {
  return useSyncExternalStore(
    (l) => lab.subscribe(l),
    () => pick(state),
    () => pick(state),
  );
}

type Follower = (t: number) => void;

/** The instant the cursor is on. What follows it is told once a frame at most, and writes
 *  its own mark: nothing is drawn again by React for a cursor that moved. */
export const cursor = {
  t: 0,
  followers: new Set<Follower>(),
  waiting: 0,
  set(t: number): void {
    if (t === this.t) return;
    this.t = t;
    if (this.waiting) return;
    this.waiting = requestAnimationFrame(() => {
      this.waiting = 0;
      this.followers.forEach((f) => f(this.t));
    });
  },
  /** Follow the cursor from now on; the follower is told at once where it is. */
  follow(f: Follower): () => void {
    this.followers.add(f);
    f(this.t);
    return () => this.followers.delete(f);
  },
  /** Tell every follower now: after the traces themselves have changed. */
  again(): void {
    this.followers.forEach((f) => f(this.t));
  },
};

/** The traces the cursor reads: the run's own, or what has come of one under way. */
export const tracesOf = (s: LabState): Series | null =>
  s.run.status === "running" && s.run.partial ? s.run.partial : (s.run.answer?.series ?? null);
export const tracesNow = (): Series | null => tracesOf(state);
