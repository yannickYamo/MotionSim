// Bringing back what was kept. What the browser keeps can be edited by hand, and a setup file
// is a file from anywhere: every value is held to the shape the page is written for, and
// whatever does not fit gives way to the page's own starting value. A wrong shape let through
// here is a page that cannot be drawn, on this visit and on every one after.

import type { KeptPart, Phase, Segment, Setup } from "./api";
import { EDGE_LIMITS, initial, KEY, POINT_KEYS, save as saveState, STALE_KEYS } from "./state";
import type { LoadItem, Mission, MotorItem, Point, State, Tab } from "./state";
import type { MotorEntry } from "./motorentry";
import { MOST } from "./steps";

type Json = Record<string, unknown>;

const TABS: Tab[] = ["proposal", "losses", "motion", "limits"];
/** The tabs of earlier versions of the page, by the tab that now holds what they showed. */
const TABS_WERE: Record<string, Tab> = { map: "losses", settings: "limits", build: "limits", capability: "limits" };

const COMPARES: State["compare"][] = ["devices", "loads", "motors", "sweep"];
const COOLINGS: State["conditions"]["cooling"][] = ["held", "heatsink", "none", "board"];

/** The most instants of a mission profile, and characters of a text, that are taken back. */
const MOST_INSTANTS = 20000;
const MOST_TEXT = 400;
/** Two texts are longer by their nature: what a cooling was sized for (every input of the
 *  sizing, written out), and a board layout file. Each is taken back whole, up to its own bound. */
const MOST_SIZING = 8000;
const MOST_LAYOUT = 2_000_000;
const longText = (v: unknown, most: number): string => (typeof v === "string" && v.length <= most ? v : "");

const isRecord = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);
const isNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isText = (v: unknown): v is string => typeof v === "string" && v.length <= MOST_TEXT;
const oneOf = <T>(v: unknown, allowed: readonly T[], otherwise: T): T =>
  allowed.includes(v as T) ? (v as T) : otherwise;
/** The tab a kept state opens on: its own, or the one that now holds what an earlier tab showed. */
export const tabOf = (v: unknown, otherwise: Tab): Tab =>
  typeof v === "string" && Object.hasOwn(TABS_WERE, v) ? TABS_WERE[v] : oneOf(v, TABS, otherwise);
const whole = (v: unknown, low: number, high: number, otherwise: number): number =>
  isNumber(v) && Number.isInteger(v) && v >= low && v <= high ? v : otherwise;
const texts = (v: unknown): string[] => (Array.isArray(v) ? v.filter(isText) : []);

/** What was saved, made safe to walk: only text, finite numbers, yes and no, lists and plain
 *  records are kept. Text is kept as it was typed, so that a name with a quote or an
 *  ampersand in it comes back whole; the page escapes it wherever it is shown. */
export function plain(value: unknown, depth = 0): unknown {
  if (typeof value === "string") return value;
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  if (typeof value === "boolean" || value === null) return value;
  if (depth > 8 || typeof value !== "object") return null;
  if (Array.isArray(value)) return value.map((v) => plain(v, depth + 1));
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plain(v, depth + 1)]));
}

/** A record of fixed fields: each saved value is kept only where it is of the kind the
 *  page's own starting value is (a number for a number, text for text). A figure kept as a
 *  number where the box holds text comes back as that figure written out. */
function like<T extends object>(saved: unknown, fresh: T): T {
  const from = isRecord(saved) ? saved : {};
  const out: Json = {};
  for (const [key, start] of Object.entries(fresh)) {
    const v = from[key];
    if (typeof start === "string" && isNumber(v)) {
      out[key] = String(v);
      continue;
    }
    const fits =
      typeof start === "number" ? isNumber(v) : typeof start === "string" ? isText(v) : typeof v === typeof start;
    out[key] = fits ? v : start;
  }
  return out as T;
}

/** The event's own figures, and its layout file whole: a layout too long to take back is
 *  dropped with its name, so that the page never names a file it no longer holds. */
function eventOf(saved: unknown, fresh: State["event"]): State["event"] {
  const event = like(saved, fresh);
  const layout = longText(isRecord(saved) ? saved.layout : "", MOST_LAYOUT);
  return { ...event, layout, layout_name: layout ? event.layout_name : "" };
}

/** A record of figures and choices, as a motor's are: text and numbers under plain names. */
function figures(saved: unknown): Record<string, string | number> {
  if (!isRecord(saved)) return {};
  return Object.fromEntries(
    Object.entries(saved).filter(([, v]) => isNumber(v) || isText(v)) as [string, string | number][],
  );
}

function segmentsOf(saved: unknown, fresh: Segment[]): Segment[] {
  if (!Array.isArray(saved)) return fresh;
  const good = saved.filter(
    // A stretch lasts some time: one of no length, or of less, is not a stretch.
    (s): s is Segment =>
      isRecord(s) && isNumber(s.duration) && s.duration > 0 && isNumber(s.speed_start) && isNumber(s.speed_end),
  );
  const kept = good.map((s) => ({
    duration: s.duration,
    speed_start: s.speed_start,
    speed_end: s.speed_end,
    ...(s.at_limit === true ? { at_limit: true } : {}),
    ...(s.until_steady === true ? { until_steady: true } : {}),
    ...(isNumber(s.slope_percent) ? { slope_percent: s.slope_percent } : {}),
  }));
  return kept.length && kept.length === saved.length ? kept : fresh;
}

/** A duty's phases as kept: each named, repeated a whole number of times, with its stretches. */
function phasesOf(saved: unknown): Phase[] | null {
  if (!Array.isArray(saved) || !saved.length) return null;
  const kept = saved.flatMap((p): Phase[] => {
    if (!isRecord(p) || !isText(p.name) || !isNumber(p.repeat) || p.repeat < 1 || p.repeat > 500) return [];
    const segments = segmentsOf(p.segments, []);
    return segments.length ? [{ name: p.name, repeat: Math.round(p.repeat), segments }] : [];
  });
  return kept.length === saved.length ? kept : null;
}

function missionOf(saved: unknown): Mission | null {
  if (!isRecord(saved) || !isText(saved.name)) return null;
  const columns = [saved.time, saved.rpm, saved.torque];
  const n = Array.isArray(saved.time) ? saved.time.length : 0;
  const whole_ = columns.every((c) => Array.isArray(c) && c.length === n && c.every(isNumber));
  if (!whole_ || n < 2 || n > MOST_INSTANTS) return null;
  const [time, rpm, torque] = columns as number[][];
  // Its instants run forward: a profile whose time goes back is not one.
  if (time.some((t, k) => k > 0 && t <= time[k - 1])) return null;
  return { name: saved.name, time, rpm, torque };
}

function loadSetOf(saved: unknown, fresh: State): LoadItem[] {
  if (!Array.isArray(saved)) return [];
  const items = saved.flatMap((x): LoadItem[] => {
    if (!isRecord(x) || !isText(x.id) || !isText(x.label) || !isText(x.loadKind)) return [];
    const segments = segmentsOf(x.segments, []);
    if (!segments.length) return [];
    const item = { id: x.id, label: x.label, loadKind: x.loadKind, load: like(x.load, fresh.load), segments };
    const phases = phasesOf(x.phases);
    return [{ ...item, ...(phases ? { phases } : {}), mission: missionOf(x.mission) }];
  });
  return items.slice(0, MOST - 1);
}

function motorSetOf(saved: unknown): MotorItem[] {
  if (!Array.isArray(saved)) return [];
  const items = saved.flatMap((x): MotorItem[] => {
    if (!isRecord(x) || !isText(x.id) || !isText(x.label) || !isRecord(x.motor) || !isRecord(x.conditions)) return [];
    const conditions = Object.fromEntries(
      Object.entries(x.conditions).filter(([, v]) => v === null || isNumber(v) || isText(v)),
    ) as MotorItem["conditions"];
    return [{ id: x.id, label: x.label, motor: figures(x.motor), conditions }];
  });
  return items.slice(0, MOST - 1);
}

/** A record of text only, as a part's typed figures are kept: anything else is left out. */
const textsOf = (v: unknown): Record<string, string> =>
  Object.fromEntries(Object.entries(isRecord(v) ? v : {}).filter(([, x]) => isText(x))) as Record<string, string>;

/** The figures of the point the user typed, for the kinds of motor the page has. */
function pointsOf(saved: unknown, setup: Setup): State["pointOf"] {
  if (!isRecord(saved)) return {};
  const out: State["pointOf"] = {};
  for (const kind of Object.keys(setup.motors)) {
    const from = saved[kind];
    if (!isRecord(from)) continue;
    const point: Partial<Point> = {};
    for (const key of POINT_KEYS) {
      const v = from[key];
      if (key === "pwm" ? isText(v) : isNumber(v)) (point as Json)[key] = v;
    }
    out[kind] = point;
  }
  return out;
}

function ownOf(saved: unknown, setup: Setup): State["motorOwn"] {
  if (!isRecord(saved)) return {};
  const kinds = Object.keys(setup.motors).filter((k) => Array.isArray(saved[k]));
  return Object.fromEntries(kinds.map((k) => [k, texts(saved[k])]));
}

/** How the motor's boxes were shown. Kept before the page had the choice, they are shown as
 *  datasheets give them; the figures the engine takes are the ones kept, either way. */
function entryOf(saved: unknown, setup: Setup): MotorEntry {
  const from = isRecord(saved) ? saved : {};
  const constant = isRecord(from.constant) ? from.constant : {};
  return {
    wiring: oneOf(from.wiring, ["line", "phase"] as const, "line"),
    constant: Object.fromEntries(
      Object.keys(setup.motors)
        .filter((k) => constant[k] === "kv" || constant[k] === "kt")
        .map((k) => [k, constant[k] as "kv" | "kt"]),
    ),
  };
}

/** What an earlier version kept one flag for, said the way this one keeps it: there, once
 *  anything of the motor or the point was touched, all of it was the user's own. */
function fromV10(saved: Json): Json {
  if (!saved.motorTouched) return saved;
  const kind = String(saved.kind);
  const conditions = isRecord(saved.conditions) ? saved.conditions : {};
  const motors = isRecord(saved.motors) ? saved.motors : {};
  const edited = texts(saved.motorEdited);
  return {
    ...saved,
    kindPicked: true,
    pointOf: { [kind]: Object.fromEntries(POINT_KEYS.map((k) => [k, conditions[k]])) },
    motorOwn: Object.fromEntries(edited.map((k) => [k, isRecord(motors[k]) ? Object.keys(motors[k]) : []])),
    loadPicked: saved.loadTouched ? "" : saved.loadKind,
  };
}

/** The steps opened. Kept before the page kept them, every step up to the furthest one
 *  opened is taken as opened, as the rail then showed them. */
function visitedOf(saved: Json): number[] {
  const step = whole(saved.step, 0, 4, 0);
  if (Array.isArray(saved.visited)) {
    const kept = saved.visited.filter((k): k is number => isNumber(k) && Number.isInteger(k) && k >= 0 && k <= 4);
    return [...new Set(kept)].sort();
  }
  const furthest = Math.max(whole(saved.reached, 0, 4, 0), step);
  return Array.from({ length: furthest + 1 }, (_, k) => k);
}

/**
 * A saved state held to the page's shape. Returns null when it is not a state at all.
 * `keepDevices`: the list of devices is not final yet, so the saved choice is kept as it is.
 */
function shaped(raw: unknown, setup: Setup, keepDevices = false): State | null {
  const saved = plain(raw);
  if (
    !isRecord(saved) ||
    !isText(saved.kind) ||
    !Object.hasOwn(setup.motors, saved.kind) ||
    !Array.isArray(saved.devices)
  )
    return null;
  const state = drawnFrom(saved, setup, keepDevices);
  return "phases" in saved ? state : asSaved(state);
}

/** A design kept before the applications came, when a load was sized to the motor and the same
 *  names did not yet stand for whole applications of a size of their own: it opens with its
 *  loads exactly as they were saved, the user's own from then on, not swapped for what the
 *  names stand for now. */
function asSaved(state: State): State {
  return {
    ...state,
    loadTouched: state.loadTouched || state.loadKind !== "",
    loadPicked: "",
    loadSet: state.loadSet.map((x) => (x.id.startsWith("own-") ? x : { ...x, id: `own-${x.id}` })),
  };
}

/** A saved state held to the page's shape, field by field. */
function drawnFrom(saved: Json, setup: Setup, keepDevices: boolean): State {
  const fresh = initial(setup);
  const known = new Set(setup.devices.map((d) => d.id));
  const held = (ids: unknown) => texts(ids).filter((id) => keepDevices || known.has(id));
  const focus = isText(saved.focus) && (keepDevices || known.has(saved.focus)) ? saved.focus : null;
  const flat = like(saved, fresh);
  const conditions = like(saved.conditions, fresh.conditions);
  const savedMotors = isRecord(saved.motors) ? saved.motors : {};
  // Kept before the inertia followed the weight on the arm: a load edited then may hold an
  // inertia typed by hand, so it is taken as the user's own.
  if (typeof saved.inertiaOwn !== "boolean") flat.inertiaOwn = saved.loadTouched === true;
  // Kept before the supply followed the device: a battery there was the user's own choice.
  if (typeof saved.supplyOwn !== "boolean") flat.supplyOwn = saved.supply === "battery";
  return {
    ...flat,
    kind: String(saved.kind), // checked by shaped()
    motors: Object.fromEntries(
      Object.entries(fresh.motors).map(([k, start]) => [k, { ...start, ...figures(savedMotors[k]) }]),
    ),
    motorEntry: entryOf(saved.motorEntry, setup),
    conditions: {
      ...conditions,
      cooling: oneOf(conditions.cooling, COOLINGS, fresh.conditions.cooling),
      interface: oneOf(conditions.interface, ["", "pad"] as const, ""),
      edge_limit: oneOf(conditions.edge_limit, EDGE_LIMITS, fresh.conditions.edge_limit),
      sized: oneOf(conditions.sized, ["", "rth_sink", "board_area"] as const, ""),
      sizedFor: longText(isRecord(saved.conditions) ? saved.conditions.sizedFor : "", MOST_SIZING),
    },
    typed: textsOf(saved.typed),
    typedOf: Object.fromEntries(
      Object.entries(isRecord(saved.typedOf) ? saved.typedOf : {}).map(([id, figures]) => [id, textsOf(figures)]),
    ),
    mission: missionOf(saved.mission),
    supply: oneOf(saved.supply, ["one-way", "battery"] as const, fresh.supply),
    load: like(saved.load, fresh.load),
    sink: like(saved.sink, fresh.sink),
    start: like(saved.start, fresh.start),
    map: like(saved.map, fresh.map),
    event: eventOf(saved.event, fresh.event),
    sweep: like(saved.sweep, fresh.sweep),
    segments: segmentsOf(saved.segments, fresh.segments),
    phases: phasesOf(saved.phases),
    loadSet: loadSetOf(saved.loadSet, fresh),
    motorSet: motorSetOf(saved.motorSet),
    pointOf: pointsOf(saved.pointOf, setup),
    motorOwn: ownOf(saved.motorOwn, setup),
    devices: held(saved.devices),
    added: held(saved.added),
    focus,
    focusPicked: saved.focusPicked === true && focus !== null,
    // A step or a tab the page does not have would leave it with nothing to draw.
    step: whole(saved.step, 0, 4, fresh.step),
    reached: Math.max(whole(saved.reached, 0, 4, fresh.reached), whole(saved.step, 0, 4, fresh.step)),
    visited: visitedOf(saved),
    tab: tabOf(saved.tab, fresh.tab),
    compare: oneOf(saved.compare, COMPARES, fresh.compare),
    metric: oneOf(saved.metric, ["loss", "tj", "efficiency"] as const, fresh.metric),
    mapAt: oneOf(saved.mapAt, ["", "motor", "load"] as const, fresh.mapAt),
    pwmPeriods: whole(saved.pwmPeriods, 1, 50, fresh.pwmPeriods),
  };
}

const read = (key: string): unknown => JSON.parse(localStorage.getItem(key) ?? "null");

/** What the last visit left, or a fresh start. What an earlier version of the page kept is
 *  taken over once and then removed, with everything older. */
export function restore(setup: Setup, keepDevices = false): State {
  let state: State | null = null;
  try {
    state = shaped(read(KEY), setup, keepDevices);
    if (!state) {
      const older = plain(read("motionsim.bench.v10"));
      if (isRecord(older)) state = shaped(fromV10(older), setup, keepDevices);
    }
    for (const key of STALE_KEYS) localStorage.removeItem(key);
  } catch {
    /* nothing readable was kept, or nothing can be: start fresh */
  }
  return state ?? initial(setup);
}

/** The version of a setup file this page writes: 3, the file carries the model of each part
 *  brought on the page. The older ones, 1 and 2, still open. */
export const SETUP_VERSION = 3;

/** The state in a setup file, held to the page's shape, or null when the file is not one. */
export function fromSetupFile(data: unknown, setup: Setup): State | null {
  if (!isRecord(data) || data.app !== "MotionSim" || !isRecord(data.state)) return null;
  if (data.setup !== 1 && data.setup !== 2 && data.setup !== SETUP_VERSION) return null;
  const saved = plain(data.state) as Json;
  return shaped(data.setup === 1 ? fromV10(saved) : saved, setup, true);
}

interface Engine {
  bring: (part: KeptPart) => Promise<unknown>;
  setup: () => Promise<Setup>;
  save?: (state: State) => unknown;
}

/**
 * Once the engine in the browser is up after a reload: the parts on the page it came up
 * without are brought again from what this browser kept, once each, and only a part it then
 * still does not have is taken off the page. What is left is saved, so that the page and what
 * a reload reads stay the same. Returns the engine's list as it now stands.
 */
export async function keptBack(state: State, setup: Setup, parts: KeptPart[], engine: Engine): Promise<Setup> {
  const known = (s: Setup) => new Set(s.devices.map((d) => d.id));
  const wanted = new Set([...state.devices, ...state.added]);
  const missing = parts.filter((p) => wanted.has(p.id) && !known(setup).has(p.id));
  let now = setup;
  if (missing.length) {
    for (const part of missing) await engine.bring(part).catch(() => undefined);
    now = await engine.setup();
  }
  const have = known(now);
  const before = state.devices.length + state.added.length;
  state.devices = state.devices.filter((d) => have.has(d));
  state.added = state.added.filter((d) => have.has(d));
  if (state.focus && !have.has(state.focus)) state.focus = null;
  if (state.devices.length + state.added.length !== before) (engine.save ?? saveState)(state);
  return now;
}
