// The scheme as a block diagram: drawn from the scheme's own wiring, left to right as a
// control engineer draws it in Simulink or PSIM, with the way back underneath. Each block is
// its symbol and nothing more; each block is a button the keyboard reaches, and opens the
// inspector where the block is alive. Each wire is a probe: pointed at, it says what it carries
// at the cursor; pressed, it is drawn in the scope under the diagram. It takes the room its own
// shape asks for, and is panned, zoomed and fitted, never smaller than its words can be read
// at, or opened full screen. On a phone the same symbols are set out as a list down the signal
// chain, and the drawing itself is a press away, full screen.

import {
  Background,
  BackgroundVariant,
  ControlButton,
  Controls,
  Handle,
  Position,
  ReactFlow,
  useOnViewportChange,
  useReactFlow,
  ViewportPortal,
} from "@xyflow/react";
import type { Node, NodeProps } from "@xyflow/react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SchemeHead, schemeIsFull, setSchemeFull, useSchemeFull, useSchemeFullMode } from "./fullscheme";
import { Icon } from "./ui";
import { CAPTION_PX, layoutOf } from "./layout";
import type { Layout, LGroup, LNode } from "./layout";
import { BlockBody } from "./node";
import { setWiring } from "./path";
import { calm, stop, usePlaying } from "./play";
import { togglePlotted } from "./actions";
import { plainWords, probesOf, signalWords, unshown } from "./probes";
import { lab, useLab } from "./store";
import { MathName } from "./strip";
import { usualWires } from "./wires";
import type { Port, Presets, Scheme } from "./types";
import { ProbeTip } from "./probetip";
import { LearnCard, learnOn, LearnToggle } from "./learncard";
import { SupplyChain } from "./supplychain";
import { Wiring } from "./wiring";
import { KEY_HINT, roveReset } from "./rover";

type BlockData = { node: LNode; near: Layout["near"]; width: number; first: boolean };
type BandData = { group: LGroup };

/** The least the drawing is fitted at: its blocks' names never under 12.5 px on the screen.
 *  Where the room is narrower, the drawing is read along by panning. */
export const LEAST = 12.5 / CAPTION_PX;
/** The most it is fitted at: a short scheme is not blown up past a calm size. */
export const MOST = 1.15;
/** The most it is fitted at full screen. */
const MOST_FULL = 2;
/** The height of the row the Learn switch stands in, px: kept clear above a drawing read by panning. */
const LEARN_ROW = 44;
const FIT = { padding: 0.01, minZoom: LEAST, maxZoom: MOST };

/** A block on the canvas. Reached by the keyboard, it is brought into view. */
const FlowBlock = memo(function FlowBlock({ data }: NodeProps<Node<BlockData>>) {
  const width = data.width;
  const flow = useReactFlow();
  const show = useCallback(
    (n: LNode) => {
      // The browser scrolls a button it gives the keyboard to into view; the canvas is moved instead.
      document.querySelectorAll(".lab-diagram .react-flow, .lab-diagram .react-flow__renderer").forEach((el) => {
        el.scrollTop = 0;
        el.scrollLeft = 0;
      });
      const { x, y, zoom } = flow.getViewport();
      const pane = document.querySelector(".lab-diagram .react-flow")?.getBoundingClientRect();
      if (!pane) return;
      const left = n.x * zoom + x;
      const top = n.y * zoom + y;
      const inside = left >= 0 && top >= 0 && left + n.w * zoom <= pane.width && top + n.h * zoom <= pane.height;
      // Brought into view along the drawing, its height kept: the drawing is read sideways.
      const along = Math.min(0, Math.max(pane.width - width * zoom, pane.width / 2 - (n.x + n.w / 2) * zoom));
      if (!inside) void flow.setViewport({ x: along, y, zoom }, { duration: calm() ? 0 : 200 });
    },
    [flow, width],
  );
  return (
    <>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <BlockBody
        node={data.node}
        near={data.near}
        onShow={show}
        first={data.first}
        intro={Math.round(((data.node.x + data.node.w / 2) / (width || 1)) * 560)}
      />
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </>
  );
});

/** A loop, as the stretch of the forward path it takes in: a frame round its blocks, named. */
const Band = memo(function Band({ data }: NodeProps<Node<BandData>>) {
  return (
    <div className="lab-band">
      <span>{data.group.label}</span>
    </div>
  );
});

/** The whole of the drawing, wires and all: what fitting the drawing fits. */
const Frame = memo(function Frame() {
  return null;
});

const NODE_TYPES = { block: FlowBlock, band: Band, frame: Frame };
/** Room kept clear under the drawing, where the library's own line is. */
const UNDER = 16;

function flowOf(layout: Layout): Node[] {
  const bands: Node[] = layout.groups.map((g) => ({
    id: `band-${g.loop}`,
    type: "band",
    position: { x: g.x, y: g.y },
    width: g.w,
    height: g.h,
    data: { group: g },
    zIndex: -1,
    selectable: false,
    focusable: false,
    draggable: false,
  }));
  const blocks: Node[] = layout.nodes.map((n) => ({
    id: n.id,
    type: "block",
    position: { x: n.x, y: n.y },
    width: n.w,
    height: n.h,
    data: { node: n, near: layout.near, width: layout.width, first: n.id === layout.nodes[0]?.id },
    focusable: false,
  }));
  const frame: Node = {
    id: "lab-frame",
    type: "frame",
    position: { x: 0, y: 0 },
    width: layout.width,
    height: layout.height + UNDER,
    data: {},
    zIndex: -2,
    selectable: false,
    focusable: false,
    draggable: false,
  };
  return [frame, ...bands, ...blocks];
}

/** What of a scheme its drawing follows: its blocks and their wiring, not their figures. */
const wiringOf = (s: Scheme): string =>
  JSON.stringify([s.actuation.wires, s.blocks.map((b) => [b.name, b.kind, b.inputs, Object.keys(b.params)])]);

export function useLayout(scheme: Scheme, registry: Presets["blocks"], sources: Port[]): Layout {
  const wiring = wiringOf(scheme);
  // The wiring is all of the scheme the drawing follows: a figure changed moves nothing.
  return useMemo(() => layoutOf(scheme, registry, sources), [wiring, registry, sources]);
}

/** The drawing is fitted again whenever the room it has changes: the inspector opening
 *  beside it, the window resized. */
function Refit({ layout }: { layout: Layout }) {
  const flow = useReactFlow();
  // Where the drawing goes on past an edge of its room, that edge fades: more lies that way.
  const edges = () => {
    const host = document.querySelector<HTMLElement>(".lab-canvas");
    if (!host) return;
    const { width } = host.getBoundingClientRect();
    const { x, zoom } = flow.getViewport();
    host.classList.toggle("goes-left", x < -1);
    host.classList.toggle("goes-right", x + layout.width * zoom > width + 1);
  };
  useOnViewportChange({ onEnd: edges });
  useEffect(() => {
    const host = document.querySelector(".lab-canvas");
    if (!host) return;
    let first = true;
    const fit = () => {
      const { width, height } = host.getBoundingClientRect();
      // Hidden (the lab closing, or not yet shown) the canvas has no room: nothing to fit to,
      // and fitting to nought would set the drawing's scale to NaN.
      if (!(width > 0 && height > 0)) return;
      // Read along by panning, the canvas is taller by the Learn switch's row (lab.css, is-panned):
      // the room is judged without it, so the two states do not chase each other.
      const row = host.classList.contains("is-panned") ? LEARN_ROW : 0;
      const whole = Math.min(width / layout.width, (height - row) / (layout.height + UNDER)) * 0.98;
      // Where the room is too narrow for all of it at a size its words can be read at, it is
      // read along by panning, from the reference on; else all of it is in sight.
      // Full screen, a short scheme is shown larger: the window is given to it.
      const zoom = Math.max(LEAST, Math.min(schemeIsFull() ? MOST_FULL : MOST, whole));
      const duration = calm() || first ? 0 : 160;
      host.classList.toggle("is-panned", zoom > whole * 1.02);
      if (zoom > whole * 1.02) {
        // The drawing runs under the canvas's right edge, where the Learn switch stands: it is
        // set under the switch's row, so the switch covers no block.
        const y = Math.max(0, (height - row - (layout.height + UNDER) * zoom) / 2) + row;
        // Read along by panning: from the reference on, or with the block picked in the middle.
        const picked = layout.nodes.find((n) => n.id === lab.get().selected);
        const mid = picked ? width / 2 - (picked.x + picked.w / 2) * zoom : 0;
        const x = Math.min(0, Math.max(width - layout.width * zoom, mid));
        void flow.setViewport({ x, y, zoom }, { duration });
      } else void flow.fitView({ ...FIT, maxZoom: schemeIsFull() ? MOST_FULL : MOST, duration });
      first = false;
      window.setTimeout(edges, duration + 20);
    };
    const seen = new ResizeObserver(fit);
    seen.observe(host);
    return () => seen.disconnect();
  }, [flow, layout]);
  return null;
}

/** A block picked where the inspector lies over the drawing (a narrower window) is brought
 *  out from under it, into the middle of what is left in sight. */
function Uncover({ layout }: { layout: Layout }) {
  const flow = useReactFlow();
  const selected = useLab((s) => s.selected);
  useEffect(() => {
    const picked = layout.nodes.find((n) => n.id === selected);
    const pane = document.querySelector(".lab-canvas")?.getBoundingClientRect();
    const over = document.querySelector(".lab-inspector")?.getBoundingClientRect();
    if (!picked || !pane || !over || over.left >= pane.right || over.left <= pane.left) return;
    const { x, y, zoom } = flow.getViewport();
    const right = pane.left + x + (picked.x + picked.w) * zoom;
    if (right <= over.left - 8) return;
    const mid = (over.left - pane.left) / 2 - (picked.x + picked.w / 2) * zoom;
    void flow.setViewport({ x: Math.min(x, mid), y, zoom }, { duration: calm() ? 0 : 200 });
  }, [flow, layout, selected]);
  return null;
}

/** The drawing's own keys while it has the keyboard: + and − zoom about its middle. The zoom
 *  presses are left out of the tab order, so that the drawing stays one stop; the full-screen
 *  press stays in it. */
function Keys() {
  const flow = useReactFlow();
  useEffect(() => {
    const host = document.querySelector<HTMLElement>(".lab-canvas");
    if (!host) return;
    host
      .querySelectorAll<HTMLElement>(".react-flow__controls-zoomin, .react-flow__controls-zoomout")
      .forEach((b) => (b.tabIndex = -1));
    const keys = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (!(e.target as Element | null)?.closest?.(".lab-node-head, .lab-hit")) return;
      const by = e.key === "+" || e.key === "=" ? 1 : e.key === "-" || e.key === "−" ? -1 : 0;
      if (!by) return;
      e.preventDefault();
      void (by > 0 ? flow.zoomIn({ duration: calm() ? 0 : 120 }) : flow.zoomOut({ duration: calm() ? 0 : 120 }));
    };
    host.addEventListener("keydown", keys);
    return () => host.removeEventListener("keydown", keys);
  }, [flow]);
  return null;
}

/** The diagram as a canvas. */
function Canvas({ layout }: { layout: Layout }) {
  const nodes = useMemo(() => flowOf(layout), [layout]);
  return (
    <ReactFlow
      nodes={nodes}
      edges={NONE}
      nodeTypes={NODE_TYPES}
      fitView
      fitViewOptions={FIT}
      minZoom={0.3}
      maxZoom={2.5}
      nodesDraggable={false}
      nodesConnectable={false}
      nodesFocusable={false}
      edgesFocusable={false}
      elementsSelectable={false}
      zoomOnDoubleClick={false}
      preventScrolling={false}
      // @xyflow/react is MIT licensed: its attribution may be left off the canvas. It is
      // credited in THIRD_PARTY.md with the page's other libraries.
      proOptions={{ hideAttribution: true }}
      aria-label="Block diagram of the control scheme"
    >
      {/* Drawing paper: a dot every 20 units, moving with the drawing as it is panned and zoomed. */}
      <Background variant={BackgroundVariant.Dots} gap={20} size={1.1} />
      <ViewportPortal>
        <Wiring layout={layout} />
      </ViewportPortal>
      <Refit layout={layout} />
      <Uncover layout={layout} />
      <Keys />
      <Controls showInteractive={false} showFitView={false} position="bottom-left" aria-label="Zoom the diagram">
        <FullButton />
      </Controls>
    </ReactFlow>
  );
}

const NONE: never[] = [];

/** In place of fitting the drawing: the drawing full screen, and back. */
function FullButton() {
  const on = useSchemeFull();
  const words = on ? "Leave full screen" : "Open the diagram full screen";
  return (
    <ControlButton
      data-scheme-full=""
      aria-label={words}
      title={on ? "Leave full screen" : "Full screen"}
      aria-pressed={on}
      onClick={() => setSchemeFull(!on)}
    >
      <Icon name={on ? "x" : "maximize"} />
    </ControlButton>
  );
}

/** One signal of a block in the phone's list: a probe, pressed to draw it in the scope or to
 *  take it out, as a wire of the drawing is. */
function Chip({ wire, unit, about }: { wire: string; unit: string; about: string }) {
  const drawn = useLab((s) => probesOf(s).includes(wire));
  const word = signalWords(wire, unit);
  return (
    <li>
      <button
        type="button"
        className="lab-chip"
        aria-pressed={drawn}
        aria-label={`${plainWords(word)}${about ? `, ${about}` : ""}: ${drawn ? "in the scope" : "not in the scope"}`}
        onClick={() => togglePlotted(wire, usualWires(lab.get()))}
      >
        <MathName word={word} />
      </button>
    </li>
  );
}

/** The same blocks down the signal chain, for a screen too narrow for the drawing: each with
 *  its signals as probes, since there are no wires to press. */
function Chain({ layout }: { layout: Layout }) {
  return (
    <details className="lab-chain-fold" open>
      <summary>The scheme, block by block along the signal chain: {layout.nodes.length} blocks</summary>
      <button type="button" className="ghost lab-chain-full" data-scheme-full="" onClick={() => setSchemeFull(true)}>
        <Icon name="maximize" />
        Open the diagram full screen
      </button>
      <ol className="lab-chain">
        {layout.nodes.map((n) => {
          const outs = n.outputs.filter((o) => !unshown(o.wire) && !/limited|clamped/.test(o.name));
          return (
            <li key={n.id}>
              <BlockBody node={n} near={{}} chain />
              {outs.length ? (
                <ul className="lab-chips" aria-label={`Signals of ${n.title}, each a probe`}>
                  {outs.map((o) => (
                    <Chip key={o.wire} wire={o.wire} unit={o.unit} about={o.about} />
                  ))}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ol>
    </details>
  );
}

/** Whether the screen is as narrow as a phone's. */
export function useNarrow(query = "(max-width: 700px)"): boolean {
  const [narrow, setNarrow] = useState(() => matchMedia(query).matches);
  useEffect(() => {
    const media = matchMedia(query);
    const heard = () => setNarrow(media.matches);
    media.addEventListener("change", heard);
    return () => media.removeEventListener("change", heard);
  }, [query]);
  return narrow;
}

/** The drawing on its canvas: one group, one stop of the keyboard, its keys said in its corner. */
function Drawing({ layout, onLearn }: { layout: Layout; onLearn: () => void }) {
  return (
    <div
      className="lab-canvas"
      role="group"
      aria-roledescription="block diagram"
      aria-label="The scheme"
      aria-describedby="lab-diagram-keys"
    >
      <Canvas layout={layout} />
      <p id="lab-diagram-keys" className="lab-diagram-keys">
        {KEY_HINT}
      </p>
      <ProbeTip />
      <LearnCard />
      <LearnToggle onOn={onLearn} />
    </div>
  );
}

/** Learn turned on (or the lab opened with it on): the card is put at once on the block picked,
 *  else the first regulator, so the mode is seen without hunting for it. */
function useFirstCard(
  layout: Layout,
  host: React.RefObject<HTMLDivElement | null>,
  learning: boolean,
  narrow: boolean,
): () => void {
  const firstCard = useCallback(() => {
    const picked = lab.get().selected;
    const n =
      layout.nodes.find((x) => x.id === picked) ??
      layout.nodes.find((x) => /regulator/.test(x.hint)) ??
      layout.nodes.find((x) => x.role === "block");
    const el = n && host.current?.querySelector(`[data-block="${CSS.escape(n.id)}"] .lab-node-head`);
    if (n && el) learnOn(n, el);
  }, [layout, host]);
  useEffect(() => {
    if (!learning || narrow) return;
    const frame = requestAnimationFrame(firstCard);
    return () => cancelAnimationFrame(frame);
  }, [learning, narrow, firstCard]);
  return firstCard;
}

export function Diagram({ scheme, presets }: { scheme: Scheme; presets: Presets }) {
  const layout = useLayout(scheme, presets.blocks, presets.sources);
  const narrow = useNarrow();
  const resting = useLab((s) => !s.run.answer && !s.run.partial);
  const learning = useLab((s) => s.learn);
  const play = usePlaying();
  const host = useRef<HTMLDivElement>(null);
  // The drawing opens with a pulse along its wires, the way the signal goes: once as the lab
  // opens and once for each new wiring, never under reduced motion.
  const [intro, setIntro] = useState(false);
  useEffect(() => {
    if (calm()) return;
    setIntro(true);
    const off = window.setTimeout(() => setIntro(false), 1700);
    return () => window.clearTimeout(off);
  }, [layout]);
  const full = useSchemeFull();
  useSchemeFullMode(host);
  useEffect(() => setWiring(layout.edges), [layout]);
  // A new wiring is entered by the keyboard at its first block.
  useEffect(() => roveReset, [layout]);
  const firstCard = useFirstCard(layout, host, learning, narrow);
  // Leaving the lab stops the run being played, and leaves the scheme full screen.
  useEffect(
    () => () => {
      stop();
      setSchemeFull(false);
    },
    [],
  );
  const shape = {
    "--lab-ratio": ((layout.height + UNDER) / layout.width).toFixed(4),
    "--lab-least": `${Math.ceil((layout.height + UNDER) * LEAST + 2)}px`,
    "--lab-most": `${Math.ceil((layout.height + UNDER) * MOST + 2)}px`,
  } as React.CSSProperties;
  return (
    <div
      ref={host}
      className={[
        "lab-diagram",
        narrow && !full ? "is-chain" : "",
        resting ? "is-resting" : "has-run",
        learning ? "is-learning" : "",
        intro ? "is-intro" : "",
        play.on ? "is-playing" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      style={shape}
    >
      {full ? <SchemeHead /> : null}
      {narrow && !full ? <Chain layout={layout} /> : <Drawing layout={layout} onLearn={firstCard} />}
      <SupplyChain />
    </div>
  );
}
