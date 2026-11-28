// @vitest-environment happy-dom
// Nothing typed is lost to the session: a write waiting when the page closes goes at once; on
// the next load the browser's newer copy wins over the session's older one and is written; a
// read never lays its figures over an edit or a Reset made after it began; and a tab left open
// across an update stops writing and says a newer build is running.
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability", "setup"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => "server", keeps: () => true, forget: vi.fn(), remember: vi.fn() } };
});

import type { Setup } from "../src/api";
import { startShared } from "../src/session";
import { resetBuild } from "../src/session/build";
import { hide } from "../src/session/notice";
import { hear, MARK, readMark, stopSession, sync, tab, undoChange } from "../src/session/sync";
import type { Entry } from "../src/session/types";
import { initial, save } from "../src/state";
import type { State } from "../src/state";
import { app, draw } from "../src/store";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;

type Call = { url: string; method: string; body: Record<string, unknown> | undefined; init?: RequestInit };

/** The server, played by the test: the session, what it was asked, and a read held back. */
const server = {
  version: 0,
  doc: { design: null as unknown, lab: null as unknown },
  calls: [] as Call[],
  build: "",
  /** While set, a read waits until it is let go. */
  hold: null as null | Promise<void>,
  /** What an undo puts back. */
  undoTo: null as unknown,
};

function answer(status: number, body: unknown) {
  const headers = new Headers(server.build ? { "X-MotionSim-Build": server.build } : {});
  return { ok: status === 200, status, headers, json: () => Promise.resolve(body) };
}

async function serve(url: string, init?: RequestInit) {
  const method = init?.method ?? "GET";
  const body = init?.body ? (JSON.parse(init.body as string) as Record<string, unknown>) : undefined;
  server.calls.push({ url, method, body, init });
  if (url === "api/session" && method === "GET") {
    const at = { version: server.version, doc: structuredClone(server.doc) };
    if (server.hold) await server.hold;
    return answer(200, at);
  }
  if (url === "api/session" && method === "PUT") {
    server.doc = { ...server.doc, ...(body!.doc as object) };
    server.version += 1;
    const rebased = body!.base !== server.version - 1;
    return answer(200, { version: server.version, changed: ["design"], rebased, overwrote: [], change: null });
  }
  if (url === "api/session/undo" && method === "POST") {
    server.doc = { ...server.doc, design: server.undoTo };
    server.version += 1;
    return answer(200, {
      version: server.version,
      changed: ["design.conditions.v_dc"],
      rebased: false,
      overwrote: [],
      change: null,
    });
  }
  return answer(404, { error: "no such address" });
}

class Socket {
  static open: Socket[] = [];
  onmessage: ((m: MessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) {
    Socket.open.push(this);
  }
  say(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
  close() {}
}

const kept = new Map<string, string>();
const settled = async () => {
  for (let k = 0; k < 30; k++) await new Promise((r) => setTimeout(r, 0));
};
const puts = () => server.calls.filter((c) => c.url === "api/session" && c.method === "PUT");
const sentDesign = (c: Call) => (c.body!.doc as { design: State }).design;
const designWith = (v: number): State => {
  const s = initial(setup);
  s.conditions.v_dc = v;
  return s;
};

/** A page loaded on what the browser kept: its state, then the session started. */
async function load(local: State): Promise<void> {
  stopSession();
  app.state = structuredClone(local);
  await startShared();
  await settled();
}

beforeEach(() => {
  vi.useRealTimers();
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  kept.clear();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => kept.get(k) ?? null,
    setItem: (k: string, v: string) => void kept.set(k, v),
    removeItem: (k: string) => void kept.delete(k),
  });
  vi.stubGlobal("fetch", serve);
  vi.stubGlobal("WebSocket", Socket);
  Socket.open = [];
  Object.assign(server, { version: 0, doc: { design: null, lab: null }, calls: [], build: "", hold: null });
  document.head.querySelector('meta[name="motionsim-build"]')?.remove();
  document.body.innerHTML = `<div id="app"></div>`;
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  for (const k of Object.keys(draw) as (keyof typeof draw)[]) (draw as Record<string, unknown>)[k] = () => undefined;
});

afterEach(() => {
  hide();
  stopSession();
  resetBuild();
});

describe("a write waiting as the page goes", () => {
  it("is sent at once when the page is hidden or closed, by a request that outlives the page", async () => {
    server.doc.design = designWith(25.2);
    server.version = 4;
    await load(designWith(25.2));
    app.state.conditions.v_dc = 60;
    save(app.state);
    // The typing pause has not passed: nothing is written yet.
    expect(puts()).toHaveLength(0);
    dispatchEvent(new Event("pagehide"));
    expect(puts()).toHaveLength(1);
    const put = puts()[0];
    expect(put.init?.keepalive).toBe(true);
    expect(put.body!.base).toBe(4);
    expect(sentDesign(put).conditions.v_dc).toBe(60);
    await settled();
    expect(readMark()).toEqual({ version: 5, edited: false });
  });

  it("is sent when the tab is hidden too", async () => {
    server.doc.design = designWith(25.2);
    server.version = 1;
    await load(designWith(25.2));
    app.state.conditions.v_dc = 61;
    save(app.state);
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
    expect(puts().map((c) => sentDesign(c).conditions.v_dc)).toEqual([61]);
  });
});

describe("the next load", () => {
  it("keeps the browser's edit the session never had, and writes it on the version it was made on", async () => {
    server.doc.design = designWith(25.2);
    server.version = 4;
    await load(designWith(25.2));
    app.state.conditions.v_dc = 60;
    save(app.state); // typed, then the page reloaded before the write went
    expect(readMark()).toEqual({ version: 4, edited: true });
    const local = structuredClone(app.state);
    server.calls = [];
    await load(local);
    expect(app.state.conditions.v_dc).toBe(60);
    expect(puts()).toHaveLength(1);
    expect(puts()[0].body!.base).toBe(4);
    expect(sentDesign(puts()[0]).conditions.v_dc).toBe(60);
    expect(server.doc.design).toMatchObject({ conditions: { v_dc: 60 } });
    expect(readMark()).toEqual({ version: 5, edited: false });
  });

  it("keeps a Reset made just before the reload: the cleared design is written, the old not taken back", async () => {
    const old = designWith(25.2);
    old.devices = [setup.devices[0].id];
    server.doc.design = old;
    server.version = 7;
    await load(old);
    // Reset: the browser's copy cleared, and saved, and the page reloaded at once.
    app.state = initial(setup);
    save(app.state);
    await load(initial(setup));
    expect(app.state.devices).toEqual(initial(setup).devices);
    expect(puts().at(-1)!.body!.base).toBe(7);
    expect(sentDesign(puts().at(-1)!).devices).toEqual(initial(setup).devices);
  });

  it("takes the session's copy where the browser's holds nothing newer", async () => {
    server.doc.design = designWith(25.2);
    server.version = 2;
    await load(designWith(25.2));
    // The agent changes the design while the tab is closed.
    server.doc.design = designWith(72);
    server.version = 3;
    server.calls = [];
    await load(designWith(25.2));
    expect(app.state.conditions.v_dc).toBe(72);
    expect(puts()).toHaveLength(0);
  });

  it("is not put back over a Reset or an edit made while the first read was under way", async () => {
    const old = designWith(25.2);
    server.doc.design = old;
    server.version = 3;
    let go: () => void = () => undefined;
    server.hold = new Promise<void>((r) => (go = r));
    stopSession();
    app.state = designWith(25.2);
    const started = startShared();
    await settled();
    // Pressed before the session's copy came.
    app.state.conditions.v_dc = 48;
    save(app.state);
    server.hold = null;
    go();
    await started;
    await settled();
    expect(app.state.conditions.v_dc).toBe(48);
    expect(sentDesign(puts().at(-1)!).conditions.v_dc).toBe(48);
  });
});

describe("a read of the session", () => {
  it("never lays its figures over an edit made after it began", async () => {
    server.doc.design = designWith(25.2);
    server.version = 1;
    await load(designWith(25.2));
    // Another tab writes; this tab reads, and the user types while the read is on its way.
    const theirs = designWith(30);
    theirs.conditions.rpm = 4321;
    server.doc.design = theirs;
    server.version = 2;
    let go: () => void = () => undefined;
    server.hold = new Promise<void>((r) => (go = r));
    Socket.open[0].say({ type: "session", version: 2, source: "page", client: "another-tab", change: null });
    await settled();
    app.state.conditions.v_dc = 99;
    save(app.state);
    server.hold = null;
    go();
    await settled();
    expect(app.state.conditions.v_dc).toBe(99);
    // What the other tab changed and this one did not is taken up.
    expect(app.state.conditions.rpm).toBe(4321);
  });
});

describe("a tab left open across an update", () => {
  const named = (id: string) => {
    const meta = document.createElement("meta");
    meta.name = "motionsim-build";
    meta.content = id;
    document.head.append(meta);
  };

  it("sends its build with every write", async () => {
    named("aaaa1111");
    server.build = "aaaa1111";
    server.doc.design = designWith(25.2);
    server.version = 1;
    await load(designWith(25.2));
    app.state.conditions.v_dc = 50;
    save(app.state);
    dispatchEvent(new Event("pagehide"));
    const headers = puts()[0].init!.headers as Record<string, string>;
    expect(headers["X-MotionSim-Build"]).toBe("aaaa1111");
    expect(document.querySelector("#newer-build")).toBeNull();
  });

  it("says a newer build is running when the socket's hello names another, and writes nothing more", async () => {
    named("aaaa1111");
    server.build = "aaaa1111";
    server.doc.design = designWith(25.2);
    server.version = 1;
    await load(designWith(25.2));
    Socket.open[0].say({ type: "hello", version: 1, build: "bbbb2222" });
    const bar = document.querySelector<HTMLElement>("#newer-build")!;
    expect(bar.getAttribute("role")).toBe("status");
    expect(bar.textContent).toContain("A newer MotionSim is running");
    expect(bar.querySelector("button")!.textContent).toBe("Reload");
    // Not a dialog: the keyboard stays where it was.
    expect(document.activeElement).not.toBe(bar.querySelector("button"));
    expect(sync.stale).toBe(true);
    app.state.conditions.v_dc = 50;
    save(app.state);
    dispatchEvent(new Event("pagehide"));
    await new Promise((r) => setTimeout(r, 450));
    expect(puts()).toHaveLength(0);
    expect(kept.get(MARK)).not.toContain('"edited":true');
  });

  it("says so too when an answer's header names another build", async () => {
    named("aaaa1111");
    server.build = "cccc3333";
    server.doc.design = designWith(25.2);
    server.version = 1;
    await load(designWith(25.2));
    expect(document.querySelector("#newer-build")).not.toBeNull();
    expect(sync.stale).toBe(true);
  });

  it("takes no build as a difference where the page names none (in development)", async () => {
    server.build = "cccc3333";
    server.doc.design = designWith(25.2);
    server.version = 1;
    await load(designWith(25.2));
    Socket.open[0].say({ type: "hello", version: 1, build: "dddd4444" });
    expect(document.querySelector("#newer-build")).toBeNull();
    expect(sync.stale).toBe(false);
  });
});

describe("an undo of the agent's change", () => {
  const entry = { id: "c0ffee000001", what: "Supply voltage 52 V → 60 V" } as Entry;

  /** The page at 52 V, then the agent's 60 V taken up from the socket. */
  async function agentSet(): Promise<void> {
    server.doc.design = designWith(52);
    server.version = 3;
    await load(designWith(52));
    server.doc.design = designWith(60);
    server.version = 4;
    server.undoTo = designWith(52);
    Socket.open[0].say({ type: "session", version: 4, source: "agent", client: "", change: null });
    await settled();
    expect(app.state.conditions.v_dc).toBe(60);
  }

  it("is taken up by the tab that pressed it, whose own write the socket does not bring back", async () => {
    await agentSet();
    await undoChange(entry);
    // The socket says it too, under this tab's name: not read again.
    hear({
      type: "session",
      version: 5,
      source: "undo",
      client: tab,
      changed: [],
      rebased: false,
      overwrote: [],
      change: null,
    });
    await settled();
    expect(app.state.conditions.v_dc).toBe(52);
    expect(sync.version).toBe(5);
    expect(puts()).toHaveLength(0);
  });

  it("is taken up by another tab from the socket", async () => {
    await agentSet();
    // Another tab pressed Undo: the server puts 52 back, and the socket says so.
    server.doc.design = designWith(52);
    server.version = 5;
    Socket.open[0].say({ type: "session", version: 5, source: "undo", client: "other-tab", change: null });
    await settled();
    expect(app.state.conditions.v_dc).toBe(52);
    expect(puts()).toHaveLength(0);
  });
});

describe("the parts on the page and the parts ticked", () => {
  const [a, b] = ["example", "example-mosfet"];
  const parts = (added: string[], devices: string[], lead: string): State =>
    Object.assign(designWith(25.2), { added, devices, lead });
  const held = (s: { added: string[]; devices: string[] }) => {
    // Every part ticked is on the page, and a page with parts has one ticked.
    expect(s.devices.every((d) => s.added.includes(d))).toBe(true);
    if (s.added.length) expect(s.devices.length).toBeGreaterThan(0);
  };

  it("are never taken half from a read and half from an edit made while it was under way", async () => {
    server.doc.design = parts([a, b], [a], a);
    server.version = 1;
    await load(parts([a, b], [a], a));
    // Another tab unticks this part and ticks the other; this tab, meanwhile, takes the other off.
    server.doc.design = parts([a, b], [b], b);
    server.version = 2;
    let go: () => void = () => undefined;
    server.hold = new Promise<void>((r) => (go = r));
    Socket.open[0].say({ type: "session", version: 2, source: "page", client: "another-tab", change: null });
    await settled();
    app.state.added = [a];
    save(app.state);
    server.hold = null;
    go();
    await settled();
    // The edit made here is the newer: the whole set is this tab's, not added from here and
    // the ticks from there.
    expect([app.state.added, app.state.devices, app.state.lead]).toEqual([[a], [a], a]);
    held(app.state);
  });

  it("are taken whole from a read where this tab did not touch them", async () => {
    server.doc.design = parts([a], [a], a);
    server.version = 1;
    await load(parts([a], [a], a));
    server.doc.design = { ...parts([a, b], [a, b], b), conditions: { ...designWith(30).conditions } };
    server.version = 2;
    let go: () => void = () => undefined;
    server.hold = new Promise<void>((r) => (go = r));
    Socket.open[0].say({ type: "session", version: 2, source: "agent", client: "", change: null });
    await settled();
    app.state.conditions.rpm = 4321; // an edit elsewhere in the design, while the read is on its way
    save(app.state);
    server.hold = null;
    go();
    await settled();
    expect([app.state.added, app.state.devices, app.state.lead]).toEqual([[a, b], [a, b], b]);
    expect(app.state.conditions.rpm).toBe(4321);
  });

  it("are kept whole when they were edited while the first read was under way", async () => {
    server.doc.design = parts([a, b], [b], b);
    server.version = 3;
    let go: () => void = () => undefined;
    server.hold = new Promise<void>((r) => (go = r));
    stopSession();
    app.state = parts([a, b], [a], a);
    const started = startShared();
    await settled();
    app.state.added = [a]; // the other part taken off before the session's copy came
    save(app.state);
    server.hold = null;
    go();
    await started;
    await settled();
    expect([app.state.added, app.state.devices, app.state.lead]).toEqual([[a], [a], a]);
    expect(sentDesign(puts().at(-1)!)).toMatchObject({ added: [a], devices: [a], lead: a });
  });

  it("are mended where the session holds a part on the page and none ticked, and written so", async () => {
    // The shape the session was found in: a part on the page, nothing ticked.
    server.doc.design = parts([b], [], "");
    server.version = 42;
    await load(parts([b], [], ""));
    expect([app.state.added, app.state.devices, app.state.lead]).toEqual([[b], [b], b]);
    expect(sentDesign(puts().at(-1)!)).toMatchObject({ added: [b], devices: [b], lead: b });
    expect(readMark()).toEqual({ version: 43, edited: false });
  });

  it("are mended where a read brings that shape", async () => {
    server.doc.design = parts([b], [b], b);
    server.version = 1;
    await load(parts([b], [b], b));
    server.doc.design = parts([a, b], [], "");
    server.version = 2;
    server.calls = [];
    Socket.open[0].say({ type: "session", version: 2, source: "agent", client: "", change: null });
    await settled();
    // No part leads: the first brought is ticked.
    expect(app.state.devices).toEqual([a]);
    held(app.state);
    expect(sentDesign(puts().at(-1)!)).toMatchObject({ added: [a, b], devices: [a], lead: a });
  });
});
