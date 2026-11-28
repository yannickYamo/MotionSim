// @vitest-environment happy-dom
// What a control says of itself when pointed at: the first tip waits, the next is there at
// once, and the page cools a moment after the pointer has left them all.
import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { coldTips, COOL, keyCaps, QUICK, tooltips, WAIT } from "../src/tips";

const point = (el: Element, type = "pointerover", pointerType = "mouse") =>
  el.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerType }));
const $ = (s: string) => document.querySelector<HTMLElement>(s)!;
const tip = () => document.querySelector<HTMLElement>("#tt");
const up = () => !!tip() && !tip()!.hidden;

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML =
    '<button id="a" title="Zoom in"><svg></svg></button>' +
    '<button id="b" aria-label="Zoom out" title="Zoom out"><svg></svg></button>' +
    '<button id="run" data-tip="Run the test" data-keys="Ctrl+Enter">Run the test</button>' +
    '<button id="now" title="Stop the run" data-tip-wait="quick">Stop</button>' +
    '<button id="ask" title="Ask" aria-label="Ask about the design"><svg></svg><span>Ask</span></button>' +
    '<button id="step" title="Device"><span><span>1</span>Device</span><span>The part to test</span></button>' +
    '<span id="h" class="has-tip" tabindex="0" aria-describedby="t1">Loss' +
    '<span role="tooltip" id="t1" class="tip">Every switch.</span></span>' +
    '<p id="plain">Nothing to say</p>';
  tooltips();
  coldTips();
});

afterEach(() => {
  coldTips();
  vi.useRealTimers();
});

describe("a tip pointed at", () => {
  it("waits the first time, and is the control's title, kept from the browser's own tip", () => {
    point($("#a"));
    expect($("#a").hasAttribute("title")).toBe(false);
    vi.advanceTimersByTime(WAIT - 1);
    expect(up()).toBe(false);
    vi.advanceTimersByTime(1);
    expect(up()).toBe(true);
    expect(tip()!.textContent).toBe("Zoom in");
    expect(tip()!.getAttribute("role")).toBe("tooltip");
    // A control named by its title alone keeps its name while the title is away.
    expect($("#a").getAttribute("aria-label")).toBe("Zoom in");
  });

  it("is there at once on the control beside it, and waits again once the page has cooled", () => {
    point($("#a"));
    vi.advanceTimersByTime(WAIT);
    point($("#b"));
    expect(up()).toBe(true);
    expect(tip()!.textContent).toBe("Zoom out");
    expect(tip()!.classList.contains("is-instant")).toBe(true);
    // Left for less than the cooling time: still warm.
    point($("#plain"));
    expect(up()).toBe(false);
    vi.advanceTimersByTime(COOL - 1);
    point($("#a"));
    expect(up()).toBe(true);
    // Left for the whole of it: the next one waits as the first did.
    point($("#plain"));
    vi.advanceTimersByTime(COOL);
    point($("#b"));
    expect(up()).toBe(false);
    vi.advanceTimersByTime(WAIT);
    expect(up()).toBe(true);
  });

  it("gives the title back when the control is left, and never came up if left early", () => {
    point($("#a"));
    vi.advanceTimersByTime(WAIT - 100);
    point($("#plain"));
    vi.advanceTimersByTime(WAIT);
    expect(up()).toBe(false);
    expect($("#a").title).toBe("Zoom in");
    expect($("#a").dataset.tip).toBeUndefined();
  });

  it("comes sooner where it is marked quick", () => {
    point($("#now"));
    vi.advanceTimersByTime(QUICK);
    expect(up()).toBe(true);
  });

  it("says nothing where its words are only the label the control already shows", () => {
    for (const id of ["#ask", "#step"]) {
      point($(id));
      vi.advanceTimersByTime(WAIT);
      expect(up(), id).toBe(false);
      point($("#plain"));
      vi.advanceTimersByTime(COOL);
      // The title is given back as it was written: the control keeps its name.
      expect($(id).title).not.toBe("");
    }
  });

  it("still says the label of a control whose words are not on screen: an icon alone, a narrow rail", () => {
    // The name is in the page but not drawn (display: none on a narrow rail).
    const hidden = $("#step").querySelector<HTMLElement>("span")!;
    for (const el of [hidden, ...hidden.querySelectorAll<HTMLElement>("*")]) el.checkVisibility = () => false;
    point($("#step"));
    vi.advanceTimersByTime(WAIT);
    expect(up()).toBe(true);
    expect(tip()!.textContent).toBe("Device");
    point($("#plain"));
    vi.advanceTimersByTime(COOL);
    // Kept for a screen reader alone, the words are not on screen either.
    $("#ask").querySelector("span")!.className = "sr";
    point($("#ask"));
    vi.advanceTimersByTime(WAIT);
    expect(up()).toBe(true);
    expect(tip()!.textContent).toBe("Ask");
  });

  it("shows the keys that do the same, each in its cap", () => {
    point($("#run"));
    vi.advanceTimersByTime(WAIT);
    expect([...tip()!.querySelectorAll("kbd.kbd")].map((k) => k.textContent)).toEqual(["Ctrl", "Enter"]);
    expect(tip()!.firstElementChild!.textContent).toBe("Run the test");
    // The words are the press's own name: nothing is said twice to a screen reader.
    expect($("#run").hasAttribute("aria-describedby")).toBe(false);
    expect(keyCaps("Esc").length).toBe(1);
  });

  it("describes the control while it is up where it says more than the name", () => {
    $("#b").title = "Zoom out of the drawing";
    point($("#b"));
    vi.advanceTimersByTime(WAIT);
    expect($("#b").getAttribute("aria-describedby")).toBe("tt");
    point($("#plain"));
    expect($("#b").hasAttribute("aria-describedby")).toBe(false);
    expect($("#b").title).toBe("Zoom out of the drawing");
  });

  it("goes at a press and at a key, and does not come back until the control is left", () => {
    point($("#a"));
    vi.advanceTimersByTime(WAIT);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(up()).toBe(false);
    point($("#a"));
    vi.advanceTimersByTime(WAIT);
    expect(up()).toBe(false);
    point($("#b"));
    expect(up()).toBe(true);
    point($("#b"), "pointerdown");
    expect(up()).toBe(false);
  });

  it("is not raised by a finger, but a figure's own tip opens to a touch", () => {
    point($("#a"), "pointerover", "touch");
    vi.advanceTimersByTime(WAIT);
    expect(up()).toBe(false);
    point($("#h"), "pointerdown", "touch");
    expect($("#h").classList.contains("is-tipped")).toBe(true);
    point($("#plain"), "pointerdown", "touch");
    expect($("#h").classList.contains("is-tipped")).toBe(false);
  });

  it("gives a figure's drawn tip the same wait and the same warmth", () => {
    point($("#h"));
    vi.advanceTimersByTime(WAIT - 1);
    expect($("#h").classList.contains("is-tipped")).toBe(false);
    vi.advanceTimersByTime(1);
    expect($("#h").classList.contains("is-tipped")).toBe(true);
    expect(up()).toBe(false);
    point($("#a"));
    expect($("#h").classList.contains("is-tipped")).toBe(false);
    expect(up()).toBe(true);
  });

  it("is only for words cut short where it is marked so", () => {
    document.body.insertAdjacentHTML(
      "beforeend",
      '<div id="row" data-tip="A long name" data-tip-clipped="">A long…</div>',
    );
    point($("#row"));
    vi.advanceTimersByTime(WAIT);
    expect(up()).toBe(false);
    Object.defineProperty($("#row"), "scrollWidth", { value: 300 });
    Object.defineProperty($("#row"), "clientWidth", { value: 120 });
    point($("#plain"));
    vi.advanceTimersByTime(COOL);
    point($("#row"));
    vi.advanceTimersByTime(WAIT);
    expect(up()).toBe(true);
  });
});

describe("the sheet of the tips", () => {
  const css = readFileSync("src/tips.css", "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const page = readFileSync("src/style.css", "utf8");

  it("keeps to the page's tokens: spacing, radii, colours and times", () => {
    for (const m of css.matchAll(/^\s*(margin|padding|gap|row-gap|column-gap)[a-z-]*\s*:\s*([^;]+);/gm))
      expect(m[2].replace(/var\(--s[1-8]\)/g, ""), m[0]).not.toMatch(/[3-9]px|\d\dpx|r?em\b/);
    for (const m of css.matchAll(/border-radius\s*:\s*([^;]+);/g))
      expect(m[1].trim(), m[0]).toMatch(/^(var\(--r(-mark|-sm|-lg)?\)|inherit)$/);
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(|cubic-bezier\(/i);
    expect(css).toMatch(/prefers-reduced-motion: reduce/);
  });

  it("never breaks one of the verdict's figures inside a word, and steps its size by the column", () => {
    const rule = /\.key-figures \.figure,\s*\.key-figures \.figure\.words\s*\{([^}]*)\}/.exec(css)![1];
    expect(rule).toMatch(/white-space:\s*nowrap/);
    expect(rule).toMatch(/overflow-wrap:\s*normal/);
    const steps = [...css.matchAll(/@container panel \(max-width: ([\d.]+)px\)\s*\{[^}]*font-size:\s*([^;]+);/g)];
    expect(steps.map((s) => [Math.round(Number(s[1])), s[2]])).toEqual([
      [560, "36px"],
      [460, "var(--t-figure)"],
    ]);
    // The panel is the container the steps are read from.
    expect(page).toMatch(/container:\s*panel \/ inline-size/);
  });

  it("shows a figure's drawn tip when it is marked, not at the first touch of the pointer", () => {
    expect(page).toMatch(/\.has-tip\.is-tipped > \.tip,\s*\.has-tip:focus-visible > \.tip \{\s*display: block/);
    expect(page).not.toMatch(/\.has-tip:hover > \.tip/);
  });
});
