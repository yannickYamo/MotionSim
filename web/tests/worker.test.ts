import { describe, expect, it, vi } from "vitest";

vi.stubGlobal("postMessage", () => undefined);
vi.stubGlobal("onmessage", null); // the worker sets its own; outside a worker there is none to set
const { answerTo, setEngine } = await import("../src/engine.worker");

describe("the worker's answer to one request", () => {
  it("is the engine's answer, under the request's own number", () => {
    setEngine((route, payload) => JSON.stringify({ status: 200, body: { route, got: JSON.parse(payload) } }));
    expect(answerTo({ id: 7, route: "/api/stage", payload: '{"a":1}' })).toEqual({
      id: 7,
      status: 200,
      body: { route: "/api/stage", got: { a: 1 } },
    });
  });
  it("is an answer when the engine throws, so that no request is left waiting", () => {
    setEngine(() => {
      throw new Error("Traceback (most recent call last):\n  File x\nMemoryError: out of memory");
    });
    expect(answerTo({ id: 8, route: "/api/cycle", payload: "{}" })).toEqual({
      id: 8,
      status: 500,
      body: { error: "the engine failed: MemoryError: out of memory" },
    });
  });
  it("is an answer when what the engine hands back cannot be read", () => {
    setEngine(() => "not json");
    expect(answerTo({ id: 9, route: "/api/cycle", payload: "{}" })).toMatchObject({ id: 9, status: 500 });
  });
  it("is an answer when the engine has not started", () => {
    setEngine(null);
    expect(answerTo({ id: 1, route: "/api/stage", payload: "{}" })).toEqual({
      id: 1,
      status: 500,
      body: { error: "the engine failed: the engine has not started" },
    });
  });
});

describe("the engine starting in the browser", () => {
  it("fails, naming the library, when one of the numerical libraries did not arrive", async () => {
    const posted: object[] = [];
    vi.stubGlobal("postMessage", (m: object) => posted.push(m));
    vi.stubGlobal("importScripts", () => undefined);
    vi.stubGlobal("fetch", () => Promise.resolve({ arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)) }));
    // The runtime's loader says a package failed and goes on, as Pyodide's does when a
    // download breaks: the module is then missing at the first request that needs it.
    const python = {
      loadPackage: (_names: string[], options?: { errorCallback?: (m: string) => void }) => {
        options?.errorCallback?.("Couldn't load package from URL https://cdn.example/scipy.whl");
        return Promise.resolve();
      },
      unpackArchive: () => undefined,
      runPython: (code: string) => {
        if (/import .*scipy/.test(code)) throw new Error("ModuleNotFoundError: No module named 'scipy'");
      },
      globals: { get: () => () => "" },
    };
    vi.stubGlobal("loadPyodide", () => Promise.resolve(python));
    (globalThis as unknown as { onmessage: (e: MessageEvent) => void }).onmessage({
      data: { start: { engineUrl: "e", runtimeUrl: "r/", parts: [] } },
    } as MessageEvent);
    await vi.waitFor(() => expect(posted.some((m) => "failed" in m || "ready" in m)).toBe(true));
    expect(posted).not.toContainEqual({ ready: true });
    const failed = posted.find((m) => "failed" in m) as { failed: string };
    expect(failed.failed).toMatch(/scipy/);
    vi.stubGlobal("postMessage", () => undefined);
  });
});
