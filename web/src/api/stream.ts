// A search answered a step at a time: each step handed to whoever asked as it finishes, then
// the answer. From the local server it comes as lines of JSON; in the browser, as messages
// from the worker. Whoever stops waiting stops the search itself, in both.

import { answerOf, bodyOf, isRecord, superseded, Unreachable } from "./answers";
import { engineReady, modeNow } from "./transport";
import { askWorker } from "./worker";

/** One line of a streamed answer: a step, or the answer as the address would give it. */
type Line = { probe: unknown } | { status: number; body: unknown };

/** Each whole line of text read so far, and what is left of a line not yet whole. */
export function linesOf(held: string): { lines: string[]; rest: string } {
  const parts = held.split("\n");
  const rest = parts.pop() ?? "";
  return { lines: parts.filter((l) => l.trim() !== ""), rest };
}

/** A line read: a step goes to `onStep`, the answer is handed back. */
function readLine<T>(route: string, text: string, onStep: (step: unknown) => void): { done: T } | null {
  let line: Line;
  try {
    line = JSON.parse(text) as Line;
  } catch {
    throw new Error("the engine sent something unreadable");
  }
  if (!isRecord(line)) throw new Error("the engine sent something unreadable");
  if ("probe" in line) {
    onStep(line.probe);
    return null;
  }
  return { done: answerOf<T>(route, Number(line.status), line.body) };
}

/** The lines of the local server's answer, read as they come. */
async function fromServer<T>(
  route: string,
  data: unknown,
  onStep: (s: unknown) => void,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${route.slice(1)}/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
      signal,
    });
  } catch (e) {
    if (signal?.aborted || (e as Error).name === "AbortError") throw e;
    throw new Unreachable();
  }
  // A request refused before the search began is answered as any other is.
  if (!response.ok || !response.body) return answerOf<T>(route, response.status, await bodyOf(response, signal));
  return readAll<T>(route, response.body.getReader(), onStep, signal);
}

/** Every line of the answer, read as it comes, to the answer at its end. */
async function readAll<T>(
  route: string,
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onStep: (s: unknown) => void,
  signal?: AbortSignal,
): Promise<T> {
  const decoder = new TextDecoder();
  let held = "";
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch (e) {
      if (signal?.aborted) throw superseded();
      throw e;
    }
    held += decoder.decode(chunk.value ?? new Uint8Array(), { stream: !chunk.done });
    const { lines, rest } = linesOf(chunk.done ? `${held}\n` : held);
    held = rest;
    for (const text of lines) {
      const read = readLine<T>(route, text, onStep);
      if (read) {
        // The answer is the last line: what is left (the close) is read to its end, so the
        // request finishes as it should and is never cut off as if it had been stopped.
        void drained(reader);
        return read.done;
      }
    }
    if (chunk.done) throw new Error("the answer was cut short");
  }
}

/** The rest of an answer read and let go: a request stopped after its answer is no fault. */
async function drained(reader: ReadableStreamDefaultReader<Uint8Array>): Promise<void> {
  try {
    while (!(await reader.read()).done) {
      /* nothing more is said after the answer */
    }
  } catch {
    /* stopped once its answer was in: as normal */
  }
}

/** The answer of a search, with each of its steps handed to `onStep` as it finishes. */
export async function streamed<T>(
  route: string,
  data: unknown,
  onStep: (step: unknown) => void,
  signal?: AbortSignal,
): Promise<T> {
  if (modeNow() === "server") return fromServer<T>(route, data, onStep, signal);
  await engineReady();
  const answer = await askWorker(route, data, signal, onStep);
  return answerOf<T>(route, answer.status, answer.body);
}
