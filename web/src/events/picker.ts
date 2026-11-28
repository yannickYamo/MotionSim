// The list of made-up parts on step 1 (and in the dialog that adds a part): a select-only
// combobox as WAI-ARIA's pattern has it. The keyboard stays on the box; the arrows, Home, End
// and the first letters move along the list, Enter, Space or Tab take the part shown, Escape
// shuts the list and keeps the part chosen before. With no part on the page yet, the part chosen
// is brought at once (the way on must never wait on a second press); once parts are on the page
// the list only selects, and the button beside it adds exactly the part shown, once.

import { picked } from "../store";

/** Told of each part chosen in the list: set by the presses, which know how to bring one. */
export const taking: { chose: (id: string) => void } = { chose: () => {} };

const box = () => document.querySelector<HTMLButtonElement>("#example-pick");
const list = () => document.querySelector<HTMLElement>("#example-pick-list");
const options = () => [...(list()?.querySelectorAll<HTMLElement>("[role=option]") ?? [])];
const isOpen = () => box()?.getAttribute("aria-expanded") === "true";

/** The option the keyboard is on: marked for the eye, named to the screen reader, in view. */
function activate(option: HTMLElement | undefined): void {
  const b = box();
  if (!b || !option) return;
  for (const o of options()) o.classList.toggle("is-active", o === option);
  b.setAttribute("aria-activedescendant", option.id);
  option.scrollIntoView({ block: "nearest" });
}

/** The most the list is ever tall, the least it is cut to, and the air kept round it. */
const TALLEST = 360;
const LEAST = 120;
const AIR = 12;

/** Where the open list goes: under its box where it fits there, over it where only that side
 *  has the room, and no taller than the room it is given, so it never runs off what shows it.
 *  `box` and `frame` are the box's and the frame's top and bottom on the screen. */
export function listPlace(
  box: { top: number; bottom: number },
  frame: { top: number; bottom: number },
  wanted: number,
): { up: boolean; height: number } {
  const below = frame.bottom - box.bottom - AIR;
  const above = box.top - frame.top - AIR;
  const tall = Math.min(wanted, TALLEST);
  const up = below < tall && above > below;
  return { up, height: Math.round(Math.max(LEAST, Math.min(tall, up ? above : below))) };
}

/** What shows the list: the screen, cut to the panel or the dialog the box scrolls in. */
function frameOf(b: HTMLElement): { top: number; bottom: number } {
  const screen = { top: 0, bottom: window.innerHeight };
  const within = b.closest("dialog, #panel")?.getBoundingClientRect();
  if (!within || within.height <= 0) return screen;
  return { top: Math.max(screen.top, within.top), bottom: Math.min(screen.bottom, within.bottom) };
}

/** Set the open list on the side with room, at a height that fits it. */
function fitList(b: HTMLElement, l: HTMLElement): void {
  l.style.maxHeight = "";
  l.classList.remove("is-up");
  const { up, height } = listPlace(b.getBoundingClientRect(), frameOf(b), l.scrollHeight || TALLEST);
  l.classList.toggle("is-up", up);
  l.style.maxHeight = `${height}px`;
}

/** The page was drawn again: a list left open keeps its side and its height. */
export function refitPick(): void {
  const b = box();
  const l = list();
  if (b && l && isOpen() && !l.hidden) fitList(b, l);
}

function openList(): void {
  const b = box();
  const l = list();
  if (!b || !l) return;
  picked.open = true;
  l.hidden = false;
  b.setAttribute("aria-expanded", "true");
  fitList(b, l);
  activate(options().find((o) => o.getAttribute("aria-selected") === "true") ?? options()[0]);
  document.addEventListener("pointerdown", away, true);
}

function shutList(): void {
  const b = box();
  const l = list();
  picked.open = false;
  document.removeEventListener("pointerdown", away, true);
  if (!b || !l) return;
  l.hidden = true;
  b.setAttribute("aria-expanded", "false");
  b.removeAttribute("aria-activedescendant");
  for (const o of options()) o.classList.remove("is-active");
}

/** A press anywhere but the box and its list shuts the list. */
function away(e: Event): void {
  if (!(e.target as Element | null)?.closest?.(".pick")) shutList();
}

/** Take a part: ticked in the list, and shown in the box with its application. */
function choose(option: HTMLElement): void {
  const b = box();
  if (!b) return;
  const id = option.dataset.exampleChoose ?? "";
  // Kept through a redraw: the box shows the part chosen until it is brought.
  picked.id = id;
  b.dataset.value = id;
  for (const o of options()) {
    const on = o === option;
    o.setAttribute("aria-selected", String(on));
    o.classList.toggle("is-on", on);
  }
  const name = option.querySelector(".pick-name")?.outerHTML ?? "";
  const use = option.querySelector(".pick-use")?.outerHTML ?? "";
  const face = b.querySelector(".pick-face");
  if (face) face.innerHTML = name + use;
}

/** The box pressed: the list opens, or shuts. */
export function togglePick(): void {
  if (isOpen()) shutList();
  else openList();
  box()?.focus();
}

/** An option pressed: the part is shown in the box, the list shuts, the keyboard is back on it. */
export function choosePick(el: HTMLElement): void {
  choose(el);
  shutList();
  box()?.focus();
  taking.chose(pickedId());
}

/** The part shown in the box, as its id. */
export const pickedId = (): string => box()?.dataset.value ?? "";

let typed = "";
let typedAt = 0;

/** The first option after the active one whose name starts with what was typed in the last
 *  half second, as a native list finds it. */
function byLetters(key: string, from: number): HTMLElement | undefined {
  const now = Date.now();
  typed = now - typedAt > 500 ? key : typed + key;
  typedAt = now;
  const all = options();
  const words = typed.toLowerCase();
  const order = [...all.slice(from + 1), ...all.slice(0, from + 1)];
  return order.find((o) => (o.querySelector(".pick-name")?.textContent ?? "").toLowerCase().startsWith(words));
}

const OPENING = ["ArrowDown", "ArrowUp", "Enter", " ", "Home", "End"];

const printable = (e: KeyboardEvent) => e.key.length === 1 && e.key !== " " && !e.ctrlKey && !e.metaKey && !e.altKey;

/** A key on the box while the list is shut: the arrows, Enter, Space, Home, End and a letter
 *  open it, on the part shown or the one the key names. */
function keyShut(e: KeyboardEvent, all: HTMLElement[], now: number): boolean {
  if (!OPENING.includes(e.key) && !printable(e)) return false;
  e.preventDefault();
  openList();
  if (e.key === "Home") activate(all[0]);
  if (e.key === "End") activate(all[all.length - 1]);
  if (printable(e)) activate(byLetters(e.key, now));
  return true;
}

/** Where a key moves the keyboard in the open list, or null for a key that does not move it. */
function moved(e: KeyboardEvent, now: number, count: number): number | null {
  if (e.altKey) return null;
  const to: Record<string, number> = {
    ArrowDown: now + 1,
    ArrowUp: now - 1,
    Home: 0,
    End: count - 1,
    PageDown: now + 10,
    PageUp: now - 10,
  };
  return e.key in to ? Math.min(Math.max(to[e.key], 0), count - 1) : null;
}

/** A key that takes the part the keyboard is on and shuts the list: Enter, Space, Alt+Up, and
 *  Tab, which goes on as well. */
function keyTake(e: KeyboardEvent, option: HTMLElement | undefined): boolean {
  const take = e.key === "Enter" || e.key === " " || e.key === "Tab" || (e.key === "ArrowUp" && e.altKey);
  if (!take) return false;
  if (e.key !== "Tab") e.preventDefault();
  if (option) choose(option);
  shutList();
  if (option) taking.chose(pickedId());
  return true;
}

/** The keyboard on the box. True when the key was the list's. */
export function pickKey(e: KeyboardEvent): boolean {
  const b = box();
  if (!b || e.target !== b) return false;
  const all = options();
  const now = all.findIndex((o) => o.classList.contains("is-active"));
  if (!isOpen()) return keyShut(e, all, now);
  const to = moved(e, now, all.length);
  if (to !== null) {
    e.preventDefault();
    activate(all[to]);
    return true;
  }
  if (keyTake(e, all[now])) return true;
  if (e.key === "Escape") {
    e.preventDefault();
    e.stopPropagation();
    shutList();
    return true;
  }
  if (!printable(e)) return false;
  e.preventDefault();
  activate(byLetters(e.key, now));
  return true;
}
