// The engine, running in the browser. This worker loads a Python runtime, the numerical
// libraries and the motionsim package itself, then answers the same requests the local
// server answers, by calling the same Python functions. No second implementation exists.

declare function importScripts(...urls: string[]): void;

interface Python {
  loadPackage(
    names: string[],
    options?: { checkIntegrity?: boolean; errorCallback?: (message: string) => void },
  ): Promise<unknown>;
  unpackArchive(data: Uint8Array, format: string, options: { extractDir: string }): void;
  runPython(code: string): unknown;
  globals: { get(name: string): (...args: unknown[]) => unknown };
}

/** A search the engine answers a step at a time: the next line of it, or null once it is all
 *  said; and a way to stop it between two steps. */
export interface Lines {
  next(): string | null;
  close(): void;
}
declare function loadPyodide(options: { indexURL: string; lockFileURL?: string }): Promise<Python>;

interface Start {
  engineUrl: string;
  runtimeUrl: string;
  parts: { route: string; body: Record<string, string> }[];
}

let call: ((route: string, payload: string) => string) | null = null;
let open: ((route: string, payload: string) => Lines) | null = null;

async function start({ engineUrl, runtimeUrl, parts }: Start): Promise<void> {
  const say = (progress: string, stage: number) => postMessage({ progress, stage, of: 3 });
  // Said plainly: the Python runtime is part of this page; the numerical libraries are
  // fetched from a public file server. Nothing the user enters is sent anywhere.
  say("Starting the Python runtime", 1);
  importScripts(`${runtimeUrl}pyodide.js`);
  const py = await loadPyodide({ indexURL: runtimeUrl, lockFileURL: `${runtimeUrl}pyodide-lock.json` });
  // The numerical libraries come from a public file server, once, and are then kept by
  // the browser. The lock file served with this page names each and carries its hash: a
  // file that was changed on the way is not loaded.
  say("Fetching the numerical libraries from cdn.jsdelivr.net", 2);
  // The loader says a package it could not fetch and goes on without it; the engine would
  // then answer every request that needs it with a missing module. It stops here instead,
  // naming what did not arrive, and the page says the engine could not start.
  const missed: string[] = [];
  await py.loadPackage(["numpy", "scipy", "pydantic", "pyyaml"], {
    checkIntegrity: true,
    errorCallback: (message) => missed.push(message),
  });
  try {
    py.runPython("import numpy, scipy, scipy.optimize, scipy.signal, scipy.sparse, pydantic, yaml");
  } catch (error) {
    const why = error instanceof Error ? (error.message.split("\n").pop() ?? "") : String(error);
    throw new Error(`the numerical libraries did not all arrive (${[why, ...missed].join("; ")})`, {
      cause: error,
    });
  }
  say("Loading the engine", 3);
  const archive = await (await fetch(engineUrl)).arrayBuffer();
  py.unpackArchive(new Uint8Array(archive), "zip", { extractDir: "/engine" });
  py.runPython(`
import sys
sys.path.insert(0, "/engine")
from pathlib import Path
from motionsim import page
_workspace = page.Workspace(Path("/devices"))
def _call(route, payload):
    return page.call(route, payload, _workspace)
def _stream(route, payload):
    return page.stream_call(route, payload, _workspace)
def _next(lines):
    return next(lines, None)
def _close(lines):
    lines.close()
`);
  const python = py.globals.get("_call");
  call = (route, payload) => python(route, payload) as string;
  const [stream, step, stop] = ["_stream", "_next", "_close"].map((name) => py.globals.get(name));
  open = (route, payload) => {
    const lines = stream(route, payload) as { destroy?: () => void };
    const done = () => lines.destroy?.();
    return {
      next: () => {
        const line = step(lines) as string | null | undefined;
        if (line == null) done();
        return line ?? null;
      },
      close: () => {
        stop(lines);
        done();
      },
    };
  };
  // The parts the user brought on an earlier visit live in this browser only: each is
  // brought again, in the order it was, so that measurements find the part they belong to.
  for (const part of parts) call(part.route, JSON.stringify(part.body));
  postMessage({ ready: true });
}

/** One request, answered. Whatever goes wrong in the engine is an answer too: a request
 *  that is never answered leaves the page waiting for ever. */
export function answerTo(message: { id: number; route: string; payload: string }): object {
  try {
    if (!call) throw new Error("the engine has not started");
    const answer = JSON.parse(call(message.route, message.payload)) as { status: number; body: unknown };
    return { id: message.id, status: answer.status, body: answer.body };
  } catch (error) {
    const why = error instanceof Error ? error.message : String(error);
    return { id: message.id, status: 500, body: { error: `the engine failed: ${why.split("\n").pop()}` } };
  }
}

/** For the tests: put a stand-in where the Python engine goes. */
export function setEngine(engine: typeof call, lines: typeof open = null): void {
  call = engine;
  open = lines;
}

/** The searches the page has given up, by their number: each is stopped before its next step. */
const givenUp = new Set<number>();

/** A pause in which a message from the page, telling a search to stop, is heard. */
const pause = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

/** A search, answered a step at a time: each step is posted as it finishes, and between two
 *  the search stops if the page has given it up. Its last line is the answer, as `answerTo`
 *  would have given it; a search stopped answers that it was. */
export async function streamTo(message: { id: number; route: string; payload: string }): Promise<object> {
  const said = (why: string) => ({ id: message.id, status: 500, body: { error: `the engine failed: ${why}` } });
  if (!open) return said("the engine has not started");
  let lines: Lines;
  try {
    lines = open(message.route, message.payload);
  } catch (error) {
    return said(error instanceof Error ? (error.message.split("\n").pop() ?? "") : String(error));
  }
  try {
    for (;;) {
      await pause();
      if (givenUp.delete(message.id)) {
        lines.close();
        return { id: message.id, status: 499, body: { error: "given up" } };
      }
      const line = lines.next();
      if (line === null) return said("the search ended with no answer");
      const read = JSON.parse(line) as { probe?: unknown; status?: number; body?: unknown };
      if (!("probe" in read)) return { id: message.id, status: read.status, body: read.body };
      postMessage({ id: message.id, probe: read.probe });
    }
  } catch (error) {
    return said(error instanceof Error ? (error.message.split("\n").pop() ?? "") : String(error));
  }
}

onmessage = (event: MessageEvent) => {
  const message = event.data as {
    start?: Start;
    cancel?: number;
    stream?: boolean;
    id: number;
    route: string;
    payload: string;
  };
  if (message.start) {
    start(message.start).catch((error) => postMessage({ failed: String((error as Error)?.message ?? error) }));
    return;
  }
  if (message.cancel !== undefined) {
    givenUp.add(message.cancel);
    return;
  }
  if (message.stream) {
    void streamTo(message).then((answer) => postMessage(answer));
    return;
  }
  postMessage(answerTo(message));
};
