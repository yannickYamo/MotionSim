// The page's only door to the engine. Every number on screen comes through here.

export type Level = "ok" | "caution" | "fail";
export interface Check { level: Level; topic: string; message: string }
export interface Field { key: string; label: string; unit: string; help: string; options: string[] | null }
export interface MotorKind {
  family: string; label: string; about: string; start: Record<string, number>;
  values: Record<string, string | number>; fields: Field[];
  fixed_scheme: string | null; default_pwm: string;
  optional: { key: string; label: string; unit: string; help: string }[];
}
export interface DeviceSummary {
  id: string; name: string; technology: string; v_max: number; i_nominal: number; tj_max: number;
  positions: number; integrated_driver: boolean; example: boolean; switching: string;
  support: string; needs_gate_drive: boolean;
}
export interface Setup {
  motors: Record<string, MotorKind>; pwm: string[]; load: Record<string, unknown>;
  profile: { name?: string; start_angle_deg?: number; segments: Segment[] };
  devices: DeviceSummary[]; can_read: boolean;
}
export interface Segment { duration: number; speed_start: number; speed_end: number }
export interface Role { name: string; count: number; forward: number; reverse: number; switching: number }
export interface Stage {
  positions: number; i_peak: number; p_shaft: number; p_electrical: number; p_motor_loss: number;
  scheme: string; summary: { label: string; value: number; unit: string }[]; notes: string[]; roles: Role[];
}
export interface Advice { lines: string[]; v_minimum: number; v_comfortable: number; i_peak: number; i_stall: number | null }
export interface Losses {
  conduction: number; turn_on: number; turn_off: number; dead_time: number; recovery: number;
  diode_conduction: number; diode_recovery: number; total: number;
}
export interface Position extends Losses { name: string; count: number; tj: number; tj_switch: number; tj_diode: number }
export interface Result {
  loss: number; conduction: number; switching: number; efficiency: number | null; tj_peak: number;
  tj_range: [number, number] | null; tj_max: number; t_case: number; validity: string;
  notes: string[]; limits: string[]; assumptions: string[]; warnings: string[];
  hottest: Losses; positions: Position[];
}
export interface GateUsed { kind: "chosen" | "given" | "datasheet" | "built in"; v_drive: number | null; rg_on: number | null; rg_off: number | null; lines: string[] }
/** One PWM period of the hottest switch at the instant it works hardest. */
export interface SwitchingPeriod { current: number; duty: number; p_on: number; e_on: number; e_off: number; f_sw: number; position: string }
export interface Candidate {
  gate: GateUsed;
  pwm: SwitchingPeriod | null;
  link: { capacitor_rms: number | null; ripple_pp: number | null } | null;
  id: string; name: string; technology: string; level: Level; problem: string | null; fix: string;
  result: Result | null; stall_tj: number | null; efficiency: number | null; checks: Check[]; needs: string[];
}
export interface Proposal { candidates: Candidate[]; explain: string[] }
export interface Cycle {
  time: number[]; tj: (number | null)[]; steady: (number | null)[]; t_sink: number[];
  rpm: number[]; torque: number[]; p_stage: (number | null)[]; p_dc: (number | null)[];
  summary: Record<string, number | null>; checks: Check[];
  i_peak: (number | null)[];
  life: { repeats: number | null; hours: number | null; swing: number; swing_mean: number; swing_share: number; swings: number; chip: string; within_turn: boolean };
  start: { applies: "method" | "flux" | "none"; method: string; current?: number; align_time?: number; handover_rpm?: number; flux_time?: number; lines: string[] };
  inrush: { energy: number; peak: number | null; time: number | null } | null;
}
export interface MapGrid {
  rpm: number[]; torque: number[]; loss: (number | null)[][]; tj: (number | null)[][];
  efficiency: (number | null)[][]; reason: string[][]; tj_max: number;
}
export interface Recommendation { topic: string; value: Record<string, number>; lines: string[] }
export interface ReadOutcome {
  device: DeviceSummary;
  read: { values: number; curves: number; from_images?: number; flagged: { what: string; page: number; why: string }[] };
}

/** An input the engine says cannot work: the reason, and what to change. */
export class Refused extends Error {
  constructor(public reason: string, public fix: string, public field: string) { super(reason); }
}

// ---------- where the engine runs ----------
//
// Served by `motionsim serve`, the engine is on this machine and answers over HTTP. Opened as
// a plain web page, there is no server: the engine is loaded into the browser itself and
// answers from a worker. The page cannot tell the difference beyond the first few seconds.

export type Mode = "server" | "browser";
const STORED = "motionsim.devices.v1";

let mode: Mode = "server";
let worker: Worker | null = null;
let ready: Promise<void> = Promise.resolve();
let next = 1;
const waiting = new Map<number, (answer: { status: number; body: any }) => void>();

function storedDevices(): { name: string; text: string }[] {
  try {
    return JSON.parse(localStorage.getItem(STORED) ?? "[]");
  } catch {
    return [];
  }
}

function answerOf<T>(status: number, body: any): T {
  if (status === 422) throw new Refused(body.refused, body.fix ?? "", body.field ?? "");
  if (status !== 200) throw new Error(body?.error ?? `the engine answered ${status}`);
  return body as T;
}

/** What a device can hold at a point: the torque, what stops it, and where it is then. */
export interface LimitRow { torque: number; why: string; tj: number | null; current: number | null }
export interface Capability {
  rpm: number[]; edge: LimitRow[];
  design: LimitRow & { rpm: number; share: number | null; power: number; rated: number };
  f_sw: number[]; by_f_sw: LimitRow[]; t_sink: number[]; by_t_sink: LimitRow[];
}
export interface Largest { scale: number; open: boolean; why: string; peak: number | null; tj_max: number | null }

/** A kind of load a motor usually drives, sized from the motor's design point. */
export interface LoadPreset {
  id: string; label: string; about: string; link: string; fields: string[]; start_angle_deg: number;
  load: Record<string, any>; segments: { duration: number; speed_start: number; speed_end: number }[];
}

/** For a device: the supply it suits, and how each kind of motor fits it. */
export interface Suggest {
  v_supply: number;
  motors: Record<string, { fit: "recommended" | "suits" | "unusual"; why: string; values: Record<string, string | number>; start: { v_dc: number; rpm: number; torque: number; f_sw: number } }>;
}

/** One table of a device model: a value against current, one curve a temperature. */
export interface ModelTable {
  unit: string; basis: string; assumption: string | null; source: string | null; page: number | null;
  curves: { tj: number; x: number[]; y: number[] }[];
}
/** A device model's tables, and what the reader took from the datasheet it came from. */
export interface Reading {
  summary: DeviceSummary;
  conduction: ModelTable | null; e_on: ModelTable | null; e_off: ModelTable | null;
  reverse: ModelTable | null; diode: ModelTable | null; e_rr: ModelTable | null;
  reading: {
    document: string; pages: number; from_images: number;
    values: { what: string; printed: string; at: string; page: number; flags: string[] }[];
    figures: { what: string; label: string; page: number; tj: number | null; points: number; flags: string[]; notes: string[]; within: number | null; method: string }[];
  } | null;
}

async function send<T>(route: string, data: unknown, signal?: AbortSignal, method = "POST"): Promise<T> {
  if (mode === "server") {
    const response = await fetch(route.slice(1), method === "GET" ? { signal } : {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data), signal,
    });
    const body = await response.json().catch(() => ({ error: "the engine sent something unreadable" }));
    return answerOf<T>(response.status, body);
  }
  await ready;
  if (signal?.aborted) throw new DOMException("superseded", "AbortError");
  const id = next++;
  const answer = await new Promise<{ status: number; body: any }>((resolve) => {
    waiting.set(id, resolve);
    worker!.postMessage({ id, route, payload: JSON.stringify(data) });
  });
  if (signal?.aborted) throw new DOMException("superseded", "AbortError");
  return answerOf<T>(answer.status, answer.body);
}

/**
 * Find the engine. Returns what the first screen needs straight away, and a promise that
 * settles when the engine can answer. `onProgress` hears what the engine is doing meanwhile.
 */
export async function boot(onProgress: (text: string) => void): Promise<{ mode: Mode; setup: Setup; ready: Promise<void> }> {
  try {
    const response = await fetch("api/setup");
    if (response.ok && (response.headers.get("Content-Type") ?? "").includes("json")) {
      mode = "server";
      return { mode, setup: (await response.json()) as Setup, ready };
    }
  } catch {
    /* no server here: the engine runs in this page */
  }
  mode = "browser";
  const setup = (await (await fetch("engine/setup.json")).json()) as Setup;
  worker = new Worker(new URL("./engine.worker.ts", import.meta.url));
  ready = new Promise<void>((resolve, reject) => {
    worker!.onmessage = (event) => {
      const m = event.data;
      if (m.progress) onProgress(m.progress);
      else if (m.ready) resolve();
      else if (m.failed) reject(new Error(m.failed));
      else if (waiting.has(m.id)) { waiting.get(m.id)!(m); waiting.delete(m.id); }
    };
    worker!.onerror = (event) => reject(new Error(event.message || "the engine could not start"));
  });
  ready.catch(() => undefined); // reported by whoever awaits it
  worker.postMessage({ start: { engineUrl: new URL("engine/motionsim.zip", document.baseURI).href, devices: storedDevices() } });
  return { mode, setup, ready };
}

export const api = {
  mode: () => mode,
  setup: () => send<Setup>("/api/setup", {}, undefined, "GET"),
  stage: (d: unknown, s?: AbortSignal) => send<{ stage: Stage; advice: Advice }>("/api/stage", d, s),
  proposal: (d: unknown, s?: AbortSignal) => send<Proposal>("/api/proposal", d, s),
  cycle: (d: unknown, s?: AbortSignal) => send<Cycle>("/api/cycle", d, s),
  map: (d: unknown, s?: AbortSignal) => send<MapGrid>("/api/map", d, s),
  recommend: (d: unknown, s?: AbortSignal) => send<{ items: Recommendation[] }>("/api/recommend", d, s),
  /** Add a device file. In the browser it is kept in this browser and sent nowhere. */
  addDevice: async (file: File) => {
    const device = { name: file.name, text: await file.text() };
    const answer = await send<{ device: DeviceSummary }>("/api/device", device);
    if (mode === "browser") {
      const kept = storedDevices().filter((d) => d.name !== device.name);
      try { localStorage.setItem(STORED, JSON.stringify([...kept, device])); } catch { /* it lasts this visit only */ }
    }
    return answer;
  },
  /** Put the user's own double-pulse measurements in place of a device's datasheet switching energy. */
  addMeasurement: async (deviceId: string, file: File) => {
    const answer = await send<{ device: DeviceSummary }>("/api/measure", { device: deviceId, name: file.name, text: await file.text() });
    return answer;
  },
  /** Read a datasheet PDF. Only where a local server holds the user's key. */
  loads: (kind: string, rpm: number, torque: number, v_dc: number) => send<{ loads: LoadPreset[] }>("/api/loads", { kind, rpm, torque, v_dc }),
  capability: (d: unknown) => send<Capability>("/api/capability", d),
  largest: (d: unknown) => send<Largest>("/api/largest", d),
  suggest: (device: string) => send<Suggest>("/api/suggest", { device }),
  reading: (id: string) => send<Reading>(`/api/device/${encodeURIComponent(id)}`, null, undefined, "GET"),
  read: async (file: File) => {
    const response = await fetch(`api/read?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
    const body = await response.json().catch(() => ({ error: "the engine sent something unreadable" }));
    return answerOf<ReadOutcome>(response.status, body);
  },
};
