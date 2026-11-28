// The note that follows the pointer over a wire of the diagram, as a probe's: what each of its
// lines is, what it carries at the cursor, and what a press does. One for the drawing, written
// straight into, never drawn again by React; it follows the cursor while it is shown.

import { useEffect, useRef } from "react";
import type { LEdge } from "./layout";
import type { Word } from "./drawn";
import { signalWords } from "./probes";
import { valueAt, written } from "./series";
import { cursor, lab, tracesNow } from "./store";

/** What a wire's lines are called, and what each is, as the run says. */
function namesOf(edge: LEdge, units: Map<string, string>): { wire: string; word: string; about: string }[] {
  const known = lab.get().run.answer?.wires ?? lab.get().presets?.sources ?? [];
  return edge.wires.map((w) => ({
    wire: w,
    word: mathOf(signalWords(w, units.get(w) ?? "")),
    about: known.find((k) => k.name === w)?.about ?? "",
  }));
}

/** A name as the scope's legend writes it, as markup: the letter, its star, its small letters. */
const mathOf = (w: Word): string =>
  `<span class="scope-name${[...w.text].length > 2 ? " is-word" : ""}">${escapeText(w.text)}` +
  `${w.star ? "<sup>*</sup>" : ""}${w.sub ? `<sub>${escapeText(w.sub)}</sub>` : ""}</span>`;

/** The note that follows the pointer over a wire: what it carries at the cursor, and what a
 *  press does. One for the drawing, written straight into, never drawn again by React. */
const tip: { el: HTMLDivElement | null; edge: LEdge | null; units: Map<string, string>; off: (() => void) | null } = {
  el: null,
  edge: null,
  units: new Map(),
  off: null,
};

function writeTip(t: number): void {
  const { el, edge } = tip;
  if (!el || !edge) return;
  const s = tracesNow();
  el.querySelectorAll<HTMLElement>("[data-tip-value]").forEach((v) => {
    const wire = v.dataset.tipValue!;
    v.textContent = s ? written(valueAt(s.t, s.wires[wire], t), tip.units.get(wire) ?? "") : "";
  });
}

export function placeTip(x: number, y: number): void {
  const el = tip.el;
  const box = el?.parentElement?.getBoundingClientRect();
  if (!el || !box) return;
  const w = el.offsetWidth;
  const h = el.offsetHeight;
  let left = x - box.left + 14;
  let top = y - box.top + 16;
  if (left + w > box.width - 4) left = Math.max(4, x - box.left - w - 14);
  if (top + h > box.height - 4) top = Math.max(4, y - box.top - h - 12);
  el.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
}

const escapeText = (v: string): string =>
  v.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function showTip(edge: LEdge, units: Map<string, string>, pinned: boolean, x: number, y: number): void {
  const el = tip.el;
  if (!el) return;
  tip.edge = edge;
  tip.units = units;
  const ran = !!tracesNow();
  const rows = namesOf(edge, units)
    .slice(0, 4)
    .map(
      (n) =>
        `<span class="lab-tip-row">${n.word}` +
        `<span class="lab-tip-about">${escapeText(n.about || n.wire)}</span>` +
        (ran ? `<span class="lab-live" data-tip-value="${escapeText(n.wire)}"></span>` : "") +
        `</span>`,
    )
    .join("");
  const more = edge.wires.length > 4 ? `<span class="lab-tip-about">and ${edge.wires.length - 4} more</span>` : "";
  const hint = pinned ? "In the scope. Press to take it out." : "Press to draw it in the scope.";
  el.innerHTML = `${rows}${more}<span class="lab-tip-hint">${hint}</span>`;
  el.hidden = false;
  placeTip(x, y);
  writeTip(cursor.t);
  tip.off?.();
  tip.off = cursor.follow(writeTip);
}

export function hideTip(): void {
  tip.off?.();
  tip.off = null;
  tip.edge = null;
  if (tip.el) tip.el.hidden = true;
}

/** The note itself, set in the canvas over the drawing. */
export function ProbeTip() {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    tip.el = el.current;
    return () => {
      hideTip();
      tip.el = null;
    };
  }, []);
  return <div className="lab-probe-tip" ref={el} hidden aria-hidden="true" />;
}
