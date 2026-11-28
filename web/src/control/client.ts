// The lab's requests: the control addresses of the local engine, and the local store. All
// of it is worked out by the engine; nothing here simulates anything.

import { Refused, Unreachable } from "../api/answers";
import { streamed } from "../api/stream";
import type {
  Exploration,
  Kept,
  Loops,
  Phrased,
  Presets,
  Quality,
  ReadWords,
  Run,
  RunProbe,
  Sweep,
  Verdict,
} from "./types";
import { inWords } from "./problemwords";
import type { Problem } from "./store";

/** The address is not in this build of the engine: the page is newer than its server. */
export class Missing extends Error {
  constructor(route: string) {
    super(`${route} is not in this build of the engine`);
  }
}

const text = (v: unknown): string => (typeof v === "string" ? v : "");

async function ask<T>(route: string, method: string, data?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(route.slice(1), {
      method,
      signal,
      ...(data === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }),
    });
  } catch (e) {
    if (signal?.aborted || (e as Error).name === "AbortError") throw e;
    throw new Unreachable();
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  const b = (typeof body === "object" && body !== null ? body : {}) as Record<string, unknown>;
  if (response.status === 404) throw new Missing(route);
  if (response.status === 422)
    throw new Refused(text(b.refused) || "the engine refused this", text(b.fix), text(b.field));
  if (response.status !== 200) throw new Error(text(b.error) || `the engine answered ${response.status}`);
  return body as T;
}

/** A failure as the lab says it: a refusal with its field, or null for what is not one. */
export const problemOf = (e: unknown): Problem | null =>
  e instanceof Refused ? inWords({ reason: e.reason, fix: e.fix, field: e.field }) : null;

export const aborted = (e: unknown): boolean => (e as Error)?.name === "AbortError";

/** A streamed address that this build of the engine does not have answers as no address. */
const missingStream = (e: unknown): boolean => /no such address/.test(String((e as Error)?.message));

const kindPath = (kind: string, id?: string) => `/api/store/${kind}${id ? `/${encodeURIComponent(id)}` : ""}`;

export const control = {
  presets: (d: unknown, s?: AbortSignal) => ask<Presets>("/api/control/presets", "POST", d, s),
  loops: (d: unknown, s?: AbortSignal) => ask<Loops>("/api/control/loops", "POST", d, s),
  run: (d: unknown, s?: AbortSignal) => ask<Run>("/api/control/run", "POST", d, s),
  /** A run with what has come of it handed over as it goes. */
  runStreamed: (d: unknown, onProbe: (p: RunProbe) => void, s?: AbortSignal) =>
    streamed<Run>("/api/control/run", d, (p) => onProbe(p as RunProbe), s),
  explorations: (d: unknown, s?: AbortSignal) =>
    ask<{ explorations?: Exploration[]; reads?: ReadWords; groups?: string[] }>(
      "/api/control/explorations",
      "POST",
      d,
      s,
    ),
  /** A sweep, each of its variants handed over as it is worked out. */
  async sweep(d: unknown, onProbe: (step: unknown) => void, s?: AbortSignal): Promise<Sweep> {
    try {
      return await streamed<Sweep>("/api/control/sweep", d, onProbe, s);
    } catch (e) {
      if (missingStream(e)) throw new Missing("/api/control/sweep");
      throw e;
    }
  },
  /** A run's verdict judged again, against the figures of a run before. */
  verdict: (d: { quality: Quality; before?: Quality }, s?: AbortSignal) =>
    ask<Verdict>("/api/control/verdict", "POST", d, s),
  /** The verdict's summary phrased by the language model set up: the program that serves the
   *  page alone has it (Missing elsewhere). */
  phrase: (d: { quality: Quality; before?: Quality }, s?: AbortSignal) =>
    ask<Phrased>("/api/control/phrase", "POST", d, s),
  /** The scheme's control law as C, with the replay that shows it steps as the simulation does. */
  exportC: <T>(d: unknown, s?: AbortSignal) => ask<T>("/api/control/export_c", "POST", d, s),
  /** The C with its port to a microcontroller, written by the language model set up: the program
   *  that serves the page alone has it (Missing elsewhere). */
  exportPort: <T>(d: unknown, s?: AbortSignal) => ask<T>("/api/control/export_port", "POST", d, s),
  kept: async (kind: string) => (await ask<{ items: Kept[] }>(kindPath(kind), "GET")).items ?? [],
  keep: (kind: string, id: string, doc: unknown) => ask<Kept>(kindPath(kind, id), "PUT", doc),
  bring: async <T>(kind: string, id: string) => (await ask<{ doc: T }>(kindPath(kind, id), "GET")).doc,
  drop: (kind: string, id: string) => ask<unknown>(kindPath(kind, id), "DELETE"),
};
