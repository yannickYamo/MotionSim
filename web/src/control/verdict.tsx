// The so-what of a run, under the scope's head: one or two sentences on what is good and what
// to optimize and how, then the findings they come from, each with its figure. Everything is
// worked out by the engine (control/verdict.py); this only draws it. A finding to improve
// carries its lever: pressed, it opens that block's inspector at the setting, takes the scheme
// named, or opens the test at its figure.
//
// The sentences shown first are the engine's own, made from the findings. Where the program
// that serves the page has a language model set up, it is asked to phrase the same findings,
// and its sentences, checked there to cite only the findings' numbers, take their place with
// a quiet note that they were phrased by the model.
//
// An edited scheme is judged against the last run of the same scheme as tuned, of the same
// test, kept here for as long as the page is open.

import { written } from "./figures";
import "./verdict.css";

import { useEffect, useMemo, useRef, useState } from "react";
import { sentence } from "../format";
import { takeScheme } from "./actions";
import { DESIGN_STEPS, openDesign } from "./designsteps";
import { ExportCButton } from "./exportc";
import { ReportButton } from "./fullscheme";
import { aborted, control } from "./client";
import { chipsOf, targetOf } from "./findings";
import type { Chip, Target, Tone } from "./findings";
import { choiceWord, keyWord } from "./keys";
import { pointAt } from "./pointat";
import { lab, useLab } from "./store";
import type { Finding, Lever, Phrased, Presets, Quality, Run, Verdict as Judged, Value } from "./types";
import { Icon } from "./ui";
import { summaryAfterWord, VerdictWord } from "./verdictword";

/** The last run of each scheme as tuned, by design, scheme, test and fidelity. */
const asTuned = new Map<string, Quality>();
const placeOf = (design: string, q: Quality) => `${design}|${q.scheme.id}|${q.test}|${q.fidelity}`;

/** The run of the scheme as tuned an edited run is set beside; a run as tuned is kept to be one. */
export function baselineOf(design: string, q: Quality): Quality | undefined {
  const place = placeOf(design, q);
  if (!q.tuned?.edits.length) {
    asTuned.set(place, q);
    return undefined;
  }
  return asTuned.get(place);
}

/** Forget every run kept as tuned: for the tests. */
export const forgetTuned = (): void => asTuned.clear();

interface Said {
  verdict: Judged;
  phrased: Phrased | null;
}

/** The verdict of the run in the lab, judged again against the scheme as tuned where it was
 *  edited, and phrased by the model where one is set up. Never waits on either. */
function useVerdict(run: Run | null, design: string): Said | null {
  const [said, setSaid] = useState<Said | null>(null);
  useEffect(() => {
    const own = run?.verdict;
    const q = run?.quality;
    if (!own || !q) {
      setSaid(null);
      return;
    }
    setSaid({ verdict: own, phrased: null });
    const before = baselineOf(design, q);
    const body = before ? { quality: q, before } : { quality: q };
    const asked = new AbortController();
    void (async () => {
      let verdict = own;
      if (before) {
        try {
          verdict = await control.verdict(body, asked.signal);
          setSaid({ verdict, phrased: null });
        } catch (e) {
          if (aborted(e)) return;
        }
      }
      try {
        const phrased = await control.phrase(body, asked.signal);
        if (phrased.summary && phrased.key === verdict.key) setSaid({ verdict, phrased });
      } catch {
        // No model, a model that failed, or a page served without one: the engine's own sentences stand.
      }
    })();
    return () => asked.abort();
  }, [run, design]);
  return said;
}

/** Open a block's inspector at one of its settings: a key setting where it is one, else the
 *  same figure under All parameters. */
export function openAt(block: string, param: string): void {
  lab.set({ selected: block });
  // The inspector takes the keyboard to its heading as it opens: the setting is focused after.
  window.setTimeout(() => {
    const key = document.getElementById(`lab-k-${block}-${param}`);
    if (key) {
      key.scrollIntoView?.({ block: "nearest" });
      key.focus();
      return;
    }
    const all = document.querySelector<HTMLDetailsElement>(".lab-inspector .lab-all");
    if (all) all.open = true;
    window.requestAnimationFrame(() => document.getElementById(`lab-p-${block}-${param}`)?.focus());
  }, 60);
}

/** Open the test's settings at one of its figures. */
function openTest(param: string): void {
  const opener = document.querySelector<HTMLButtonElement>(".lab-test-open");
  if (opener && opener.getAttribute("aria-expanded") !== "true") opener.click();
  const kind = lab.get().scenario;
  window.setTimeout(() => document.getElementById(`lab-s-${kind}-${param}`)?.focus(), 60);
}

const VERB = { raise: "Raise", lower: "Lower", set: "Set" } as const;

/** A setting's name after a verb: a plain word is lowercase ("Lower weight"); a symbol or an
 *  abbreviation (Ki, Kp,q, PLL bandwidth) stays as it is written. */
export const afterVerb = (word: string): string =>
  /^[A-Z][a-z]{2,}(?![\w,])/.test(word) ? word.charAt(0).toLowerCase() + word.slice(1) : word;

/** " to <figure>" of a lever that sets: a number at three figures with its unit, a choice as a word. */
function setTo(to: Value | null | undefined, block: { kind: string } | undefined, param: string, presets: Presets) {
  if (to === null || to === undefined) return "";
  if (typeof to !== "number") return ` to ${choiceWord(String(to))}`;
  const unit = (block && presets.blocks[block.kind]?.params.find((p) => p.name === param)?.unit) ?? "";
  return ` to ${written(to, unit, 3)}`;
}

/** What a lever's button says, or null for a lever outside the lab (the design's own figures). */
export function leverWords(lever: Lever, presets: Presets): string | null {
  if (lever.kind === "block") {
    const block = lab.get().scheme?.blocks.find((b) => b.name === lever.block);
    const title = (block && presets.blocks[block.kind]?.title) || lever.block;
    const to = lever.direction === "set" ? setTo(lever.to, block, lever.param, presets) : "";
    return `${VERB[lever.direction]} ${afterVerb(keyWord(lever.param))}${to} · ${title}`;
  }
  if (lever.kind === "scheme") {
    const scheme = presets.schemes.find((s) => s.id === lever.to);
    return scheme ? `Try ${scheme.label.toLowerCase()}` : null;
  }
  if (lever.kind === "tuned") return "Back to the scheme as tuned";
  if (lever.kind === "test") return `Test: ${keyWord(lever.param).toLowerCase()}`;
  if (lever.kind === "design") return DESIGN_STEPS[lever.param]?.words ?? null;
  return null;
}

export function pull(lever: Lever, presets: Presets): void {
  if (lever.kind === "block") return openAt(lever.block, lever.param);
  if (lever.kind === "scheme") {
    const scheme = presets.schemes.find((s) => s.id === lever.to);
    if (scheme) takeScheme(scheme);
    return;
  }
  if (lever.kind === "tuned") {
    const tuned = lab.get().tuned;
    if (tuned) takeScheme(tuned);
    return;
  }
  if (lever.kind === "test") openTest(lever.param);
  if (lever.kind === "design") openDesign(lever.param);
}

function LeverOf({ lever, presets }: { lever: Lever; presets: Presets }) {
  const words = leverWords(lever, presets);
  if (words === null) {
    const param = lever.kind === "design" ? lever.param : "";
    return <span className="lab-finding-lever quiet">Lever: {param.replace(/_/g, " ")}</span>;
  }
  return (
    <button type="button" className="ghost lab-finding-pull" onClick={() => pull(lever, presets)}>
      <Icon name="adjustments" />
      {words}
    </button>
  );
}

const upper = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** How a finding is tagged: in words and an icon, never by colour alone. */
function Tag({ f }: { f: Finding }) {
  if (f.tag === "good")
    return (
      <span className="lab-finding-tag is-good">
        <Icon name="circle-check" />
        Passes
      </span>
    );
  if (f.tag === "note")
    return (
      <span className="lab-finding-tag is-note">
        <Icon name="info-circle" />
        Note
      </span>
    );
  return (
    <span className={`lab-finding-tag${f.severity >= 3 ? " is-severe" : ""}`}>
      <Icon name={f.severity >= 3 ? "alert-triangle" : "arrow-right"} />
      {f.severity >= 3 ? "Fails" : f.severity <= 1 ? "Design action" : "Needs a change"}
    </span>
  );
}

/** Where a finding is seen, as a press: its strip, its loop or the cost. */
function SeeIt({ target }: { target: Target | null }) {
  if (!target) return null;
  const words = target.kind === "laplace" ? "Bode plot" : target.kind === "cost" ? "Thermal plot" : "Show on trace";
  return (
    <button type="button" className="link lab-finding-see" onClick={() => pointAt(target)}>
      <Icon name={target.kind === "strip" ? "wave-sine" : "chart-line"} />
      {words}
    </button>
  );
}

function Row({ f, presets, run }: { f: Finding; presets: Presets; run: Run }) {
  const change = f.change;
  const target = targetOf(f, run);
  return (
    <li className={`lab-finding is-${f.tag}`}>
      <Tag f={f} />
      <div className="lab-finding-body">
        <p className="lab-finding-said">
          {upper(f.said)}
          {change ? (
            <span className="lab-finding-change">
              {" "}
              ({change.said} against {change.against === "tuned" ? "as tuned" : "the run before"}
              {change.better === null ? "" : change.better ? ", better" : ", worse"})
            </span>
          ) : null}
        </p>
        {(f.tag === "improve" && (f.lever || f.expect)) || target ? (
          <div className="lab-finding-how">
            {f.tag === "improve" && f.lever ? <LeverOf lever={f.lever} presets={presets} /> : null}
            {f.tag === "improve" && f.expect ? <span className="lab-finding-expect">{upper(f.expect)}.</span> : null}
            <SeeIt target={target} />
          </div>
        ) : null}
      </div>
    </li>
  );
}

const TONE_ICON: Record<Tone, string> = {
  fail: "alert-triangle",
  improve: "arrow-up-right",
  note: "info-circle",
  good: "circle-check",
};
const TONE_WORD: Record<Tone, string> = {
  fail: "fails",
  improve: "needs a change",
  note: "a note on the data",
  good: "passes",
};

/** The count of passing checks, said with its noun: "6 checks pass", "1 check passes". */
export const passWords = (figure: string): string => (figure === "1" ? "1 check passes" : `${figure} checks pass`);

/** The row of chips as one stop of the keyboard (a toolbar): Tab reaches the chip last reached,
 *  the arrows go along the row, Home and End to its ends. */
function useAlong(many: number) {
  const [at, setAt] = useState(0);
  const here = Math.min(at, Math.max(0, many - 1));
  const along = (e: React.KeyboardEvent<HTMLUListElement>) => {
    const last = many - 1;
    const to =
      e.key === "ArrowRight"
        ? Math.min(last, here + 1)
        : e.key === "ArrowLeft"
          ? Math.max(0, here - 1)
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? last
              : null;
    if (to === null) return;
    e.preventDefault();
    setAt(to);
    e.currentTarget.querySelectorAll<HTMLButtonElement>(".lab-chip")[to]?.focus();
  };
  return { here, setAt, along };
}

/** The run's findings in one row: a chip each to change or note, worst first, then the passing
 *  headline figures, then how many pass. A chip opens what it stands for under the row. */
function Chips({ chips, presets, run }: { chips: Chip[]; presets: Presets; run: Run }) {
  const [open, setOpen] = useState<string | null>(null);
  const [filling, setFilling] = useState(false);
  const was = useRef<Run | null>(null);
  // A new result fills the row in, chip by chip, once; a redraw does not.
  useEffect(() => {
    if (was.current === run) return;
    was.current = run;
    setOpen(null);
    setFilling(true);
    const off = window.setTimeout(() => setFilling(false), 900);
    return () => window.clearTimeout(off);
  }, [run]);
  // Two findings of a kind (a torque and a speed not held) are two chips of one id: each is
  // told apart by its place, so a later run never leaves one of them behind.
  const place = (c: Chip, n: number) => `${c.id}-${n}`;
  const shown = chips.find((c, n) => place(c, n) === open) ?? null;
  const { here, setAt, along } = useAlong(chips.length);
  // The worst chip alone stands out: the one emphasis of the row.
  const lead = chips[0] && chips[0].tone !== "good" ? chips[0].id : null;
  return (
    <>
      <ul
        className={`lab-chips${filling ? " is-filling" : ""}`}
        role="toolbar"
        aria-label="What the run found: arrows go along"
        onKeyDown={along}
      >
        {chips.map((c, n) => (
          <li key={place(c, n)} role="presentation" style={{ "--i": n } as React.CSSProperties}>
            <button
              type="button"
              tabIndex={n === here ? 0 : -1}
              onFocus={() => setAt(n)}
              className={`lab-chip tone-${c.tone}${n === 0 && c.id === lead ? " is-lead" : ""}`}
              aria-expanded={open === place(c, n)}
              aria-controls="lab-chip-detail"
              aria-label={c.id === "passes" ? passWords(c.figure) : `${c.label} ${c.figure}, ${TONE_WORD[c.tone]}`}
              onClick={() => setOpen(open === place(c, n) ? null : place(c, n))}
            >
              <Icon name={TONE_ICON[c.tone]} />
              {c.id === "passes" ? (
                // The count of checks that pass, with its noun: never a bare "6".
                <span className="lab-chip-label">{passWords(c.figure)}</span>
              ) : (
                <span className="lab-chip-label">{c.label}</span>
              )}
              {c.figure && c.id !== "passes" ? <span className="lab-chip-figure">{c.figure}</span> : null}
            </button>
          </li>
        ))}
      </ul>
      {shown ? (
        <div id="lab-chip-detail" className="lab-chip-detail">
          <ul className="lab-findings">
            {shown.findings.map((f, n) => (
              <Row key={`${f.id}-${n}`} f={f} presets={presets} run={run} />
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}

/** The ways to take the scheme away: the report and the C. */
export function Exports() {
  const run = useLab((s) => s.run.answer);
  if (!run?.verdict) return null;
  return (
    <div className="lab-exports" role="group" aria-label="Take this scheme away">
      <ReportButton />
      <ExportCButton />
    </div>
  );
}

/** What the run simulated beyond the controller's own model (a shaft that twists, iron that
 *  saturates), in the engine's words for this run: a verdict is of the motor as simulated. */
const BEYOND = /^the (shaft twists|simulated motor's iron)/;

function Simulated({ run }: { run: Run }) {
  const beyond = (run.taken ?? []).filter((t) => BEYOND.test(t));
  if (!beyond.length) return null;
  return (
    <p className="lab-verdict-by lab-verdict-plant">
      <Icon name="engine" /> Simulated beyond the controller's model: {beyond.map((t) => sentence(t)).join(". ")}.
    </p>
  );
}

/** The verdict: one line, the chips, and every finding a press away. Nothing before a run has
 *  answered. */
export function VerdictCard({ presets }: { presets: Presets }) {
  const run = useLab((s) => s.run.answer);
  const stale = useLab((s) => s.run.stale || s.run.status === "running");
  const design = useLab((s) => s.designKey);
  const said = useVerdict(run, design);
  const [all, setAll] = useState(false);
  // The run with the verdict it is judged by now (as tuned, or phrased): held still between changes.
  const judged = useMemo(() => (run && said ? { ...run, verdict: said.verdict } : null), [run, said?.verdict]);
  const chips = useMemo(() => chipsOf(judged), [judged]);
  // Until the verdict is read, its room is kept: nothing under it moves when it comes.
  if (!said || !run || !judged) return run ? <div className="lab-verdict-slot" aria-hidden="true" /> : null;
  const { verdict, phrased } = said;
  return (
    <section className={`lab-verdict${stale ? " is-stale" : ""}`} aria-labelledby="lab-verdict-h">
      <h4 id="lab-verdict-h" className="sr-only">
        What this run says of the design
      </h4>
      <div className="lab-verdict-line">
        <p className="lab-verdict-said" aria-live="polite">
          <VerdictWord run={judged} className="lab-verdict-word" />
          <span className="sr-only">. </span>
          <span className="lab-verdict-text">{summaryAfterWord(phrased?.summary ?? verdict.summary)}</span>
        </p>
        <button
          type="button"
          className="link lab-verdict-more"
          aria-expanded={all}
          aria-controls="lab-verdict-all"
          onClick={() => setAll(!all)}
        >
          <Icon name={all ? "minus" : "plus"} />
          Details
        </button>
      </div>
      {phrased ? (
        <p className="lab-verdict-by">Phrased by your model{phrased.model ? ` (${phrased.model})` : ""}.</p>
      ) : null}
      {stale ? <p className="lab-verdict-by">Of the run before the latest change.</p> : null}
      <Simulated run={run} />
      <Chips chips={chips} presets={presets} run={judged} />
      {all ? (
        <ul id="lab-verdict-all" className="lab-findings">
          {verdict.findings.map((f, n) => (
            <Row key={`${f.id}-${n}`} f={f} presets={presets} run={run} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
