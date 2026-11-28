// @vitest-environment happy-dom
// The lab's menus as a keyboard uses them: the list of schemes is a command menu (search, the
// arrows, Enter, Escape), its rows are the labels cut at their bracket for the eye alone, the
// list is in one order however often it is opened, and every press drawn as an icon says what
// it does.

import { act, fireEvent } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelRun } from "../src/control/actions";
import { control, Missing } from "../src/control/client";
import { mount, unmount } from "../src/control/lab";
import { stop } from "../src/control/play";
import { groupsFor, moveOf, partsOf } from "../src/control/schemepicker";
import { lab } from "../src/control/store";
import { inkOf } from "../src/control/tabink";
import type { Loops, Presets, Run } from "../src/control/types";
import designFile from "./fixtures/control-design.json";
import loopsFile from "./fixtures/control-loops.json";
import presetsFile from "./fixtures/control-presets.json";
import allFile from "./fixtures/control-schemes-all.json";
import holdFile from "./fixtures/control-run-hold.json";

const presets = presetsFile as unknown as Presets;
const hold = holdFile as unknown as Run;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDialogElement;
const $ = <T extends Element = HTMLElement>(s: string) => host.querySelector<T>(s);
const all = <T extends Element = HTMLElement>(s: string) => [...host.querySelectorAll<T>(s)];
const press = (s: string) => act(() => fireEvent.click($(s)!));
const key = (name: string, more: KeyboardEventInit = {}) =>
  act(() => fireEvent.keyDown($(".lab-picker-search input")!, { key: name, ...more }));
const labels = () => all(".lab-picker-list .lab-picker-label").map((l) => l.textContent);
const lit = () => $(".lab-picker-option.is-active .lab-picker-label")!.textContent;

async function opened(): Promise<void> {
  host = document.body.appendChild(document.createElement("dialog"));
  await act(async () => {
    mount(host, { key: `k${Math.random()}`, design: designFile, presets, name: "a made-up part" });
    await Promise.resolve();
  });
}

beforeEach(() => {
  const media = { matches: true, addEventListener: () => undefined, removeEventListener: () => undefined };
  vi.stubGlobal("matchMedia", () => media);
  localStorage.clear();
  lab.reset();
  vi.spyOn(control, "loops").mockResolvedValue(loopsFile as unknown as Loops);
  vi.spyOn(control, "kept").mockResolvedValue([]);
  vi.spyOn(control, "run").mockResolvedValue(hold);
  vi.spyOn(control, "runStreamed").mockResolvedValue(hold);
  vi.spyOn(control, "explorations").mockRejectedValue(new Missing("/api/control/explorations"));
});

afterEach(() => {
  cancelRun();
  stop();
  if (host) act(() => unmount(host));
  host?.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("a scheme's label in the list", () => {
  const every = (allFile as unknown as Presets).schemes.map((s) => s.label);

  it("is cut at its bracket for the eye, with not a word changed", () => {
    expect(partsOf("Cascaded speed and current control (servo)")).toEqual({
      name: "Cascaded speed and current control",
      more: "servo",
    });
    expect(partsOf("Joint servo: speed and current control along an S-curve").more).toBe("");
    for (const label of every) {
      const { name, more } = partsOf(label);
      expect(more ? `${name} (${more})` : name).toBe(label);
    }
    expect(every.filter((l) => partsOf(l).more).length).toBeGreaterThan(5);
  });

  it("is drawn whole in its row: the name, then what its brackets add, and whole in its tip", async () => {
    await opened();
    await press("#lab-scheme");
    const rows = all('.lab-picker-list [role="option"]');
    expect(rows.map((r) => r.querySelector(".lab-picker-label")!.textContent)).toEqual(
      groupsFor(presets, [], "").flatMap((g) => g.options.map((o) => o.label)),
    );
    for (const row of rows) {
      const label = row.querySelector(".lab-picker-label")!.textContent;
      const { name, more } = partsOf(label);
      expect(row.querySelector(".lab-picker-name")!.textContent).toBe(name);
      expect(row.querySelector(".lab-picker-more")?.textContent.trim() ?? "").toBe(more ? `(${more})` : "");
      // Cut short by the list's width, it is read whole in its tip (and only then).
      expect(row.dataset.tip).toBe(label);
      expect(row.dataset.tipClipped).toBe(".lab-picker-label");
    }
    // The reason is on the recommended one alone.
    expect(all(".lab-picker-note").length).toBe(1);
    expect(rows[0].querySelector(".lab-picker-note")).not.toBeNull();
  });
});

describe("the list of schemes under the keyboard", () => {
  it("goes round with the arrows, to its ends with Ctrl+Home and Ctrl+End, and nowhere when empty", () => {
    expect(moveOf({ key: "ArrowDown" }, 0, 3)).toBe(1);
    expect(moveOf({ key: "ArrowDown" }, 3, 3)).toBe(0);
    expect(moveOf({ key: "ArrowUp" }, 0, 3)).toBe(3);
    expect(moveOf({ key: "ArrowUp" }, 2, 3)).toBe(1);
    expect(moveOf({ key: "End", ctrlKey: true }, 1, 3)).toBe(3);
    expect(moveOf({ key: "Home", ctrlKey: true }, 2, 3)).toBe(0);
    expect(moveOf({ key: "Home" }, 2, 3)).toBeNull();
    expect(moveOf({ key: "a" }, 2, 3)).toBeNull();
    expect(moveOf({ key: "ArrowDown" }, 0, -1)).toBeNull();
  });

  it("opens with the keyboard in its search, on the scheme in the lab, and says its keys", async () => {
    await opened();
    await press("#lab-scheme");
    const search = $<HTMLInputElement>(".lab-picker-search input")!;
    expect(document.activeElement).toBe(search);
    expect(search.getAttribute("role")).toBe("combobox");
    expect(search.getAttribute("aria-expanded")).toBe("true");
    const current = $('.lab-picker-list [role="option"][aria-selected="true"]')!;
    expect(search.getAttribute("aria-activedescendant")).toBe(current.id);
    expect(current.classList.contains("is-active")).toBe(true);
    expect(all(".lab-picker-foot kbd").map((k) => k.textContent)).toEqual(["↑", "↓", "Enter", "Esc"]);
    // The keys are for the eye: the roles say them to a screen reader.
    expect($(".lab-picker-foot")!.getAttribute("aria-hidden")).toBe("true");
  });

  it("moves with the arrows, takes with Enter, and gives the keyboard back to its press", async () => {
    await opened();
    await press("#lab-scheme");
    const order = labels();
    await key("ArrowDown");
    expect(lit()).toBe(order[1]);
    expect($(".lab-picker-search input")!.getAttribute("aria-activedescendant")).toBe(
      $(".lab-picker-option.is-active")!.id,
    );
    await key("ArrowUp");
    await key("ArrowUp");
    expect(lit()).toBe(order[order.length - 1]);
    await key("ArrowDown");
    await key("ArrowDown");
    await key("Enter");
    expect($(".lab-picker-panel")!.hidden).toBe(true);
    expect(document.activeElement).toBe($("#lab-scheme"));
    expect(lab.get().scheme!.id).toBe(presets.schemes.find((s) => s.label === order[1])!.id);
  });

  it("narrows as it is typed in, the first left lit, and Enter takes it", async () => {
    await opened();
    await press("#lab-scheme");
    const search = $<HTMLInputElement>(".lab-picker-search input")!;
    await act(() => fireEvent.change(search, { target: { value: "predictive" } }));
    expect(labels().length).toBeGreaterThan(0);
    expect(labels().length).toBeLessThan(presets.schemes.length);
    expect(lit()).toBe(labels()[0]);
    const taken = labels()[0];
    await key("Enter");
    expect(lab.get().scheme!.label).toBe(taken);
    // Nothing named so: said, and Enter takes nothing.
    await press("#lab-scheme");
    await act(() => fireEvent.change($(".lab-picker-search input")!, { target: { value: "zzzz" } }));
    expect($(".lab-picker-none")).not.toBeNull();
    await key("Enter");
    expect(lab.get().scheme!.label).toBe(taken);
  });

  it("keeps its order: the scheme taken is ticked where it stood, never moved to the top", async () => {
    await opened();
    await press("#lab-scheme");
    const order = labels();
    await key("ArrowDown");
    await key("ArrowDown");
    await key("Enter");
    await press("#lab-scheme");
    expect(labels()).toEqual(order);
    const ticked = $('.lab-picker-list [role="option"][aria-selected="true"]')!;
    expect(ticked.querySelector(".lab-picker-label")!.textContent).toBe(order[2]);
    expect(all('.lab-picker-list [role="option"]').indexOf(ticked)).toBe(2);
    // It opens on the one in the lab, the search emptied.
    expect(lit()).toBe(order[2]);
    expect($<HTMLInputElement>(".lab-picker-search input")!.value).toBe("");
  });
});

describe("the presses of the lab drawn as an icon", () => {
  /** Whether a press shows words of its own (not only an icon, or words for a screen reader). */
  const worded = (b: Element): boolean => {
    const copy = b.cloneNode(true) as Element;
    copy.querySelectorAll("svg, .sr-only, [aria-hidden='true'], .lab-icon").forEach((x) => x.remove());
    return copy.textContent.trim() !== "";
  };

  it("each have a name and a tip that says what they do", async () => {
    await opened();
    await press(".lab-run button.primary");
    await press('[data-block="speed"] .lab-node-head');
    expect($(".lab-inspector")).not.toBeNull();
    const bare = all("button").filter((b) => !worded(b) && !b.closest(".lab-diagram, .scope"));
    expect(bare.map((b) => b.getAttribute("aria-label"))).toEqual(
      expect.arrayContaining(["Why this scheme for your design", "Close the inspector"]),
    );
    for (const b of bare) {
      expect(b.getAttribute("aria-label") ?? "", b.outerHTML.slice(0, 120)).not.toBe("");
      expect(b.title || b.dataset.tip || "", b.outerHTML.slice(0, 120)).not.toBe("");
    }
  });

  it("say the key that does the same where there is one", async () => {
    await opened();
    expect($(".lab-close")!.dataset.keys).toBe("Esc");
    expect($(".lab-go")!.dataset.keys).toBe("Ctrl+Enter");
    expect($(".lab-go")!.dataset.tip).toBe("Run the test");
    expect($(".lab-go")!.getAttribute("aria-keyshortcuts")).toBe("Control+Enter");
  });
});

describe("the tabs' underline", () => {
  it("is one mark in the strip, placed under the words of the tab taken", async () => {
    await opened();
    expect(all(".tabs .lab-tab-ink").length).toBe(1);
    expect($(".tabs .lab-tab-ink")!.getAttribute("aria-hidden")).toBe("true");
    // Nothing is measured here (no layout): each tab keeps its own underline.
    expect($(".tabs")!.classList.contains("has-ink")).toBe(false);
    const tab = document.createElement("button");
    expect(inkOf(tab)).toBeNull();
    for (const [name, value] of Object.entries({ offsetWidth: 116, offsetLeft: 249, offsetTop: 0, offsetHeight: 42 }))
      Object.defineProperty(tab, name, { value });
    tab.style.paddingLeft = "16px";
    document.body.append(tab);
    expect(inkOf(tab)).toEqual({ x: 265, y: 40, w: 84 });
    tab.remove();
  });
});

describe("the sheet of the lab's menus", () => {
  const dir = "src/control";
  const css = readFileSync(`${dir}/menus.css`, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const rule = (selector: string): string =>
    [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter(([, s]) => s.split(",").some((x) => x.trim() === selector))
      .map(([, , body]) => body)
      .join("\n");

  it("keeps to the page's tokens: spacing, radii, colours and times", () => {
    for (const m of css.matchAll(/^\s*(margin|padding|gap|row-gap|column-gap)[a-z-]*\s*:\s*([^;]+);/gm))
      expect(m[2].replace(/var\(--s[1-8]\)/g, ""), m[0]).not.toMatch(/[3-9]px|\d\dpx|r?em\b/);
    for (const m of css.matchAll(/border-radius\s*:\s*([^;]+);/g))
      expect(m[1].trim(), m[0]).toMatch(/^var\(--r(-mark|-sm|-lg)?\)$/);
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(|cubic-bezier\(/i);
    for (const m of css.matchAll(/(?:transition|animation)[^;]*?(\d+m?s)\b/g)) expect(m[0]).toBe("");
    expect(readdirSync(dir)).toContain("menus.css");
  });

  it("sets a row as one line, its family named small in the data face", () => {
    expect(rule(".lab-picker-option")).toMatch(/min-height:\s*32px/);
    expect(rule(".lab-picker-option")).toMatch(/border-radius:\s*var\(--r-sm\)/);
    expect(rule(".lab-picker-label")).toMatch(/text-overflow:\s*ellipsis/);
    expect(rule(".lab-picker-name")).toMatch(/font-weight:\s*500/);
    const group = rule(".lab-picker-group");
    expect(group).toMatch(/font-family:\s*var\(--mono\)/);
    expect(group).toMatch(/font-size:\s*var\(--t-data\)/);
    expect(group).toMatch(/text-transform:\s*uppercase/);
  });

  it("gives the recommended row the room to be read: its name whole, its reason on two lines", () => {
    // Cut on both its lines, the one scheme the list recommends could not be read in it.
    const name = rule(".lab-picker-option:has(.lab-picker-note) .lab-picker-label");
    expect(name).toMatch(/white-space:\s*normal/);
    expect(name).not.toMatch(/line-clamp|text-overflow/);
    const reason = rule(".lab-picker-option:has(.lab-picker-note) .lab-picker-note");
    expect(reason).toMatch(/white-space:\s*normal/);
    expect(reason).toMatch(/line-clamp:\s*2/);
    // The rows of the other schemes stay one line each.
    expect(rule(".lab-picker-label")).toMatch(/white-space:\s*nowrap/);
  });

  it("holds the lab's frame still, and keeps the account of a scheme on a phone's screen", () => {
    // Words kept for a screen reader, out of the flow, never make the frame itself scroll.
    expect(rule("dialog.control-lab")).toMatch(/overflow:\s*clip/);
    const phone = css.slice(css.indexOf("@media (max-width: 700px)"));
    expect(phone).toMatch(/\.lab-why \{\s*position: static;/);
    expect(phone).toMatch(/\.lab-why-panel \{\s*right: 0;\s*left: 0;\s*width: auto;/);
    // A search box under 16px makes a phone zoom the page.
    expect(css).toMatch(/@media \(pointer: coarse\)[^{]*\{\s*\.lab-picker-search input \{\s*font-size: 16px;/);
  });

  it("opens a panel out of its press and shuts it back, at the fast time", () => {
    const panels = rule(".lab-picker-panel");
    expect(panels).toMatch(/opacity var\(--dur-1\) var\(--ease-out\)/);
    expect(panels).toMatch(/display var\(--dur-1\) allow-discrete/);
    expect(panels).toMatch(/border-radius:\s*var\(--r-lg\)/);
    expect(panels).toMatch(/box-shadow:\s*var\(--shadow-float\)/);
    expect(rule(".lab-picker-panel[hidden]")).toMatch(/transform:\s*scale\(/);
    // Where each grows from is its own press: lab.css says the corner.
    const lab = readFileSync(`${dir}/lab.css`, "utf8");
    expect(lab).toMatch(/\.lab-picker-panel \{[^}]*transform-origin: top left/);
    expect(lab).toMatch(/\.lab-test-panel \{[^}]*transform-origin: top right/);
    // Stilled with the rest of the lab where motion is asked to be reduced.
    expect(lab).toMatch(/\.lab \*,[^{]*\{\s*transition: none !important;\s*animation: none !important/);
  });
});
