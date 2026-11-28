// Playing the run: the cursor swept from the start of what the scope shows to its end, so that
// every strip of the scope draws itself and every face of the diagram moves as the drive did.
// It ends held at the end, the whole run drawn; played again from there, it starts over. It is
// started and stopped by a press, never by itself; moving the cursor by hand stops it.

import { useSyncExternalStore } from "react";
import { cursor, lab, tracesNow } from "./store";

/** How long one sweep of the run takes at the usual pace, in seconds. */
const SWEEP = 8;
/** The paces, by how long one sweep of what the scope shows takes: a run of milliseconds is
 *  never played in real time, so a pace is named for what it is. */
export const PACES: [string, string][] = [
  ["0.25", "32 s"],
  ["0.5", "16 s"],
  ["1", "8 s"],
  ["2", "4 s"],
];

interface Playing {
  on: boolean;
  pace: string;
}

let state: Playing = { on: false, pace: "1" };
const heard = new Set<() => void>();
let frame = 0;
let last = 0;

const tell = (change: Partial<Playing>): void => {
  state = { ...state, ...change };
  heard.forEach((l) => l());
};

/** The stretch the cursor is swept over: what the scope shows, or all of the run. */
function stretch(): [number, number] | null {
  const s = tracesNow();
  if (!s?.t.length) return null;
  const view = lab.get().view;
  return view ?? [s.t[0], s.t[s.t.length - 1]];
}

function tick(now: number): void {
  const span = stretch();
  if (!state.on || !span) return stop();
  const [from, to] = span;
  const step = ((to - from) / SWEEP) * Number(state.pace) * Math.min(0.1, (now - last) / 1000);
  last = now;
  const next = Math.max(from, cursor.t + step);
  if (next >= to) {
    cursor.set(to);
    return stop();
  }
  cursor.set(next);
  frame = requestAnimationFrame(tick);
}

export function stop(): void {
  cancelAnimationFrame(frame);
  frame = 0;
  if (state.on) tell({ on: false });
}

export function start(): void {
  const span = stretch();
  if (state.on || !span) return;
  // Played from the end, or from outside what is shown, it starts over.
  if (cursor.t >= span[1] - (span[1] - span[0]) * 1e-3 || cursor.t < span[0]) cursor.set(span[0]);
  tell({ on: true });
  last = performance.now();
  frame = requestAnimationFrame(tick);
}

export const toggle = (): void => (state.on ? stop() : start());
export const playing = (): boolean => state.on;
export const setPace = (pace: string): void => tell({ pace });

/** Whether motion is asked to be kept down: nothing then draws itself in. */
export const calm = (): boolean =>
  typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The lab opened anew: nothing is playing. */
export function unpressed(): void {
  stop();
}

/** The user's own press: play or pause. */
export function pressed(): void {
  toggle();
}

export function usePlaying(): Playing {
  return useSyncExternalStore(
    (l) => {
      heard.add(l);
      return () => heard.delete(l);
    },
    () => state,
    () => state,
  );
}
