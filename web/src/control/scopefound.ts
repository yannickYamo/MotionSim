// What a run found, set on the scope's strips: its marks, the moment they arrive, and the run
// whose traces draw themselves in once.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { notesOf, placedNotes } from "./findings";
import { shaftSeries, shaftWires } from "./scopeview";
import { tracesNow, useLab } from "./store";
import type { Presets, Run, Series, Wire } from "./types";
import { withUnits } from "./units";

export interface StripsProps {
  series: Series;
  wires: Wire[];
  /** The live traces as the scope reads them, for the cursor. */
  read: () => Series | null;
  run: Run | null;
  fresh: Run | null;
}

/** The run as the scope shows it: every wire with its unit (a transform's in the unit of what
 *  goes into it), the traces drawn, and the live ones the cursor reads. The shaft's speed is in
 *  rpm: turned once, here (scopeview.ts). `partial` is what has come of a run under way. */
export function useScopeView(presets: Presets, partial: Series | null) {
  const run = useLab((s) => s.run.answer);
  const scheme = useLab((s) => s.scheme);
  const sources = useMemo<Wire[]>(() => presets.sources.map((w) => ({ ...w, block: "" })), [presets.sources]);
  const known = useMemo(
    () => withUnits(run?.wires ?? sources, run?.scheme ?? scheme, presets.blocks),
    [run, sources, scheme, presets.blocks],
  );
  const read = useCallback(() => {
    const now = tracesNow();
    return now && shaftSeries(now, known);
  }, [known]);
  const raw = partial ?? run?.series ?? null;
  return { wires: shaftWires(known), series: raw && shaftSeries(raw, known), read };
}

/** Whether a run has just come: for the moment its marks take to arrive, once. */
function useLanding(run: Run | null): boolean {
  const [landing, setLanding] = useState(false);
  const was = useRef<Run | null>(null);
  useEffect(() => {
    if (!run || was.current === run) return;
    was.current = run;
    setLanding(true);
    const off = window.setTimeout(() => setLanding(false), 900);
    return () => window.clearTimeout(off);
  }, [run]);
  return landing;
}

/** The run whose traces are drawn in as it arrives: one that came whole, not one that was seen
 *  streaming in (its traces have drawn themselves already). Null for anything after it. */
export function useFresh(run: Run | null, status: string): Run | null {
  const streamed = useRef(false);
  const seen = useRef<Run | null>(run);
  const partial = useLab((s) => !!s.run.partial);
  if (status === "running" && partial) streamed.current = true;
  if (status !== "done" || !run || seen.current === run) return null;
  seen.current = run;
  const whole = !streamed.current;
  streamed.current = false;
  return whole ? run : null;
}

/** What the run found, drawn on the strips it was read from, and whether it has just come. */
export function useFound(run: Run | null, groups: { key: string; traces?: { name: string }[] }[]) {
  const landing = useLanding(run);
  const notes = useMemo(() => placedNotes(notesOf(run), groups), [run, groups]);
  return { landing, notes };
}
