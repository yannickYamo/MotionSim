// What is set side by side on the results: up to five devices, loads or motors, or one
// setting at up to five values. One kind at a time; more at once is too much to read.

import { notRefused } from "./api";
import type { Candidate, Field } from "./api";
import { sig } from "./format";
import { outOfRange } from "./limits";
import { shownAs, shownText } from "./motorentry";
import { readList } from "./parse";
import { request } from "./state";
import type { LoadItem, MotorItem } from "./state";
import { MOST } from "./steps";
import { app, focused, res } from "./store";

export interface Series {
  key: string;
  name: string;
  candidate: Candidate | null;
  item: LoadItem | null;
  /** For a motor or a setting compared: what differs from the request of the page. */
  over?: { motor?: Record<string, string | number>; conditions?: Record<string, number | string | null> };
}

interface Sweep {
  label: string;
  unit: string;
  field: string;
  scale: number;
}

/** The settings that can be tried at several values, and how each reaches the engine. */
export const SWEEPS: Record<string, Sweep> = {
  f_khz: { label: "Switching frequency", unit: "kHz", field: "f_sw", scale: 1000 },
  v_dc: { label: "Supply voltage", unit: "V", field: "v_dc", scale: 1 },
  t_sink: { label: "Heatsink temperature", unit: "°C", field: "t_sink", scale: 1 },
  parallel: { label: "Devices in parallel", unit: "a switch", field: "parallel", scale: 1 },
};

/** A setting as it is tried. With cooling to air there is no heatsink temperature to set:
 *  the temperature tried is the air's. */
export function sweepOf(key: string): Sweep {
  if (key === "t_sink" && app.state.conditions.cooling !== "held") {
    return { label: "Air temperature", unit: "°C", field: "t_ambient", scale: 1 };
  }
  return SWEEPS[key] ?? SWEEPS.f_khz;
}

/** The values in the table with what was typed added to them, in order; or why not, in
 *  which case nothing is added. `key`: the setting tried, which says what a value may be. */
export function withValues(
  now: number[],
  typed: string,
  key: string,
): { ok: true; values: number[] } | { ok: false; why: string } {
  const read = readList(typed, SWEEPS[key]?.unit);
  const values: number[] = [];
  for (const r of read) {
    if (!r.ok) return { ok: false, why: `${r.why} Nothing was added.` };
    const range = outOfRange(`conditions.${key}`, r.value);
    if (range) return { ok: false, why: `${range} Nothing was added.` };
    values.push(r.value);
  }
  const merged = [...new Set([...now, ...values])].sort((a, b) => a - b);
  if (merged.length === now.length) return { ok: false, why: "That value is already in the table." };
  if (merged.length > MOST) {
    const room = MOST - now.length;
    return { ok: false, why: `Five values is the most: ${now.length} are in the table, so ${room} more can be added.` };
  }
  return { ok: true, values: merged };
}

/** The values a setting is tried at: the user's, or the present one with half and double. */
export function sweepValues(): number[] {
  const { state } = app;
  const degrees = state.sweep.key === "t_sink"; // a temperature may be zero or below
  const typed = state.sweep.values
    .split(/[\s,;]+/)
    .filter((v) => v !== "")
    .map(Number)
    .filter((v) => Number.isFinite(v) && (degrees || v > 0));
  const key = degrees && state.conditions.cooling !== "held" ? "t_ambient" : state.sweep.key;
  const held = (state.conditions as Record<string, unknown>)[key];
  const now = degrees ? Number(held) || 0 : Number(held) || 1;
  const count = Math.min(12, Math.max(1, Math.round(now)));
  const beside = count === 1 ? [1, 2, 3] : count === 12 ? [10, 11, 12] : [count - 1, count, count + 1];
  const usual = state.sweep.key === "parallel" ? beside : degrees ? [now - 20, now, now + 20] : [now / 2, now, now * 2];
  // The value as it is set is one of them as it is; those beside it are round figures.
  const round = usual.map((v) => (v === now ? v : Number(v.toPrecision(3))));
  return [...new Set(typed.length ? typed : round)].slice(0, MOST);
}

/** The request for one thing compared: the page's own, with what differs laid over it. */
export function requestOf(x: Series) {
  const base = request(app.state);
  if (!x.over) return base;
  return { ...base, motor: x.over.motor ?? base.motor, conditions: { ...base.conditions, ...x.over.conditions } };
}

/** The candidate a column shows: its own answer where its request differs from the page's. */
export function resultOf(x: Series): Candidate | null {
  if (!x.over) return x.candidate;
  const own = res.variants.get(x.key);
  return notRefused(own);
}

function loadSeries(): Series[] {
  const { state } = app;
  const preset = res.presets?.list.find((p) => p.id === state.loadKind)?.label;
  const now = state.mission ? state.mission.name : state.loadTouched ? "Your load" : (preset ?? "Your load");
  const kept = state.loadSet
    .slice(0, MOST - 1)
    .map((item) => ({ key: item.id, name: item.label, candidate: focused(), item }));
  return [{ key: "now", name: `${now} (step 4)`, candidate: focused(), item: null }, ...kept];
}

const POINT_UNITS = { v_dc: "V", rpm: "rpm", torque: "N·m" } as const;

/** A changed figure of the motor, said the way step 2 shows it (line to line or per phase,
 *  mH or mΩ, Kv or Kt, as the user chose there), never in the engine's terms. */
function entrySaid(kind: string, f: Field, engine: string | number | undefined): string {
  const as = shownAs(kind, f.key, app.state.motorEntry, f.label, f.help);
  const unit = as?.unit ?? f.unit;
  return `${as?.label ?? f.label} ${shownText(as, engine ?? "")}${unit ? ` ${unit}` : ""}`;
}

/** What a copy of the motor changes from the motor and the design point of step 2, in words. */
export function motorLabel(m: Pick<MotorItem, "motor" | "conditions">): string {
  const { state, setup } = app;
  const key = String(m.motor.type ?? state.kind);
  const kind = setup.motors[key];
  if (!kind) return "Another motor";
  const step2 = state.motors[key] ?? {};
  const changed = kind.fields.filter((f) => String(m.motor[f.key] ?? "") !== String(step2[f.key] ?? ""));
  const k = state.conditions;
  const moved = (["v_dc", "rpm", "torque"] as const).filter((p) => m.conditions[p] !== k[p]);
  const what = [
    ...changed.map((f) => (f.options ? `${f.label} ${m.motor[f.key]}` : entrySaid(key, f, m.motor[f.key]))),
    ...moved.map((p) => `${sig(Number(m.conditions[p]))} ${POINT_UNITS[p]}`),
  ];
  return `${kind.label}: ${what.length ? what.join(", ") : "a copy, as set"}`;
}

function motorSeries(): Series[] {
  const { state, setup } = app;
  const kept = state.motorSet.slice(0, MOST - 1).map((m) => ({
    key: m.id,
    // Said afresh each time, so a switch on step 2 between line to line and per phase, or
    // Kv and Kt, is followed in the column's name.
    name: motorLabel(m),
    candidate: focused(),
    item: null,
    over: { motor: m.motor, conditions: m.conditions },
  }));
  return [
    { key: "now", name: `${setup.motors[state.kind].label} (step 2)`, candidate: focused(), item: null },
    ...kept,
  ];
}

function sweepSeries(): Series[] {
  const key = app.state.sweep.key;
  const sweep = sweepOf(key);
  return sweepValues().map((v) => ({
    key: `${key}=${v}`,
    name: `${sig(v)} ${sweep.unit}`,
    candidate: focused(),
    item: null,
    over: { conditions: { [sweep.field]: v * sweep.scale } },
  }));
}

/** The things compared, in the order of the table's columns. */
export function series(): Series[] {
  if (app.state.compare === "loads") return loadSeries();
  if (app.state.compare === "motors") return motorSeries();
  if (app.state.compare === "sweep") return sweepSeries();
  const run = (res.proposal?.candidates ?? []).filter((c) => c.result).slice(0, MOST);
  return run.map((c) => ({ key: c.id, name: c.name, candidate: c, item: null }));
}

export const comparing = (): boolean => series().length > 1;
