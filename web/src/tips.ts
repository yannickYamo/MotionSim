// What a control says of itself when pointed at: one mechanism for the page and the lab. The
// first tip waits, so a pointer crossing the page raises nothing; once one is up, the next
// control pointed at says its own at once, and the page cools again a moment after the pointer
// has left them all. A `title` is taken as the words (and kept from the browser's own slow,
// unstyled tip while pointed at), `data-tip` likewise, with `data-keys` for the keys that do
// the same; a `.has-tip` keeps its own drawn tip (views/html.ts) and takes the same timing.

import "./tips.css";

/** How long the first tip waits, a tip marked quick (or reached by the keyboard) waits, and
 *  how long after the pointer has left the next one still comes at once. */
export const WAIT = 600;
export const QUICK = 150;
export const COOL = 300;

const SOURCE = "[title], [data-tip], .has-tip";

let floating: HTMLElement | null = null;
/** The control pointed at (or with the keyboard), whether its tip is up yet or not. */
let at: HTMLElement | null = null;
let shown = false;
let warm = false;
let waiting = 0;
let cooling = 0;

/** The control a tip belongs to, from whatever in it is pointed at. */
function sourceOf(target: EventTarget | null): HTMLElement | null {
  const el = target instanceof Element ? target.closest(SOURCE) : null;
  if (!(el instanceof HTMLElement)) return null;
  return el.classList.contains("has-tip") || el.title || el.dataset.tip ? el : null;
}

/** The words are taken off the `title` while the control is pointed at, so the browser shows
 *  no tip of its own over this one; a control named by its title alone keeps its name. */
function take(el: HTMLElement): void {
  if (!el.title) return;
  el.dataset.tip = el.title;
  el.dataset.tipFrom = "title";
  const named = el.hasAttribute("aria-label") || el.hasAttribute("aria-labelledby") || el.textContent.trim() !== "";
  if (!named) el.setAttribute("aria-label", el.title);
  el.removeAttribute("title");
}

/** And given back once it is left, as it was written. */
function giveBack(el: HTMLElement): void {
  if (el.dataset.tipFrom !== "title") return;
  if (!el.hasAttribute("title") && el.dataset.tip) el.title = el.dataset.tip;
  delete el.dataset.tip;
  delete el.dataset.tipFrom;
}

/** A tip marked `data-tip-clipped` is only for words cut short (its own, or those of the part
 *  of it the mark names): none where everything is read in place. */
function clipped(el: HTMLElement): boolean {
  const part = el.dataset.tipClipped;
  if (part === undefined) return true;
  const cut = part ? el.querySelector<HTMLElement>(part) : el;
  // Cut at its end, or (words kept to a few lines) at its foot.
  return !!cut && (cut.scrollWidth > cut.clientWidth + 1 || cut.scrollHeight > cut.clientHeight + 1);
}

const same = (words: string) => words.replace(/\s+/g, " ").trim().toLowerCase();

/** Whether words of a control are there to be read: drawn, and not kept for a screen reader alone. */
function seen(el: Element | null): boolean {
  if (!el || el.closest(".sr")) return false;
  return typeof el.checkVisibility !== "function" || el.checkVisibility();
}

/** A tip that says only what the control already shows in words (a press named "Ask" whose
 *  tip is "Ask") says nothing: none is raised. One with keys to show, or whose words are not
 *  on screen (an icon alone, a name hidden on a narrow rail), is. */
function repeats(el: HTMLElement): boolean {
  const words = same(el.dataset.tip ?? "");
  if (!words || el.dataset.keys || el.classList.contains("has-tip")) return false;
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let node = walk.nextNode(); node; node = walk.nextNode())
    if (same(node.textContent ?? "") === words && seen(node.parentElement)) return true;
  return false;
}

/** The keys that do the same as the press, each in its cap: "Ctrl+Enter" is two caps. */
export function keyCaps(keys: string): HTMLElement[] {
  return keys
    .split(/[+\s]+/)
    .filter(Boolean)
    .map((k) => {
      const cap = document.createElement("kbd");
      cap.className = "kbd";
      cap.textContent = k;
      return cap;
    });
}

function tipElement(): HTMLElement {
  if (floating) return floating;
  floating = document.createElement("div");
  floating.id = "tt";
  floating.className = "tt";
  floating.setAttribute("role", "tooltip");
  floating.hidden = true;
  return floating;
}

/** Under the control and centred on it; over it where there is no room under; never off the
 *  screen. Read in the frame of what it is laid in: a dialog that is moved is its own frame. */
function place(tip: HTMLElement, el: HTMLElement): void {
  const r = el.getBoundingClientRect();
  const room = { w: document.documentElement.clientWidth, h: document.documentElement.clientHeight };
  const { width, height } = tip.getBoundingClientRect();
  const left = Math.max(8, Math.min(r.left + r.width / 2 - width / 2, room.w - width - 8));
  const under = r.bottom + 6;
  const over = under + height > room.h - 8 && r.top - 6 - height >= 8;
  tip.dataset.side = over ? "top" : "bottom";
  tip.style.left = `${Math.round(left)}px`;
  tip.style.top = `${Math.round(over ? r.top - 6 - height : under)}px`;
}

/** Draw the floating tip of a control: its words, the keys after them. */
function float(el: HTMLElement): void {
  const tip = tipElement();
  const words = document.createElement("span");
  words.textContent = el.dataset.tip ?? "";
  tip.replaceChildren(words, ...keyCaps(el.dataset.keys ?? ""));
  // Over whatever is open on top of the page: a dialog shown as a modal covers the body.
  const host = el.closest("dialog[open]") ?? document.body;
  if (tip.parentElement !== host) host.append(tip);
  // The first comes in; one that follows it is there at once.
  tip.classList.toggle("is-instant", warm);
  tip.hidden = false;
  place(tip, el);
  // Said to a screen reader too while it is up, unless it only repeats the control's name.
  const name = el.getAttribute("aria-label") ?? el.textContent.trim();
  if (!el.hasAttribute("aria-describedby") && name !== el.dataset.tip) {
    el.setAttribute("aria-describedby", tip.id);
    el.dataset.tipSaid = "";
  }
}

function show(el: HTMLElement): void {
  if (!el.isConnected || !clipped(el)) return;
  // Redrawn while it waited, its title is the words as they are now.
  take(el);
  if (repeats(el)) return;
  if (el.classList.contains("has-tip")) el.classList.add("is-tipped");
  else if (el.dataset.tip) float(el);
  else return;
  shown = true;
  warm = true;
}

/** Take the tip down; the control is still the one pointed at, and says nothing again until
 *  it is left and come back to. */
function hide(): void {
  window.clearTimeout(waiting);
  if (!shown) return;
  shown = false;
  at?.classList.remove("is-tipped");
  if (at && "tipSaid" in at.dataset) {
    at.removeAttribute("aria-describedby");
    delete at.dataset.tipSaid;
  }
  if (floating) floating.hidden = true;
}

function leave(): void {
  hide();
  if (at) giveBack(at);
  at = null;
  // Still warm for a moment: the control beside this one says its own at once.
  window.clearTimeout(cooling);
  if (warm) cooling = window.setTimeout(() => (warm = false), COOL);
}

function enter(el: HTMLElement, wait: number): void {
  leave();
  at = el;
  take(el);
  window.clearTimeout(cooling);
  const after = warm ? 0 : el.dataset.tipWait === "quick" ? Math.min(wait, QUICK) : wait;
  if (after === 0) show(el);
  else waiting = window.setTimeout(() => show(el), after);
}

function onPointerOver(e: PointerEvent): void {
  const el = sourceOf(e.target);
  if (el === at) return;
  // A finger points at nothing: its press is the control's own (but see onPointerDown).
  if (!el || e.pointerType === "touch") leave();
  else enter(el, WAIT);
}

function onPointerDown(e: PointerEvent): void {
  const el = sourceOf(e.target);
  // A figure's name that explains itself is read on a phone by touching it.
  if (e.pointerType === "touch" && el?.classList.contains("has-tip") && el !== at) enter(el, 0);
  else if (e.pointerType === "touch") leave();
  else hide();
}

function onFocusIn(e: FocusEvent): void {
  const el = sourceOf(e.target);
  let byKeys = false;
  try {
    byKeys = !!el?.matches(":focus-visible");
  } catch {
    /* a browser without :focus-visible shows its tips to the pointer alone */
  }
  if (el && byKeys && el !== at) enter(el, QUICK);
}

let installed = false;

/** Start the tips, once, for everything in the document. */
export function tooltips(): void {
  if (installed) return;
  installed = true;
  document.addEventListener("pointerover", onPointerOver);
  document.addEventListener("pointerdown", onPointerDown, true);
  document.addEventListener("focusin", onFocusIn);
  document.addEventListener("focusout", (e) => sourceOf(e.target) === at && leave());
  // A key pressed is work begun: the tip is out of its way (Escape among them).
  document.addEventListener("keydown", hide, true);
  document.addEventListener("scroll", hide, { capture: true, passive: true });
  document.documentElement.addEventListener("pointerleave", leave);
  // What was pointed at may be redrawn away under the pointer: its tip goes with it.
  document.addEventListener("pointermove", () => at && !at.isConnected && leave(), { passive: true });
}

/** For the tests: as if the page had only now been opened. */
export function coldTips(): void {
  leave();
  window.clearTimeout(cooling);
  warm = false;
}
