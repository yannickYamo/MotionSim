// What is set beside the design to compare, taken in or out one at a time: the load of step 4
// kept as it is, and a column of any kind taken out.

import { suggestFor } from "../engine/suggest";
import { app, res } from "../store";
import { redrawCompared } from "./redraw";

/** The user's own load: what step 4 holds now, kept as it is. They can then change
 *  step 4 and see the two side by side. */
export function keepOwnLoad(): void {
  const { state } = app;
  const own = state.loadSet.filter((x) => x.id.startsWith("own-"));
  const n = Math.max(0, ...own.map((x) => Number(/^Your load (\d+)/.exec(x.label)?.[1] ?? 0))) + 1;
  const preset = res.presets?.list.find((p) => p.id === state.loadKind)?.label;
  const from = state.mission ? state.mission.name : (preset ?? "load");
  state.loadSet.push({
    id: `own-${Date.now()}`,
    label: `Your load ${n} (${from}, as set)`,
    loadKind: state.loadKind,
    load: { ...state.load },
    segments: state.segments.map((x) => ({ ...x })),
    phases: state.phases,
    mission: state.mission,
  });
  redrawCompared();
}

/** Take one column out of what is compared, by its key. `values`: the values of the setting
 *  tried, as the table shows them. With fewer than two values left, no setting is tried. */
export function dropOne(key: string, values: number[]): void {
  const { state } = app;
  if (state.compare === "devices") {
    state.devices = state.devices.filter((d) => d !== key);
    if (state.focus === key) state.focusPicked = false;
    void suggestFor();
    return;
  }
  if (state.compare === "loads") state.loadSet = state.loadSet.filter((x) => x.id !== key);
  if (state.compare === "motors") state.motorSet = state.motorSet.filter((m) => m.id !== key);
  res.variants.delete(key);
  res.cycles.delete(key);
  if (state.compare !== "sweep") return;
  const left = values.filter((v) => `${state.sweep.key}=${v}` !== key);
  state.sweep = { ...state.sweep, values: left.length > 1 ? left.join(", ") : "" };
  if (left.length < 2) state.compare = "devices";
  res.cycles.clear();
}
