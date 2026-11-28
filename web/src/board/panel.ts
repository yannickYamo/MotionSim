// What was read from a board's file, in the event's fold: which board and which leg, what was
// taken as the loop with the means to take another, each of the six figures with the range it
// is believed in and what it rests on, the cautions, and the one press that puts the figures
// under the event's boxes. Everything the engine sends is written out as text.

import { escape, sentence, sig, whole } from "../format";
import { icon } from "../icons";
import { refusal, waiting } from "../views/html";
import { board, boardInUse } from "./reading";
import { FIGURES } from "./types";
import type { BoardFigure, BoardRead, Bridge, FigureName } from "./types";

const NAMES: Record<FigureName, string> = {
  l_loop_nh: "Loop inductance",
  l_cs_nh: "Common-source inductance",
  l_gate_nh: "Gate-loop inductance",
  r_loop_mohm: "Loop resistance",
  c_dc_uf: "Decoupling capacitance",
  esl_nh: "Capacitors' own inductance",
};

const FORMATS: Record<string, string> = { kicad: "a KiCad board", ipc2581: "an IPC-2581 file" };

/** What the engine sent where a text is expected: a text or a number as it is, else nothing. */
const text = (v: unknown): string => (typeof v === "string" ? v : typeof v === "number" ? String(v) : "");
const texts = (v: unknown): string[] => (Array.isArray(v) ? v.map(text).filter(Boolean) : []);
const isNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** Said where a board file is given to the engine in the browser, which reads none. */
export const ELSEWHERE =
  "Reading a board file runs on your own machine: start <code>motionsim serve</code>, or the Docker " +
  "image, and give the file there.";

const fact = (what: string, said: string, wide = false) =>
  `<div${wide ? ' class="wide"' : ""}><dt>${what}</dt><dd>${said}</dd></div>`;

/** The board and the leg taken: the file, what was read of it, its supply and switch node. */
function facts(a: BoardRead, leg: Bridge | undefined, legs: string[]): string {
  const kind = FORMATS[text(a.format)] ?? "a board file";
  const count = (n: unknown, one: string) => (isNumber(n) ? `${whole(n)} ${one}${n === 1 ? "" : "s"}` : "");
  const read = [count(a.parts, "part"), count(a.nets?.count, "net")].filter(Boolean).join(" and ");
  const series = texts(leg?.series);
  return (
    `<dl class="facts board-facts">` +
    fact("Board", `${escape(text(a.name))}, ${kind}${read ? ` of ${read}` : ""}`, true) +
    fact("Supply, positive", escape(text(a.nets?.dc_plus)) || "–") +
    fact("Supply, negative", escape(text(a.nets?.dc_minus)) || "–") +
    (legs.length > 1 ? "" : fact("Switch node", escape(text(leg?.switch_node ?? a.taken)) || "–")) +
    (series.length ? fact("In series with the low side", escape(series.join(", ")), true) : "") +
    `</dl>`
  );
}

/** One role of the loop as a list to choose from, in the page's own box. */
function pick(role: string, label: string, options: [string, string][], chosen: string, help = ""): string {
  // A list with a line under it (the legs) takes a row of its own, so the two sides sit level.
  const wide = help ? " wide" : "";
  const id = `board-${role}`;
  const list = options
    .map(([v, t]) => `<option value="${escape(v)}"${v === chosen ? " selected" : ""}>${escape(t)}</option>`)
    .join("");
  const below = help ? `<p class="help" id="${id}-h">${help}</p>` : "";
  return (
    `<div class="field${wide}"><label for="${id}">${label}</label><div class="control">` +
    `<select id="${id}" data-board-choose="${role}"${help ? ` aria-describedby="${id}-h"` : ""}>${list}</select>` +
    `</div>${below}</div>`
  );
}

/** The switches of one side: the one taken first, then every other the board has. Switches
 *  in parallel are taken together as read, and one of them alone once it is chosen. */
function side(role: "high_side" | "low_side", label: string, taken: string[], all: string[], asked?: string[]): string {
  const now = asked ?? taken;
  const one = now.length === 1 && all.includes(now[0]);
  const options: [string, string][] = all.map((ref) => [ref, ref]);
  if (!one) options.unshift(["", now.length ? `${now.join(" and ")}, as read` : "None found"]);
  return pick(role, label, options, one ? now[0] : "");
}

/** The capacitors across the supply, those taken for this leg's loop ticked. */
function capacitors(a: BoardRead, taken: string[]): string {
  const all = Array.isArray(a.candidates.capacitors) ? a.candidates.capacitors : [];
  const refs = new Set(all.map((c) => text(c?.ref)));
  const rows = [...all, ...taken.filter((ref) => !refs.has(ref)).map((ref) => ({ ref, value: "" }))];
  if (!rows.length) return "";
  const tick = (c: { ref: string; value?: string }) => {
    const ref = text(c?.ref);
    const value = text(c?.value);
    return (
      `<label><input type="checkbox" data-board-choose="capacitors" value="${escape(ref)}"` +
      `${taken.includes(ref) ? " checked" : ""}/><span>${escape(ref)}` +
      `${value ? ` <span class="quiet">${escape(value)}</span>` : ""}</span></label>`
    );
  };
  return (
    `<fieldset class="board-caps"><legend>Capacitors taken for the loop</legend>` +
    `<div>${rows.map(tick).join("")}</div></fieldset>`
  );
}

/** The switches that fit one side of the leg on the page, as the reader found them; where it
 *  says nothing of the leg's sides, every switch of the board. */
function fitting(a: BoardRead, role: "high_side" | "low_side", leg: Bridge | undefined): string[] {
  const bySide = a.candidates[role];
  const node = text(leg?.switch_node ?? a.taken);
  const fit = bySide && typeof bySide === "object" ? texts((bySide as Record<string, unknown>)[node]) : [];
  return fit.length ? fit : texts(a.candidates.switches);
}

/** The pairs of nets that could be the supply, as a list to choose from where there is more
 *  than one: another pair starts the board's reading again from it. */
function supply(a: BoardRead): string {
  // Each pair goes by its place in the list the reader sent: a name may hold anything.
  const rails = (Array.isArray(a.candidates.rails) ? a.candidates.rails : [])
    .map((r, k) => [String(k), text(r?.dc_plus), text(r?.dc_minus)] as const)
    .filter(([, plus, minus]) => plus && minus);
  if (rails.length < 2) return "";
  const now = rails.find(([, plus, minus]) => plus === text(a.nets?.dc_plus) && minus === text(a.nets?.dc_minus));
  const options: [string, string][] = rails.map(([k, plus, minus]) => [k, `${plus} to ${minus}`]);
  return pick(
    "rails",
    "Supply, positive to negative",
    options,
    now?.[0] ?? "",
    `${rails.length} pairs of nets could be the supply. Another starts from what is read for it.`,
  );
}

/** What was taken as the loop, each part of it changeable: the board is read again with it. */
function loop(a: BoardRead, leg: Bridge | undefined, legs: string[]): string {
  const asked = board.since ? board.asked : board.choose;
  const many = legs.length > 1;
  const legPick = many
    ? pick(
        "leg",
        "Leg, by its switch node",
        legs.map((l) => [l, l]),
        asked.leg ?? text(a.taken),
        `${legs.length} legs were found. Another starts from what is read for it.`,
      )
    : "";
  return (
    `<p class="board-took">We took these as the loop. Change one and the board is read again.</p>` +
    `<div class="fields">${supply(a)}${legPick}` +
    side("high_side", "High side", texts(leg?.high_side), fitting(a, "high_side", leg), asked.high_side) +
    side("low_side", "Low side", texts(leg?.low_side), fitting(a, "low_side", leg), asked.low_side) +
    `</div>${capacitors(a, asked.capacitors ?? texts(leg?.capacitors))}`
  );
}

/** Whether the layout's text leaves a figure out, as a comment: the event then assumes it. */
const leftOut = (layout: string, key: FigureName) => new RegExp(`^\\s*#\\s*${key}\\s*:`, "m").test(layout);

type Worked = BoardFigure & { value: number; low: number; high: number };
const isWorked = (f: BoardFigure | undefined): f is Worked =>
  !!f && isNumber(f.value) && isNumber(f.low) && isNumber(f.high);

const caution = (said: string) => `<p class="help caution">${icon("alert-triangle")}${said}</p>`;

/** A figure worked out: its value with the range it is believed in, never the value alone,
 *  and what of it is not the board's own or does not reach the event. */
function workedOut(key: FigureName, f: Worked, layout: string): string {
  const unit = escape(text(f.unit));
  const { board_nh: onBoard, package_nh: inPackages } = f.parts ?? {};
  const shares =
    isNumber(onBoard) && isNumber(inPackages)
      ? ` <span class="quiet">${sig(onBoard)} on the board, ${sig(inPackages)} in the packages.</span>`
      : "";
  const range = `<span class="quiet">believed ${sig(f.low)} to ${sig(f.high)} ${unit}.</span>`;
  return (
    `<p><b>${sig(f.value)} ${unit}</b> ${range}${shares}</p>` +
    (leftOut(layout, key) ? caution("Outside what a layout file takes: the usual figure is assumed.") : "") +
    (f.assumed ? caution("Partly assumed, not all read from the board.") : "")
  );
}

/** One figure, or that it was not worked out and the usual is assumed. Under it, what it rests on. */
function figure(key: FigureName, f: BoardFigure | undefined, layout: string): string {
  const said = isWorked(f)
    ? workedOut(key, f, layout)
    : `<p><span class="quiet">Not worked out: the usual figure is assumed.</span></p>`;
  const rests = texts(f?.rests_on);
  const fold = rests.length
    ? `<details class="board-rests" data-fold="board-rests-${key}"><summary>What this rests on</summary>` +
      `<ul class="plain small">${rests.map((r) => `<li>${escape(sentence(r))}</li>`).join("")}</ul></details>`
    : "";
  return `<div data-figure="${key}"><dt>${NAMES[key]}</dt><dd>${said}${fold}</dd></div>`;
}

/** The cautions, each on a line, under the word and the icon that say what they are. */
function cautions(a: BoardRead): string {
  const stack = a.stackup?.assumed
    ? text(a.stackup.said) || "the board's stack-up was not in the file: the usual one stands in"
    : "";
  const lines = [...new Set([stack, ...texts(a.warnings)].filter(Boolean))];
  if (!lines.length) return "";
  return (
    `<div class="board-cautions"><p class="caution-word">${icon("alert-triangle")}Cautions</p>` +
    `<ul class="plain small">${lines.map((w) => `<li>${escape(sentence(w))}</li>`).join("")}</ul></div>`
  );
}

/** The one press that takes the figures, or word that they are taken with the way out. */
function taking(): string {
  if (boardInUse()) {
    return (
      `<p class="board-use">${icon("check")}<span>These figures are in use for the event, under the boxes ` +
      `above.</span>` +
      `<button type="button" class="link" data-event-layout-drop>Stop using them</button></p>`
    );
  }
  return (
    `<p class="board-use"><button type="button" class="primary" data-board-use${board.since ? " disabled" : ""}>` +
    `Use these figures</button><span class="quiet small">They go under the boxes above: a box that is filled ` +
    `still wins, and a figure not worked out stays assumed.</span></p>`
  );
}

function whatWasRead(a: BoardRead): string {
  const bridges = Array.isArray(a.bridges) ? a.bridges : [];
  const leg = bridges.find((b) => b?.leg === a.taken) ?? bridges[0];
  const found = texts(a.candidates?.switch_nodes);
  const legs = found.length ? found : bridges.map((b) => text(b?.leg)).filter(Boolean);
  const figures = FIGURES.map((key) => figure(key, a.figures?.[key], text(a.layout))).join("");
  return (
    `<h4>Read from the board</h4>${facts(a, leg, legs)}${loop({ ...a, candidates: a.candidates ?? {} }, leg, legs)}` +
    `<dl class="board-figures" aria-label="The loop's figures">${figures}</dl>${cautions(a)}${taking()}`
  );
}

/** The board's place in the fold: word that it is being read, with the time it has taken; why
 *  it was not read; where a board is read, on a page that reads none; and what was read. */
export function boardPanel(): string {
  const name = board.sent?.name ?? "the board";
  const busy = board.since
    ? waiting(`Reading ${name}: finding the loop and working out its figures.`, board.since)
    : "";
  const elsewhere = board.elsewhere
    ? `<div class="asking" role="status">${icon("info-circle")}<div><p>${ELSEWHERE}</p></div></div>`
    : "";
  const refused = board.refused ? refusal(board.refused) : "";
  const read = board.answer ? whatWasRead(board.answer) : "";
  if (!busy && !elsewhere && !refused && !read) return "";
  const stale = board.since && read ? " is-reading" : "";
  return `<section class="board-read${stale}" data-key="board-read">${busy}${elsewhere}${refused}${read}</section>`;
}
