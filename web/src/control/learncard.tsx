// Learning on the diagram. With Learn on, a block pointed at (or reached by the keyboard) says
// in one line what it does and which of its settings matter, in a card beside it, and "+ Learn"
// opens its inspector on the theory: the equations, what changing each setting does, and the
// loop it closes answering the gain as it is dragged. The card is drawn over the canvas at the
// screen's own size, never scaled with the drawing, and it is one for the whole diagram.

import { useEffect, useRef, useSyncExternalStore } from "react";
import { remember } from "./actions";
import { wordsOf } from "./inspector";
import { keysOf, keyWord } from "./keys";
import type { LNode } from "./layout";
import { lab, useLab } from "./store";
import { Icon } from "./ui";
import { Tex } from "./math";

/** The block the card is on, and where its drawing is on the screen. */
const shown: { node: LNode | null; rect: DOMRect | null; listeners: Set<() => void> } = {
  node: null,
  rect: null,
  listeners: new Set(),
};
let leaving = 0;
/** How long the card outlasts its block, ms: the time to move the pointer onto it. */
const LINGER = 220;

const tell = () => shown.listeners.forEach((l) => l());

/** Show the card on a block, where Learn is on. */
export function learnOn(node: LNode, el: Element): void {
  window.clearTimeout(leaving);
  if (!lab.get().learn) return;
  shown.node = node;
  shown.rect = el.getBoundingClientRect();
  tell();
}

/** Take the card away: at once (Learn turned off), or a moment after the pointer or the keyboard
 *  has left its block, long enough to cross over to the card and read or press it there. */
export function learnOff(now = false): void {
  window.clearTimeout(leaving);
  const go = () => {
    shown.node = null;
    tell();
  };
  if (now) go();
  else leaving = window.setTimeout(go, LINGER);
}

/** The block the card stands on, or none. */
export const learnShown = (): LNode | null => shown.node;

function useShown(): LNode | null {
  return useSyncExternalStore(
    (l) => {
      shown.listeners.add(l);
      return () => shown.listeners.delete(l);
    },
    () => shown.node,
  );
}

export function setLearn(on: boolean): void {
  lab.set({ learn: on });
  remember({ learn: on });
}

/** The switch that turns learning on, on the diagram's own corner. */
export function LearnToggle({ onOn }: { onOn?: () => void }) {
  const on = useLab((s) => s.learn);
  return (
    <button
      type="button"
      className={`lab-learn-toggle${on ? " is-on" : ""}`}
      aria-pressed={on}
      title={on ? "Learning: point at a block to read what it does" : "Point at a block to read what it does"}
      onClick={() => {
        setLearn(!on);
        if (on) learnOff(true);
        else requestAnimationFrame(() => onOn?.());
      }}
    >
      <Icon name="school" />
      <span>Learn</span>
      <span className="lab-learn-switch" aria-hidden="true" />
    </button>
  );
}

/** The card set beside its block: above it where there is room, else under it; put in place
 *  at once the first time, then gliding from block to block. */
function usePlaced(el: React.RefObject<HTMLDivElement | null>, node: LNode | null): void {
  useEffect(() => {
    const card = el.current;
    const host = card?.parentElement?.getBoundingClientRect();
    const r = shown.rect;
    if (!card || !host || !r) return;
    const w = card.offsetWidth;
    const h = card.offsetHeight;
    let left = r.left - host.left + r.width / 2 - w / 2;
    left = Math.max(8, Math.min(host.width - w - 8, left));
    // Above the block where there is room for it, else under it.
    let top = r.top - host.top - h - 10;
    if (top < 8) top = r.bottom - host.top + 10;
    // Put in place without gliding the first time it is drawn; after that it glides.
    const fresh = !card.style.transform;
    if (fresh) card.style.transition = "none";
    card.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
    if (fresh) {
      void card.offsetWidth;
      card.style.transition = "";
    }
  }, [node]);
}

/** The card: the block's title, what it does in one line, its key settings, and the way in. */
export function LearnCard() {
  const node = useShown();
  const presets = useLab((s) => s.presets);
  const learn = useLab((s) => s.learn);
  const el = useRef<HTMLDivElement>(null);
  usePlaced(el, node);
  if (!node || !learn || !presets) return null;
  const kind = presets.blocks[node.kind];
  const { about } = wordsOf(node, kind);
  const keys = node.block ? keysOf(kind, node.gains).slice(0, 3) : [];
  const open = () => {
    lab.set({ selected: node.id });
    learnOff(true);
    requestAnimationFrame(() => {
      const fold = document.querySelector<HTMLDetailsElement>(".lab-inspector details.lab-learn");
      if (fold) fold.open = true;
      const side = fold?.closest(".lab-inspector");
      if (fold && side) side.scrollTop += fold.getBoundingClientRect().top - side.getBoundingClientRect().top - 12;
    });
  };
  return (
    <div
      ref={el}
      className="lab-learn-card"
      role="note"
      aria-label={`${node.title}: what it does`}
      onPointerEnter={() => window.clearTimeout(leaving)}
      onPointerLeave={() => learnOff()}
      onFocus={() => window.clearTimeout(leaving)}
      onBlur={() => learnOff()}
    >
      <p className="lab-learn-title">{node.title}</p>
      {about ? <p className="lab-learn-about">{about}</p> : null}
      {kind?.math[0] ? (
        <div className="lab-learn-math">
          <Tex tex={kind.math[0]} />
        </div>
      ) : null}
      {keys.length ? (
        <p className="lab-learn-keys">
          <span className="quiet">Set by</span> {keys.map(([p]) => keyWord(p.name, node.kind)).join(" · ")}
        </p>
      ) : null}
      {node.role === "block" ? (
        <button type="button" className="link lab-learn-more" onClick={open}>
          <Icon name="plus" />
          Learn: its equations and settings
        </button>
      ) : null}
    </div>
  );
}
