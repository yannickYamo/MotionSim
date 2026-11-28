// A search answered a step at a time, the largest load: from the local server as lines of
// JSON, and from the engine in the browser as messages, each stopped for real when given up.
import { beforeEach, describe, expect, it, vi } from "vitest";

const tick = () => new Promise((r) => setTimeout(r, 5));
const probe = (scale: number) => ({
  scale,
  passes: true,
  full: false,
  why: "",
  peak: 50,
  tj_max: 150,
  low: 1,
  high: 2,
});
const answer = { scale: 2.69, open: false, why: "too hot", peak: 140, tj_max: 150 };

/** A body read in the pieces it is given in, as a network hands it over. */
function body(pieces: string[]) {
  const bytes = pieces.map((p) => new TextEncoder().encode(p));
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const b of bytes) controller.enqueue(b);
      controller.close();
    },
  });
}

describe("lines read as they come", () => {
  it("are whole lines only, with what is left of one kept for the next piece", async () => {
    const { linesOf } = await import("../src/api/stream");
    expect(linesOf('{"a":1}\n{"b"')).toEqual({ lines: ['{"a":1}'], rest: '{"b"' });
    expect(linesOf("\n\n")).toEqual({ lines: [], rest: "" });
  });
});

describe("the largest load from a local server", () => {
  let posted: { url: string; init?: RequestInit }[] = [];
  let reply: () => unknown;
  beforeEach(() => {
    vi.resetModules();
    posted = [];
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
      posted.push({ url, init });
      if (url === "engine/mode.json")
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ server: true }) });
      const setup = { devices: [], motors: {}, profile: {}, load: {} };
      const headers = { get: () => "application/json" };
      if (url === "api/setup")
        return Promise.resolve({ ok: true, status: 200, headers, json: () => Promise.resolve(setup) });
      return Promise.resolve(reply());
    });
  });
  const boot = async () => {
    const mod = await import("../src/api");
    await mod.boot(() => undefined);
    return mod;
  };

  it("hands each probe on as its line comes, a line split across pieces too, then the answer", async () => {
    const lines = [{ probe: probe(1) }, { probe: probe(2) }, { status: 200, body: answer }].map((x) =>
      JSON.stringify(x),
    );
    const text = `${lines.join("\n")}\n`;
    reply = () => ({ ok: true, status: 200, body: body([text.slice(0, 20), text.slice(20, 75), text.slice(75)]) });
    const { api } = await boot();
    const seen: number[] = [];
    await expect(api.largest({ device: "x" }, (p) => seen.push(p.scale))).resolves.toEqual(answer);
    expect(seen).toEqual([1, 2]);
    expect(posted.at(-1)!.url).toBe("api/largest/stream");
  });
  it("reads the answer to its end once its last line is in, so the request is never cut off", async () => {
    const text = `${JSON.stringify({ status: 200, body: answer })}\n`;
    let pulls = 0;
    let cancelled = false;
    // Pulled only as it is read: the close is read only by a reader that reads past the answer.
    const stream = new ReadableStream<Uint8Array>(
      {
        pull(controller) {
          pulls += 1;
          if (pulls === 1) controller.enqueue(new TextEncoder().encode(text));
          else controller.close();
        },
        cancel() {
          cancelled = true;
        },
      },
      { highWaterMark: 0 },
    );
    reply = () => ({ ok: true, status: 200, body: stream });
    const { api } = await boot();
    await expect(api.largest({}, () => undefined)).resolves.toEqual(answer);
    await new Promise((r) => setTimeout(r, 20));
    expect(pulls).toBe(2);
    expect(cancelled).toBe(false);
  });
  it("throws the refusal its last line carries, as the address would have", async () => {
    const refused = { status: 422, body: { refused: "the load does not fit", fix: "check it", field: "load" } };
    reply = () => ({ ok: true, status: 200, body: body([`${JSON.stringify(refused)}\n`]) });
    const { api, Refused } = await boot();
    const asked = api.largest({}, () => undefined);
    await expect(asked).rejects.toBeInstanceOf(Refused);
    await expect(asked).rejects.toMatchObject({ field: "load" });
  });
  it("says so when the answer stops before its last line", async () => {
    reply = () => ({ ok: true, status: 200, body: body([`${JSON.stringify({ probe: probe(1) })}\n`]) });
    const { api } = await boot();
    await expect(api.largest({}, () => undefined)).rejects.toThrow("the answer was cut short");
  });
  it("is answered as any request is when refused before the search begins", async () => {
    reply = () => ({ ok: false, status: 400, json: () => Promise.resolve({ error: "the request was not JSON" }) });
    const { api } = await boot();
    await expect(api.largest({}, () => undefined)).rejects.toThrow("the request was not JSON");
  });
  it("hands the stop on to the request, which closes it on the server", async () => {
    reply = () => ({ ok: true, status: 200, body: body([]) });
    const { api } = await boot();
    const stop = new AbortController();
    void api.largest({}, () => undefined, stop.signal).catch(() => undefined);
    await tick();
    expect(posted.at(-1)!.init!.signal).toBe(stop.signal);
  });
});

interface Posted {
  id: number;
  route?: string;
  stream?: boolean;
  cancel?: number;
  start?: unknown;
}
class FakeWorker {
  static last: FakeWorker;
  posted: Posted[] = [];
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onerror: ((e: { message: string }) => void) | null = null;
  constructor() {
    FakeWorker.last = this;
  }
  postMessage(m: Posted) {
    this.posted.push(m);
  }
  get asked() {
    return this.posted.filter((m) => !m.start && m.cancel === undefined);
  }
  say(data: unknown) {
    this.onmessage!({ data });
  }
}

describe("the largest load from the engine in the browser", () => {
  const boot = async () => {
    vi.resetModules();
    vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
    vi.stubGlobal("document", { baseURI: "http://host/" });
    vi.stubGlobal("Worker", FakeWorker);
    vi.stubGlobal("fetch", (url: string) => {
      if (url === "engine/mode.json")
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ server: false }) });
      const setup = { devices: [], motors: {}, profile: {}, load: {} };
      return Promise.resolve({ ok: true, json: () => Promise.resolve(setup) });
    });
    const mod = await import("../src/api");
    const engine = await mod.boot(() => undefined);
    FakeWorker.last.say({ ready: true });
    await engine.ready;
    return { ...mod, w: FakeWorker.last };
  };

  it("is asked for as a search, and hands on each probe the engine posts", async () => {
    const { api, w } = await boot();
    const seen: number[] = [];
    const asked = api.largest({}, (p) => seen.push(p.scale));
    await tick();
    const id = w.asked.at(-1)!.id;
    expect(w.asked.at(-1)).toMatchObject({ route: "/api/largest", stream: true });
    w.say({ id, probe: probe(1) });
    w.say({ id: id + 99, probe: probe(7) }); // another job's: not this one's
    w.say({ id, probe: probe(2) });
    w.say({ id, status: 200, body: answer });
    await expect(asked).resolves.toEqual(answer);
    expect(seen).toEqual([1, 2]);
  });
  it("tells the engine to stop a search given up, and moves on once it has", async () => {
    const { api, w } = await boot();
    const stop = new AbortController();
    const seen: number[] = [];
    const asked = api.largest({}, (p) => seen.push(p.scale), stop.signal);
    const next = api.stage({ n: 2 });
    await tick();
    const id = w.asked.at(-1)!.id;
    w.say({ id, probe: probe(1) });
    stop.abort();
    await expect(asked).rejects.toMatchObject({ name: "AbortError" }); // heard at once
    expect(w.posted.at(-1)).toEqual({ cancel: id });
    w.say({ id, probe: probe(2) }); // on its way before the engine heard: shown to nobody
    expect(seen).toEqual([1]);
    expect(w.asked).toHaveLength(1); // the engine is still the search's until it stops
    w.say({ id, status: 499, body: { error: "given up" } });
    await tick();
    expect(w.asked.at(-1)).toMatchObject({ route: "/api/stage" });
    w.say({ id: w.asked.at(-1)!.id, status: 200, body: { stage: {}, advice: null } });
    await expect(next).resolves.toEqual({ stage: {}, advice: null });
  });
  it("does not tell the engine to stop a request that is not a search", async () => {
    const { api, w } = await boot();
    const stop = new AbortController();
    void api.stage({}, stop.signal).catch(() => undefined);
    await tick();
    stop.abort();
    expect(w.posted.some((m) => m.cancel !== undefined)).toBe(false);
  });
});

describe("the worker's answer to a search", () => {
  const posted: unknown[] = [];
  vi.stubGlobal("postMessage", (m: unknown) => posted.push(m));
  vi.stubGlobal("onmessage", null);

  /** A stand-in for the Python search: its lines, and how far it was read before it stopped. */
  function search(lines: string[]) {
    const read = { count: 0, closed: false };
    const open = () => ({
      next: () => (read.count < lines.length ? lines[read.count++] : null),
      close: () => void (read.closed = true),
    });
    return { open, read };
  }
  const lines = [probe(1), probe(2), probe(4)].map((p) => JSON.stringify({ probe: p }));
  const last = JSON.stringify({ status: 200, body: answer });

  beforeEach(() => void (posted.length = 0));

  it("posts each probe under the request's number, and ends with the answer", async () => {
    const { setEngine, streamTo } = await import("../src/engine.worker");
    const { open } = search([...lines, last]);
    setEngine(null, open);
    await expect(streamTo({ id: 3, route: "/api/largest", payload: "{}" })).resolves.toEqual({
      id: 3,
      status: 200,
      body: answer,
    });
    expect(posted).toEqual([1, 2, 4].map((scale) => ({ id: 3, probe: probe(scale) })));
  });
  it("stops between two probes once the page gives it up, and says so", async () => {
    const mod = await import("../src/engine.worker");
    const long = Array.from({ length: 500 }, (_, k) => JSON.stringify({ probe: probe(k) }));
    const { open, read } = search([...long, last]);
    mod.setEngine(null, open);
    const answered = mod.streamTo({ id: 4, route: "/api/largest", payload: "{}" });
    await tick(); // the search is under way, a pause between two probes
    (globalThis as unknown as { onmessage: (e: { data: unknown }) => void }).onmessage({ data: { cancel: 4 } });
    await expect(answered).resolves.toEqual({ id: 4, status: 499, body: { error: "given up" } });
    expect(read.closed).toBe(true);
    expect(read.count).toBeLessThan(long.length);
  });
  it("is an answer when the engine throws, or has not started", async () => {
    const { setEngine, streamTo } = await import("../src/engine.worker");
    setEngine(null, () => ({
      next: () => {
        throw new Error("Traceback\nMemoryError: out of memory");
      },
      close: () => undefined,
    }));
    await expect(streamTo({ id: 5, route: "/api/largest", payload: "{}" })).resolves.toEqual({
      id: 5,
      status: 500,
      body: { error: "the engine failed: MemoryError: out of memory" },
    });
    setEngine(null, null);
    await expect(streamTo({ id: 6, route: "/api/largest", payload: "{}" })).resolves.toMatchObject({ status: 500 });
  });
});
