// The engine in the browser: loaded into a worker, and handed one request at a time.

import { superseded } from "./answers";
import type { KeptPart } from "./types";

interface Answer {
  status: number;
  body: unknown;
}

/** A request waiting its turn at the engine in the browser, or being answered by it. */
interface Job {
  id: number;
  route: string;
  payload: string;
  signal?: AbortSignal;
  /** A search's steps as each finishes, for a request answered a step at a time. */
  onStep?: (step: unknown) => void;
  settle: (answer: Answer) => void;
  fail: (error: Error) => void;
}

let worker: Worker | null = null;
let next = 1;
let dead: Error | null = null;
const queue: Job[] = [];
let inFlight: Job | null = null;

/** Hand the engine in the browser its next request. One is with it at a time: a request
 *  given up while it waited is never sent, so the engine does not work out what nobody
 *  is waiting for. */
function pump(): void {
  while (!inFlight && queue.length) {
    const job = queue.shift()!;
    if (job.signal?.aborted) {
      job.fail(superseded());
      continue;
    }
    inFlight = job;
    const stream = job.onStep ? { stream: true } : {};
    worker!.postMessage({ id: job.id, route: job.route, payload: job.payload, ...stream });
  }
}

/** The engine in the browser has answered: the answer goes to whoever asked, if they still
 *  wait for it, and the next request has its turn. */
function answered(m: Answer & { id: number }): void {
  const job = inFlight;
  if (!job || job.id !== m.id) return;
  inFlight = null;
  if (job.signal?.aborted) job.fail(superseded());
  else job.settle({ status: m.status, body: m.body });
  pump();
}

/** A step of the search the engine is at, for whoever asked, while they still wait. */
function stepped(m: { id: number; probe?: unknown }): void {
  const job = inFlight;
  if (job?.id === m.id && !job.signal?.aborted) job.onStep?.(m.probe);
}

/** Given up while the engine works on it: a search is told to stop before its next step, and
 *  frees the engine then. Any other request cannot be stopped midway; its answer is dropped. */
function givenUp(job: Job): void {
  job.fail(superseded());
  if (inFlight === job && job.onStep) worker!.postMessage({ cancel: job.id });
}

/** The engine in the browser has stopped: everyone waiting hears so now, and so does
 *  everyone who asks from here on. */
function stopped(why: string): void {
  dead = new Error(`the engine in this browser stopped: ${why}`);
  for (const job of [inFlight, ...queue.splice(0)]) job?.fail(dead);
  inFlight = null;
}

/** One request to the engine in the browser. With `onStep`, it is a search answered a step at
 *  a time, which stops when it is given up. */
export function askWorker(
  route: string,
  data: unknown,
  signal?: AbortSignal,
  onStep?: (step: unknown) => void,
): Promise<Answer> {
  return new Promise<Answer>((settle, fail) => {
    if (dead) return fail(dead);
    if (signal?.aborted) return fail(superseded());
    const job: Job = { id: next++, route, payload: JSON.stringify(data ?? {}), signal, onStep, settle, fail };
    // Whoever gives a request up hears so at once, wherever the request is by then.
    signal?.addEventListener("abort", () => givenUp(job), { once: true });
    queue.push(job);
    pump();
  });
}

/** Start the engine in this page, with the parts this browser kept. The promise settles
 *  when it can answer. */
export function startWorker(onProgress: (text: string, stage: number) => void, parts: KeptPart[]): Promise<void> {
  worker = new Worker(new URL("../engine.worker.ts", import.meta.url));
  const started = new Promise<void>((resolve, reject) => {
    worker!.onmessage = (event: MessageEvent) => {
      const m = event.data as { progress?: string; stage?: number; ready?: boolean; failed?: string } & Answer & {
          id: number;
          probe?: unknown;
        };
      if (m.progress) onProgress(m.progress, m.stage ?? 1);
      else if ("probe" in m) stepped(m);
      else if (m.ready) resolve();
      else if (m.failed) reject(new Error(m.failed));
      else answered(m);
    };
    worker!.onerror = (event) => {
      const why = event.message || "it could not be started";
      reject(new Error(why));
      stopped(why);
    };
  });
  started.catch(() => undefined); // reported by whoever awaits it
  const engineUrl = new URL("engine/motionsim.zip", document.baseURI).href;
  const runtimeUrl = new URL("engine/pyodide/", document.baseURI).href;
  worker.postMessage({ start: { engineUrl, runtimeUrl, parts } });
  return started;
}
