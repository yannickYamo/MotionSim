// The small pieces every step is built from: a field, a fold, a verdict, a refusal.

import { NotWorkedOut, Refused } from "../api";
import type { Check } from "../api";
import type { Change } from "../follow";
import { eng, escape, num, sentence, tied } from "../format";
import { icon } from "../icons";
import { signNote } from "../limits";
import { shownAs, shownText } from "../motorentry";
import { numberOr } from "../parse";
import { since as sinceTag } from "../elapsed";
import { noteAt } from "../boxes";
import { app, res, ui, underTest } from "../store";
import { verdictMarkup, verdictWords } from "../verdictwords";
import type { VerdictWords } from "../verdictwords";

export const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
/** The element a selector names, where the page has one. */
export const at = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector);
export const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Said once to a screen reader, now: what an action the user started came to. */
export function say(text: string): void {
  ui.announced = text;
  const region = document.querySelector("#announce");
  if (region) region.textContent = text;
}

/** A small turning mark beside a job under way; still, under reduced motion. */
export const spinner = '<span class="spinner" aria-hidden="true"></span>';

/** A figure and its unit kept on one line. */
export const together = (text: string) => text.replace(/(\d) (N·m|A|V|rpm|°C|K\/W|W|kHz|ns|µs)\b/g, "$1 $2");

/**
 * Detail one press away. The face says what is inside as it stands now, so that nothing
 * the tool assumed is hidden: only the means of changing it is folded.
 * `holds`: the fields inside; a refusal about one of them opens the fold.
 */
export function fold(
  id: string,
  glyph: string,
  title: string,
  face: string,
  body: string,
  holds: string[] = [],
): string {
  const at = res.blocked?.field;
  const wrong = at ? holds.some((h) => h === at || h.endsWith(`.${at}`)) : false;
  // A refusal about a figure inside opens the fold, whatever the user left it as.
  const open = wrong ? " open data-must-open" : "";
  const summary = `<summary>${icon(glyph)}${escape(title)}<span class="quiet">${escape(face)}</span></summary>`;
  return `<details class="more" data-fold="${id}"${open}>${summary}${body}</details>`;
}

/** The cooling as the user set it, in a few words. */
export function coolingWords(): string {
  const k = app.state.conditions;
  const given = String(k.rth_case_sink ?? "").trim() !== "";
  const pad = k.interface === "pad" ? ", each package on a thermal pad" : "";
  const under = given ? `, ${k.rth_case_sink} K/W from each case to it` : pad;
  // What the user typed is text until the engine has taken it: it is written out as text.
  if (k.cooling === "heatsink")
    return escape(`a ${k.rth_sink || "?"} K/W heatsink in ${num(k.t_ambient)} °C air${under}`);
  if (k.cooling === "none") return `no heatsink, in ${num(k.t_ambient)} °C air`;
  if (k.cooling === "board") {
    return escape(`no heatsink, on a ${k.board_area || "?"} cm² board in ${num(k.t_ambient)} °C air`);
  }
  return escape(`a ${num(k.t_sink)} °C heatsink${under}`);
}

/** A figure typed in a base unit, said the way it is spoken: 0.00833 H is "8.33 mH". Only
 *  where the two differ enough to help; it follows the figure as it is typed. */
const SPOKEN = new Set(["H", "Ω", "F", "Wb", "V·s/rad"]);
function saidAs(raw: string | number, unit: string): string {
  const v = numberOr(raw, null, unit);
  if (!SPOKEN.has(unit) || v === null || v === 0) return "";
  return Math.abs(v) < 0.1 || Math.abs(v) >= 10000 ? `That is ${eng(v, unit)}. ` : "";
}

/** The engine's name for a figure, as the page's box for it is bound. */
const BOX: Record<string, string[]> = {
  f_sw: ["f_khz"],
  t_dead: ["t_dead_ns"],
  l_loop: ["l_loop_nh"],
  t_min_pulse: ["t_min_ns"],
  point: ["rpm", "torque"],
  speed: ["rpm"],
};

/** Whether the box bound to this path holds the figure the engine refused. */
function wrongAt(path: string): boolean {
  const at = res.blocked?.field;
  if (!at) return false;
  const last = path.split(".").pop()!;
  return (BOX[at] ?? [at]).includes(last) && /^(conditions|motors|load|sink|start)\./.test(path);
}

export const idOf = (path: string) => `f-${path.replace(/\W+/g, "-")}`;

/** A figure a motor rarely has, said at its box as a caution: it is still used. */
function unusual(path: string, given: string, figure: number | null): string | null {
  if (figure === null || !path.startsWith("motors.") || figure <= 0) return null;
  // A motor's box in mH or mΩ is held to the same bounds as one in H or Ω.
  const milli = given === "mH" || given === "mΩ";
  const [unit, value] = milli ? [given.slice(1), figure * 1e-3] : [given, figure];
  if (unit === "H" && (value < 1e-6 || value > 0.1))
    return (
      `${eng(value, "H")} is unusual for a motor: a phase inductance is mostly between 1 µH and 100 mH. ` +
      "Check the figure and its unit."
    );
  if (unit === "Ω" && value > 10)
    return (
      `${eng(value, "Ω")} is unusual for a motor: a phase resistance is mostly below 10 Ω. ` +
      "Check the figure and its unit."
    );
  return null;
}

/** A figure the design waits for, asked for at its box in the page's voice: nothing is wrong
 *  yet, so nothing is marked as wrong. */
const wantedAt = (path: string): string | null =>
  res.waiting && path === `conditions.${res.waiting.field}` ? `Needed: ${res.waiting.reason}.` : null;

/** A figure that moved to follow the device under test, said the way its box shows it: a
 *  motor's in the terms of step 2 (line to line or per phase, mH or mΩ, Kv or Kt). */
export function changeShown(c: Change): Change {
  const [head, kind, key] = c.path.split(".");
  const box = head === "motors" ? shownAs(kind, key, app.state.motorEntry, c.label) : null;
  if (!box) return c;
  return { ...c, label: box.label, unit: box.unit, from: shownText(box, c.from), to: shownText(box, c.to) };
}

/** Where the figure in a box moved to follow the device under test: what it was. */
function wasAt(path: string): string | null {
  const moved = ui.followed?.changes.find((c) => c.path === path);
  if (!moved) return null;
  const { from, unit } = changeShown(moved);
  return `Was ${from}${unit ? ` ${unit}` : ""}: it follows the device under test.`;
}

/** How a note under a box is marked: a refusal, a figure asked for, a caution, or plain help. */
function noteClass(refused: boolean, wanted: boolean, caution: boolean): string {
  if (refused) return "help said-wrong";
  if (wanted) return "help needed";
  return caution ? "help caution" : "help";
}

/** What a box says of a figure it takes, in order: the engine's refusal of it, how its sign is
 *  taken, that it is needed, where it was before it followed the device, that it is unusual,
 *  or that it is over the rating. `noted`: the box says the figure was not taken. */
function plainSaid(path: string, value: string | number, raw: string, unit: string, noted: boolean, refused: boolean) {
  const id = idOf(path);
  const sign = numberOr(raw);
  const signed = sign !== null && !noted ? signNote(path, sign) : null;
  const wanted = wantedAt(path);
  // A figure the engine refused is said at its box too, not only above the form.
  const refusedHere = refused && res.blocked ? `${sentence(res.blocked.reason)}.` : null;
  const odd = noted || refusedHere ? null : unusual(path, unit, numberOr(value));
  const plainNote = refusedHere ?? signed ?? wanted ?? wasAt(path) ?? odd;
  if (plainNote) {
    const cls = noteClass(!!refusedHere, !!wanted, odd === plainNote);
    return `<p class="${cls}" id="${id}-n">${escape(plainNote)}</p>`;
  }
  const above = overRating(path, numberOr(value));
  return above ? `<p class="help" id="${id}-n">${above}</p>` : "";
}

/** What a box has to say of the figure in it: that it was refused, cannot be read, or is
 *  outside what the box takes. The text in the box is what was typed, read or not. */
export function saidAt(path: string, value: string | number, unit = ""): { text: string; raw: string; wrong: boolean } {
  const kept = noteAt(path, value);
  // What a unit or a prefix came to is said under the box; nothing is wrong with it.
  const echo = kept?.echo ? kept : null;
  const note = echo ? null : kept;
  const refused = wrongAt(path);
  const raw = kept?.raw ?? String(value ?? "");
  const id = idOf(path);
  const why = note ? `<p class="help unread" id="${id}-n">${escape(note.why)}</p>` : "";
  const how = plainSaid(path, value, raw, unit, !!note, refused);
  const echoed = echo ? `<p class="help echo" id="${id}-e">${escape(echo.why)}</p>` : "";
  return { text: why || echoed + how, raw, wrong: refused || !!note };
}

export function field(
  path: string,
  label: string,
  value: string | number,
  unit: string,
  help = "",
  attrs = "",
): string {
  const id = idOf(path);
  const said = saidAt(path, value, unit);
  const marked = (wrongAt(path) ? " is-wrong" : "") + (said.text.includes("unread") ? " is-unread" : "");
  const spoken = SPOKEN.has(unit);
  const aloud = spoken ? `<span data-said="${escape(unit)}">${escape(saidAs(said.raw, unit))}</span>` : "";
  const below = help || spoken ? `<p class="help" id="${id}-h">${aloud}${escape(help)}</p>` : "";
  const by = [
    below ? `${id}-h` : "",
    said.text.includes(`id="${id}-e"`) ? `${id}-e` : "",
    said.text.includes(`id="${id}-n"`) ? `${id}-n` : "",
  ]
    .filter(Boolean)
    .join(" ");
  const described = (by ? ` aria-describedby="${by}"` : "") + (said.wrong ? ' aria-invalid="true"' : "");
  const input =
    `<input id="${id}" data-bind="${escape(path)}" inputmode="decimal" autocomplete="off" ` +
    `value="${escape(said.raw)}" ${attrs}${described}/>`;
  const tail = unit ? `<span class="unit">${escape(unit)}</span>` : "";
  const control = `<div class="control">${input}${tail}</div>`;
  const body = `<label for="${id}">${escape(label)}</label>${control}${below}${said.text}`;
  return `<div class="field${marked}">${body}</div>`;
}

export function select(path: string, label: string, value: string, options: [string, string][], help = ""): string {
  const id = idOf(path);
  const list = options
    .map(([v, t]) => `<option value="${escape(v)}"${v === value ? " selected" : ""}>${escape(t)}</option>`)
    .join("");
  const below = help ? `<p class="help" id="${id}-h">${escape(help)}</p>` : "";
  const by = help ? ` aria-describedby="${id}-h"` : "";
  const control = `<div class="control"><select id="${id}" data-bind="${escape(path)}"${by}>${list}</select></div>`;
  return `<div class="field"><label for="${id}">${escape(label)}</label>${control}${below}</div>`;
}

/** A supply above what the part under test is rated for, said at the supply's box, with the
 *  rating in the colour of a caution. Markup, escaped here. */
function overRating(path: string, volts: number | null): string | null {
  if (path !== "conditions.v_dc" || volts === null) return null;
  const part = app.setup.devices.find((d) => d.id === underTest());
  if (!part?.v_max || volts <= part.v_max) return null;
  return (
    `${escape(num(volts))} V is above this part's ` +
    `<b class="caution-figure">${escape(num(part.v_max))} V</b> rating.`
  );
}

/** A level as a class name: only the levels the page has styles for, whatever was sent. */
export const levelClass = (level: string): string =>
  ["ok", "caution", "undecided", "fail"].includes(level) ? level : "caution";

/** A verdict known only by its level, in the one vocabulary (verdictwords.ts): a caution with
 *  nothing counted is a result that asks for a change. A part's verdict is said from its
 *  counts instead (verdictline.ts, wordsOf). */
const byLevel = (level: string) => verdictWords({ level, needsChange: level === "caution" });

/** The verdict as a word, as it is written and as it is said. */
export const verdictWord = (level: string): string => byLevel(level).text;

/** The verdict as its icon and word, by level; or, given its words, those. */
export const verdict = (level: string, words?: VerdictWords) => verdictMarkup(words ?? byLevel(level));

const CHECK_ICON: Record<string, string> = { ok: "check", fail: "x", undecided: "help-circle" };

/** The way from a check about one figure to its box: the datasheet's figure for one the tool
 *  took, or a cooling of the user's own for one the tool sized. */
function toFigure(c: Check): string {
  if (!c.field) return "";
  const cooling = c.field === "rth_sink" || c.field === "board_area";
  const label = cooling ? "Give your own figure" : "Add the datasheet figure";
  return (
    ` <button type="button" class="link to-figure" data-to-figure="${escape(c.field)}" ` +
    `data-figure-of="${escape(c.device ?? "")}">${icon("arrow-left")}${label}</button>`
  );
}

export function checkList(checks: Check[]): string {
  const row = (c: Check) =>
    `<li class="${levelClass(c.level)}">${icon(CHECK_ICON[c.level] ?? "alert-triangle")}` +
    `<span><b>${escape(sentence(c.topic))}.</b> ${escape(sentence(c.message))}${toFigure(c)}</span></li>`;
  return `<ul class="checks">${checks.map(row).join("")}</ul>`;
}

/** A group as one row: its name and the figure to remember, with the lines behind it one press
 *  away, in place, under a +. `lines` are markup already escaped. */
export function recRow(id: string, name: string, value: string, lines: string[], cls = ""): string {
  const list = lines.length ? `<ul class="plain small">${lines.map((l) => `<li>${l}</li>`).join("")}</ul>` : "";
  return (
    `<details class="rec${cls}" data-fold="${escape(id)}"><summary><h4>${name}` +
    `<span class="rec-value">${value}</span></h4><span class="plus" aria-hidden="true">${icon("plus")}</span>` +
    `</summary>${list}</details>`
  );
}

/** A block drawn as a heading over a list, folded into one row under its heading. */
export function foldBlock(id: string, block: string, value = ""): string {
  const m = /^<h4>([\s\S]*?)<\/h4><ul class="plain small">([\s\S]*)<\/ul>$/.exec(block);
  if (!m) return block;
  const items = m[2]
    .split(/(?=<li>)/)
    .map((l) => l.replace(/^<li>|<\/li>$/g, ""))
    .filter(Boolean);
  return recRow(id, m[1], value, items);
}

/** Topics that say what a result rests on (the data, the model) rather than what to change in
 *  the design: they are notes, read after the design actions. */
export const NOTE_TOPICS = new Set(["data", "solver", "edges"]);

/** Whether a check asks for a change to the design, or to a figure given: every fail, and every
 *  caution or open question that is not about the data a result rests on. */
export const isAction = (c: Check): boolean => c.level === "fail" || (c.level !== "ok" && !NOTE_TOPICS.has(c.topic));

/** A finding's message as one line and the rest: the line ends at its first colon or semicolon,
 *  where the engine's sentences turn from the number and its limit to the reason and the fix. */
export function splitFinding(message: string): [string, string] {
  const at = message.search(/[:;] /);
  if (at < 16 || at > 140) return [message, ""];
  return [message.slice(0, at), message.slice(at + 2)];
}

/** Findings one line each: the topic, the number against its limit, and, one press away in
 *  place, why and what to change. `id` keeps an opened line open through a redraw. */
export function findingList(checks: Check[], id: string): string {
  const row = (c: Check, k: number) => {
    const [line, rest] = splitFinding(sentence(c.message));
    const mark = icon(CHECK_ICON[c.level] ?? "alert-triangle");
    const head = `${mark}<span class="f-line"><b>${escape(sentence(c.topic))}</b> ${escape(line)}</span>`;
    const more = rest || c.field;
    if (!more) return `<li class="finding ${levelClass(c.level)}"><div class="f-head">${head}</div></li>`;
    const body = `<p>${rest ? `${escape(sentence(rest))}.` : ""}${toFigure(c)}</p>`;
    const opens = rest ? "Why, and how to fix it" : "How to fix it";
    return (
      `<li class="finding ${levelClass(c.level)}"><details data-fold="${escape(`${id}-${k}`)}">` +
      `<summary class="f-head">${head}<span class="f-more">${opens}</span></summary>` +
      `${body}</details></li>`
    );
  };
  return `<ul class="findings">${checks.map(row).join("")}</ul>`;
}

/** The one-line why of a figure, on hover and on focus (the WAI-ARIA tooltip pattern): the
 *  figure stays one value and its unit, and the reason is one move away, never a paragraph. */
export function tip(label: string, why: string): string {
  if (!why) return escape(label);
  // Named by what it says, so a redraw keeps the same id and the same text.
  let h = 0;
  for (const ch of label + why) h = (h * 31 + ch.charCodeAt(0)) | 0;
  const id = `tip-${(h >>> 0).toString(36)}`;
  return (
    `<span class="has-tip" tabindex="0" aria-describedby="${id}">${escape(label)}` +
    `<span role="tooltip" id="${id}" class="tip">${escape(why)}</span></span>`
  );
}

export function refusal(r: Refused): string {
  // No answer came: said in its own, neutral style, never as a refusal of the design.
  if (r instanceof NotWorkedOut) {
    const said = `<p><b>Not worked out.</b> ${escape(sentence(r.reason))}.</p>`;
    return `<div class="fault" role="status">${icon("info-circle")}<div>${said}</div></div>`;
  }
  const fix = r.fix ? `<p class="fix">${escape(sentence(r.fix))}.</p>` : "";
  const said = `<p><b>This cannot work.</b> ${escape(sentence(r.reason))}.</p>`;
  return `<div class="refusal" role="alert">${icon("ban")}<div>${said}${fix}</div></div>`;
}

/** The note that figures moved when the device under test changed: what moved, from what to
 *  what, with the way to put them back. It stays until it is put away. */
export function followedNote(): string {
  const f = ui.followed;
  if (!f) return "";
  const item = (c: { label: string; from: string | number; to: string | number; unit: string }) =>
    `<li>${escape(c.label)}: ${escape(String(c.from))} → <b>${escape(String(c.to))}</b>` +
    `${c.unit ? ` ${escape(c.unit)}` : ""}</li>`;
  const lead =
    `<p><b>The motor and the design point now start from ${escape(f.device)}.</b> ` +
    "Figures you typed are as you left them; these, which you had not touched, moved:</p>";
  const buttons =
    `<p><button type="button" class="ghost" data-followed="keep">${icon("check")}Keep them</button>` +
    `<button type="button" class="ghost" data-followed="back">${icon("arrow-left")}Put them back</button></p>`;
  const list = `<ul class="plain small">${f.changes.map((c) => item(changeShown(c))).join("")}</ul>`;
  return `<div class="asking followed" id="followed">${icon("info-circle")}<div>${lead}${list}${buttons}</div></div>`;
}

/** Word that something is being worked out, with how long it has been on its way: never a
 *  guess of how long it takes. `since`: when it was asked for; the count is left out without it.
 *  The count moves on unspoken: a screen reader is told what is being worked out, once, and
 *  not a new second every second. */
export const waiting = (text: string, since = 0) =>
  `<p class="waiting" role="status"><span class="spinner" aria-hidden="true"></span>` +
  `<span>${escape(text)}${since ? ` <span class="quiet" aria-hidden="true">${sinceTag(since)}</span>` : ""}</span></p>`;

/** A slower answer as its tab shows it: word that it is on its way, with how long it has been,
 *  while `key` is being worked out or nothing has come; the engine's refusal of it, said by
 *  `refused`; else what `shown` draws of it. */
export function whenAnswered<T>(
  key: string,
  answer: T | Refused | null,
  words: string,
  shown: (answer: T) => string,
  refused: (r: Refused) => string = refusal,
): string {
  if (res.loading.has(key) || answer === null) return waiting(words, res.started.get(key));
  return answer instanceof Refused ? refused(answer) : shown(answer);
}

/** A figure the design cannot be worked out without: asked for at its box, and no verdict
 *  is given on a design that is not all there yet. */
export function asking(r: Refused): string {
  const said = `<p><b>One figure is still needed.</b> ${escape(sentence(r.reason))}.</p>`;
  return `<div class="asking" role="status">${icon("info-circle")}<div>${said}</div></div>`;
}

/** A figure as the page shows it: its name, the value with its unit, at most one short line
 *  under it, and `why`, the line that explains it, on hover and on focus of the name. */
export function readout(label: string, value: string, note = "", tone = "", why = "", delta = ""): string {
  // A figure is set large; a name or a phrase is set smaller and may wrap. A what-if's
  // difference from the result pinned as A sits beside it.
  const words = /^[^\d–]/.test(value) ? " words" : "";
  const figure = `<span class="figure${words}" data-roll>${escape(tied(value))}</span>${delta}`;
  const under = note ? `<span class="note">${escape(tied(note))}</span>` : "";
  return `<div class="readout ${tone}"><dt>${tip(label, why)}</dt><dd>${figure}${under}</dd></div>`;
}

/** How a part is packaged, in the words a builder would use. */
export const packaging = (d: { positions: number; integrated_driver: boolean }) =>
  d.integrated_driver
    ? "IPM: power module with its gate drivers built in"
    : d.positions >= 6
      ? "Module: six switches in one package, gates driven from outside"
      : d.positions >= 4
        ? "Module: two legs in one package, gates driven from outside"
        : d.positions >= 2
          ? "Module: one leg in a package, gates driven from outside"
          : "Discrete: one switch a package, gates driven from outside";

/** Up to five lines on one chart, told apart by weight and dash as well as by tone. */
export const legendOf = (names: string[]) =>
  `<ul class="legend inline series-legend">${names
    .map((n, k) => `<li><span class="key line s${k}"></span>${escape(n)}</li>`)
    .join("")}</ul>`;

/** For a part compared on a design that was started from another: the press that starts the
 *  design from this part instead. The figures that move are said, with the way to put them back. */
export function leadButton(id: string, name: string): string {
  return (
    `<button type="button" class="ghost" data-lead="${escape(id)}" ` +
    `aria-label="Start the design from ${escape(name)}">${icon("player-play")}Start the design from this part</button>`
  );
}
