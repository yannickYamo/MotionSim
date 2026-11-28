// The things compared, side by side: the table of their main figures, at the design point or
// over each load's own motion.

import { failureOf, NotWorkedOut, notRefused, Refused } from "../api";
import type { Candidate, Cycle, Position, Result } from "../api";
import { resultOf, series } from "../compare";
import type { Series } from "../compare";
import { degrees, escape, fig, num, percent, sentence, watts } from "../format";
import { icon } from "../icons";
import { app, focused, res } from "../store";
import { addMenu, columnHead, columnsOf } from "./columns";
import { isAction, splitFinding, tip, verdict } from "./html";
import { verdictShort } from "../verdictwords";
import { wordsOf } from "./verdictline";

/** A reason cut to one line of a table cell, at a word: at most 60 characters. */
export function clipped(text: string, most = 60): string {
  if (text.length <= most) return text;
  const cut = text.slice(0, most - 1);
  const at = cut.lastIndexOf(" ");
  return `${(at > most / 2 ? cut.slice(0, at) : cut).replace(/[,;:\s]+$/, "")}…`;
}

/** What a column has at the design point: its result, a refusal, or nothing yet. */
type Got = Result | "refused" | "unworked" | null;

/** A column with no figures: refused by the engine, or with no answer from it at all. */
const failed = (g: Got): g is "refused" | "unworked" => g === "refused" || g === "unworked";
const noFigures = (g: "refused" | "unworked"): string => (g === "refused" ? "cannot run" : "not worked out");
type Link = NonNullable<Candidate["link"]>;

/** One row of the table: its label, a cell for each column, and which cells are marked. */
function line(label: string, cells: string[], best: number[] = [], name = "", word = "lowest"): string {
  // The marked cell says so in words, not by a colour.
  const lowest = ` <span class="best-mark">${word}</span>`;
  const cell = (v: string, k: number) =>
    best.includes(k) ? `<td class="best">${v}${lowest}</td>` : `<td class="">${v}</td>`;
  const tds = cells.map(cell).join("");
  // The last column is the one that adds another: empty in every row below its head.
  return `<tr${name ? ` class="${name}"` : ""}><th scope="row">${label}</th>${tds}<td class="add-col"></td></tr>`;
}

/** The head of the table: the name of each thing compared with its menu, and the way to add one. */
function headOf(list: Series[]): string {
  const names = columnsOf(list).map(columnHead);
  const add = `<th scope="col" class="add-col">${addMenu()}</th>`;
  return `<thead><tr><th scope="col"><span class="sr">Figure</span></th>${names.join("")}${add}</tr></thead>`;
}

/** A row that names the group of rows under it, across every column. */
const group = (list: Series[], title: string): string =>
  `<tr class="group"><th scope="rowgroup" colspan="${list.length + 2}"><span>${title}</span></th></tr>`;

/** A loss, and the share it is of the whole it belongs to. */
const share = (w: number, whole: number): string =>
  `${watts(w)} <span class="quiet">${percent(w / Math.max(whole, 1e-9), 0)}</span>`;

/** A temperature, marked when it is over its limit. */
const hot = (t: number, limit: number): string => `<span class="${t > limit ? "fail" : ""}">${degrees(t)}</span>`;

/** The name of the device the other things are compared on. */
export const onDevice = (): string => escape(focused()?.name ?? "the device under test");

/** The switch position that runs hottest in each column, where the column has a result. */
const hottestOf = (got: Got[]): (Position | null)[] =>
  got.map((g) => (g && !failed(g) && g.positions.length ? g.positions.reduce((a, b) => (b.tj > a.tj ? b : a)) : null));

/** The losses and the temperatures of one device at the hottest switch position. */
function deviceRows(got: Got[]): string[] {
  const at = hottestOf(got);
  const cells = (pick: (p: Position, r: Result, k: number) => string) =>
    got.map((g, k) => (failed(g) ? noFigures(g) : g === null || !at[k] ? "…" : pick(at[k], g, k)));
  const row = (label: string, pick: (p: Position, r: Result, k: number) => string) => line(label, cells(pick));
  const some = (pick: (p: Position) => number) => at.some((p) => p !== null && pick(p) > 0);
  const both = (peak: number, mean: number) => {
    const swing = num(Math.max(peak - mean, 0), 2);
    return `${degrees(peak)} <span class="sub">average ${degrees(mean)}, swing ${swing} K a turn</span>`;
  };
  const diode = some((p) => p.diode_conduction + p.diode_recovery);
  const cooling = app.state.conditions.cooling;
  const sunk = got.some((g) => g && !failed(g) && g.t_sink != null);
  return [
    row("Loss in that device", (p) => watts(p.total)),
    row("Switch, conducting", (p) => share(p.conduction, p.total)),
    row("Switch, turning on", (p) => share(p.turn_on, p.total)),
    row("Switch, turning off", (p) => share(p.turn_off, p.total)),
    some((p) => p.dead_time) ? row("Dead time, through the body diode", (p) => share(p.dead_time, p.total)) : "",
    some((p) => p.recovery) ? row("Body-diode recovery", (p) => share(p.recovery, p.total)) : "",
    diode ? row("Diode, conducting", (p) => share(p.diode_conduction, p.total)) : "",
    diode ? row("Diode, recovery", (p) => share(p.diode_recovery, p.total)) : "",
    row("Switch junction, peak", (p) => both(p.tj_switch, p.tj_switch_mean)),
    diode ? row("Diode junction, peak", (p) => both(p.tj_diode, p.tj_diode_mean)) : "",
    row("Case", (_, r) => degrees(r.t_case)),
    (cooling === "held" || cooling === "heatsink") && sunk
      ? row("Heatsink", (_, r) => (r.t_sink != null ? degrees(r.t_sink) : "n/a"))
      : "",
  ];
}

/** What the switching does to the link and to the motor current, for each column. */
function aroundRows(list: Series[], got: Got[]): string[] {
  const link = list.map((x) => resultOf(x)?.link ?? null);
  const cells = (unit: string, pick: (l: Link) => number | null) =>
    got.map((g, k) => {
      if (failed(g)) return noFigures(g);
      const l = link[k];
      const value = l ? pick(l) : null;
      if (value != null) return `${num(value)} ${unit}`;
      return resultOf(list[k]) ? "n/a" : "…";
    });
  const row = (label: string, unit: string, pick: (l: Link) => number | null) => line(label, cells(unit, pick));
  return [
    row("DC-link capacitor current", "A rms", (l) => l.capacitor_rms),
    row("Motor current ripple", "A peak to peak", (l) => l.ripple_pp),
  ];
}

/** Whether the rows of one device and of the stage around it stand open: one press away, so
 *  that the table's face is the totals and the verdict (kept while the table is drawn again). */
export const moreRows = { open: false };

/** Beside the totals: every loss and every temperature of the switch position that runs
 *  hottest, one device of it, and what the switching does to the link and the motor current.
 *  A row is left out when it is nothing in every column (a diode the part does not have).
 *  Behind one press, in the same table so the columns stay aligned. */
function chipRows(list: Series[], got: Got[]): string {
  const open = moreRows.open;
  const press =
    `<tr class="group more-rows-row"><th scope="rowgroup" colspan="${list.length + 2}">` +
    `<button type="button" class="link" data-more-rows aria-expanded="${open}" aria-controls="more-rows">` +
    `${open ? "Fewer figures" : "Every loss and temperature of one device"}</button></th></tr>`;
  const rows = [
    group(list, "One device at the hottest switch position"),
    ...deviceRows(got),
    group(list, "What the switching does around the stage"),
    ...aroundRows(list, got),
  ];
  return `${press}</tbody><tbody id="more-rows"${open ? "" : " hidden"}>${rows.filter(Boolean).join("\n")}`;
}

/** The columns whose loss is marked as the lowest at the design point. */
function lowestLoss(list: Series[], got: Got[]): number[] {
  // A part that does not pass is not the one with the lowest loss, whatever it would lose.
  const losses = got.map((g, k) => {
    const passes = !["fail", "undecided"].includes(resultOf(list[k])?.level ?? "");
    return g && !failed(g) && passes ? g.loss : Infinity;
  });
  // Losses closer than the engine can tell apart are marked together, not one as the winner.
  const least = Math.min(...losses);
  if (!Number.isFinite(least)) return [];
  return losses.flatMap((v, k) => (v <= least * (1 + (res.proposal?.level ?? 0.05)) ? [k] : []));
}

/** Under the table at the design point: what the columns stand on, and what the mark means. */
function footNote(list: Series[], level: number[]): string {
  const compare = app.state.compare;
  const foot =
    compare === "devices"
      ? "At your design point."
      : compare === "motors"
        ? `Each motor at its own design point, on ${onDevice()}.`
        : `At your design point, on ${onDevice()}, with one setting changed.`;
  const within = percent(res.proposal?.level ?? 0.05, 0);
  const marked =
    level.length > 1
      ? `These losses are within ${within} of each other, closer than the model tells apart: ` +
        "they are marked together."
      : "The lowest loss is marked.";
  const slide = list.length > 2 ? " Slide the table sideways if a column is cut." : "";
  return `<p class="quiet small">${foot} ${marked}${slide}</p>`;
}

/** A note for each motor or setting the engine refused, with its reason. */
function refusedNotes(list: Series[]): string {
  const notes = list.flatMap((x) => {
    const r = x.over ? res.variants.get(x.key) : null;
    // No answer says nothing of the motor or the setting: it is not a refusal.
    if (!(r instanceof Refused) || r instanceof NotWorkedOut) return [];
    const said = `${escape(x.name)} cannot run: ${escape(r.reason)}.`;
    return [`<p class="fact warn">${icon("alert-triangle")}<span>${said}</span></p>`];
  });
  return notes.join("");
}

/** How far a temperature is from its limit, said beside it. */
function room(m: number | null): string {
  if (m == null) return "";
  const said = m < 0 ? `${num(-m, 2)} K over the limit` : `${num(m, 2)} K to the limit`;
  return ` <span class="room ${m < 0 ? "fail" : ""}">${said}</span>`;
}

/** The best of a row among the columns that pass, marked in words; ties within `near` are
 *  marked together, and where every column is as good none is marked: a mark on each says nothing. */
function bestAmong(
  list: Series[],
  got: Got[],
  pick: (c: Candidate) => number | null | undefined,
  higher: boolean,
  near: number,
): number[] {
  const v = list.map((x, k) => {
    const c = resultOf(x);
    const passes = c && !failed(got[k]) && got[k] !== null && !["fail", "undecided"].includes(c.level);
    const n = passes ? pick(c) : null;
    return n == null || !Number.isFinite(n) ? null : higher ? -n : n;
  });
  const ok = v.filter((n): n is number => n !== null);
  if (ok.length < 2) return [];
  const top = Math.min(...ok);
  const best = v.flatMap((n, k) => (n !== null && n - top <= near ? [k] : []));
  return best.length === ok.length ? [] : best;
}

/** The rows of totals at the design point: the verdict, the losses, the temperatures. */
function totalRows(list: Series[], got: Got[], level: number[]): string[] {
  const cell = (pick: (r: Result, k: number) => string) =>
    got.map((g, k) => (g === null ? "…" : failed(g) ? noFigures(g) : pick(g, k)));
  // What a candidate carries beside its result: its verdict, its margins, its data.
  const whole = (pick: (c: Candidate) => string) =>
    got.map((g, k) => {
      const c = resultOf(list[k]);
      return failed(g) ? noFigures(g) : g === null || !c ? "…" : pick(c);
    });
  const lost = cell((r) => watts(r.loss));
  const efficiency = list.map((x, k) => {
    const e = resultOf(x)?.efficiency;
    const g = got[k];
    return failed(g) ? noFigures(g) : e != null ? percent(e) : resultOf(x) ? "n/a" : "…";
  });
  const still = (c: Candidate) =>
    c.stall_tj == null ? "n/a" : `${hot(c.stall_tj, c.result!.tj_max)}${room(c.stall_margin)}`;
  const total = (label: string, pick: (r: Result, k: number) => string) => line(label, cell(pick));
  const about = (label: string, pick: (c: Candidate) => string, best: number[] = [], word = "lowest") =>
    line(label, whole(pick), best, "", word);
  const bestBy = (pick: (c: Candidate) => number | null | undefined, higher = false, near = 0.1) =>
    bestAmong(list, got, pick, higher, near);
  // A verdict short of a clean pass carries its first reason as one short line, the whole of
  // it one hover or focus away, so a caution is never left unexplained nor a cell a paragraph.
  const because = (c: Candidate) => {
    const first = c.checks.find((x) => x.level === "fail") ?? c.checks.find((x) => x.level !== "ok" && isAction(x));
    if (!first) return "";
    const whole = sentence(first.message);
    return `<span class="basis">${tip(clipped(splitFinding(whole)[0]), `${whole}.`)}</span>`;
  };
  const basis = (c: Candidate) => `<span class="basis">${escape(sentence(c.switching?.text ?? "not given"))}</span>`;
  return [
    // In the colour of its state, with its icon, as the verdict is everywhere on the page.
    about("Verdict", (c) => `${verdict("", verdictShort(wordsOf(c)))}${because(c)}`),
    line("Power-stage loss", lost, level, "loss"),
    total("Conduction", (r) => share(r.conduction, r.loss)),
    total("Switching", (r) => share(r.switching, r.loss)),
    about(
      // What the margin stands on, one hover or focus away.
      tip("Hottest junction", "The margin is counted from the top of the temperature range where values are assumed."),
      (c) => `${hot(c.result!.tj_peak, c.result!.tj_max)}${room(c.margin)}`,
      bestBy((c) => c.margin, true, 0.5),
      "most margin",
    ),
    about(
      "Held at standstill",
      still,
      bestBy((c) => c.stall_tj, false, 0.5),
    ),
    line(
      "DC-to-shaft efficiency",
      efficiency,
      bestBy((c) => (c.efficiency == null ? null : c.efficiency * 100), true, 0.05),
      "",
      "highest",
    ),
    app.state.compare === "devices" ? about("Switching data", basis) : "",
  ];
}

/** The table at the design point: devices, motors, or one setting at several values. */
function designTable(list: Series[]): string {
  const got: Got[] = list.map(
    (x) => failureOf(x.over ? res.variants.get(x.key) : undefined) ?? resultOf(x)?.result ?? null,
  );
  const level = lowestLoss(list, got);
  const lines = [
    `<table class="data wide" style="--cols:${list.length}">${headOf(list)}<tbody>`,
    ...totalRows(list, got, level),
    chipRows(list, got),
    `</tbody></table>${refusedNotes(list)}${footNote(list, level)}`,
  ];
  return lines.join("\n");
}

/** The table over each load's own motion, on the one device. */
function motionTable(list: Series[]): string {
  const got = list.map((x) => res.cycles.get(x.key));
  const cell = (pick: (c: Cycle) => string) =>
    got.map((g) => {
      const failure = failureOf(g);
      return g === undefined ? "…" : failure ? noFigures(failure) : pick(g as Cycle);
    });
  const means = got.map((g) => notRefused(g)?.summary.mean_loss ?? Infinity);
  const least = means.some(Number.isFinite) ? means.indexOf(Math.min(...means)) : -1;
  const row = (label: string, pick: (c: Cycle) => string) => line(label, cell(pick));
  const mean = cell((c) => watts(c.summary.mean_loss));
  const foot = `Over each load's own motion, on ${onDevice()}. The lowest mean loss is marked.`;
  const lines = [
    `<table class="data wide" style="--cols:${list.length}">${headOf(list)}<tbody>`,
    line("Mean loss", mean, [least], "loss"),
    row("Hottest junction reached", (c) => hot(c.summary.peak!, c.summary.tj_max!)),
    row("Peak motor current", (c) => `${num(Math.max(...c.i_peak.map((v) => v ?? 0)))} A`),
    row("Energy lost", (c) => `${fig(c.summary.loss_energy)} J`),
    row("Returned by braking", (c) => `${fig(c.summary.returned ?? 0)} J`),
    `</tbody></table><p class="quiet small">${foot}</p>`,
  ];
  return lines.join("\n");
}

/** The main figures, one column for each thing compared. Devices are compared at the design
 *  point; loads are compared over their motion, since the design point is the same for all. */
export function compareTable(): string {
  const list = series();
  return app.state.compare !== "loads" ? designTable(list) : motionTable(list);
}
