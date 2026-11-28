// What a run found, drawn on a strip of the scope: a band of values, a stretch of time, a limit,
// an instant. The regions and the lines lie in the plot, where they were read; their words
// stand in a header line over the plot, where no trace runs, each over the place it names
// (an instant, a stretch) or at the right end (a limit, a band of values).

import type { Box, Scale } from "../charts/frame";
import { escape } from "../format";
import type { Note } from "./findings";

/** Where a strip's notes are drawn: its plot area, its two scales, the time's factor and the
 *  values its scale spans. */
export interface NoteFrame {
  box: Box;
  sx: Scale;
  sy: Scale;
  k: number;
  lo: number;
  hi: number;
}

/** The height a line of words takes in the header, and about how wide a letter of it is. */
export const LINE = 15;
const LETTER = 7;
/** The room kept between two words of one line, and the room a limit's key takes before its words. */
const APART = 12;
const KEY = 18;

/** One note's words in the header: where they start, how wide they are, and which line they
 *  are on, counted up from the plot. */
export interface Word {
  note: Note | null;
  kind: "band" | "span" | "level" | "edge" | "tick" | "mark";
  text: string;
  x: number;
  w: number;
  row: number;
}

/** The header of a strip: its words, and how many lines they take. */
export interface Head {
  words: Word[];
  rows: number;
}

/** What the header is laid out by: the plot's left edge and width, the time's scale, and the
 *  values the scale spans (none of which moves when the header takes room over the plot). */
export type HeadFrame = Pick<NoteFrame, "sx" | "k" | "lo" | "hi"> & { box: Pick<Box, "x" | "w"> };

const widthOf = (text: string, key = false) => [...text].length * LETTER + (key ? KEY : 0);

/** Whether a limit lies on the scale, on one side at least. */
const levelsIn = (n: Extract<Note, { kind: "level" }>, lo: number, hi: number): number[] =>
  (n.both ? [n.value, -n.value] : [n.value]).filter((v) => v >= lo && v <= hi);

/** The first line, from the plot up, on which a stretch is clear of the words already set. */
function clearRow(words: Word[], x: number, w: number): number {
  for (let row = 0; ; row++) {
    const taken = words.some((o) => o.row === row && x < o.x + o.w + APART && o.x < x + w + APART);
    if (!taken) return row;
  }
}

/** Words that name a place in time: set from it, or ending at it where the plot ends first. */
function anchored(words: Word[], word: Omit<Word, "x" | "w" | "row">, at: number, { x, w }: Pick<Box, "x" | "w">) {
  const wide = widthOf(word.text);
  const left = at + wide > x + w ? Math.max(x, Math.min(at, x + w) - wide) : Math.max(x, at);
  words.push({ ...word, x: left, w: wide, row: clearRow(words, left, wide) });
}

/** Words that name a value: at the right end of the first line with room, one beside another. */
function atRight(words: Word[], word: Omit<Word, "x" | "w" | "row">, { x, w }: Pick<Box, "x" | "w">) {
  const wide = widthOf(word.text, word.kind === "level");
  for (let row = 0; ; row++) {
    const on = words.filter((o) => o.row === row);
    let left = x + w - wide;
    // Moved left past whatever is in its way, from the right end.
    for (const o of [...on].sort((a, b) => b.x - a.x))
      if (left < o.x + o.w + APART && o.x < left + wide + APART) left = o.x - APART - wide;
    if (left >= x || !on.length) {
      words.push({ ...word, x: Math.max(x, left), w: wide, row });
      return;
    }
  }
}

/** Where a note names a place in time, that place across the plot; null where it names a value
 *  or lies out of sight. */
function placeOf(n: Note, { box, sx, k }: HeadFrame): number | null {
  const right = box.x + box.w;
  if (n.kind === "tick") {
    const x = sx(n.t * k);
    return x >= box.x && x <= right ? x : null;
  }
  if (n.kind !== "span") return null;
  const [a, b] = [sx(n.from * k), sx(n.to * k)].sort((p, q) => p - q);
  return Math.min(b, right) - Math.max(a, box.x) >= 1 ? Math.max(a, box.x) : null;
}

/** The words of a note that names a value, and their kind: a limit on the scale, one past its
 *  edge (said with an arrow to that edge), or a band of values in sight. Null for the others. */
function valueOf(n: Note, { lo, hi }: HeadFrame): Pick<Word, "kind" | "text"> | null {
  if (n.kind === "level") {
    if (levelsIn(n, lo, hi).length) return { kind: "level", text: n.label };
    const above = (n.both ? [n.value, -n.value] : [n.value]).some((v) => v > hi);
    return { kind: "edge", text: `${above ? "↑" : "↓"} ${n.label}` };
  }
  if (n.kind !== "band") return null;
  return Math.min(hi, Math.max(n.lo, n.hi)) > Math.max(lo, Math.min(n.lo, n.hi))
    ? { kind: "band", text: n.label }
    : null;
}

/** The words of a strip's notes and of its step's mark, laid out over the plot: none on
 *  another, none in the plot. */
export function headOf(notes: Note[], mark: { x: number; label: string } | null, frame: HeadFrame): Head {
  const words: Word[] = [];
  if (mark?.label) anchored(words, { note: null, kind: "mark", text: mark.label }, mark.x, frame.box);
  for (const n of notes) {
    const at = placeOf(n, frame);
    if (at !== null) anchored(words, { note: n, kind: n.kind, text: n.label }, at, frame.box);
  }
  for (const n of notes) {
    const said = valueOf(n, frame);
    if (said) atRight(words, { note: n, ...said }, frame.box);
  }
  return { words, rows: words.reduce((most, o) => Math.max(most, o.row + 1), 0) };
}

const group = (kind: string, n: Note, inner: string) =>
  `<g class="scope-note is-${kind} tone-${n.tone}" data-note="${escape(n.id)}">${inner}</g>`;

/** The region or the line a note draws in the plot: under the traces, or over them. */
function drawn(n: Note, { box, sx, sy, k, lo, hi }: NoteFrame): { under?: string; over?: string } {
  if (n.kind === "band") {
    const a = Math.max(lo, Math.min(n.lo, n.hi));
    const b = Math.min(hi, Math.max(n.lo, n.hi));
    if (b <= a) return {};
    const h = Math.max(2, sy(a) - sy(b));
    const y = (sy(a) - h).toFixed(1);
    return { under: group("band", n, `<rect x="${box.x}" y="${y}" width="${box.w}" height="${h.toFixed(1)}"/>`) };
  }
  if (n.kind === "span") {
    const [x1, x2] = [sx(n.from * k), sx(n.to * k)];
    const a = Math.max(box.x, Math.min(x1, x2));
    const b = Math.min(box.x + box.w, Math.max(x1, x2));
    if (b - a < 1) return {};
    const region =
      `<rect x="${a.toFixed(1)}" y="${box.y}" width="${(b - a).toFixed(1)}" height="${box.h}"/>` +
      `<path d="M${a.toFixed(1)} ${box.y}v${box.h}M${b.toFixed(1)} ${box.y}v${box.h}"/>`;
    return { under: group("span", n, region) };
  }
  if (n.kind === "level") {
    const d = levelsIn(n, lo, hi)
      .map((v) => `M${box.x} ${sy(v).toFixed(1)}h${box.w}`)
      .join("");
    return d ? { over: group("level", n, `<path d="${d}"/>`) } : {};
  }
  const x = sx(n.t * k);
  if (x < box.x || x > box.x + box.w) return {};
  const at = x.toFixed(1);
  return {
    over: group("tick", n, `<path d="M${at} ${box.y}v${box.h}"/><circle cx="${at}" cy="${box.y + 3}" r="2.5"/>`),
  };
}

/** One of the header's words: in its note's tone, a limit's led by a dash of its line. */
function written(o: Word, box: Box): string {
  const y = box.y - 6 - o.row * LINE;
  if (!o.note) return `<text class="tick scope-mark-label" x="${o.x.toFixed(1)}" y="${y}">${escape(o.text)}</text>`;
  const key = o.kind === "level" ? `<path d="M${o.x.toFixed(1)} ${y - 4}h${KEY - 6}"/>` : "";
  const x = (o.x + (key ? KEY : 0)).toFixed(1);
  const words = `<text class="scope-note-label tone-${o.note.tone}" x="${x}" y="${y}">${escape(o.text)}</text>`;
  return group(o.kind, o.note, key + words);
}

/** The findings of a strip drawn where they were read. Regions sit under the traces; lines and
 *  ticks over them; the words of all of them in the header over the plot, laid out by `headOf`.
 *  A limit off the scale is said there with an arrow to the edge it lies past, never by
 *  stretching the scale to it. */
export function stripNotes(notes: Note[], frame: NoteFrame, head: Head): { under: string; over: string; head: string } {
  const all = notes.map((n) => drawn(n, frame));
  const pick = (key: "under" | "over") => all.flatMap((d) => (d[key] ? [d[key]] : [])).join("");
  const words = head.words.map((o) => written(o, frame.box)).join("");
  return { under: pick("under"), over: pick("over"), head: words ? `<g class="scope-head">${words}</g>` : "" };
}
