// The engine in the browser, as the page talks to it: a worker stands in for the Python
// engine, and the tests play its part by hand.
import { beforeEach, describe, expect, it, vi } from "vitest";

interface Posted {
  id: number;
  route: string;
  payload: string;
  start?: { parts: unknown[] };
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
  /** The requests handed to the engine, without the message that started it. */
  get asked() {
    return this.posted.filter((m) => !m.start);
  }
  answer(body: unknown, status = 200) {
    this.onmessage!({ data: { id: this.asked.at(-1)!.id, status, body } });
  }
}

const store = new Map<string, string>();
let full = false;

async function bootInBrowser(mode: unknown = { server: false }) {
  vi.resetModules();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => {
      if (full) throw new DOMException("full", "QuotaExceededError");
      store.set(k, v);
    },
    removeItem: (k: string) => void store.delete(k),
  });
  vi.stubGlobal("document", { baseURI: "http://host/" });
  vi.stubGlobal("Worker", FakeWorker);
  vi.stubGlobal("fetch", (url: string) => {
    if (url === "engine/mode.json") return Promise.resolve({ ok: true, json: () => Promise.resolve(mode) });
    const setup = { devices: [], motors: {}, profile: {}, load: {} };
    if (url === "engine/setup.json") return Promise.resolve({ ok: true, json: () => Promise.resolve(setup) });
    return Promise.reject(new Error(`no server at ${url}`));
  });
  const mod = await import("../src/api");
  const engine = await mod.boot(() => undefined);
  const w = FakeWorker.last;
  w.onmessage!({ data: { ready: true } });
  await engine.ready;
  return { ...mod, w };
}
const tick = () => new Promise((r) => setTimeout(r, 5));
const outcome = (p: Promise<unknown>) =>
  Promise.race([
    p.then(
      () => "answered",
      (e: Error) => `failed: ${e.name === "AbortError" ? "superseded" : e.message}`,
    ),
    new Promise((r) => setTimeout(() => r("PENDING"), 150)),
  ]);
const file = (name: string, text: string) => ({ name, text: () => Promise.resolve(text) }) as unknown as File;
const good = { stage: {}, advice: null };

beforeEach(() => {
  vi.unstubAllGlobals();
  store.clear();
  full = false;
});

describe("the engine in the browser", () => {
  it("settles every waiting request when it dies, and every request after", async () => {
    const { api, w } = await bootInBrowser();
    const first = api.stage({});
    const second = api.proposal({});
    await tick();
    w.onerror!({ message: "Uncaught PythonError: MemoryError" });
    expect(await outcome(first)).toBe("failed: the engine in this browser stopped: Uncaught PythonError: MemoryError");
    expect(await outcome(second)).toMatch(/^failed: the engine in this browser stopped/);
    expect(await outcome(api.stage({}))).toMatch(/^failed: the engine in this browser stopped/);
  });
  it("is asked for a device's reading with an empty record, never with null", async () => {
    const { api, w } = await bootInBrowser();
    void api.reading("example").catch(() => undefined);
    await tick();
    expect(w.asked.at(-1)).toMatchObject({ route: "/api/device/example", payload: "{}" });
  });
  it("has one request at a time, in the order they were asked", async () => {
    const { api, w } = await bootInBrowser();
    const a = api.stage({ n: 1 });
    const b = api.stage({ n: 2 });
    await tick();
    expect(w.asked.map((m) => m.payload)).toEqual(['{"n":1}']);
    w.answer(good);
    await a;
    await tick();
    expect(w.asked.map((m) => m.payload)).toEqual(['{"n":1}', '{"n":2}']);
    w.answer(good);
    await expect(b).resolves.toEqual(good);
  });
  it("is never handed a request that was given up while it waited its turn", async () => {
    const { api, w } = await bootInBrowser();
    const busy = api.stage({ n: 1 });
    const gone = new AbortController();
    const dropped = api.stage({ n: 2 }, gone.signal);
    const kept = api.stage({ n: 3 });
    await tick();
    gone.abort();
    expect(await outcome(dropped)).toBe("failed: superseded"); // heard at once, not when the engine is free
    w.answer(good);
    await busy;
    await tick();
    w.answer(good);
    await kept;
    expect(w.asked.map((m) => m.payload)).toEqual(['{"n":1}', '{"n":3}']);
  });
  it("tells whoever gave up a request already with the engine so at once, and moves on when it answers", async () => {
    const { api, w } = await bootInBrowser();
    const gone = new AbortController();
    const asked = api.stage({ n: 1 }, gone.signal);
    const next = api.stage({ n: 2 });
    await tick();
    gone.abort();
    expect(await outcome(asked)).toBe("failed: superseded");
    w.answer(good); // the engine finishes what it had; nobody is waiting for it
    await tick();
    w.answer({ stage: { later: true }, advice: null });
    await expect(next).resolves.toEqual({ stage: { later: true }, advice: null });
  });
  it("says so when its answer is not the answer that was asked for", async () => {
    const { api, w } = await bootInBrowser();
    const asked = api.stage({});
    await tick();
    w.answer({ something: "else" });
    expect(await outcome(asked)).toBe("failed: the engine sent an answer this page cannot read");
    const refused = api.stage({});
    await tick();
    w.answer({ refused: "supply voltage cannot be above 2000", field: "v_dc" }, 422);
    await expect(refused).rejects.toMatchObject({
      reason: "supply voltage cannot be above 2000",
      fix: "",
      field: "v_dc",
    });
  });
});

describe("the parts kept in the browser", () => {
  const kept = () => JSON.parse(store.get("motionsim.devices.v1") ?? "[]") as { id: string; route: string }[];
  async function bring(api: Awaited<ReturnType<typeof bootInBrowser>>, how: () => Promise<unknown>, id: string) {
    const done = how();
    await tick();
    api.w.answer({ device: { id } });
    await done;
  }
  it("are kept by what they are, so two files of one name are two parts", async () => {
    const page = await bootInBrowser();
    await bring(page, () => page.api.addDevice(file("part.device.yaml", "A")), "part");
    await bring(page, () => page.api.addDevice(file("part.device.yaml", "B")), "part-2");
    expect(kept().map((d) => d.id)).toEqual(["part", "part-2"]);
    await bring(page, () => page.api.addDevice(file("renamed.yaml", "A again")), "part");
    expect(kept().map((d) => d.id)).toEqual(["part-2", "part"]);
  });
  it("include a part made from measurements, after the part it was made from", async () => {
    const page = await bootInBrowser();
    await bring(page, () => page.api.addDevice(file("part.device.yaml", "x")), "part");
    await bring(page, () => page.api.addMeasurement("part", file("dp.json", "{}")), "part-measured");
    expect(kept()).toMatchObject([
      { id: "part", route: "/api/device" },
      { id: "part-measured", route: "/api/measure", body: { device: "part", name: "dp.json", text: "{}" } },
    ]);
  });
  it("are handed to the engine again on the next visit, in the order they were brought", async () => {
    const page = await bootInBrowser();
    await bring(page, () => page.api.addDevice(file("part.device.yaml", "x")), "part");
    await bring(page, () => page.api.addMeasurement("part", file("dp.json", "{}")), "part-measured");
    const again = await bootInBrowser();
    expect(again.w.posted[0].start!.parts).toMatchObject([{ route: "/api/device" }, { route: "/api/measure" }]);
  });
  it("are read from what an earlier version kept, a device file by its name", async () => {
    store.set("motionsim.devices.v1", JSON.stringify([{ name: "old.yaml", text: "t", id: "old" }, { junk: 1 }, 7]));
    const page = await bootInBrowser();
    expect(page.storedParts()).toEqual([{ id: "old", route: "/api/device", body: { name: "old.yaml", text: "t" } }]);
  });
  it("are said not to be kept when the browser will not keep them", async () => {
    const page = await bootInBrowser();
    expect(page.api.keeps()).toBe(true);
    full = true;
    await bring(page, () => page.api.addDevice(file("part.device.yaml", "x")), "part");
    expect(page.api.keeps()).toBe(false);
  });
  it("lose a part that is forgotten, and only that one", async () => {
    const page = await bootInBrowser();
    await bring(page, () => page.api.addDevice(file("a.yaml", "A")), "a");
    await bring(page, () => page.api.addDevice(file("b.yaml", "B")), "b");
    page.api.forget("a");
    expect(kept().map((d) => d.id)).toEqual(["b"]);
  });
  it("put back a part forgotten where it was, before the parts brought after it", async () => {
    const page = await bootInBrowser();
    await bring(page, () => page.api.addDevice(file("a.yaml", "A")), "a");
    await bring(page, () => page.api.addDevice(file("b.yaml", "B")), "b");
    const a = page.storedParts()[0];
    page.api.forget("a");
    page.api.remember(a, 0);
    expect(kept().map((d) => d.id)).toEqual(["a", "b"]);
  });
});

describe("where the engine is", () => {
  it("is not looked for in the browser when the page was served by a local server that has stopped", async () => {
    await expect(bootInBrowser({ server: true })).rejects.toThrow(/local engine did not answer/);
  });
});
