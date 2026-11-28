// The scope, under the diagram, as Simulink's Scope and PSIM's SIMVIEW set a run out: one strip
// for each quantity probed, stacked on one time axis, a cursor line across them all with each
// trace's value read out beside it, and the run played from here. Play sweeps the cursor
// through the run: every strip draws itself up to the instant reached, what is still to come set
// back, while the wires and blocks of the diagram show their values at the same instant. Drag
// across a strip to look at a stretch; double-press to see the whole run again.
//
// Nothing here is drawn again by React for a cursor that moved: each strip follows the cursor
// and writes its own marks, once a frame at most.

import { scrubKey } from "./scrubkeys";
import { useEffect, useMemo, useRef, useState } from "react";
import { togglePlotted } from "./actions";
import { calm, PACES, playing, pressed, setPace, stop, usePlaying } from "./play";
import { STRIP_LEFT, timeUnit } from "./plots";
import {
  inked,
  optionWords,
  probesOf,
  signalWords,
  sourceTitle,
  stripsOf,
  tracedOf,
  typedWords,
  unshown,
} from "./probes";
import { emptyArt } from "../emptyart";
import type { Empty } from "../emptyart";
import { sentence } from "../format";
import { Ripple } from "./results";
import { Said } from "./runpanel";
import { written as figureWritten } from "./figures";
import { ghostOf, shaftRun } from "./scopeview";
import { useScopeView } from "./scopefound";
import type { StripsProps } from "./scopefound";
import { Strip, useWidth } from "./strip";
import { cursor, lab, tracesNow, useLab } from "./store";
import type { Presets, Run, Series, Wire } from "./types";
import { Icon, Segments } from "./ui";
import { Exports, VerdictCard } from "./verdict";
import { useFound, useFresh } from "./scopefound";
import { usualWires } from "./wires";

/** An instant of a run that lasts `whole`, in the unit and to the figures that length reads in. */
export function instantIn(t: number, whole: number): string {
  const { unit, k } = timeUnit(whole);
  return `${(t * k).toFixed(2)} ${unit}`;
}

/** The instant the cursor is on, and how long the run is. */
function Instant({ to }: { to: number }) {
  const el = useRef<HTMLOutputElement>(null);
  // The instant in the unit the run's length is written in: "0.00 ms of 85.70 ms".
  useEffect(
    () =>
      cursor.follow((t) => {
        if (el.current) el.current.textContent = instantIn(t, to);
      }),
    [to],
  );
  return (
    <span className="lab-instant">
      <output ref={el} className="lab-live" aria-label="The instant the cursor is on" />
      <span className="quiet"> of {instantIn(to, to)}</span>
    </span>
  );
}

/** Play and pause, and the pace: the cursor swept through the run so that every strip draws
 *  itself and every face of the diagram moves. */
export function Player({ id }: { id: string }) {
  const play = usePlaying();
  return (
    <div className="lab-player" role="group" aria-label="Play the run">
      <button
        type="button"
        className="lab-play"
        id={id}
        aria-pressed={play.on}
        onClick={pressed}
        title={play.on ? "Pause" : "Play the run: every strip draws itself and the diagram moves with it"}
      >
        <Icon name={play.on ? "player-pause" : "player-play"} />
        {play.on ? "Pause" : "Play"}
      </button>
      {/* Said in words: the lengths are how long one sweep takes, not a window of the run. */}
      <span className="lab-pace-label" aria-hidden="true">
        Play over
      </span>
      <Segments
        label="How long one sweep of the run takes, played"
        value={play.pace}
        options={PACES}
        onPick={setPace}
      />
    </div>
  );
}

/** An instant of the run as it is said: 23.35 ms. */
export const instantWords = (t: number): string => figureWritten(t, "s");

/** The cursor as a slider: for the keyboard, and to scrub through the run by hand. */
function Scrubber({ from, to, whole }: { from: number; to: number; whole: [number, number] }) {
  const slider = useRef<HTMLInputElement>(null);
  useEffect(
    () =>
      cursor.follow((t) => {
        const el = slider.current;
        if (!el) return;
        if (document.activeElement !== el) el.value = String(t);
        // A reader says the instant as a time, not the slider's raw figure.
        el.setAttribute("aria-valuetext", instantWords(t));
      }),
    [from, to],
  );
  return (
    <input
      id="lab-cursor"
      className="scope-scrub"
      ref={slider}
      type="range"
      min={from}
      max={to}
      step={(to - from) / 1000 || 1e-6}
      defaultValue={cursor.t}
      aria-valuetext={instantWords(cursor.t)}
      aria-label="The cursor's instant: every strip and every wire of the diagram is read there"
      aria-keyshortcuts="Shift+ArrowLeft Shift+ArrowRight + - 0"
      onKeyDown={(e) => {
        const did = scrubKey({ key: e.key, shift: e.shiftKey }, cursor.t, lab.get().view, whole);
        if (!did) return;
        e.preventDefault();
        if ("t" in did) {
          stop();
          cursor.set(did.t);
          e.currentTarget.value = String(did.t);
        } else lab.set({ view: did.view });
      }}
      onChange={(e) => {
        stop();
        cursor.set(Number(e.target.value));
      }}
    />
  );
}

/** Any wire of the run, picked from a list, for one that the diagram does not draw or that the
 *  keyboard would rather name: grouped by the block it comes from, each by what it is and its
 *  symbol. The clock and the nought of an open input are not signals, and are not listed. */
function AddSignal({ wires, probes }: { wires: Wire[]; probes: string[] }) {
  const scheme = useLab((s) => s.scheme);
  const presets = useLab((s) => s.presets);
  const byBlock = useMemo(() => {
    const out = new Map<string, { name: string; words: string }[]>();
    const taken = new Map<string, number>();
    for (const w of wires) {
      if (unshown(w.name) || probes.includes(w.name)) continue;
      const block = sentence(sourceTitle(w.name, { scheme, presets }));
      const symbol = typedWords(signalWords(w.name, w.unit));
      // Each entry says the block it is of, and none says what another says: two blocks may
      // each have an "at limit", and two wires a T*.
      let words = optionWords(block, w.about ?? "", symbol, w.name);
      const seen = (taken.get(words) ?? 0) + 1;
      taken.set(words, seen);
      if (seen > 1) words = `${words} (${seen})`;
      out.set(block, [...(out.get(block) ?? []), { name: w.name, words }]);
    }
    return [...out.entries()];
  }, [wires, probes, scheme, presets]);
  if (!byBlock.length) return null;
  return (
    <div className="control scope-add">
      <select
        value=""
        aria-label="Add a signal to the scope"
        onChange={(e) => e.target.value && togglePlotted(e.target.value, usualWires(lab.get()))}
      >
        <option value="">Add a signal</option>
        {byBlock.map(([block, list]) => (
          <optgroup key={block} label={block}>
            {list.map((w) => (
              <option key={w.name} value={w.name}>
                {w.words}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}

/** The instant under the pointer, read on a strip's plot: the one pressed while a drag is under
 *  way (the pointer is held by the strips then, so what is under it is not a plot), else the
 *  one under the pointer. */
function instant(e: React.PointerEvent | React.MouseEvent, on?: Element | null): { t: number; x: number } | null {
  const plot = on ?? (e.target as Element).closest?.(".scope-plot");
  const svg = plot?.querySelector("svg");
  const box = svg?.getBoundingClientRect();
  const s = tracesNow();
  if (!svg || !box || !s?.t.length) return null;
  const w = Number(svg.getAttribute("width")) || box.width;
  const [from, to] = shownOf(lab.get().view, s);
  const x = ((e.clientX - box.left) / (box.width || 1)) * w;
  const share = Math.min(1, Math.max(0, (x - STRIP_LEFT) / (w - STRIP_LEFT - 8 || 1)));
  return { t: from + share * (to - from), x: e.clientX };
}

/** Where the scope's strips are pressed and dragged: the cursor follows the pointer, a drag
 *  across shows that stretch alone, a double-press the whole run again. */
function usePointer(host: React.RefObject<HTMLDivElement | null>, band: React.RefObject<HTMLDivElement | null>) {
  const press = useRef<{ x: number; t: number; plot: Element } | null>(null);
  const showBand = (a: number, b: number) => {
    const el = band.current;
    const at = host.current?.getBoundingClientRect();
    if (!el || !at) return;
    el.style.transform = `translateX(${Math.min(a, b) - at.left}px)`;
    el.style.width = `${Math.abs(a - b)}px`;
    el.hidden = false;
  };
  const hideBand = () => {
    if (band.current) band.current.hidden = true;
  };
  return {
    onPointerMove: (e: React.PointerEvent) => {
      const at = instant(e, press.current?.plot);
      if (!at) return;
      if (press.current) {
        if (Math.abs(at.x - press.current.x) > 2) showBand(press.current.x, at.x);
        return cursor.set(at.t);
      }
      // While the run plays the cursor is the player's: a press takes it back.
      if (!playing()) cursor.set(at.t);
    },
    onPointerDown: (e: React.PointerEvent) => {
      if (e.button !== 0 || (e.target as Element).closest?.("button, a, input, select")) return;
      const plot = (e.target as Element).closest?.(".scope-plot");
      const at = plot ? instant(e, plot) : null;
      if (!at || !plot) return;
      stop();
      press.current = { ...at, plot };
      cursor.set(at.t);
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    },
    onPointerUp: (e: React.PointerEvent) => {
      const from = press.current;
      press.current = null;
      hideBand();
      const at = from ? instant(e, from.plot) : null;
      // A drag across more than a few pixels asks for that stretch alone.
      if (from && at && Math.abs(at.x - from.x) > 6 && at.t !== from.t)
        lab.set({ view: [Math.min(at.t, from.t), Math.max(at.t, from.t)] });
    },
    onPointerCancel: () => {
      press.current = null;
      hideBand();
    },
    onDoubleClick: () => lab.set({ view: null }),
  };
}

/** The probes, as one value the store holds still between changes. */
const useProbes = (): string[] => {
  const joined = useLab((s) => probesOf(s).join("|"));
  return useMemo(() => (joined ? joined.split("|") : []), [joined]);
};

/** The stretch of the run the scope shows: the one dragged across, or all of it. While a run
 *  streams in, all of it is the run as it will be, so the traces draw left to right on a time
 *  axis that holds still. */
const shownOf = (view: [number, number] | null, series: Series, progress = 1): [number, number] => {
  if (view) return view;
  const from = series.t[0] ?? 0;
  const last = series.t[series.t.length - 1] ?? 1;
  return [from, progress > 0.02 && progress < 1 ? from + (last - from) / progress : last];
};

/** Each wire's unit and what it is, by its name. */
const saidOf = (wires: Wire[]) => ({
  units: new Map(wires.map((w) => [w.name, w.unit])),
  about: new Map(wires.map((w) => [w.name, w.about])),
});

function Strips({ series, wires, read, run, fresh }: StripsProps) {
  const probes = useProbes();
  const scenario = useLab((s) => s.scenario);
  const view = useLab((s) => s.view);
  const held = useLab((s) => s.held);
  const progress = useLab((s) => (s.run.status === "running" ? s.run.progress : 1));
  const running = useLab((s) => s.run.status === "running");
  const play = usePlaying();
  const host = useRef<HTMLDivElement>(null);
  const band = useRef<HTMLDivElement>(null);
  const width = useWidth(host);
  const pointer = usePointer(host, band);
  const groups = useMemo(() => stripsOf(probes, wires, series, scenario), [probes, wires, series, scenario]);
  const inks = useMemo(() => inked(groups), [groups]);
  const { units, about } = useMemo(() => saidOf(wires), [wires]);
  const ghost = ghostOf(held?.run ?? null, run);
  const [from, to] = shownOf(view, series, progress);
  const traced = useMemo(() => tracedOf(groups, inks, ghost, series), [groups, inks, ghost, series]);
  const { landing, notes } = useFound(running || !run ? null : shaftRun(run), groups);
  if (!groups.length)
    return (
      <div className="lab-rest is-none">
        <Art kind="signals" />
        <p className="scope-none quiet">
          Nothing is probed. Press a wire of the diagram, or add a signal, to draw it here.
        </p>
      </div>
    );
  return (
    <div
      className={`scope-strips${play.on ? " is-playing" : ""}`}
      ref={host}
      data-landing={landing ? "" : undefined}
      {...pointer}
    >
      {groups.map((g, n) => (
        <Strip
          key={g.key}
          group={g}
          traces={traced[n]}
          units={units}
          about={about}
          from={from}
          to={to}
          width={width}
          series={series}
          read={read}
          first={n === 0}
          last={n === groups.length - 1}
          step={running ? null : (run?.step ?? null)}
          on={play.on}
          notes={notes.get(g.key)}
          fresh={fresh}
        />
      ))}
      <div className="scope-band" ref={band} hidden aria-hidden="true" />
    </div>
  );
}

/** The bar over the strips: the run played from here, the instant, the scrubber, and what is
 *  shown of it. */
function Transport({ series, run }: { series: Series; run: Run | null }) {
  const view = useLab((s) => s.view);
  const progress = useLab((s) => (s.run.status === "running" ? s.run.progress : 1));
  const [detail, setDetail] = useState(false);
  const [from, to] = shownOf(view, series);
  const end = shownOf(null, series, progress)[1];
  const ripple = !!run?.waveform?.t?.length;
  return (
    <>
      <div className="scope-bar">
        <Player id="lab-play" />
        <Instant to={end} />
        <Scrubber from={from} to={to} whole={shownOf(null, series)} />
        <div className="scope-tools">
          {view ? (
            <button type="button" className="ghost scope-tool" onClick={() => lab.set({ view: null })}>
              <Icon name="zoom-out" />
              Whole run
            </button>
          ) : null}
          {ripple ? (
            <button
              type="button"
              className="ghost scope-tool"
              aria-expanded={detail}
              aria-controls="lab-ripple"
              onClick={() => setDetail(!detail)}
            >
              <Icon name="wave-sine" />
              Ripple, every point
            </button>
          ) : null}
        </div>
      </div>
      {run && ripple && detail ? <RippleHere run={run} /> : null}
    </>
  );
}

/** The stretch kept point by point, opened from the scope. */
function RippleHere({ run }: { run: Run }) {
  const fsw = useLab((s) => Number(s.presets?.design.f_sw) || 0);
  return (
    <div id="lab-ripple" className="scope-detail">
      <Ripple run={run} fsw={fsw} name={run.scheme.label} />
    </div>
  );
}

/** On a phone, where the scope stands far under the press that runs the test, a run started
 *  brings the scope into view, and again once it ends: what the press did is in sight. */
function useShownOnPhone(status: string): void {
  const was = useRef(status);
  useEffect(() => {
    const from = was.current;
    was.current = status;
    if (from === status || !(status === "running" || from === "running")) return;
    if (typeof matchMedia !== "function" || !matchMedia("(max-width: 700px)").matches) return;
    const head = document.getElementById("lab-scope-h");
    const top = head?.getBoundingClientRect().top ?? 0;
    if (!head || (top >= 0 && top < innerHeight * 0.4)) return;
    head.scrollIntoView?.({ block: "start", behavior: calm() ? "auto" : "smooth" });
  }, [status]);
}

export function Scope({ presets }: { presets: Presets }) {
  const status = useLab((s) => s.run.status);
  useShownOnPhone(status);
  const partial = useLab((s) => s.run.partial);
  const run = useLab((s) => s.run.answer);
  const probes = useProbes();
  const { wires, series, read } = useScopeView(presets, status === "running" ? partial : null);
  const fresh = useFresh(run, status);
  const head = (
    <div className="scope-head">
      <h3 id="lab-scope-h" tabIndex={-1}>
        Scope
      </h3>
      <Said />
    </div>
  );
  const running = status === "running";
  if (!series?.t.length) return <Resting head={head} running={running} wires={wires} />;
  return (
    <section className={`scope${running ? " is-running" : ""}`} aria-labelledby="lab-scope-h" aria-busy={running}>
      {head}
      {/* The verdict's room is kept from the first trace on, so that nothing under it moves when it comes. */}
      {run?.verdict ? <VerdictCard presets={presets} /> : <div className="lab-verdict-slot" aria-hidden="true" />}
      <Transport series={series} run={running ? null : run} />
      <Strips series={series} wires={wires} read={read} run={run} fresh={fresh} />
      {run && !running ? <AddSignal wires={wires} probes={probes} /> : null}
      {run && !running ? <Exports /> : null}
    </section>
  );
}

/** The strips as they will be, before the first of the run has come: each strip's frame and
 *  name in place, so the press is answered at once and nothing moves when the traces arrive. */
function Skeleton({ wires }: { wires: Wire[] }) {
  const probes = useProbes();
  const scenario = useLab((s) => s.scenario);
  const keys = useMemo(() => {
    const empty: Series = { t: [], wires: Object.fromEntries(probes.map((p) => [p, []])) };
    return stripsOf(probes, wires, empty, scenario).map((g) => [g.key, g.title] as const);
  }, [probes, wires, scenario]);
  return (
    <div className="scope-strips is-skeleton" aria-hidden="true">
      {keys.map(([key, title]) => (
        <section className="scope-strip" key={key}>
          <div className="scope-legend">
            <div className="scope-strip-head">
              <h4>{title}</h4>
            </div>
          </div>
          <div className="scope-plot">
            <span className="scope-shimmer" />
          </div>
        </section>
      ))}
    </div>
  );
}

/** The drawing of an empty place, made once when it is first shown: drawn in that once. */
function Art({ kind }: { kind: Empty }) {
  const [html] = useState(() => emptyArt(kind));
  return <span className="lab-art" aria-hidden="true" dangerouslySetInnerHTML={{ __html: html }} />;
}

/** The scope before anything has run: what it will show, and a way to run. */
function Resting({ head, running, wires }: { head: React.ReactNode; running: boolean; wires: Wire[] }) {
  return (
    <section
      className={`scope is-empty${running ? " is-running" : ""}`}
      aria-labelledby="lab-scope-h"
      aria-busy={running}
    >
      {head}
      {running ? (
        <>
          <div className="lab-verdict-slot" aria-hidden="true" />
          <div className="scope-bar-slot" aria-hidden="true" />
          <Skeleton wires={wires} />
        </>
      ) : (
        <div className="lab-rest">
          <Art kind="run" />
          <p>
            <span>Nothing has run yet: Run the test, at the top of the lab, draws it here.</span>{" "}
            <span className="quiet">Press a wire of the diagram to probe it.</span>
          </p>
        </div>
      )}
    </section>
  );
}
