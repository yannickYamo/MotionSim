// Which to choose, said in one line over the comparison, and the recommendation on the verdict
// when several parts are on the page: the first part that passes in the engine's own ranking,
// and what it wins on against the next, in figures. A part that does not pass is never chosen,
// and a figure it loses on is said too.

import { notRefused } from "../api";
import type { Candidate } from "../api";
import { resultOf, series } from "../compare";
import type { Series } from "../compare";
import { escape, num, percent, sentence, watts } from "../format";
import { icon } from "../icons";
import { app, res, ui, underTest, verdictOf } from "../store";
import { leadButton } from "./html";

const passes = (c: Candidate | null): boolean =>
  !!c?.result && c.level !== "fail" && c.level !== "undecided" && verdictOf(c).level !== "fail";

/** The differences that tell two passing parts apart: what the first wins on, what it gives up. */
function differences(top: Candidate, next: Candidate): { wins: string[]; gives: string[] } {
  const r = top.result!;
  const o = next.result!;
  const wins: string[] = [];
  const gives: string[] = [];
  const say = (d: number, least: number, more: string, less: string, words: (x: number) => string) => {
    if (Math.abs(d) >= least) (d > 0 ? wins : gives).push(`${words(Math.abs(d))} ${d > 0 ? more : less}`);
  };
  say(o.loss - r.loss, 0.01, "less loss", "more loss", (x) => watts(x));
  say(r.tj_max - r.tj_peak - (o.tj_max - o.tj_peak), 1, "more margin", "less margin", (x) => `${num(x, 2)} K`);
  if (top.stall_tj != null && next.stall_tj != null)
    say(next.stall_tj - top.stall_tj, 2, "cooler held still", "hotter held still", (x) => `${num(x, 2)} K`);
  return { wins, gives };
}

/** What the chosen wins on against the next, and what it gives up, in figures. */
function because(top: Candidate, next: Candidate | null, nextName: string): string {
  if (!next) return "the only one that passes";
  const name = escape(nextName);
  if (!passes(next)) {
    const why = next.problem ?? next.checks.find((x) => x.level === "fail")?.topic ?? "does not pass";
    return `${name} ${next.result ? "does not pass" : "cannot run"} (${escape(why)})`;
  }
  const { wins, gives } = differences(top, next);
  if (!wins.length && !gives.length) return `level with ${name} within what the model tells apart`;
  const won = wins.length ? `${wins.join(", ")} than ${name}` : `ranked first over ${name}`;
  return gives.length ? `${won}; ${gives.join(", ")}` : won;
}

/** The columns as candidates in the order to choose them: for devices the engine's ranking,
 *  for the rest the passing ones by loss. */
function ranked(list: Series[]): { c: Candidate | null; name: string; id: string | null }[] {
  if (app.state.compare === "devices") {
    const order = res.proposal?.candidates.map((c) => c.id) ?? [];
    return list
      .map((x) => ({ c: resultOf(x), name: x.name, id: x.candidate?.id ?? null }))
      .sort((a, b) => order.indexOf(a.c?.id ?? "") - order.indexOf(b.c?.id ?? ""));
  }
  return list
    .map((x) => ({ c: resultOf(x), name: x.name, id: null }))
    .sort(
      (a, b) =>
        (passes(b.c) ? 1 : 0) - (passes(a.c) ? 1 : 0) || (a.c?.result?.loss ?? 1e9) - (b.c?.result?.loss ?? 1e9),
    );
}

/** "Choose X: 0.8 W less loss, 12 K more margin than Y." over the comparison, once every
 *  column has its answer. */
export function choiceLine(): string {
  const list = series();
  // Among devices the one recommendation is the card on the Verdict tab: said once.
  if (list.length < 2 || app.state.compare === "loads" || app.state.compare === "devices") return "";
  const order = ranked(list);
  if (order.some((x) => x.c === null)) return "";
  const first = order.find((x) => passes(x.c));
  if (!first) {
    return (
      `<p class="choice-line is-none">${icon("alert-triangle")}` +
      `<span><b>None of these passes.</b> Read why in each column.</span></p>`
    );
  }
  const next = order.find((x) => x !== first) ?? null;
  const verb = "Best";
  const said = because(first.c!, next?.c ?? null, next?.name ?? "");
  const words = `<p><b>${verb} ${escape(first.name)}:</b> ${said}.</p>`;
  return `<div class="choice-line">${icon("thumb-up")}${words}</div>`;
}

/** On the verdict, with several parts on the page: the press that recommends one, and its card. */
export function recommendBlock(): string {
  const list = res.proposal?.candidates ?? [];
  if (list.length < 2) return "";
  if (!ui.recommend) {
    return (
      `<p class="recommend-ask"><button type="button" class="ghost" data-recommend>${icon("thumb-up")}` +
      `Recommend for me</button></p>`
    );
  }
  const first = list.find((c) => passes(c));
  const shut =
    `<button type="button" class="icon-button" data-recommend aria-label="Close the recommendation">` +
    `${icon("x")}</button>`;
  if (!first) {
    const reason = (c: Candidate) =>
      sentence(c.problem ?? c.checks.find((x) => x.level === "fail")?.message ?? "does not pass");
    const why = list.map((c) => `<li><b>${escape(c.name)}</b> ${escape(reason(c))}.</li>`);
    return (
      `<section class="recommend is-none" aria-label="Recommendation"><div class="recommend-head">` +
      `<h3>None of these parts passes on this design</h3>${shut}</div>` +
      `<ul class="plain small">${why.join("")}</ul></section>`
    );
  }
  const others = list.filter((c) => c !== first);
  const r = first.result!;
  const cap = notRefused(res.capable);
  const share = first.id === underTest() && cap?.design.share ? cap.design.share : null;
  const room =
    share && share > 0 && share <= 1
      ? `<li>Holds ${percent(1 / share - 1, 0)} more torque at this speed before a limit.</li>`
      : "";
  const lines =
    `<li>${watts(r.loss)} loss, Tj ${num(r.tj_peak, 3)} °C, ` +
    `${num(r.tj_max - r.tj_peak, 2)} K under its rating.</li>${room}` +
    others.map((o) => `<li>Over ${escape(o.name)}: ${because(first, o, o.name)}.</li>`).join("");
  const make = first.id !== underTest() ? leadButton(first.id, first.name) : "";
  return (
    `<section class="recommend" aria-label="Recommendation"><div class="recommend-head">` +
    `<h3>${icon("thumb-up")}Recommended: ${escape(first.name)}</h3>${shut}</div>` +
    `<ul class="plain small">${lines}</ul>${make}</section>`
  );
}
