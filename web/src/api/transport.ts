// Where the engine runs, and how a request reaches it.
//
// Served by `motionsim serve`, the engine is on this machine and answers over HTTP. Opened as
// a plain web page, there is no server: the engine is loaded into the browser itself and
// answers from a worker. The page cannot tell the difference beyond the first few seconds.

import { answerOf, bodyOf, Unreachable } from "./answers";
import type { Setup } from "./types";
import { askWorker } from "./worker";

export type Mode = "server" | "browser";

let mode: Mode = "server";
let ready: Promise<void> = Promise.resolve();

export const modeNow = (): Mode => mode;

/** The engine is the local server's, or the browser's own once `started` settles. */
export function useEngine(where: Mode, started?: Promise<void>): void {
  mode = where;
  if (started) ready = started;
}

/** Settles when the engine can answer. */
export const engineReady = (): Promise<void> => ready;

export async function send<T>(route: string, data: unknown, signal?: AbortSignal, method = "POST"): Promise<T> {
  if (mode === "server") {
    const post = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
      signal,
    };
    let response: Response;
    try {
      response = await fetch(route.slice(1), method === "GET" ? { signal } : post);
    } catch (e) {
      // A request given up is the asker's own doing; any other failure to fetch is the
      // server not being there, whatever words the browser has for it.
      if (signal?.aborted || (e as Error).name === "AbortError") throw e;
      throw new Unreachable();
    }
    return answerOf<T>(route, response.status, await bodyOf(response, signal));
  }
  await ready;
  const answer = await askWorker(route, data, signal);
  return answerOf<T>(route, answer.status, answer.body);
}

/** Where the engine is, as the small file beside the page says: true for a local server,
 *  false for the browser, null where there is no such file (the development server). */
export async function whereEngineIs(): Promise<boolean | null> {
  try {
    const said = await fetch("engine/mode.json");
    if (said.ok) return Boolean(((await said.json()) as { server?: unknown }).server);
  } catch {
    /* no such file: ask the server itself */
  }
  return null;
}

/** The first screen from the local server, or null when there is none here. */
export async function fromServer(): Promise<Setup | null> {
  try {
    const response = await fetch("api/setup");
    if (response.ok && (response.headers.get("Content-Type") ?? "").includes("json")) {
      return answerOf<Setup>("/api/setup", 200, await response.json());
    }
  } catch {
    /* no server here */
  }
  return null;
}
