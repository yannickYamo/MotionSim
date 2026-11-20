// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { morph } from "../src/views/morph";

let box: HTMLElement;
beforeEach(() => {
  document.body.innerHTML = '<div id="box"></div>';
  box = document.getElementById("box")!;
});

const field = (value: string, note = "") =>
  `<div class="field"><label for="a">Speed</label><input id="a" value="${value}"/>${note}</div><p>below</p>`;

describe("redrawing over what is there", () => {
  it("ends with the page holding the new markup", () => {
    box.innerHTML = "<p>one</p><ul><li>a</li><li>b</li></ul>";
    const next = '<p class="x">two</p><ul><li>a</li></ul><span>new</span>';
    morph(box, next);
    expect(box.innerHTML).toBe(next);
  });
  it("leaves a node that did not change the very node it was", () => {
    box.innerHTML = field("3000");
    const input = box.querySelector("input")!;
    const below = box.querySelector("p")!;
    morph(box, field("3000", '<p class="help">A note.</p>'));
    expect(box.querySelector("input")).toBe(input);
    expect(box.lastElementChild).toBe(below);
    expect(box.querySelector(".help")!.textContent).toBe("A note.");
  });
  it("keeps the text and the caret of the box being typed in", () => {
    box.innerHTML = field("3000");
    const input = box.querySelector("input")!;
    input.focus();
    input.value = "30abc";
    input.setSelectionRange(2, 2);
    // The state still holds 3000, and the redraw says so: the box keeps what was typed.
    morph(box, field("3000", '<p class="help unread">Not a number.</p>'));
    expect(document.activeElement).toBe(input);
    expect(input.value).toBe("30abc");
    expect(input.selectionStart).toBe(2);
    expect(box.querySelector(".unread")).not.toBeNull();
  });
  it("brings a box that is not being typed in to the figure the page holds", () => {
    box.innerHTML = field("3000");
    const input = box.querySelector("input")!;
    input.value = "typed and left";
    morph(box, field("1500"));
    expect(input.value).toBe("1500");
  });
  it("leaves a fold as it is where the markup says the same of it", () => {
    box.innerHTML = '<details data-fold="gate" open><summary>Gate</summary><p>in</p></details>';
    const fold = box.querySelector("details")!;
    morph(box, '<details data-fold="gate" open><summary>Gate</summary><p>in, changed</p></details>');
    expect(box.querySelector("details")).toBe(fold);
    expect(fold.open).toBe(true);
    expect(fold.querySelector("p")!.textContent).toBe("in, changed");
  });
  it("follows a tick and a choice from the markup, whatever was pressed before", () => {
    const html = (on: boolean, pick: string) =>
      `<input type="checkbox"${on ? " checked" : ""}/><select>` +
      ["a", "b"].map((v) => `<option value="${v}"${v === pick ? " selected" : ""}>${v}</option>`).join("") +
      "</select>";
    box.innerHTML = html(false, "a");
    box.querySelector<HTMLInputElement>("input")!.checked = true;
    box.querySelector("select")!.value = "b";
    morph(box, html(false, "a"));
    expect(box.querySelector<HTMLInputElement>("input")!.checked).toBe(false);
    expect(box.querySelector("select")!.value).toBe("a");
  });
  it("keeps the box being typed in where an unnamed line before its named part comes or goes", () => {
    const box = '<input id="b" value="3">';
    const root = document.createElement("div");
    document.body.append(root);
    root.innerHTML = `<p>working</p><div data-key="w"><p>a</p><p>note</p><details data-fold="f">${box}</details></div>`;
    const input = root.querySelector("input")!;
    input.focus();
    morph(root, `<div data-key="w"><p>a</p><details data-fold="f">${box}</details></div>`);
    expect(root.querySelector("input")).toBe(input);
    expect(document.activeElement).toBe(input);
    morph(
      root,
      `<p>working</p><div data-key="w"><p>a</p><p>x</p><p>y</p><details data-fold="f">${box}</details></div>`,
    );
    expect(document.activeElement).toBe(input);
    expect(root.innerHTML).toBe(
      `<p>working</p><div data-key="w"><p>a</p><p>x</p><p>y</p><details data-fold="f">${box}</details></div>`,
    );
    root.remove();
  });
  it("tells named children apart when their order changes, and keeps each one's node", () => {
    box.innerHTML = '<li id="x">x</li><li id="y">y</li><li id="z">z</li>';
    const [x, , z] = [...box.children];
    morph(box, '<li id="z">z</li><li id="x">x!</li>');
    expect([...box.children]).toEqual([z, x]);
    expect(x.textContent).toBe("x!");
  });
  it("leaves what the page set on a node itself, outside its markup, through a redraw", () => {
    // A menu placed by its button when opened, and an item marked by whatever drives the page:
    // a redraw that comes as results arrive must not undo either.
    const html = (label: string) =>
      `<div id="m" class="menu" role="menu"><button role="menuitem">${label}</button></div><p title="t">p</p>`;
    morph(box, html("Fan"));
    const menu = box.querySelector<HTMLElement>("#m")!;
    const item = menu.querySelector("button")!;
    menu.style.top = "40px";
    item.dataset.mark = "4";
    morph(box, html("Ceiling fan"));
    expect(box.querySelector("#m")).toBe(menu);
    expect(menu.style.top).toBe("40px");
    expect(item.dataset.mark).toBe("4");
    expect(item.textContent).toBe("Ceiling fan");
  });
  it("still takes off an attribute its markup no longer has", () => {
    morph(box, '<p class="a" title="t">p</p>');
    morph(box, '<p class="b">p</p>');
    expect(box.innerHTML).toBe('<p class="b">p</p>');
  });
});

describe("a menu open through a redraw", () => {
  afterEach(() => vi.restoreAllMocks());
  it("keeps its button saying that it is open", () => {
    const html =
      '<button id="b" popovertarget="m" aria-haspopup="menu" aria-expanded="false">Add</button>' +
      '<div id="m" class="menu" popover="auto" role="menu"><button role="menuitem">Fan</button></div>';
    morph(box, html);
    const button = box.querySelector("#b")!;
    const menu = box.querySelector("#m")!;
    // Opened, as the page does on the menu's toggle (no popovers in this test's document).
    const matches = Element.prototype.matches;
    vi.spyOn(Element.prototype, "matches").mockImplementation(function (this: Element, s: string) {
      return s === ":popover-open" ? this === menu : matches.call(this, s);
    });
    button.setAttribute("aria-expanded", "true");
    morph(box, html);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    vi.restoreAllMocks();
    // Shut, the markup's word holds again.
    morph(box, html);
    expect(button.getAttribute("aria-expanded")).toBe("false");
  });
});

describe("the keys that move along a row of tabs", async () => {
  const { tabAfter } = await import("../src/events/keys");
  it("go round with the arrows, and to the ends with Home and End", () => {
    expect(tabAfter("ArrowRight", 0, 6)).toBe(1);
    expect(tabAfter("ArrowRight", 5, 6)).toBe(0);
    expect(tabAfter("ArrowLeft", 0, 6)).toBe(5);
    expect(tabAfter("Home", 4, 6)).toBe(0);
    expect(tabAfter("End", 1, 6)).toBe(5);
    expect(tabAfter("Enter", 1, 6)).toBeNull();
    expect(tabAfter("a", 1, 6)).toBeNull();
  });
});
