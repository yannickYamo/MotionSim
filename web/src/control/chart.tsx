// A drawing made by the page's own chart helpers, set in the lab: the same frame, rules,
// tick labels and inks as every other chart, with the same button that saves it as an image.
// A chart of a run through time also carries the cursor: pointing at it moves the instant
// every wire of the diagram is read at.

import { useEffect, useRef } from "react";
import type { Box } from "../charts/frame";
import { stillGraph } from "./fullgraphs";
import { openGraph } from "./fullview";
import type { Graph } from "./fullview";
import { Icon } from "./ui";
import { playing, stop } from "./play";
import { cursor } from "./store";

/** A plot through time: where its plot area is, and the stretch of time across it. */
export interface TimeAxis {
  box: Box;
  width: number;
  from: number;
  to: number;
}

interface Props {
  svg: string;
  title: string;
  under?: string;
  small?: boolean;
  time?: TimeAxis;
  /** Called with a stretch of time dragged across the plot. */
  onStretch?: (from: number, to: number) => void;
  /** What it is full screen: by default the drawing itself, as it stands, under its title. */
  full?: (back: () => HTMLElement | null) => Graph | null;
}

const NS = "http://www.w3.org/2000/svg";

/** The cursor of one chart: a line up the plot that follows the instant. Left out of a saved image. */
function useCursorLine(host: React.RefObject<HTMLDivElement | null>, svg: string, time?: TimeAxis): void {
  useEffect(() => {
    const drawn = host.current?.querySelector("svg");
    if (!drawn || !time) return;
    const line = document.createElementNS(NS, "path");
    line.setAttribute("class", "ev-cross lab-cursor");
    drawn.append(line);
    const unfollow = cursor.follow((t) => {
      const share = (t - time.from) / (time.to - time.from || 1);
      const inside = share >= 0 && share <= 1;
      line.setAttribute("visibility", inside ? "visible" : "hidden");
      if (inside) line.setAttribute("d", `M${time.box.x + share * time.box.w} ${time.box.y}v${time.box.h}`);
    });
    return () => {
      unfollow();
      line.remove();
    };
  }, [host, svg, time]);
}

/** The instant under the pointer, by where it is across the plot. */
function instantAt(e: { clientX: number }, host: HTMLElement, time: TimeAxis): number {
  const rect = host.querySelector("svg")!.getBoundingClientRect();
  const x = ((e.clientX - rect.left) / (rect.width || 1)) * time.width;
  const share = Math.min(1, Math.max(0, (x - time.box.x) / time.box.w));
  return time.from + share * (time.to - time.from);
}

async function save(button: HTMLButtonElement, title: string, under: string): Promise<void> {
  const svg = button.closest("[data-png-host]")?.querySelector<SVGSVGElement>("svg.chart");
  const said = button.closest(".control-lab")?.querySelector(".lab-said");
  if (!svg || button.getAttribute("aria-busy")) return;
  button.setAttribute("aria-busy", "true");
  try {
    const { savePng } = await import("../charts/png");
    const drawn = () => button.closest("[data-png-host]")?.querySelector<SVGSVGElement>("svg.chart");
    const name = await savePng(drawn, title, under);
    if (said) said.textContent = `Saved as ${name}.`;
  } catch (e) {
    if (said) said.textContent = `The image could not be made: ${(e as Error).message}.`;
  } finally {
    button.removeAttribute("aria-busy");
  }
}

/** A press that did not move: one that opens the chart full screen. */
const PRESS_PX = 4;

/** The presses on a chart: moving sets the cursor, a drag asks for a stretch of the run, and a
 *  press that did not move opens the chart full screen, as a switching event's plot does. */
function usePresses(
  host: React.RefObject<HTMLDivElement | null>,
  open: () => void,
  time?: TimeAxis,
  onStretch?: Props["onStretch"],
) {
  const pressed = useRef<number | null>(null);
  const pressAt = useRef<{ x: number; y: number } | null>(null);
  const at = (e: React.PointerEvent) => (time && host.current ? instantAt(e, host.current, time) : null);
  const move = (e: React.PointerEvent) => {
    // While the run is played the cursor is the player's: a press takes it back.
    if (playing() && pressed.current === null) return;
    const t = at(e);
    if (t !== null) cursor.set(t);
  };
  const down = (e: React.PointerEvent) => {
    pressAt.current = { x: e.clientX, y: e.clientY };
    if (!time) return;
    stop();
    pressed.current = at(e);
    if (pressed.current !== null) cursor.set(pressed.current);
  };
  const up = (e: React.PointerEvent) => {
    const was = pressAt.current;
    const from = pressed.current;
    pressAt.current = null;
    pressed.current = null;
    if (was && e.button === 0 && Math.hypot(e.clientX - was.x, e.clientY - was.y) < PRESS_PX) {
      open();
      return;
    }
    const t = at(e);
    if (t === null || from === null || !time || !onStretch) return;
    // A drag across more than a fiftieth of the plot asks for that stretch alone.
    if (Math.abs(t - from) > (time.to - time.from) / 50) onStretch(Math.min(t, from), Math.max(t, from));
  };
  return { move, down, up };
}

export function Chart({ svg, title, under = "", small, time, onStretch, full }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const open = () => {
    const back = () => opener.current;
    const g = full?.(back) ?? stillGraph(title, [svg], back);
    if (g) openGraph(g);
  };
  useCursorLine(host, svg, time);
  const { move, down, up } = usePresses(host, open, time, onStretch);
  return (
    <div className={`chart-box can-open${small ? " small" : ""}${time ? " lab-timed" : ""}`} data-png-host>
      <div
        ref={host}
        data-chart-host
        onPointerMove={time ? move : undefined}
        onPointerDown={down}
        onPointerUp={up}
        dangerouslySetInnerHTML={{ __html: svg }}
      />
      <button
        ref={opener}
        type="button"
        className="chart-full"
        aria-label={`Open full screen: ${title}`}
        title="Full screen"
        onClick={open}
      >
        <Icon name="maximize" />
      </button>
      <button
        type="button"
        className="chart-save"
        aria-label={`Save as a PNG image: ${title}`}
        title="Save as PNG"
        onClick={(e) => void save(e.currentTarget, title, under)}
      >
        <Icon name="photo-down" />
      </button>
    </div>
  );
}
