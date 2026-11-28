// One verdict, one vocabulary. Every surface that names the state of a result (the headline,
// the screen reader's announcement, the phone's strip, the compare table, the report, the
// lab's tables) takes its words, its colour and its icon from here, so a result is never
// "Passes" in one place and "Cautions" in another.
//
// The map:
//   pass               "Passes"                 ok
//   pass + actions     "Passes · 1 design action"   ok word, the count in caution
//   notes only         "Passes · 2 notes"       ok word, the count in ink-2 (notes on the
//                                               data never colour the verdict)
//   needs a change     "Needs a change"         caution
//   undecided          "Undecided on this data" undecided
//   fails / refused    "Ruled out"              fail (never softened: it leads, in its word)

import { escape } from "./format";
import { icon } from "./icons";

export type VerdictState = "pass" | "pass-actions" | "notes" | "change" | "undecided" | "ruled-out";

/** The colour a part of the words is drawn in: a status, or the quiet ink. */
export type Tone = "ok" | "caution" | "fail" | "undecided" | "ink-2";

export interface VerdictInput {
  /** The engine's level: ok, caution, undecided or fail. */
  level: string;
  /** Design actions: changes the result asks of the design (a fail over the motion is a fail). */
  actions?: number;
  /** Notes: what the result rests on (the data, the model); they never colour the verdict. */
  notes?: number;
  /** The result does not hold as it stands and a change is asked for (a scheme as tuned that
   *  misses a check, short of being ruled out). */
  needsChange?: boolean;
  /** Refused by the engine, or failed over the motion: ruled out whatever the level says. */
  refused?: boolean;
}

export interface VerdictPart {
  text: string;
  tone: Tone;
}

export interface VerdictWords {
  state: VerdictState;
  /** The state's own word: "Passes", "Needs a change", "Ruled out", "Undecided on this data". */
  word: string;
  /** The colour of the word and its icon. */
  tone: Exclude<Tone, "ink-2">;
  icon: string;
  /** What follows the word after " · ", each in its own colour: the counts. */
  tail: VerdictPart[];
  /** The whole string, as written and as said: word and tail joined by " · ". */
  text: string;
}

const WORD: Record<VerdictState, string> = {
  pass: "Passes",
  "pass-actions": "Passes",
  notes: "Passes",
  change: "Needs a change",
  undecided: "Undecided on this data",
  "ruled-out": "Ruled out",
};

const TONE: Record<VerdictState, VerdictWords["tone"]> = {
  pass: "ok",
  "pass-actions": "ok",
  notes: "ok",
  change: "caution",
  undecided: "undecided",
  "ruled-out": "fail",
};

export const STATE_ICON: Record<VerdictWords["tone"], string> = {
  ok: "circle-check",
  caution: "alert-triangle",
  fail: "circle-x",
  undecided: "help-circle",
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The state of a result, from its level and what it asks of the user. */
export function stateOf(v: VerdictInput): VerdictState {
  if (v.refused || v.level === "fail") return "ruled-out";
  if (v.level === "undecided") return "undecided";
  if (v.needsChange) return "change";
  if (v.actions) return "pass-actions";
  if (v.notes) return "notes";
  return "pass";
}

/** A result's verdict in the one vocabulary. Counts follow a pass and a needs-a-change; a
 *  ruled-out or undecided result says its word alone (its reason is said beside it). */
export function verdictWords(v: VerdictInput): VerdictWords {
  const state = stateOf(v);
  const tail: VerdictPart[] = [];
  if (state !== "ruled-out" && state !== "undecided") {
    if (v.actions && state !== "change")
      tail.push({ text: plural(v.actions, "design action", "design actions"), tone: "caution" });
    if (v.notes) tail.push({ text: plural(v.notes, "note", "notes"), tone: "ink-2" });
  }
  const word = WORD[state];
  const tone = TONE[state];
  return { state, word, tone, icon: STATE_ICON[tone], tail, text: [word, ...tail.map((t) => t.text)].join(" · ") };
}

/** The verdict as markup: the icon and the word in the state's colour, each part of the tail
 *  in its own after a quiet " · ". `extra` parts come last (as "on an assumed drive"); `lead`,
 *  markup, comes between the icon and the word (a part's name among several). */
export function verdictMarkup(w: VerdictWords, extra: VerdictPart[] = [], cls = "verdict", lead = ""): string {
  const parts = [...w.tail, ...extra]
    .map((p) => `<span class="v-sep"> · </span><span class="v-tail tone-${p.tone}">${escape(p.text)}</span>`)
    .join("");
  return (
    `<span class="${cls} ${w.tone}" data-state="${w.state}">${icon(w.icon)}${lead}` +
    `<span class="v-word">${escape(w.word)}</span>${parts}</span>`
  );
}

/** The verdict as a plain string, with extra parts: what the live region says. */
export const verdictText = (w: VerdictWords, extra: VerdictPart[] = []): string =>
  [w.text, ...extra.map((p) => p.text)].join(" · ");

/** The words for a narrow cell (the compare table, a row among parts, a phone's bar): the
 *  word, and the design actions as a count only when there are some ("Passes · 1 action").
 *  Notes are left to the full line. */
export function verdictShort(w: VerdictWords): VerdictWords {
  const tail = w.tail
    .filter((p) => p.tone === "caution")
    .map((p) => ({ ...p, text: p.text.replace("design action", "action") }));
  return { ...w, tail, text: [w.word, ...tail.map((t) => t.text)].join(" · ") };
}

/** The short token as a plain string. */
export const verdictToken = (w: VerdictWords): string => verdictShort(w).text;
