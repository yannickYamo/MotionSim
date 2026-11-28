// What the drawings of the frame transforms are read from: the wires a transform is drawn
// from, and the full scale of a set of wires over the run.

import type { LNode } from "./layout";
import { useLab } from "./store";
import type { Scheme } from "./types";

interface FrameWires {
  alpha: string;
  beta: string;
  theta: string;
  phases: string[];
}

/** The wires a frame transform is drawn from: the stator-frame pair, the angle, the phases. */
export function frameWires(node: LNode, scheme: Scheme): FrameWires {
  const input = (port: string) => node.inputs.find((i) => i.port === port)?.wire;
  const output = (port: string) => node.outputs.find((o) => o.name === port)?.wire;
  const anyAngle = scheme.blocks.flatMap((b) => Object.values(b.inputs)).find((w) => /\.theta$/.test(w));
  return {
    alpha: input("alpha") ?? output("alpha") ?? "",
    beta: input("beta") ?? output("beta") ?? "",
    theta: input("theta") ?? anyAngle ?? "plant.theta_e",
    phases: ["a", "b", "c"].map((p) => input(p) ?? ""),
  };
}

/** The largest size any value of a trace has. */
function largest(values: number[]): number {
  let most = 0;
  for (const v of values) if (Math.abs(v) > most) most = Math.abs(v);
  return most;
}

const mosts = new WeakMap<object, Map<string, number>>();

/** The largest any of some wires gets in the run, with a little room: full scale for a
 *  drawing. Worked out once for each run, however often it is asked for. */
export function useMost(wires: string[]): number {
  return useLab((s) => {
    const series = s.run.answer?.series.wires;
    if (!series) return 1;
    const known = mosts.get(series) ?? new Map<string, number>();
    mosts.set(series, known);
    const key = wires.join("|");
    const had = known.get(key);
    if (had !== undefined) return had;
    const most = Math.max(0, ...wires.map((w) => largest(series[w] ?? []))) * 1.15 || 1;
    known.set(key, most);
    return most;
  });
}
