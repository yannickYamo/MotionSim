// One block of the scheme as the diagram draws it: its symbol and its short name, and nothing
// that moves. It is a button: pressed, it opens the block's inspector, where its figures, its
// mathematics, its values and its animation are. Pointed at, it lights its path and says in
// one line what it puts out at the cursor. The only states it shows are its own: picked,
// its figures changed, at its limit.

import { memo, useEffect, useMemo, useRef } from "react";
import { blockEdited } from "./actions";
import { useFollow } from "./follow";
import type { Layout, LNode } from "./layout";
import { learnOff, learnOn } from "./learncard";
import { light } from "./path";
import { valueAt, written } from "./series";
import { cursor, lab, tracesNow, tracesOf, useLab } from "./store";
import type { LabState } from "./store";
import { nextWire, roveTo, useRoving } from "./rover";
import { Symbol, symbolWords } from "./symbol";

const ARROWS: Record<string, "left" | "right" | "up" | "down"> = {
  ArrowLeft: "left",
  ArrowRight: "right",
  ArrowUp: "up",
  ArrowDown: "down",
};

/** The arrow keys go from a block to the one its wires lead to, each way. */
function moveBy(e: React.KeyboardEvent<HTMLElement>, id: string, near: Layout["near"]): void {
  const way = ARROWS[e.key];
  const to = way ? near[id]?.[way] : undefined;
  if (!way) return;
  e.preventDefault();
  if (!to) return;
  const host = e.currentTarget.closest(".lab-diagram");
  host?.querySelector<HTMLElement>(`[data-block="${CSS.escape(to)}"] .lab-node-head`)?.focus();
}

const ROLE_WORDS: Record<string, string> = {
  reference: "what the test asks for",
  inverter: "the power stage",
  motor: "the motor and its load, simulated",
};

/** How a block says it is at its limit: the wire that says so where it has one, else its
 *  first output against the limit it is given. */
function limitOf(node: LNode, limit: number | null): { flag: string | undefined; first: string; limit: number | null } {
  const flag = (node.outputs.find((o) => o.name === "limited") ?? node.outputs.find((o) => /saturat/.test(o.name)))
    ?.wire;
  return { flag, first: node.outputs[0]?.wire ?? "", limit };
}

const heldAt = (read: (wire: string) => number | null, l: ReturnType<typeof limitOf>): boolean => {
  const told = l.flag ? read(l.flag) : null;
  if (told !== null) return told > 0.5;
  const out = Math.abs(read(l.first) ?? 0);
  return l.limit !== null && l.limit > 0 && out >= l.limit * 0.999;
};

/** Whether a block is at its limit at any instant of a run's traces: only such a block is
 *  ever marked, and only while it holds. */
export function reachesLimit(
  node: LNode,
  series: { t: number[]; wires: Record<string, number[]> } | null,
  limit: number | null,
): boolean {
  if (!series?.t.length) return false;
  const l = limitOf(node, limit);
  if (!l.flag && l.limit === null) return false;
  for (let n = 0; n < series.t.length; n++) {
    if (heldAt((wire) => series.wires[wire]?.[n] ?? null, l)) return true;
  }
  return false;
}

const limitParam = (node: LNode) => (s: LabState) => {
  const v = s.scheme?.blocks.find((b) => b.name === node.id)?.params.limit;
  return typeof v === "number" && v < 1e11 ? v : null;
};

/** Whether this block reaches its limit somewhere in the run in the lab (or the one under way). */
export function useReaches(node: LNode): boolean {
  const limit = useLab(limitParam(node));
  const series = useLab(tracesOf);
  return useMemo(() => reachesLimit(node, series, limit), [node, series, limit]);
}

/** Mark an element while a block's limit holds, at the cursor: by the wire that says so where
 *  it has one, else by its output standing at the limit it is given. A block that never reaches
 *  its limit in the run is never marked. */
export function useHeld(node: LNode, host: React.RefObject<HTMLElement | null>): void {
  const limit = useLab(limitParam(node));
  const reaches = useReaches(node);
  const l = limitOf(node, limit);
  useFollow(
    (read) => host.current?.toggleAttribute("data-held", reaches && heldAt(read, l)),
    [l.flag, l.first, limit, reaches],
  );
}

/** The block the pointer is on: the one whose line of values follows the cursor. */
let pointed: string | null = null;

/** One line over a block pointed at: what it puts out first, at the cursor. */
function Tip({ node }: { node: LNode }) {
  const el = useRef<HTMLSpanElement>(null);
  const out = node.outputs[0];
  const say = (t: number) => {
    const s = tracesNow();
    if (!el.current || !out || !s) return;
    el.current.textContent = `${out.about || out.name}: ${written(valueAt(s.t, s.wires[out.wire], t), out.unit)}`;
  };
  useFollow((_, t) => pointed === node.id && say(t), [out?.wire]);
  useEffect(() => {
    const host = el.current?.parentElement;
    const enter = () => say(cursor.t);
    host?.addEventListener("pointerenter", enter);
    return () => host?.removeEventListener("pointerenter", enter);
  });
  if (!out) return null;
  return <span className="lab-tip" ref={el} aria-hidden="true" />;
}

interface Props {
  node: LNode;
  near: Layout["near"];
  onShow?: (node: LNode) => void;
  /** Set down the phone's chain, with its title beside it. */
  chain?: boolean;
  /** When the pulse that runs along the drawing as it opens reaches this block, in ms. */
  intro?: number;
  /** The first block of the drawing: its one stop of the keyboard until another is reached. */
  first?: boolean;
}

/** What a block's press says of itself: what it is, how it is drawn, and what pressing does. */
function headLabel(node: LNode, selected: boolean, changed: boolean): string {
  const what = node.role === "block" ? node.title : `${node.title}: ${ROLE_WORDS[node.role]}`;
  const drawn = `Drawn as ${symbolWords(node.symbol)}.`;
  const edited = changed ? " Its figures have been changed." : "";
  return `${what}. ${drawn}${edited} ${selected ? "Its inspector is open." : "Opens its inspector."}`;
}

/** The pointer or the keyboard gone from a block: its path no longer lit. */
const unlit = () => {
  light(null);
  learnOff();
};

/** A key on a block of the canvas: W goes round its wires, an arrow to the next block. */
function onBlockKey(e: React.KeyboardEvent<HTMLElement>, id: string, near: Layout["near"]): void {
  if (nextWire(e, id)) return;
  moveBy(e, id, near);
}

/** The pointer or the keyboard left a block: its lit wires go out, and its Learn card soon after. */
function left(): void {
  unlit();
  learnOff();
}

/** A block: its symbol, which is the button that opens its inspector. */
export const BlockBody = memo(function BlockBody({ node, near, onShow, chain, intro, first = false }: Props) {
  // The canvas is one tab stop (the block reached); down the phone's chain every block is one.
  const stop = useRoving(node.id, first);
  const selected = useLab((s) => s.selected === node.id);
  const changed = useLab((s) => blockEdited(s, node.id));
  const ran = useLab((s) => !!s.run.answer || !!s.run.partial);
  const host = useRef<HTMLDivElement>(null);
  useHeld(node, host);
  const reaches = useReaches(node);
  const marks = `${selected ? " is-on" : ""}${node.known ? "" : " is-new"}${changed ? " is-changed" : ""}`;
  return (
    <div
      ref={host}
      className={`lab-node is-${node.role} is-${node.symbol.kind}${marks}${ran ? " has-run" : ""}`}
      data-block={node.id}
      data-symbol={node.symbol.kind}
      style={intro === undefined ? undefined : ({ "--intro": `${intro}ms` } as React.CSSProperties)}
      onPointerEnter={(e) => {
        pointed = node.id;
        light(node.id);
        if (!chain) learnOn(node, e.currentTarget);
      }}
      onPointerLeave={() => {
        pointed = null;
        left();
      }}
      onFocus={(e) => {
        light(node.id);
        if (!chain) learnOn(node, e.currentTarget);
      }}
      onBlur={left}
    >
      <button
        type="button"
        className="lab-node-head"
        aria-pressed={selected}
        aria-label={headLabel(node, selected, changed)}
        onClick={() => lab.set({ selected: selected ? null : node.id })}
        tabIndex={chain || stop ? 0 : -1}
        onKeyDown={(e) => (chain ? moveBy(e, node.id, near) : onBlockKey(e, node.id, near))}
        onFocus={() => {
          if (!chain) roveTo(node.id);
          onShow?.(node);
        }}
      >
        <Symbol node={node} holds={reaches} />
        {chain ? (
          <span className="lab-node-words">
            <span className="lab-node-title">{node.title}</span>
            {changed ? <span className="lab-changed">changed</span> : null}
          </span>
        ) : null}
      </button>
      {changed && !chain ? <span className="lab-changed">changed</span> : null}
      {chain ? null : <Tip node={node} />}
    </div>
  );
});
