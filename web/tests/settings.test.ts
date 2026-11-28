// @vitest-environment happy-dom
// The settings of a page served on this machine: the key the datasheet reader is given, set
// and forgotten from a dialog, never drawn on the page, and not offered on the hosted page.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { useEngine } from "../src/api/transport";
import { NoSettings, settingsApi } from "../src/api/settings";
import { onClick } from "../src/events/presses";
import { openSettings } from "../src/settings/actions";
import { KEPT, settingsBody } from "../src/settings/view";
import { initial } from "../src/state";
import { app, draw } from "../src/store";
import { frame, topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;
const KEY = "sk-made-up-0123456789";

type Reader = { available: boolean; key: string; source: string | null; saved: boolean };
const UNSET: Reader = { available: true, key: "unset", source: null, saved: false };
const SAVED: Reader = { available: true, key: "set", source: "saved", saved: true };
const FROM_SHELL: Reader = { available: true, key: "set", source: "environment", saved: false };

/** The server the page talks to, played by the test: what it was sent, and how it stands. */
const server = {
  calls: [] as { url: string; method: string; body: unknown }[],
  reader: UNSET,
  answer: null as null | ((url: string, method: string) => { status: number; body: unknown } | undefined),
  down: false,
};

function serve(url: string, init?: RequestInit) {
  const method = init?.method ?? "GET";
  server.calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined });
  if (server.down) return Promise.reject(new TypeError("Failed to fetch"));
  let said = server.answer?.(url, method);
  if (!said && url === "api/setup") said = { status: 200, body: { ...setup, can_read: server.reader.key === "set" } };
  if (!said && url === "api/settings/key") server.reader = method === "PUT" ? SAVED : UNSET;
  said ??= { status: 200, body: { reader: server.reader } };
  const { status, body } = said;
  return Promise.resolve({ ok: status === 200, status, json: () => Promise.resolve(body) });
}

const dialog = () => document.querySelector<HTMLDialogElement>("#settings-dialog")!;
const box = () => document.querySelector<HTMLInputElement>("#settings-key")!;
const state = () => document.querySelector(".settings-state")!.textContent;
const press = (selector: string) => document.querySelector<HTMLElement>(selector)!.click();
/** Every request under way has been answered, and the page has drawn what came. */
const settled = async () => {
  for (let i = 0; i < 10; i++) await Promise.resolve();
  await new Promise((done) => setTimeout(done, 0));
};
const settingsCalls = () => server.calls.filter((c) => c.url.startsWith("api/settings"));

function page(mode: "server" | "browser" = "server"): void {
  useEngine(mode);
  document.body.innerHTML = `<div id="app">${topBar()}${frame()}</div>`;
  document.querySelector("#app")!.addEventListener("click", onClick);
}

async function opened(reader: Reader = UNSET): Promise<void> {
  server.reader = reader;
  page();
  press("#top-more [data-settings]");
  await settled();
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.stubGlobal("fetch", serve);
  Object.assign(server, { calls: [], reader: UNSET, answer: null, down: false });
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  draw.panel = () => undefined;
});

describe("the settings entry", () => {
  it("is in the bar's menu, a button that says Settings, and not a button of the bar itself", () => {
    page();
    expect(document.querySelector("header.top > button[data-settings]")).toBeNull();
    expect(document.querySelector("#top-more button[data-settings]")!.textContent).toBe("Settings");
  });
  it("has its dialog on a page served on this machine", () => {
    page("server");
    expect(dialog().getAttribute("aria-labelledby")).toBe("settings-title");
    expect(document.querySelector("#settings-title")!.textContent).toBe("Settings");
  });
  it("has no dialog on the hosted page, and is hidden wherever there is none", () => {
    page("browser");
    expect(document.querySelector("#settings-dialog")).toBeNull();
    // The style sheet shows the entry only beside its dialog.
    const css = readFileSync("src/settings/settings.css", "utf8").replace(/\s+/g, " ");
    expect(css).toContain(".top-menu .settings-entry { display: none; }");
    expect(css).toContain("#app:has(#settings-dialog) .top-menu .settings-entry { display: flex; }");
  });
  it("asks nothing and opens nothing on the hosted page", async () => {
    page("browser");
    press("#top-more [data-settings]");
    await openSettings();
    await settled();
    expect(server.calls).toEqual([]);
  });
});

describe("the settings dialog", () => {
  it("opens with the keyboard in the key's box, and asks how the settings stand", async () => {
    await opened();
    expect(dialog().open).toBe(true);
    expect(document.activeElement).toBe(box());
    expect(settingsCalls()).toEqual([{ url: "api/settings", method: "GET", body: undefined }]);
  });
  it("takes the key in a box that does not show it and that the browser is told not to keep", async () => {
    await opened();
    expect(box().type).toBe("password");
    expect(box().getAttribute("autocomplete")).toBe("off");
    expect(box().getAttribute("spellcheck")).toBe("false");
    expect(document.querySelector('label[for="settings-key"]')!.textContent).toBe("Anthropic API key");
  });
  it("says in one sentence where the key is kept and when it leaves the machine", async () => {
    await opened();
    const kept = document.querySelector("#settings-key-kept")!;
    expect(kept.textContent).toBe(KEPT);
    expect(KEPT).toContain("kept in a file on this machine that only your account can read");
    expect(KEPT).toContain("leaves the machine only when a datasheet is read");
    expect(KEPT.match(/[.!?](\s|$)/g)).toHaveLength(1);
    expect(box().getAttribute("aria-describedby")).toBe("settings-key-kept");
  });
  it("says no key is set, and offers nothing to forget", async () => {
    await opened(UNSET);
    expect(state()).toContain("No key is set.");
    expect(document.querySelector("[data-settings-forget]")).toBeNull();
    expect(document.querySelector("[data-settings-save]")!.textContent).toBe("Save the key");
  });
  it("says a key is saved on this machine, and offers to forget it", async () => {
    await opened(SAVED);
    expect(state()).toContain("A key is saved on this machine.");
    expect(document.querySelector("[data-settings-forget]")!.textContent).toBe("Forget the key");
  });
  it("says a key in the environment is the one used", async () => {
    await opened(FROM_SHELL);
    expect(state()).toContain("A key is set in the environment");
    expect(state()).toContain("it is the one used");
    expect(state()).toContain("A key saved here would be used only when that one is gone.");
    expect(document.querySelector("[data-settings-forget]")).toBeNull();
  });
  it("offers to forget a key that is kept while the environment's is the one used", async () => {
    await opened({ ...FROM_SHELL, saved: true });
    expect(state()).toContain("The key saved here is kept, and is used only when that one is gone.");
    expect(document.querySelector("[data-settings-forget]")).not.toBeNull();
  });
  it("says so where the libraries that read a PDF are not installed", async () => {
    await opened({ ...SAVED, available: false });
    expect(document.querySelector(".settings-note")!.textContent).toContain("are not installed");
    await opened(SAVED);
    expect(document.querySelector(".settings-note")).toBeNull();
  });
});

describe("saving a key", () => {
  it("sends the key once, empties the box, and says a key is saved", async () => {
    await opened();
    box().value = KEY;
    press("[data-settings-save]");
    await settled();
    expect(settingsCalls()[1]).toEqual({ url: "api/settings/key", method: "PUT", body: { key: KEY } });
    expect(settingsCalls().filter((c) => c.method === "PUT")).toHaveLength(1);
    expect(box().value).toBe("");
    expect(state()).toContain("A key is saved on this machine.");
    expect(document.activeElement).toBe(box());
  });
  it("leaves the key nowhere on the page", async () => {
    await opened();
    box().value = KEY;
    press("[data-settings-save]");
    await settled();
    expect(document.documentElement.outerHTML).not.toContain(KEY);
    expect([...document.querySelectorAll("input")].some((input) => input.value.includes(KEY))).toBe(false);
  });
  it("is done by Enter in the box as by the button", async () => {
    await opened();
    box().value = KEY;
    box().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await settled();
    expect(settingsCalls().at(-1)).toEqual({ url: "api/settings/key", method: "PUT", body: { key: KEY } });
  });
  it("takes off the space or line end a pasted key came with", async () => {
    await opened();
    box().value = `  ${KEY}\n`;
    press("[data-settings-save]");
    await settled();
    expect(settingsCalls()[1].body).toEqual({ key: KEY });
  });
  it("sends nothing for an empty box, and says at the box that no key was given", async () => {
    await opened();
    box().value = "   ";
    press("[data-settings-save]");
    await settled();
    expect(settingsCalls()).toHaveLength(1);
    expect(document.querySelector("#settings-key-said")!.textContent).toBe(
      "No key was given. Paste the key into the box.",
    );
    expect(box().getAttribute("aria-invalid")).toBe("true");
  });
  it("says a refusal at the box with its fix, and keeps what was typed", async () => {
    await opened();
    server.answer = (_url, method) =>
      method === "PUT"
        ? { status: 422, body: { refused: "a key has no spaces", fix: "paste the key alone", field: "key" } }
        : undefined;
    box().value = "sk with space";
    press("[data-settings-save]");
    await settled();
    const said = document.querySelector("#settings-key-said")!;
    expect(said.textContent).toBe("A key has no spaces. Paste the key alone.");
    expect(said.getAttribute("role")).toBe("alert");
    expect(box().getAttribute("aria-invalid")).toBe("true");
    expect(box().getAttribute("aria-describedby")).toBe("settings-key-said settings-key-kept");
    expect(box().value).toBe("sk with space");
    expect(state()).toContain("No key is set.");
    expect(document.activeElement).toBe(box());
  });
  it("has the first screen say a datasheet can now be read", async () => {
    const drawn = vi.fn();
    draw.panel = drawn;
    app.setup.can_read = false;
    await opened();
    box().value = KEY;
    press("[data-settings-save]");
    await settled();
    expect(app.setup.can_read).toBe(true);
    expect(drawn).toHaveBeenCalledWith(true);
  });
  it("is not sent twice by a second press while the first is on its way", async () => {
    await opened();
    box().value = KEY;
    press("[data-settings-save]");
    expect(document.querySelector<HTMLButtonElement>("[data-settings-save]")!.disabled).toBe(true);
    press("[data-settings-save]");
    await settled();
    expect(settingsCalls().filter((c) => c.method === "PUT")).toHaveLength(1);
    expect(document.querySelector<HTMLButtonElement>("[data-settings-save]")!.disabled).toBe(false);
  });
});

describe("forgetting the key", () => {
  it("asks the server to forget it, and says no key is set", async () => {
    await opened(SAVED);
    app.setup.can_read = true;
    press("[data-settings-forget]");
    await settled();
    expect(settingsCalls().at(-1)).toEqual({ url: "api/settings/key", method: "DELETE", body: undefined });
    expect(state()).toContain("No key is set.");
    expect(document.querySelector("[data-settings-forget]")).toBeNull();
    expect(app.setup.can_read).toBe(false);
  });
});

describe("shutting the settings", () => {
  it("empties the box and gives the keyboard back to the entry", async () => {
    await opened();
    box().value = KEY;
    press("#settings-dialog [data-dialog-close]");
    expect(dialog().open).toBe(false);
    expect(box().value).toBe("");
    expect(document.activeElement).toBe(document.querySelector('[popovertarget="top-more"]'));
  });
  it("drops a refusal, so the dialog opens clean the next time", async () => {
    await opened();
    press("[data-settings-save]");
    await settled();
    expect(document.querySelector("#settings-key-said")).not.toBeNull();
    dialog().close();
    press("#top-more [data-settings]");
    await settled();
    expect(document.querySelector("#settings-key-said")).toBeNull();
  });
  it("gives the keyboard back to the menu's button when opened from the phone's menu", async () => {
    page();
    press("#top-more [data-settings]");
    await settled();
    expect(dialog().open).toBe(true);
    dialog().close();
    expect(document.activeElement).toBe(document.querySelector('[popovertarget="top-more"]'));
  });
});

describe("settings that cannot be asked", () => {
  it("are said to be missing where the program serving the page keeps none", async () => {
    server.answer = (url) => (url.startsWith("api/settings") ? { status: 404, body: { error: "x" } } : undefined);
    await opened();
    const said = document.querySelector("#settings-dialog .fault")!;
    expect(said.textContent).toContain("keeps no settings");
    expect(said.textContent).toContain("set ANTHROPIC_API_KEY in the terminal");
    expect(document.querySelector("#settings-key")).toBeNull();
    expect(document.activeElement).toBe(document.querySelector("#settings-dialog [data-dialog-close]"));
  });
  it("are said not to answer where the server has stopped", async () => {
    server.down = true;
    await opened();
    expect(document.querySelector("#settings-dialog .fault")!.textContent).toContain(
      "The local motionsim server is not answering.",
    );
  });
  it("are said in the server's own words where it will not answer this page", async () => {
    server.answer = (url) =>
      url.startsWith("api/settings")
        ? { status: 403, body: { error: "this address answers only its own page" } }
        : undefined;
    await opened();
    expect(document.querySelector("#settings-dialog .fault")!.textContent).toBe(
      "this address answers only its own page",
    );
  });
});

describe("the settings as the server sends them", () => {
  it("are read from an answer, and a key is never among them", async () => {
    server.reader = SAVED;
    await expect(settingsApi.read()).resolves.toEqual({ reader: SAVED });
    await expect(settingsApi.saveKey(KEY)).resolves.toEqual({ reader: SAVED });
    await expect(settingsApi.forgetKey()).resolves.toEqual({ reader: UNSET });
  });
  it("are a fault where the answer is not the settings", async () => {
    server.answer = () => ({ status: 200, body: { reader: { key: "maybe" } } });
    await expect(settingsApi.read()).rejects.toThrow("an answer this page cannot read");
    server.answer = () => ({ status: 405, body: {} });
    await expect(settingsApi.read()).rejects.toBeInstanceOf(NoSettings);
  });
  it("draw the words of a fault as text, never as markup", () => {
    const drawn = settingsBody({ settings: null, fault: "<img src=x onerror=alert(1)>", refused: null, busy: false });
    expect(drawn).not.toContain("<img");
    expect(drawn).toContain("&lt;img");
  });
});
