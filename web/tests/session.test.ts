// @vitest-environment happy-dom
// The design kept in step with the session a page served on this machine shares with a coding
// agent: what the agent changes comes onto the page live, over what the user has typed and not
// yet sent; the page says so quietly, with Undo; the settings show how an agent connects and
// what it did; and the hosted page asks none of it.
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mode = vi.hoisted((): { now: "server" | "browser" } => ({ now: "server" }));
vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability", "setup"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => mode.now, keeps: () => true, forget: vi.fn(), remember: vi.fn() } };
});

import type { Setup } from "../src/api";
import { startShared } from "../src/session";
import { hide } from "../src/session/notice";
import { goLive } from "../src/control/carry";
import type { LabDoc } from "../src/control/carry";
import { stopSession, sync, tab, VIEW } from "../src/session/sync";
import type { Entry } from "../src/session/types";
import { agentBody, openAgent } from "../src/settings/agent";
import { initial, save } from "../src/state";
import type { State } from "../src/state";
import { app, draw } from "../src/store";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const CODE = "made-up-code-0123456789abcdefghijklmnopqrstu";

/** The server, played by the test: the session it holds and what it was asked. */
const server = {
  version: 0,
  doc: { design: null as unknown, lab: null as unknown },
  calls: [] as { url: string; method: string; body: Record<string, unknown> | undefined }[],
  activity: [] as Entry[],
  undo: null as null | { status: number; body: unknown },
};

function answer(status: number, body: unknown) {
  return Promise.resolve({ ok: status === 200, status, json: () => Promise.resolve(body) });
}

function serve(url: string, init?: RequestInit) {
  const method = init?.method ?? "GET";
  const body = init?.body ? (JSON.parse(init.body as string) as Record<string, unknown>) : undefined;
  server.calls.push({ url, method, body });
  if (url === "api/session" && method === "GET") return answer(200, { version: server.version, doc: server.doc });
  if (url === "api/session" && method === "PUT") {
    server.doc = { ...server.doc, ...(body!.doc as object) };
    server.version += 1;
    return answer(200, { version: server.version, changed: ["design"], rebased: false, overwrote: [], change: null });
  }
  if (url === "api/session/undo") return answer(server.undo?.status ?? 200, server.undo?.body ?? { version: 9 });
  if (url === "api/session/activity") return answer(200, { items: server.activity });
  if (url === "api/settings/agent") {
    const command = `claude mcp add --transport http motionsim http://localhost:4310/mcp --header "Authorization: Bearer ${CODE}"`;
    return answer(200, { code: CODE, url: "http://localhost:4310/mcp", command, write: true });
  }
  return answer(404, { error: "no such address" });
}

/** The socket the page opens, played by the test: what the server pushes is said through it. */
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

const settled = async () => {
  for (let k = 0; k < 20; k++) await new Promise((r) => setTimeout(r, 0));
};

const entry = (over: Partial<Entry> = {}): Entry => ({
  id: "c0ffee000001",
  at: Date.now() / 1000,
  source: "agent",
  kind: "change",
  what: "Supply voltage 48 V → 60 V",
  figures: [{ path: "design.conditions.v_dc", label: "Supply voltage", unit: "V", old: 48, new: 60, had: true }],
  version: 2,
  undone: null,
  undoes: null,
  overwritten: null,
  undoable: true,
  ...over,
});

beforeEach(() => {
  vi.useRealTimers();
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  vi.stubGlobal("fetch", serve);
  vi.stubGlobal("WebSocket", Socket);
  Socket.open = [];
  Object.assign(server, { version: 0, doc: { design: null, lab: null }, calls: [], activity: [], undo: null });
  mode.now = "server";
  document.body.innerHTML = `<div id="app"></div>`;
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  for (const k of Object.keys(draw) as (keyof typeof draw)[]) (draw as Record<string, unknown>)[k] = () => undefined;
});

afterEach(() => {
  hide();
  stopSession();
});

describe("the hosted page", () => {
  it("asks nothing of a session, and opens no socket", async () => {
    mode.now = "browser";
    await startShared();
    save(app.state);
    await settled();
    expect(server.calls.filter((c) => c.url.startsWith("api/session"))).toEqual([]);
    expect(Socket.open).toEqual([]);
    expect(sync.on).toBe(false);
  });
});

describe("the page served on this machine", () => {
  it("offers no chat where the server keeps no session, and keeps it where the session only failed", async () => {
    const panel = `<dialog id="chat-panel"></dialog>`;
    document.body.insertAdjacentHTML("beforeend", panel);
    vi.stubGlobal("fetch", () => answer(500, { error: "the engine failed" }));
    await startShared();
    expect(sync.on).toBe(false);
    expect(document.getElementById("chat-panel")).not.toBeNull();
    vi.stubGlobal("fetch", () => answer(404, { error: "no such address" }));
    await startShared();
    expect(sync.on).toBe(false);
    expect(document.getElementById("chat-panel")).toBeNull();
  });

  it("writes its design as the first version where the session holds none", async () => {
    await startShared();
    await settled();
    const put = server.calls.find((c) => c.method === "PUT")!;
    expect(put.body).toMatchObject({ base: 0, client: tab });
    expect((put.body!.doc as { design: State }).design.conditions.v_dc).toBe(app.state.conditions.v_dc);
    expect(Socket.open[0].url).toMatch(/^ws:\/\/.*\/ws\/session$/);
  });

  it("takes up the design the session holds, as the shared truth", async () => {
    const theirs = initial(setup);
    theirs.conditions.v_dc = 72;
    server.doc.design = theirs;
    server.version = 5;
    await startShared();
    await settled();
    expect(app.state.conditions.v_dc).toBe(72);
    expect(sync.version).toBe(5);
  });

  it("lays the agent's change over what was typed and not yet sent", async () => {
    server.doc.design = initial(setup);
    server.version = 1;
    await startShared();
    await settled();
    // The user types a speed; the write waits for the typing to pause.
    app.state.conditions.rpm = 1234;
    // Meanwhile the agent sets the supply voltage.
    const theirs = initial(setup);
    theirs.conditions.v_dc = 60;
    server.doc.design = theirs;
    server.version = 2;
    Socket.open[0].say({ type: "session", version: 2, source: "agent", client: "", change: entry() });
    await settled();
    expect(app.state.conditions.v_dc).toBe(60);
    expect(app.state.conditions.rpm).toBe(1234);
  });

  it("does not take its own write back as another's", async () => {
    server.doc.design = initial(setup);
    server.version = 1;
    await startShared();
    await settled();
    const reads = () => server.calls.filter((c) => c.url === "api/session" && c.method === "GET").length;
    const before = reads();
    Socket.open[0].say({ type: "session", version: 2, source: "page", client: tab, change: null });
    await settled();
    expect(reads()).toBe(before);
  });
});

describe("the user's view, which is this tab's alone", () => {
  const theirs = (over: Partial<State> = {}): State => ({ ...initial(setup), ...over });
  const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

  it("is never written to the session", async () => {
    app.state.step = 3;
    app.state.tab = "losses";
    await startShared();
    await settled();
    const design = (server.calls.find((c) => c.method === "PUT")!.body!.doc as { design: object }).design;
    for (const k of VIEW) expect(design).not.toHaveProperty(k);
  });

  it("stays where it is when the session it takes up at start was left at another step", async () => {
    app.state.step = 2;
    app.state.tab = "motion";
    server.doc.design = theirs({ step: 4, reached: 4, tab: "limits", metric: "tj" });
    server.version = 3;
    await startShared();
    await settled();
    expect([app.state.step, app.state.tab, app.state.metric]).toEqual([2, "motion", "loss"]);
  });

  it("stays where it is when an update comes at a different step, and the design still changes", async () => {
    server.doc.design = theirs();
    server.version = 1;
    await startShared();
    await settled();
    app.state.step = 3;
    app.state.tab = "losses";
    // Another tab (or the agent) is on the first step, on another results tab, and sets a figure.
    const other = theirs({ step: 0, reached: 0, tab: "limits", metric: "efficiency" });
    other.conditions.v_dc = 60;
    server.doc.design = other;
    server.version = 2;
    Socket.open[0].say({ type: "session", version: 2, source: "page", client: "another-tab", change: null });
    await settled();
    expect(app.state.conditions.v_dc).toBe(60);
    expect([app.state.step, app.state.tab, app.state.metric]).toEqual([3, "losses", "loss"]);
  });

  it("takes up the agent's lab without writing it straight back", async () => {
    // The lab as the page reads it differs in form from what the agent wrote (its key, here).
    let doc: LabDoc | null = { v: 1, key: "mine", scheme: "a" };
    const hearers = new Set<() => void>();
    goLive({
      read: () => doc,
      subscribe: (h) => (hearers.add(h), () => hearers.delete(h)),
      adopt: (d) => {
        doc = { ...d, key: "mine" };
        hearers.forEach((h) => h());
      },
    });
    server.doc = { design: theirs(), lab: { v: 1, key: "mine", scheme: "a" } };
    server.version = 1;
    await startShared();
    await settled();
    server.doc = { ...server.doc, lab: { v: 1, key: "theirs", scheme: "b" } };
    server.version = 2;
    Socket.open[0].say({ type: "session", version: 2, source: "agent", client: "", change: entry() });
    await settled();
    await wait(600);
    expect(doc?.scheme).toBe("b");
    expect(server.calls.filter((c) => c.method === "PUT" && c.body && "lab" in (c.body.doc as object))).toEqual([]);
    goLive({ read: () => null, subscribe: () => () => undefined, adopt: () => undefined });
  });
});

describe("the notice", () => {
  it("says what the agent changed, from what to what, and Undo asks the server to undo it", async () => {
    server.doc.design = initial(setup);
    server.version = 1;
    await startShared();
    await settled();
    Socket.open[0].say({ type: "session", version: 2, source: "agent", client: "", change: entry() });
    await settled();
    const notice = document.querySelector<HTMLElement>("#agent-notice")!;
    expect(notice.hidden).toBe(false);
    expect(notice.getAttribute("role")).toBe("status");
    expect(notice.textContent).toContain("Changed by your agent: Supply voltage 48 V → 60 V");
    notice.querySelector<HTMLButtonElement>("[data-notice-undo]")!.click();
    await settled();
    const undo = server.calls.find((c) => c.url === "api/session/undo")!;
    expect(undo.body).toEqual({ change: "c0ffee000001", client: tab });
    expect(notice.textContent).toContain("Undone: Supply voltage 48 V → 60 V");
  });

  it("says why an undo was refused, in place", async () => {
    server.undo = {
      status: 422,
      body: { refused: "Supply voltage was changed again after this change", fix: "set it by hand", field: "x" },
    };
    await startShared();
    await settled();
    Socket.open[0].say({ type: "session", version: 2, source: "agent", client: "", change: entry() });
    await settled();
    document.querySelector<HTMLButtonElement>("[data-notice-undo]")!.click();
    await settled();
    const text = document.querySelector("#agent-notice")!.textContent;
    expect(text).toContain("Not undone.");
    expect(text).toContain("Supply voltage was changed again after this change. Set it by hand.");
  });

  it("is not shown for a change the page itself made, and takes no focus", async () => {
    await startShared();
    await settled();
    const button = document.createElement("button");
    document.body.append(button);
    button.focus();
    Socket.open[0].say({ type: "session", version: 2, source: "page", client: "other-tab", change: null });
    await settled();
    expect(document.querySelector<HTMLElement>("#agent-notice")?.hidden ?? true).toBe(true);
    Socket.open[0].say({ type: "session", version: 3, source: "agent", client: "", change: entry() });
    await settled();
    expect(document.activeElement).toBe(button);
  });
});

describe("the settings' part for an agent", () => {
  it("shows the code masked, the command to connect, and the log with Undo", async () => {
    server.activity = [
      entry(),
      entry({ id: "c0ffee000002", what: "Speed 2000 rpm → 3000 rpm", undone: { at: 1, by: "x" } }),
    ];
    await startShared();
    await settled();
    document.body.insertAdjacentHTML(
      "beforeend",
      `<dialog id="settings-dialog" open><div id="settings-agent"></div></dialog>`,
    );
    await openAgent();
    await settled();
    const section = document.querySelector<HTMLElement>("#settings-agent")!;
    const code = section.querySelector<HTMLInputElement>("#agent-code")!;
    expect(code.value).not.toContain(CODE);
    expect(section.querySelector<HTMLInputElement>("#agent-command")!.value).toContain(
      "claude mcp add --transport http",
    );
    expect(section.querySelector<HTMLInputElement>("#agent-command")!.value).not.toContain(CODE);
    section.querySelector<HTMLButtonElement>("[data-agent-reveal]")!.click();
    await settled();
    expect(section.querySelector<HTMLInputElement>("#agent-code")!.value).toBe(CODE);
    const rows = [...section.querySelectorAll(".agent-log li")].map((li) => li.textContent);
    expect(rows[0]).toContain("Supply voltage 48 V → 60 V");
    expect(rows[0]).toContain("Undo");
    expect(rows[1]).toContain("Undone");
    section.querySelector<HTMLButtonElement>('[data-agent-undo="c0ffee000001"]')!.click();
    await settled();
    expect(server.calls.some((c) => c.url === "api/session/undo")).toBe(true);
  });

  it("is not drawn where the server keeps no session", async () => {
    mode.now = "browser";
    await startShared();
    document.body.insertAdjacentHTML("beforeend", `<div id="settings-agent"></div>`);
    await openAgent();
    expect(document.querySelector("#settings-agent")!.innerHTML).toBe("");
    expect(agentBody()).toContain("Coding agent");
  });
});
