// The page's only door to the engine. Every number on screen comes through here.

import { answerOf, bodyOf } from "./api/answers";
import { forget, keep, keeps, storedParts } from "./api/kept";
import { engineReady, fromServer, modeNow, send, useEngine, whereEngineIs } from "./api/transport";
import type { Mode } from "./api/transport";
import { streamed } from "./api/stream";
import type { Advice, Capability, Cycle, DeviceSummary, KeptPart, Largest, LoadPreset, MapGrid } from "./api/types";
import type { Probe } from "./api/types";
import type { CoolingOffer, Proposal, Reading, ReadOutcome, Recommendation, Setup, Stage, Suggest } from "./api/types";
import type { SwitchingEvent } from "./api/types";
import { startWorker } from "./api/worker";

export * from "./api/types";
export {
  answerOf,
  bodyOf,
  failureOf,
  NotWorkedOut,
  notRefused,
  Refused,
  UNREACHABLE,
  Unreachable,
} from "./api/answers";
export { partsOf, storedParts } from "./api/kept";
export type { Mode } from "./api/transport";

/**
 * Find the engine. Returns what the first screen needs straight away, and a promise that
 * settles when the engine can answer. `onProgress` hears what the engine is doing meanwhile.
 * A page served by the local server never falls back to the engine in the browser: a
 * server that has stopped is said to have stopped.
 */
export async function boot(
  onProgress: (text: string, stage: number) => void,
): Promise<{ mode: Mode; setup: Setup; ready: Promise<void> }> {
  const server = await whereEngineIs();
  if (server !== false) {
    const setup = await fromServer();
    if (setup) {
      useEngine("server");
      return { mode: "server", setup, ready: engineReady() };
    }
    if (server) throw new Error("The local engine did not answer. Check that motionsim serve is still running.");
  }
  useEngine("browser");
  const setup = answerOf<Setup>("/api/setup", 200, await (await fetch("engine/setup.json")).json());
  useEngine("browser", startWorker(onProgress, storedParts()));
  return { mode: "browser", setup, ready: engineReady() };
}

type Brought = { device: DeviceSummary };

export const api = {
  /** Take a part out of what this browser keeps, so it is not brought back on the next visit. */
  forget: (id: string) => forget(id),
  mode: () => modeNow(),
  /** Keep a part again that was taken off, as it was kept before and where it was. */
  remember: (part: KeptPart, at?: number) => keep(part, at),
  /** Bring a part again from the request that first brought it, as a setup file holds it. */
  bring: async (part: KeptPart) => {
    const answer = await send<Brought>(part.route, part.body);
    keep({ ...part, id: answer.device.id });
    return answer;
  },
  /** Whether what was brought so far is kept for the next visit. False once the browser
   *  has refused to keep a part: it then lasts this visit only. */
  keeps: () => keeps(),
  setup: () => send<Setup>("/api/setup", {}, undefined, "GET"),
  stage: (d: unknown, s?: AbortSignal) => send<{ stage: Stage; advice: Advice }>("/api/stage", d, s),
  proposal: (d: unknown, s?: AbortSignal) => send<Proposal>("/api/proposal", d, s),
  cycle: (d: unknown, s?: AbortSignal) => send<Cycle>("/api/cycle", d, s),
  map: (d: unknown, s?: AbortSignal) => send<MapGrid>("/api/map", d, s),
  recommend: (d: unknown, s?: AbortSignal) => send<{ items: Recommendation[] }>("/api/recommend", d, s),
  /** Add a device file. In the browser it is kept in this browser and sent nowhere. */
  addDevice: async (file: File) => {
    const body = { name: file.name, text: await file.text() };
    const answer = await send<Brought>("/api/device", body);
    keep({ id: answer.device.id, route: "/api/device", body });
    return answer;
  },
  /** A part typed in from its datasheet figures. The device file it makes is handed back. */
  addTyped: async (figures: Record<string, string>) => {
    const answer = await send<Brought & { name: string; text: string }>("/api/typed", { figures });
    keep({ id: answer.device.id, route: "/api/device", body: { name: answer.name, text: answer.text } });
    return answer;
  },
  /** Put the user's own double-pulse measurements in place of a device's datasheet switching
   *  energy. The part this makes is kept like any other, after the part it was made from. */
  addMeasurement: async (deviceId: string, file: File) => {
    const body = { device: deviceId, name: file.name, text: await file.text() };
    const answer = await send<Brought>("/api/measure", body);
    keep({ id: answer.device.id, route: "/api/measure", body });
    return answer;
  },
  loads: (kind: string, rpm: number, torque: number, v_dc: number, motor?: Record<string, string | number>) =>
    send<{ loads: LoadPreset[] }>("/api/loads", { kind, rpm, torque, v_dc, motor }),
  capability: (d: unknown) => send<Capability>("/api/capability", d),
  /** How much heavier the load could be, each probe of the search handed to `onProbe` as it
   *  finishes. `s` stops the search itself, on the local server and in the browser alike,
   *  before its next probe. */
  largest: (d: unknown, onProbe: (p: Probe) => void, s?: AbortSignal) =>
    streamed<Largest>("/api/largest", d, (p) => onProbe(p as Probe), s),
  suggest: (device: string) => send<Suggest>("/api/suggest", { device }),
  /** The heatsink or the board the chosen cooling needs, for a box left empty. */
  cooling: (d: unknown, s?: AbortSignal) => send<CoolingOffer>("/api/cooling", d, s),
  /** One switching event of the hottest switch, through time: asked for only once it is opened. */
  event: (d: unknown, s?: AbortSignal) => send<SwitchingEvent>("/api/event", d, s),
  /** The whole design as a report in Markdown. */
  report: (d: unknown) => send<{ markdown: string }>("/api/report", d),
  /** Whether a motor as described fits a device, before any design point is set. */
  fit: (d: unknown) => send<{ level: string; lines: { level: string; text: string }[] }>("/api/fit", d),
  /** A device's model and what was read for it. Nothing is sent with the question: the
   *  engine in the browser is handed an empty record, which it takes as that. */
  reading: (id: string) => send<Reading>(`/api/device/${encodeURIComponent(id)}`, {}, undefined, "GET"),
  /** Read a datasheet PDF. Only where a local server holds the user's key. */
  read: async (file: File) => {
    const response = await fetch(`api/read?name=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
    return answerOf<ReadOutcome>("/api/read", response.status, await bodyOf(response));
  },
};
