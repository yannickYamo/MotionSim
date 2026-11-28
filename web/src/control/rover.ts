// The diagram as one stop of the keyboard (a roving tab stop): Tab enters the drawing at the
// block last reached (the first block before any), the arrow keys go from block to block along
// the wires, W and Shift+W go round the wires of the block reached, Escape goes back from a wire
// to its block, and + and − zoom. Tab leaves the drawing in one press, whatever its size: the
// 16 blocks and 27 wires are no longer 43 stops between the run and the scope.

import { useSyncExternalStore } from "react";

let at: string | null = null;
/** The block whose wires W goes round, while a wire has the keyboard. */
let from: string | null = null;
const heard = new Set<() => void>();

const listen = (f: () => void) => {
  heard.add(f);
  return () => heard.delete(f);
};

/** Make a block the drawing's stop: it is where Tab comes back into the drawing. */
export function roveTo(id: string): void {
  from = id;
  if (at === id) return;
  at = id;
  heard.forEach((f) => f());
}

/** Forget the block reached: a new drawing starts at its first block. */
export function roveReset(): void {
  at = null;
  from = null;
  heard.forEach((f) => f());
}

/** Whether a block is the drawing's one stop: the block reached, else the first. */
export function useRoving(id: string, first: boolean): boolean {
  const now = useSyncExternalStore(listen, () => at);
  return now === null ? first : now === id;
}

const quote = (id: string) => (typeof CSS !== "undefined" && CSS.escape ? CSS.escape(id) : id);

/** The wires of a block, as the keyboard reaches them, in the order they are drawn. */
function wiresOf(host: Element, id: string): HTMLElement[] {
  const q = quote(id);
  return [...host.querySelectorAll<HTMLElement>(`[data-wire-from="${q}"] .lab-hit, [data-wire-to="${q}"] .lab-hit`)];
}

/** W from a block or one of its wires: the next of its wires (Shift: the one before). */
export function nextWire(e: React.KeyboardEvent<Element>, block?: string): boolean {
  if (e.key !== "w" && e.key !== "W") return false;
  if (e.ctrlKey || e.metaKey || e.altKey) return false;
  const host = e.currentTarget.closest(".lab-diagram");
  const owner = block ?? from;
  if (!host || !owner) return false;
  e.preventDefault();
  const wires = wiresOf(host, owner);
  if (!wires.length) return true;
  const now = wires.indexOf(e.currentTarget as HTMLElement);
  const step = e.shiftKey ? -1 : 1;
  const to = now < 0 ? (e.shiftKey ? wires.length - 1 : 0) : (now + step + wires.length) % wires.length;
  from = owner;
  wires[to].focus();
  return true;
}

/** Escape, or an arrow, from a wire: back to the block whose wires were gone round. */
export function backToBlock(e: React.KeyboardEvent<Element>): boolean {
  if (!["Escape", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key) || !from) return false;
  const host = e.currentTarget.closest(".lab-diagram");
  const head = host?.querySelector<HTMLElement>(`[data-block="${quote(from)}"] .lab-node-head`);
  if (!head) return false;
  e.preventDefault();
  e.stopPropagation();
  head.focus();
  return true;
}

/** The keys said in the drawing's corner while it has the keyboard. */
export const KEY_HINT = "Arrows: blocks · W: wires · +/−: zoom";
