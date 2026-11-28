// Following the cursor: a mark or a figure that writes itself anew at every instant the
// cursor comes to, from the run's traces, without anything being drawn again by React.

import { useEffect, useRef } from "react";
import { valueAt, written } from "./series";
import { cursor, tracesNow, useLab } from "./store";

/** Set attributes on a drawn mark, where it is there. */
export const set = (el: Element | null | undefined, attrs: Record<string, number | string>): void => {
  if (el) for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
};

/** Do something at every instant the cursor comes to, with a reader of the wires there. */
export function useFollow(act: (read: (wire: string) => number | null, t: number) => void, deps: unknown[]): void {
  const traces = useLab((s) => (s.run.status === "running" ? s.run.partial : null) ?? s.run.answer?.series ?? null);
  useEffect(
    () =>
      cursor.follow((t) => {
        const s = tracesNow();
        act((wire) => (s ? valueAt(s.t, s.wires[wire], t) : null), t);
      }),
    [traces, ...deps],
  );
}

/** A wire's value at the cursor, with its unit. */
export function LiveValue({ wire, unit }: { wire: string; unit: string }) {
  const el = useRef<HTMLSpanElement>(null);
  useFollow(
    (read) => {
      if (el.current) el.current.textContent = written(read(wire), unit);
    },
    [wire, unit],
  );
  return (
    <span className="lab-live" ref={el} data-wire={wire}>
      –
    </span>
  );
}
