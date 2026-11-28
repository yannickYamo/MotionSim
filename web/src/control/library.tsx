// The library of explorations: questions worth asking of this drive, each a sweep the engine
// runs. One that does not apply to this design says why. A sweep's answer is set out as one
// small chart for each figure it reads, with what the engine says of it in words.

import { ranked } from "./libraryorder";
import { useEffect, useMemo, useState } from "react";
import { sentence } from "../format";
import { Chart } from "./chart";
import { figuresOf } from "./cost";
import { lookOf, pitchOf } from "./explorewords";
import { cancelSweep, openLibrary, opens, openVariant, runSweep } from "./libactions";
import { curvePlot } from "./plots";
import { useLab } from "./store";
import type { Exploration, ReadWords, Run, Sweep, Variant } from "./types";
import { Fault, Icon, Waiting, worded } from "./ui";

const GROUPS = ["losses", "dynamics", "sensing", "robustness", "thermal"];

/** A figure a sweep reads, out of a variant: by the name the engine gives it, wherever in
 *  the variant's answer it lies. */
export function readOf(v: Partial<Variant> | null, name: string): number | null {
  if (!v) return null;
  const path = name.split(".");
  const within = [v, v.channels, v.losses, v.step, (v as { stability?: unknown }).stability];
  for (const from of within) {
    let at: unknown = from;
    for (const key of path) at = at && typeof at === "object" ? (at as Record<string, unknown>)[key] : undefined;
    if (typeof at === "number" && Number.isFinite(at)) return at;
  }
  return null;
}

/** What a read figure is called and measured in: in the engine's words where it gives them,
 *  else in the lab's own for the figures it knows. */
function labelOf(name: string, words: ReadWords): { label: string; unit: string; hot: boolean } {
  const key = name.split(".").pop()!;
  const known = figuresOf({ channels: {}, losses: {} } as unknown as Run).find((f) => f.key === key);
  const given = words[name];
  return {
    label: sentence(given?.label ?? known?.label ?? worded(key)),
    unit: given?.unit ?? known?.unit ?? "",
    hot: known?.hot ?? false,
  };
}

/** What a sweep found, with its mark: a tick only where the engine tags it good, a warning
 *  where it tags a shortfall, and a plain note where it gives no tag. */
export interface Found {
  said: string;
  tag: "good" | "short" | "note";
}

const SHORT = new Set(["short", "shortfall", "warn", "warning", "bad", "fail", "improve", "caution"]);
const GOOD = new Set(["good", "pass", "ok"]);

export function foundOf(first: unknown, sweep: unknown): Found | null {
  const tagged = (raw: unknown): Found["tag"] => {
    const t = typeof raw === "string" ? raw.toLowerCase() : "";
    return GOOD.has(t) ? "good" : SHORT.has(t) ? "short" : "note";
  };
  if (first && typeof first === "object") {
    const f = first as { said?: unknown; text?: unknown; tag?: unknown };
    const said = typeof f.said === "string" ? f.said : typeof f.text === "string" ? f.text : "";
    return said ? { said, tag: tagged(f.tag) } : null;
  }
  if (typeof first !== "string" || !first) return null;
  // The engine may send the tag beside the words: a list of findings, or one tag for the sweep.
  const s = (sweep ?? {}) as { findings?: { tag?: unknown }[]; tag?: unknown; tags?: unknown[] };
  return { said: first, tag: tagged(s.findings?.[0]?.tag ?? s.tags?.[0] ?? s.tag) };
}

/** What a read figure is multiplied by to be in the unit it is labelled with: the engine's own
 *  scale where it sends one; a share as a percentage; a frequency the engine reads in Hz shown
 *  in the kHz its label names (no drive switches at a thousand kHz, so a figure that large is
 *  in Hz). */
export function scaleOfRead(
  name: string,
  unit: string,
  given: { scale?: unknown; unit?: string } | undefined,
  values: (number | null)[],
): number {
  if (typeof given?.scale === "number" && Number.isFinite(given.scale) && given.scale > 0) return given.scale;
  if (unit === "" && /thd|overshoot/.test(name)) return 100;
  const most = Math.max(0, ...values.map((v) => Math.abs(v ?? 0)));
  if (unit === "kHz" && most >= 1000) return 1e-3;
  if (unit === "MHz" && most >= 1e5) return 1e-6;
  return 1;
}

/** The variant the others are set against. */
const baselineOf = (sweep: Sweep): Partial<Variant> | null =>
  typeof sweep.baseline === "number" ? (sweep.variants[sweep.baseline] ?? null) : sweep.baseline;

/** Where an exploration comes from: the works it rests on, linked where they are on the web. */
function Sources({ x }: { x: Exploration }) {
  if (!x.sources?.length) return null;
  return (
    <ul className="quiet lab-sources" aria-label="Where it comes from">
      {x.sources.map((s) => {
        const words = `${s.title}${s.year ? ` (${s.year})` : ""}`;
        // Only a link of the web is followed; anything else is shown as its words.
        const link = typeof s.link === "string" && /^https?:\/\//.test(s.link) ? s.link : null;
        return (
          <li key={words}>
            {link ? (
              <a href={link} target="_blank" rel="noopener noreferrer">
                {words}
              </a>
            ) : (
              words
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** A label set inside a list: its first letter small, unless it starts an acronym. */
const lower = (s: string): string => (/^[A-Z]{2}/.test(s) ? s : s.charAt(0).toLowerCase() + s.slice(1));

const runsOf = (x: Exploration): number => x.vary.values?.length ?? x.vary.schemes?.length ?? 0;

/** What a card opens on: the engine's own account of the exploration, what it varies and
 *  reads, and where it comes from. */
function CardMore({ x, id, open }: { x: Exploration; id: string; open: boolean }) {
  const words = useLab((s) => s.library.words);
  return (
    <div className="lab-card-more" id={id} hidden={!open}>
      <p className="lab-card-method">{x.title}</p>
      <p className="lab-question">{x.question}</p>
      {!x.applies && x.why_not ? <p className="lab-why-not">{sentence(x.why_not)}.</p> : null}
      {x.about ? <p className="quiet">{x.about}</p> : null}
      {x.expects ? (
        <p className="lab-expects">
          <b>Expected.</b> {sentence(x.expects)}.
        </p>
      ) : null}
      <dl className="lab-card-facts">
        <div>
          <dt>Varied</dt>
          <dd>
            {x.vary.label}
            {x.vary.unit ? `, ${x.vary.unit}` : ""}: {runsOf(x)} runs
          </dd>
        </div>
        {x.reads.length ? (
          <div>
            <dt>Reads</dt>
            <dd>{x.reads.map((r) => lower(labelOf(r, words).label)).join(", ")}</dd>
          </div>
        ) : null}
      </dl>
      <Sources x={x} />
    </div>
  );
}

/** One exploration: an icon and a tag for its group, the problem it answers, and what running
 *  it gives back (the engine's own finding once it has run). Pressed, it opens in place on
 *  the method, the parameters and the works it rests on. */
function Card({ x, busy, found }: { x: Exploration; busy: boolean; found: Found | null }) {
  const [open, setOpen] = useState(false);
  const look = lookOf(x.group);
  const pitch = pitchOf(x);
  const detail = `lab-card-more-${x.id}`;
  return (
    <li className={`lab-card is-${x.group}${x.applies ? "" : " is-off"}${open ? " is-open" : ""}`} data-group={x.group}>
      <div className="lab-card-head">
        <span className="lab-card-icon">
          <Icon name={look.icon} />
        </span>
        <span className="lab-tag">{look.label}</span>
        <span className="lab-card-caret">
          <Icon name="chevron-down" />
        </span>
      </div>
      <h4 className="lab-card-title">
        <button
          type="button"
          className="lab-card-open"
          aria-expanded={open}
          aria-controls={detail}
          onClick={() => setOpen(!open)}
        >
          {pitch.pain}
        </button>
      </h4>
      <p className={`lab-outcome${found ? ` is-found is-${found.tag}` : ""}`}>
        {found ? (
          <>
            <Icon
              name={found.tag === "good" ? "circle-check" : found.tag === "short" ? "alert-triangle" : "info-circle"}
            />
            <span>
              {found.tag === "short" ? <span className="sr-only">Short of it: </span> : null}
              {sentence(found.said)}.
            </span>
          </>
        ) : (
          pitch.outcome
        )}
      </p>
      <div className="lab-card-act">
        {x.applies ? (
          <button type="button" className="ghost lab-card-run" disabled={busy} onClick={() => void runSweep(x)}>
            <Icon name="player-play" />
            Run it: {runsOf(x)} runs
          </button>
        ) : (
          <p className="lab-not">
            <Icon name="ban" />
            <span>Does not apply to this design.</span>
          </p>
        )}
      </div>
      <CardMore x={x} id={detail} open={open} />
    </li>
  );
}

function Charts({ x, sweep }: { x: Exploration; sweep: Sweep }) {
  const words = useLab((s) => s.library.words);
  // What is varied is set along the axis by its value where every value is a number, and in
  // the order listed where it is a choice.
  const byOrder = !sweep.variants.every((v) => typeof v.value === "number");
  const xs = sweep.variants.map((v, n) => (byOrder ? n + 1 : (v.value as number)));
  const drawn = useMemo(
    () =>
      x.reads.map((name) => {
        const { label, unit, hot } = labelOf(name, words);
        const raw = sweep.variants.map((v) => readOf(v, name));
        const scale = scaleOfRead(name, unit, words[name], raw);
        const unitShown = scale === 100 ? "%" : unit;
        const ys = raw.map((y) => (y === null ? null : y * scale));
        const base = readOf(baselineOf(sweep), name);
        const svg = curvePlot({
          title: label,
          xLabel: byOrder
            ? "variant, in the order listed"
            : `${sweep.vary.label}${sweep.vary.unit ? `, ${sweep.vary.unit}` : ""}`,
          // The title stands over the chart: its axis says the unit alone.
          yLabel: unitShown || label,
          xs,
          counted: byOrder,
          names: byOrder ? sweep.variants.map((v) => v.label) : undefined,
          missed: sweep.variants.map((v) => missedAsked(v)),
          ys,
          level: base === null ? null : base * scale,
          hot,
        });
        return { name, label, svg };
      }),
    [x.reads, sweep, byOrder, xs, words],
  );
  return (
    <div className="lab-multiples">
      {drawn.map((d) => (
        <figure key={d.name} className="lab-plot is-small">
          <figcaption className="lab-plot-title">{d.label}</figcaption>
          <Chart svg={d.svg} title={`${x.title}: ${d.label}`} small />
        </figure>
      ))}
    </div>
  );
}

/** A variant that did not do what was asked: another torque than the one asked, a step not over. */
const missedAsked = (v: Variant): boolean => (v.checks ?? []).some((c) => c.topic === "tracking" && c.level !== "ok");

const refusedWords = (v: Variant): string =>
  typeof v.refused === "string" ? v.refused : (v.refused?.refused ?? "the engine refused this variant");

function Variants({ x, sweep }: { x: Exploration; sweep: Sweep }) {
  return (
    <ol className="lab-variants">
      {sweep.variants.map((v, n) => (
        <li key={`${v.label}-${n}`}>
          <span>
            <b>{v.label}</b>
            {v.refused ? <span className="lab-not-run">: not run. {sentence(refusedWords(v))}.</span> : null}
          </span>
          {v.refused || !opens(x, v) ? null : (
            <button type="button" className="link" onClick={() => openVariant(x, v)}>
              Open this variant in the lab
            </button>
          )}
        </li>
      ))}
    </ol>
  );
}

/** How far a sweep under way has come, and the press that stops it. */
function SweepProgress({ total }: { total: number }) {
  const done = useLab((s) => s.library.done);
  return (
    <div className="lab-run-actions">
      <button type="button" className="ghost" onClick={cancelSweep}>
        <Icon name="x" />
        Cancel
      </button>
      <div className="lab-progress" role="status">
        <progress max={total || 1} value={done} aria-label="How far the exploration has come" />
        <span className="lab-live">
          {done} of {total} runs
        </span>
      </div>
    </div>
  );
}

function SweepView({ x }: { x: Exploration }) {
  const sweep = useLab((s) => s.library.sweep);
  const running = useLab((s) => s.library.running);
  const problem = useLab((s) => s.library.problem);
  const some = !!sweep?.variants.length;
  return (
    <section className="lab-sweep" aria-label={`Exploration: ${x.title}`} aria-busy={running}>
      <h3>{x.question}</h3>
      {running ? <SweepProgress total={x.vary.values?.length ?? x.vary.schemes?.length ?? 0} /> : null}
      {problem ? <Fault>The exploration did not finish: {problem}</Fault> : null}
      {sweep && some ? <Charts x={x} sweep={sweep} /> : null}
      {sweep?.said.length ? (
        <ul className="plain lab-said-list">
          {sweep.said.map((s) => (
            <li key={s}>{sentence(s)}</li>
          ))}
        </ul>
      ) : null}
      {sweep && some ? <Variants x={x} sweep={sweep} /> : null}
      <p className="quiet">Varied: {x.vary.label}. Every other figure is as the exploration sets it.</p>
    </section>
  );
}

export function Library() {
  const library = useLab((s) => s.library);
  const findings = useLab((s) => s.run.answer?.verdict?.findings);
  useEffect(() => void openLibrary(), [library.status]);
  if (library.status === "missing") {
    return (
      <p className="quiet">
        The library of explorations is not in this build of the engine. Update MotionSim on this machine to get it.
      </p>
    );
  }
  if (library.status === "fault") return <Fault>The library did not come: {library.problem}.</Fault>;
  if (library.status !== "done") return <Waiting>Fetching the explorations for this design.</Waiting>;
  if (!library.list.length) return <p className="quiet">The engine proposes no exploration for this design.</p>;
  // Those of what this run has to change first; those that do not apply folded away at the end.
  const ordered = ranked(library.list, findings ?? [], GROUPS);
  const off = ordered.filter((x) => !x.applies);
  const open = library.list.find((x) => x.id === library.open);
  const found = (x: Exploration): Found | null =>
    x.id === library.open && !library.running ? foundOf(library.sweep?.said[0], library.sweep) : null;
  return (
    <section className="lab-library" aria-label="The library of explorations">
      {open ? <SweepView x={open} /> : null}
      <ul className="lab-cards">
        {ordered
          .filter((x) => x.applies)
          .map((x) => (
            <Card key={x.id} x={x} busy={library.running} found={found(x)} />
          ))}
      </ul>
      {off.length ? (
        <details className="lab-more lab-cards-off">
          <summary>
            Not for this design ({off.length})
            <Icon name="chevron-down" />
          </summary>
          <ul className="lab-cards">
            {off.map((x) => (
              <Card key={x.id} x={x} busy={library.running} found={found(x)} />
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
