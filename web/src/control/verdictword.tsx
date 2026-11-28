// The lab's verdict on a run in the page's one vocabulary (../verdictwords): "Passes",
// "Passes · 2 notes", "Needs a change" or "Ruled out", in the same colours and icons as the
// page's headline, so a scheme is never "Good" in one place and "1 to change" in another.

import { verdictToken, verdictWords } from "../verdictwords";
import type { VerdictWords, Tone as WordTone } from "../verdictwords";
import { standingOf } from "./compare";
import type { Run } from "./types";
import { Icon } from "./ui";

/** A run's verdict in the one vocabulary: anything failing rules it out; a finding to change
 *  means it needs a change; one that would only make a result that holds better is a design
 *  action after a pass, as on the page's results; notes on the data follow and never colour it. */
export function runWords(run: Run): VerdictWords {
  const s = standingOf(run);
  return verdictWords({
    level: s.fails ? "fail" : "ok",
    needsChange: s.changes > s.actions,
    actions: s.actions,
    notes: s.notes,
  });
}

/** The lab's tone class for a colour of the words. */
const TONE: Record<WordTone, string> = {
  ok: "tone-good",
  caution: "tone-improve",
  fail: "tone-fail",
  undecided: "tone-note",
  "ink-2": "tone-quiet",
};

/** The verdict drawn: the icon and the word in the state's colour, then the counts each in its
 *  own. `short` gives the narrow cell's token (the word, and design actions only). */
export function VerdictWord({ run, short = false, className = "" }: { run: Run; short?: boolean; className?: string }) {
  const w = runWords(run);
  const tail = short ? [] : w.tail;
  return (
    <span className={`lab-vword ${TONE[w.tone]} ${className}`.trim()} data-state={w.state}>
      <Icon name={w.icon} />
      <span className="lab-vword-word">{short ? verdictToken(w) : w.word}</span>
      {tail.map((p) => (
        <span key={p.text} className={`lab-vword-tail ${TONE[p.tone]}`}>
          <span aria-hidden="true"> · </span>
          {p.text}
        </span>
      ))}
    </span>
  );
}

/** The engine's two sentences under the lab's verdict word: the word says the state, so the
 *  "Good:" or "Needs a change:" that opened the first sentence goes, and "To improve:" says what
 *  the word says. */
export const summaryAfterWord = (summary: string): string =>
  summary
    .replace(/^(Good|Needs a change):\s*/, "")
    .replace(/^(\p{Ll})/u, (c) => c.toUpperCase())
    .replace(/\bTo improve:/g, "To change:");
