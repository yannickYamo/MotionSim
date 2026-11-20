// @vitest-environment happy-dom
// Where the browser has no popovers, the menus of the bar are hidden until their button is
// pressed, and shut again as a popover would be: never laid open over the page for good.
import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Setup } from "../src/api";
import { onKeydown } from "../src/events/keys";
import { menusWithoutPopover } from "../src/events/menus";
import { initial } from "../src/state";
import { app } from "../src/store";
import { topBar } from "../src/views/render";

const setup = JSON.parse(readFileSync("tests/fixtures/setup.json", "utf8")) as Setup;

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  app.setup = structuredClone(setup);
  app.state = initial(setup);
  document.body.innerHTML = `<div id="app">${topBar()}<p id="elsewhere">The page</p></div>`;
  menusWithoutPopover(false);
});

const about = () => document.querySelector<HTMLElement>("#about")!;
const menu = () => document.querySelector<HTMLElement>("#top-more")!;
const press = (selector: string) => document.querySelector<HTMLElement>(selector)!.click();

describe("the bar's menus where the browser has no popovers", () => {
  it("are hidden until their button is pressed, and shut with a press elsewhere", () => {
    expect(about().hidden).toBe(true);
    expect(menu().hidden).toBe(true);
    press('[popovertarget="about"]');
    expect(about().hidden).toBe(false);
    expect(document.querySelector('[popovertarget="about"]')!.getAttribute("aria-expanded")).toBe("true");
    expect(menu().hidden).toBe(true);
    press("#elsewhere");
    expect(about().hidden).toBe(true);
    expect(document.querySelector('[popovertarget="about"]')!.getAttribute("aria-expanded")).toBe("false");
  });
  it("shut with Escape, and with a second press of their button", () => {
    press('[popovertarget="top-more"]');
    expect(menu().hidden).toBe(false);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(menu().hidden).toBe(true);
    press('[popovertarget="top-more"]');
    press('[popovertarget="top-more"]');
    expect(menu().hidden).toBe(true);
  });
  it("hide a menu drawn later, as the comparison's + Add and its columns' are, and keep it so redrawn", async () => {
    const later = document.createElement("div");
    later.innerHTML =
      '<button type="button" popovertarget="add-menu" aria-expanded="false">+ Add</button>' +
      '<div id="add-menu" popover="auto" role="menu"><button type="button" role="menuitem">A load</button></div>';
    document.querySelector("#app")!.append(later);
    await Promise.resolve();
    const add = () => document.querySelector<HTMLElement>("#add-menu")!;
    expect(add().hidden).toBe(true);
    press('[popovertarget="add-menu"]');
    expect(add().hidden).toBe(false);
    // Drawn again, as the page does, without the hidden it was given: it stays as it was.
    add().removeAttribute("hidden");
    press("#elsewhere");
    await Promise.resolve();
    expect(add().hidden).toBe(true);
    add().removeAttribute("hidden");
    await Promise.resolve();
    expect(add().hidden).toBe(true);
  });
  it("are left to the browser where it has popovers", () => {
    document.body.innerHTML = `<div id="app">${topBar()}</div>`;
    menusWithoutPopover(true);
    expect(about().hidden).toBe(false);
  });
});

describe("a menu of the comparison where the browser has no popovers", () => {
  const rect = (top: number, left: number, width: number, height: number) =>
    ({ top, left, width, height, bottom: top + height, right: left + width, x: left, y: top }) as DOMRect;
  const add = () => document.querySelector<HTMLElement>("#add-menu")!;
  const opener = () => document.querySelector<HTMLElement>("#add-button")!;
  const key = (k: string) =>
    (document.activeElement ?? document.body).dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));
  beforeEach(async () => {
    vi.stubGlobal("innerHeight", 900);
    vi.stubGlobal("innerWidth", 400);
    const table = document.createElement("div");
    table.innerHTML =
      '<button type="button" id="add-button" popovertarget="add-menu" aria-haspopup="menu" aria-expanded="false">' +
      "+ Add</button>" +
      '<div id="add-menu" class="menu" popover="auto" role="menu" aria-labelledby="add-button">' +
      '<button type="button" role="menuitem" tabindex="-1" disabled>Another device</button>' +
      '<button type="button" role="menuitem" tabindex="-1">A load</button>' +
      '<button type="button" role="menuitem" tabindex="-1">This motor with a change</button></div>';
    document.querySelector("#app")!.append(table);
    document.addEventListener("keydown", onKeydown);
    // The button sits low on the screen, near its right edge: the menu cannot open under it.
    opener().getBoundingClientRect = () => rect(860, 330, 60, 36);
    add().getBoundingClientRect = () => rect(0, 0, 220, 150);
    await Promise.resolve();
  });

  it("opens next to its button inside the screen, with the keyboard on its first item that can be chosen", () => {
    opener().focus();
    opener().click();
    expect(add().hidden).toBe(false);
    const top = parseFloat(add().style.top);
    const left = parseFloat(add().style.left);
    expect(top + 150).toBeLessThanOrEqual(900 - 8);
    expect(top).toBeGreaterThanOrEqual(8);
    expect(top + 150).toBeLessThanOrEqual(860); // over its button, the room below being too small
    expect(left).toBeGreaterThanOrEqual(8);
    expect(left + 220).toBeLessThanOrEqual(400 - 8);
    expect(document.activeElement?.textContent).toBe("A load");
  });

  it("is gone through with the arrows, and shut with Escape, the keyboard going back to its button", () => {
    opener().focus();
    opener().click();
    key("ArrowDown");
    expect(document.activeElement?.textContent).toBe("This motor with a change");
    key("ArrowDown");
    expect(document.activeElement?.textContent).toBe("A load");
    key("ArrowUp");
    expect(document.activeElement?.textContent).toBe("This motor with a change");
    key("Escape");
    expect(add().hidden).toBe(true);
    expect(document.activeElement).toBe(opener());
    expect(opener().getAttribute("aria-expanded")).toBe("false");
  });

  it("opens under its button where there is room", () => {
    opener().getBoundingClientRect = () => rect(100, 20, 60, 36);
    opener().click();
    expect(parseFloat(add().style.top)).toBe(140);
    expect(parseFloat(add().style.left)).toBe(8);
  });
});
