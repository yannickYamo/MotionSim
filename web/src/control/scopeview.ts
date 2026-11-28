// The run as the scope shows it. The engine keeps a shaft's speed in rad/s; the rest of the
// product speaks rpm, and so does the scope. The speeds are turned once, here at the scope's
// door: a wire of the shaft's speed is in rpm, its samples and the lowest and highest between
// them with it, and a step of the speed is in rpm too. The electrical speed is not the shaft's
// (it runs faster by the pole pairs), so it stays as the engine gives it. Nothing the engine
// sent is changed: every view is a copy, made once for each answer and kept beside it.

import type { Run, Series, Wire } from "./types";

/** One rad/s, in turns a minute. */
export const RPM = 30 / Math.PI;

/** Whether a wire is a speed of the shaft as the engine keeps it: turned to rpm on the scope. */
export const turns = (w: { name: string; unit: string }): boolean => w.unit === "rad/s" && !/omega_e$/.test(w.name);

const wiresMemo = new WeakMap<Wire[], Wire[]>();

/** The wires as the scope names their units: the shaft's speeds in rpm. */
export function shaftWires(wires: Wire[]): Wire[] {
  const had = wiresMemo.get(wires);
  if (had) return had;
  const out = wires.some(turns) ? wires.map((w) => (turns(w) ? { ...w, unit: "rpm" } : w)) : wires;
  wiresMemo.set(wires, out);
  return out;
}

const scaled = (all: Record<string, number[]> | undefined, names: string[]): Record<string, number[]> | undefined => {
  if (!all) return all;
  const out = { ...all };
  for (const name of names) if (all[name]) out[name] = all[name].map((v) => v * RPM);
  return out;
};

const seriesMemo = new WeakMap<Series, { key: string; out: Series }>();

/** The traces as the scope draws them: the shaft's speeds in rpm, every other as it came.
 *  `wires` are the wires as the engine names their units. */
export function shaftSeries(series: Series, wires: Wire[]): Series {
  const names = wires.filter((w) => turns(w) && series.wires[w.name]).map((w) => w.name);
  const key = names.join("|");
  const had = seriesMemo.get(series);
  if (had && had.key === key) return had.out;
  const out: Series = names.length
    ? { ...series, wires: scaled(series.wires, names)!, lo: scaled(series.lo, names), hi: scaled(series.hi, names) }
    : series;
  seriesMemo.set(series, { key, out });
  return out;
}

const runMemo = new WeakMap<Run, Run>();

/** A run as the scope reads it: its wires, its traces and a step of the speed, in rpm. */
export function shaftRun(run: Run): Run {
  const had = runMemo.get(run);
  if (had) return had;
  const stepped = run.step && run.wires.some((w) => w.name === run.step!.wire && turns(w));
  const out: Run = {
    ...run,
    wires: shaftWires(run.wires),
    series: shaftSeries(run.series, run.wires),
    step: stepped ? { ...run.step!, from: run.step!.from * RPM, to: run.step!.to * RPM } : run.step,
  };
  runMemo.set(run, out);
  return out;
}

/** Run A as the scope draws it under this run: held, another run, and of the same test. */
export function ghostOf(held: Run | null, run: Run | null): Run | null {
  return held && run && held !== run && held.scenario.kind === run.scenario.kind ? shaftRun(held) : null;
}
