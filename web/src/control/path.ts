// The path of a signal through the scheme: everything a block's inputs come from, back to
// the motor, and everything its outputs lead to, on to the motor. Pointed at or reached by
// the keyboard, a block lights its path and the rest of the drawing steps back; a wire
// pointed at lights itself and the two blocks it joins. The marks are set on the drawing
// itself: nothing is drawn again for a pointer that moved.

import type { LEdge } from "./layout";
import { MOTOR } from "./layout";

let wiring: LEdge[] = [];

export const setWiring = (edges: LEdge[]): void => {
  wiring = edges;
};

/** The blocks reached from one, one way along the wires. The loop closes through the motor,
 *  so the motor ends a path and is not gone through. */
export function reached(edges: LEdge[], from: string, down: boolean): Set<string> {
  const seen = new Set<string>();
  const todo = [from];
  while (todo.length) {
    const at = todo.pop()!;
    if (at === MOTOR && at !== from) continue;
    for (const e of edges) {
      const next = down ? (e.from === at ? e.to : null) : e.to === at ? e.from : null;
      if (next && next !== from && !seen.has(next)) {
        seen.add(next);
        todo.push(next);
      }
    }
  }
  return seen;
}

/** The wires and the blocks on the path of a block, or of one wire alone. */
export function pathOf(
  edges: LEdge[],
  at: { block?: string; edge?: string },
): { blocks: Set<string>; wires: Set<string> } {
  const one = edges.find((e) => e.id === at.edge);
  if (one) return { blocks: new Set([one.from, one.to]), wires: new Set([one.id]) };
  const id = at.block;
  if (!id) return { blocks: new Set(), wires: new Set() };
  const up = reached(edges, id, false);
  const down = reached(edges, id, true);
  const wires = edges.filter(
    (e) => (up.has(e.from) && (e.to === id || up.has(e.to))) || (down.has(e.to) && (e.from === id || down.has(e.from))),
  );
  return { blocks: new Set([id, ...up, ...down]), wires: new Set(wires.map((e) => e.id)) };
}

/** Light the path of a block or of a wire, or with null none. */
export function light(at: { block?: string; edge?: string } | string | null): void {
  const { blocks, wires } = pathOf(wiring, at === null ? {} : typeof at === "string" ? { block: at } : at);
  const mark = (el: Element, on: boolean) => el.toggleAttribute("data-path", on);
  document.querySelectorAll<HTMLElement>(".lab-diagram").forEach((host) => {
    host.toggleAttribute("data-lit", at !== null);
    host.querySelectorAll<HTMLElement>("[data-block]").forEach((el) => mark(el, blocks.has(el.dataset.block!)));
    host.querySelectorAll("[data-edge]").forEach((el) => mark(el, wires.has(el.getAttribute("data-edge")!)));
    // A stretch of a trunk is lit when any wire that runs in it is.
    host.querySelectorAll("[data-edges]").forEach((el) => {
      const on = el.getAttribute("data-edges")!.split(" ");
      mark(
        el,
        on.some((id) => wires.has(id)),
      );
    });
  });
}
