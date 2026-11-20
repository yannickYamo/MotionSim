// @vitest-environment happy-dom
// A setup file carries the model of each part brought on the page, and opening one puts it
// all back in place, with the page and its engine kept running. Reset is in place too, and a
// part taken off can be put back for a few seconds.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const brought: unknown[] = [];
vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "recommend", "capability", "report"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  const mine = (id: string) => ({ ...setupNow().devices[1], id, name: `Part ${id}`, example: false });
  const setupNow = () => JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8"));
  const held: string[] = [];
  return {
    ...real,
    api: {
      ...api,
      mode: () => "server",
      keeps: () => true,
      forget: vi.fn(),
      remember: vi.fn(),
      reading: vi.fn((id: string) => Promise.resolve({ file: { name: `${id}.device.yaml`, text: `model of ${id}` } })),
      bring: vi.fn((part: { id: string }) => {
        brought.push(part);
        const id = `${part.id}-again`;
        held.push(id);
        return Promise.resolve({ device: mine(id) });
      }),
      setup: vi.fn(() => {
        const s = setupNow();
        s.devices.push(...held.map(mine));
        return Promise.resolve(s);
      }),
    },
  };
});

import type { Setup } from "../src/api";
import { api } from "../src/api";
import { openSetup, saveSetup, startOver } from "../src/actions/setup";
import { initial } from "../src/state";
import { app, res, ui } from "../src/store";
import { connect, frame, renderEngineStatus, renderPanel, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
let saved: string[] = [];
let reloads = 0;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  const store = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
  saved = [];
  reloads = 0;
  vi.stubGlobal("location", { reload: () => reloads++ });
  vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined });
  vi.stubGlobal(
    "Blob",
    class {
      constructor(public parts: string[]) {}
    },
  );
  HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
    saved.push(this.download);
  };
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  connect();
  Element.prototype.scrollIntoView = () => undefined;
  app.setup = structuredClone(setup);
  app.setup.devices.push({ ...setup.devices[1], id: "mine", name: "Part mine", example: false });
  app.state = initial(app.setup);
  Object.assign(app.state, { devices: ["mine"], added: ["mine"], reached: 3, step: 3, visited: [0, 1, 2, 3] });
  res.blocked = res.fault = res.waiting = null;
  ui.notes.clear();
  ui.setupNote = null;
  brought.length = 0;
});

/** The file the page saved, as the text it wrote. */
async function savedFile(): Promise<Record<string, unknown>> {
  let text = "";
  vi.stubGlobal(
    "Blob",
    class {
      constructor(parts: string[]) {
        text = parts.join("");
      }
    },
  );
  await saveSetup();
  return JSON.parse(text);
}
const asFile = (data: unknown) => ({ name: "mine.json", text: () => Promise.resolve(JSON.stringify(data)) }) as File;

describe("a setup file", () => {
  it("carries the model of each part brought on the page", async () => {
    const file = await savedFile();
    expect(file.setup).toBe(3);
    expect(file.parts).toEqual([
      { id: "mine", route: "/api/device", body: { name: "mine.device.yaml", text: "model of mine" } },
    ]);
  });
  it("opens in place: the parts it carries are brought again and ticked, and the page is not reloaded", async () => {
    const file = await savedFile();
    app.setup = structuredClone(setup); // a page that has never seen the part
    app.state = initial(app.setup);
    await openSetup(asFile(file));
    expect(reloads).toBe(0);
    expect(brought).toEqual(file.parts);
    expect(app.state.devices).toEqual(["mine-again"]);
    expect(app.state.added).toEqual(["mine-again"]);
    expect(app.state.step).toBe(3);
    expect(document.body.dataset.at).toBe("3");
    expect(ui.setupNote).toEqual({ bad: false, text: "mine.json is open, with everything it holds." });
    expect(document.querySelector("#panel .setup-note")!.textContent).toContain("is open, with everything it holds");
  });
  it("carries the edge limit, and gives it back on opening", async () => {
    app.state.conditions.edge_limit = "close";
    const file = await savedFile();
    app.setup = structuredClone(setup);
    app.state = initial(app.setup);
    expect(app.state.conditions.edge_limit).toBe("cable");
    await openSetup(asFile(file));
    expect(app.state.conditions.edge_limit).toBe("close");
  });
  it("of an earlier version, naming its parts without carrying them, opens and says what is missing", async () => {
    const file = await savedFile();
    app.setup = structuredClone(setup);
    await openSetup(asFile({ app: "MotionSim", setup: 2, state: file.state }));
    expect(reloads).toBe(0);
    expect(brought).toEqual([]);
    expect(app.state.step).toBe(3);
    expect(app.state.devices).toEqual([]);
    expect(ui.setupNote!.bad).toBe(true);
    expect(ui.setupNote!.text).toMatch(/names a part it does not carry.*add it again in step 1/);
  });
  it("says so in the page's words when the engine does not answer once the parts are brought", async () => {
    const file = await savedFile();
    app.setup = structuredClone(setup);
    renderPanel(); // drawn once, as the page is when the file is chosen
    const before = structuredClone(app.state);
    vi.mocked(api.setup).mockRejectedValueOnce(new Error("the engine answered 500"));
    await openSetup(asFile(file));
    expect(ui.setupNote!.bad).toBe(true);
    expect(ui.setupNote!.text).not.toMatch(/^Opening/);
    expect(ui.setupNote!.text).toContain("mine.json could not be opened");
    expect(ui.setupNote!.text).toContain("the engine answered 500");
    expect(app.state).toEqual(before);
  });
  it("larger than any setup could be is refused unread", async () => {
    const read = vi.fn(() => Promise.resolve("{}"));
    await openSetup({ name: "big.json", size: 6 * 1024 * 1024, text: read } as unknown as File);
    expect(read).not.toHaveBeenCalled();
    const text = "big.json is larger than 5 MB, which no setup file saved from this page is.";
    expect(ui.setupNote).toEqual({ bad: true, text: `${text} Choose a file made by Save setup.` });
  });
  it("carrying more parts than a setup holds brings the first of them, and says the rest were left out", async () => {
    const file = await savedFile();
    app.setup = structuredClone(setup);
    const parts = Array.from({ length: 30 }, (_, k) => ({
      id: `p${k}`,
      route: "/api/device",
      body: { name: `p${k}.device.yaml`, text: `model ${k}` },
    }));
    await openSetup(asFile({ ...file, parts }));
    expect(brought.length).toBe(20);
    expect(ui.setupNote!.text).toContain("10 more parts it carries were left out");
  });
  it("brings its own model of a part where this page holds another under the same name, and says so", async () => {
    const file = await savedFile();
    const parts = [{ id: "mine", route: "/api/device", body: { name: "mine.device.yaml", text: "another model" } }];
    await openSetup(asFile({ ...file, parts }));
    expect(brought).toEqual(parts);
    expect(app.state.devices).toEqual(["mine-again"]);
    expect(ui.setupNote!.text).toContain("Part mine-again is the model this file carries");
  });
  it("uses the part this page holds where its model is the one the file carries", async () => {
    const file = await savedFile();
    await openSetup(asFile(file));
    expect(brought).toEqual([]);
    expect(app.state.devices).toEqual(["mine"]);
    expect(ui.setupNote).toEqual({ bad: false, text: "mine.json is open, with everything it holds." });
  });
  it("that is not one is refused and changes nothing", async () => {
    renderPanel(); // drawn once, as the page is when the file is chosen
    const before = structuredClone(app.state);
    await openSetup(asFile({ app: "Other" }));
    expect(app.state).toEqual(before);
    expect(ui.setupNote!.bad).toBe(true);
  });
});

describe("Reset", () => {
  it("clears everything entered in place, with step 1 open, and does not reload the page", () => {
    vi.stubGlobal("confirm", () => true);
    startOver();
    expect(reloads).toBe(0);
    expect(app.state).toEqual(initial(app.setup));
    expect(document.body.dataset.at).toBe("0");
  });
  it("asked and not confirmed, changes nothing", () => {
    vi.stubGlobal("confirm", () => false);
    const before = structuredClone(app.state);
    startOver();
    expect(app.state).toEqual(before);
  });
});

describe("the bar at the top", () => {
  it("says, from the first moment, which of its three stages the engine is starting at and for how long", () => {
    const status = document.querySelector<HTMLElement>("#engine-status")!;
    expect(status.getAttribute("role")).toBe("status");
    expect(status.getAttribute("aria-live")).toBe("polite");
    expect(status.hidden).toBe(true); // nothing is said where no engine starts
    ui.startAt = Date.now() - 4200;
    ui.startStage = 2;
    ui.starting = "Fetching the numerical libraries from cdn.jsdelivr.net";
    renderEngineStatus();
    expect(status.hidden).toBe(false);
    expect(status.querySelector(".what")!.textContent).toBe(
      "Starting the engine, 2 of 3: fetching the numerical libraries from cdn.jsdelivr.net",
    );
    expect(status.querySelector("[data-since]")!.textContent).toBe("4 s");
    ui.starting = null;
    renderEngineStatus();
    expect(status.hidden).toBe(true); // the bar is left to the page once it has started
    expect(document.querySelector("#announce")?.textContent).toBe("The engine has started.");
  });
  it("saves and opens the setup from every step, and resets with a word on it", () => {
    for (const step of [0, 1, 2, 3, 4]) {
      app.state.step = step;
      renderPanel();
      expect(document.querySelector("header.top [data-save-setup]"), `step ${step}`).not.toBeNull();
      expect(document.querySelector("header.top input[data-setup-file]"), `step ${step}`).not.toBeNull();
    }
    expect(document.querySelector("header.top .reset")!.textContent).toBe("Reset");
    expect(document.querySelector("#top-more [data-start-over]")!.textContent).toBe("Reset: clear everything entered");
  });
  it("opens what the tool is as a popover that closes by itself, under its own label", () => {
    const opener = document.querySelector<HTMLButtonElement>("header.top .about-button")!;
    expect(opener.getAttribute("popovertarget")).toBe("about");
    expect(opener.textContent).toBe("Exploratory tool");
    expect(document.querySelector("#about")!.getAttribute("popover")).toBe("auto");
  });
  it("closes the equations from a × at their top right, named for a screen reader", () => {
    const close = document.querySelector<HTMLButtonElement>("#equations .dialog-head [data-close-equations]")!;
    expect(close.getAttribute("aria-label")).toBe("Close the equations");
    expect(close.textContent).toBe("");
    expect(close.className).toBe("close");
  });
});
