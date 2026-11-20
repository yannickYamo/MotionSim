// @vitest-environment happy-dom
// A datasheet PDF dropped on the local server with no model key set says what is missing:
// a key, not that the page itself cannot read it. The page without a server keeps its words.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const where = vi.hoisted(() => ({ mode: "server" }));
vi.mock("../src/api", async (original) => {
  const real = await original<typeof import("../src/api")>();
  const names = ["stage", "proposal", "cycle", "suggest", "loads", "fit", "map", "read", "setup"];
  const api = Object.fromEntries(names.map((n) => [n, vi.fn(() => new Promise(() => undefined))]));
  return { ...real, api: { ...api, mode: () => where.mode, keeps: () => true, forget: vi.fn(), remember: vi.fn() } };
});

import type { Setup } from "../src/api";
import { api } from "../src/api";
import { addPart } from "../src/actions/parts";
import { app, ui } from "../src/store";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const pdf = { name: "sheet.pdf", arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)) } as File;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
  document.body.innerHTML = '<div id="panel"></div><div id="stage"></div>';
  app.setup = { ...setup, can_read: false };
  ui.reading = null;
});

describe("a datasheet PDF with no reader", () => {
  it("on the local server, says a model key is missing and is not read", async () => {
    where.mode = "server";
    await addPart(pdf);
    expect(ui.reading?.refused?.reason).toMatch(/needs a language model's key/);
    expect(ui.reading?.refused?.fix).toMatch(/key to set/);
    expect((api as unknown as Record<string, ReturnType<typeof vi.fn>>).read).not.toHaveBeenCalled();
  });
  it("on the page without a server, says the page cannot read it", async () => {
    where.mode = "browser";
    await addPart(pdf);
    expect(ui.reading?.refused?.reason).toBe("a datasheet PDF cannot be read on this page");
  });
});
