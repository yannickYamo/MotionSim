// The engine behind a local server, as the page talks to it over HTTP.
import { beforeEach, describe, expect, it, vi } from "vitest";

const calls: { url: string; init?: RequestInit }[] = [];
let respond: (url: string) => { status: number; body: unknown };

async function bootOnServer() {
  vi.resetModules();
  calls.length = 0;
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const { status, body } = respond(url);
    const headers = { get: () => "application/json" };
    return Promise.resolve({ ok: status === 200, status, headers, json: () => Promise.resolve(body) });
  });
  const mod = await import("../src/api");
  const engine = await mod.boot(() => undefined);
  return { ...mod, engine };
}
const setup = { devices: [], motors: {}, profile: {}, load: {} };

beforeEach(() => {
  respond = (url) => {
    if (url === "engine/mode.json") return { status: 200, body: { server: true } };
    if (url === "api/setup") return { status: 200, body: setup };
    return { status: 200, body: {} };
  };
});

describe("the engine behind a local server", () => {
  it("is found by the small file that says where it is", async () => {
    const { engine } = await bootOnServer();
    expect(engine.mode).toBe("server");
    expect(engine.setup).toEqual(setup);
  });
  it("is sent a question as JSON and asked for a reading with nothing", async () => {
    const { api } = await bootOnServer();
    respond = () => ({ status: 200, body: { stage: {}, advice: null } });
    await api.stage({ motor: { type: "pmsm" } });
    expect(calls.at(-1)).toMatchObject({
      url: "api/stage",
      init: { method: "POST", body: '{"motor":{"type":"pmsm"}}' },
    });
    respond = () => ({ status: 200, body: { summary: {} } });
    await api.reading("a part/1");
    expect(calls.at(-1)!.url).toBe("api/device/a%20part%2F1");
    expect(calls.at(-1)!.init?.method).toBeUndefined();
  });
  it("hands a refusal on as one, with its reason, its fix and its field", async () => {
    const { api, Refused } = await bootOnServer();
    respond = () => ({ status: 422, body: { refused: "no such speed", fix: "lower it", field: "rpm" } });
    const refused = await api.stage({}).catch((e: unknown) => e);
    expect(refused).toBeInstanceOf(Refused);
    expect(refused).toMatchObject({ reason: "no such speed", fix: "lower it", field: "rpm" });
  });
  it("hands a failure on as a fault, in the engine's words where it gave any", async () => {
    const { api } = await bootOnServer();
    respond = () => ({ status: 500, body: { error: "division by zero" } });
    await expect(api.proposal({})).rejects.toThrow("division by zero");
    respond = () => ({ status: 500, body: "<html>" });
    await expect(api.proposal({})).rejects.toThrow("the engine answered 500");
  });
  it("does not take an answer of the wrong shape for an answer", async () => {
    const { api } = await bootOnServer();
    for (const body of [null, [], "text", { candidate: [] }]) {
      respond = () => ({ status: 200, body });
      await expect(api.proposal({})).rejects.toThrow("the engine sent an answer this page cannot read");
    }
  });
  it("keeps nothing in the browser: the server holds the parts", async () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", { getItem: () => null, setItem: (k: string, v: string) => void store.set(k, v) });
    const { api } = await bootOnServer();
    respond = () => ({ status: 200, body: { device: { id: "part" } } });
    await api.addDevice({ name: "p.yaml", text: () => Promise.resolve("x") } as unknown as File);
    expect(store.size).toBe(0);
  });
});
