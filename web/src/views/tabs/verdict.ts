import { frontEndLine } from "../frontend";
import { Refused } from "../../api";
import { deltaTag } from "../../pin";
import { recommendBlock } from "../choice";
import type { Candidate, Check, GateUsed } from "../../api";
import { degrees, eng, escape, num, percent, ratio, sentence, watts } from "../../format";
import { casesSaid, worstJunction } from "../junction";
import { proposalNow } from "../../engine/proposed";
import { icon } from "../../icons";
import { SUPPLY } from "../../steps";
import { app, focused, res, underTest, verdictOf } from "../../store";
import { checkList, findingList, isAction, levelClass, readout, verdict } from "../html";
import { verdictShort } from "../../verdictwords";
import { wordsOf } from "../verdictline";
import { notReady } from "./ready";
import { limitedBy, resultsLoadLine } from "../proposed";

/** The attribute that keeps a fold open through a redraw, where the user opened it. */

/** The checks that passed, counted on the fold's face and listed inside it. */
function passedFold(c: Candidate, passed: Check[]): string {
  if (!passed.length) return "";
  const id = `passed-${c.id}`;
  // Under a verdict the motion made graver, these are the design point's own checks.
  const where = verdictOf(c).why ? " at the design point" : "";
  const count = `${passed.length} ${passed.length === 1 ? "check passes" : "checks pass"}${where}`;
  const topics = `<span class="quiet">${escape(passed.map((x) => x.topic).join(", "))}</span>`;
  const summary = `<summary>${icon("circle-check")}${count}${topics}</summary>`;
  return `<details class="more" data-fold="${escape(id)}">${summary}${checkList(passed)}${noTrip(c)}</details>`;
}

/** Why a part has one check fewer with some motors: what a trip at speed does to the link is
 *  asked only of a motor with magnets on its rotor, which turns into a generator. */
function noTrip(c: Candidate): string {
  if (!c.result || c.checks.some((x) => x.topic === "trip")) return "";
  const kind = app.state.kind;
  if (kind === "pmsm" || kind === "bldc") return "";
  const why =
    kind === "induction"
      ? "with no magnets on its rotor, this motor does not charge the link when the drive stops switching"
      : "this kind of motor does not charge the link through the diodes when the drive stops switching";
  return `<p class="quiet small">No check of a trip at speed: ${why}.</p>`;
}

/** The one press to the case-to-heatsink resistance, where that layer leaves the answer open. */
function mountingButton(c: Candidate, raised: Check[]): string {
  // Where the layer under the package is what leaves the answer open, the way to it is one press.
  const cond = app.state.conditions;
  const asks =
    c.result?.range_lead === "mounting" &&
    raised.some((x) => x.level === "undecided" && x.message.includes("case-to-heatsink resistance")) &&
    (cond.cooling === "held" || cond.cooling === "heatsink") &&
    String(cond.rth_case_sink ?? "").trim() === "";
  if (!asks) return "";
  const label = `${icon("adjustments")}Give the case-to-heatsink resistance`;
  return `<p><button type="button" class="ghost" data-step="${SUPPLY}" data-open-fold="mounting">${label}</button></p>`;
}

/** A part's findings, in the order they are acted on: what does not pass, the design actions
 *  (a change to the design, or a figure to give), then the notes on the data the result rests
 *  on. One line each; why and what to change open in place. The checks that pass are counted
 *  and folded. */
function checksBlock(c: Candidate): string {
  if (!c.checks.length) return "";
  const failed = c.checks.filter((x) => x.level === "fail");
  const actions = c.checks.filter((x) => x.level !== "fail" && isAction(x));
  const notes = c.checks.filter((x) => x.level !== "ok" && !isAction(x));
  const passed = c.checks.filter((x) => x.level === "ok");
  const mount = mountingButton(c, actions);
  const group = (title: string, list: Check[], id: string, extra = "") =>
    list.length ? `<section class="finding-group"><h3>${title}</h3>${findingList(list, id)}${extra}</section>` : "";
  return (
    group("Does not pass", failed, `fails-${c.id}`) +
    group(actions.length === 1 ? "Design action" : "Design actions", actions, `acts-${c.id}`, mount) +
    group(notes.length === 1 ? "Note" : "Notes", notes, `notes-${c.id}`) +
    passedFold(c, passed)
  );
}

/** The gate drive in a few words: the resistors and the voltage, or where they came from. */
function gateHead(g: GateUsed): string {
  const ohm = (v: number | null) => (v === null ? "" : `${num(v, 2)} Ω`);
  if (g.kind === "built in") return "Inside the module";
  if (g.kind === "datasheet") {
    if (!g.rg_on) return "As the datasheet measured with";
    const both = g.rg_off && g.rg_off !== g.rg_on;
    return `${both ? `${ohm(g.rg_on)} on, ${ohm(g.rg_off)} off` : ohm(g.rg_on)}, as the datasheet measured with`;
  }
  return `${ohm(g.rg_on)} on, ${ohm(g.rg_off)} off, at ${num(g.v_drive ?? 0, 2)} V drive`;
}

/** Whose choice the gate drive was, said after its headline on the fold's face. */
const gateOwner = (g: GateUsed): string =>
  g.kind === "chosen" ? ", chosen for you" : g.kind === "given" ? ", yours" : "";

/** The same, as a tag beside the value inside the fold. */
const gateTag = (g: GateUsed): string =>
  g.kind === "chosen"
    ? '<span class="tag">chosen for lowest loss</span>'
    : g.kind === "given"
      ? '<span class="tag">yours</span>'
      : "";

/** The gate drive a result was worked out with: the headline value, then the reasons. */
function gateBlock(c: Candidate): string {
  const g = c.gate;
  if (!g || !c.result) return "";
  const head = gateHead(g);
  const id = `gate-${c.id}`;
  const dead = g.t_dead ? `, ${eng(g.t_dead, "s", 2)} dead time` : "";
  const face = `<span class="quiet">${head}${gateOwner(g)}${dead}</span>`;
  const summary = `<summary>${icon("adjustments")}Gate drive${face}</summary>`;
  const used = `<p class="gate-used"><b>${head}</b> ${gateTag(g)}</p>`;
  const lines = `<ul class="plain small">${g.lines.map((l) => `<li>${escape(sentence(l))}</li>`).join("")}</ul>`;
  const own =
    g.kind === "chosen"
      ? '<p class="quiet small">To use your own, give them under Supply and point, Gate drive.</p>'
      : "";
  return `<details class="more" data-fold="${escape(id)}">${summary}${used}${lines}${own}</details>`;
}

function adviceBlock(): string {
  const advice = res.advice;
  if (!advice) return "";
  const face = '<span class="quiet">what to look for</span>';
  const summary = `<summary>${icon("list-details")}If you were choosing from scratch${face}</summary>`;
  const about =
    '<p class="quiet">Rules of thumb for the kind of part this motor and supply call for. ' +
    "Use them to find other datasheets to test.</p>";
  const lines = `<ul class="plain small">${advice.lines.map((l) => `<li>${escape(l)}</li>`).join("")}</ul>`;
  return `<details class="more">${summary}${about}${lines}</details>`;
}

/** One device's line in the table: its rank, its name, the three figures and the verdict. */
function candidateSummary(c: Candidate, k: number, alone: boolean): string {
  const r = c.result;
  const cell = (tone: string, label: string, value: string) =>
    `<span class="num ${tone}"><span class="cell-label">${label} </span>${value}</span>`;
  const name = `<span class="cand-name">${escape(c.name)}<span class="quiet">${escape(c.technology)}</span></span>`;
  const cells =
    cell("loss", "Loss", r ? watts(r.loss) : "–") +
    cell("junction", "Junction", r ? degrees(r.tj_peak) : "–") +
    cell("still", "Standstill", c.stall_tj != null ? degrees(c.stall_tj) : "–");
  // A rank says how a part stands among others: with one part there is none to give.
  const rank = alone ? '<span class="rank is-alone" aria-hidden="true"></span>' : `<span class="rank">${k + 1}</span>`;
  const said = verdict("", verdictShort(wordsOf(c)));
  return `<summary data-focus="${escape(c.id)}">${rank}${name}${cells}${said}</summary>`;
}

/** What has to be built around the device, folded under its first line. */
function needsFold(c: Candidate): string {
  if (!c.needs.length) return "";
  const face = `<span class="quiet">${escape(c.needs[0] ?? "")}</span>`;
  const summary = `<summary>${icon("adjustments")}What it needs around it${face}</summary>`;
  const lines = `<ul class="plain">${c.needs.map((n) => `<li>${escape(sentence(n))}</li>`).join("")}</ul>`;
  const open = "";
  return `<details class="more" data-fold="needs-${escape(c.id)}"${open}>${summary}${lines}</details>`;
}

/** One device of the verdict: its line, and under it the problem, the checks, the gate and the needs. */
function candidateRow(c: Candidate, k: number, all: Candidate[]): string {
  const problem = c.problem
    ? `<p class="fix"><b>${escape(sentence(c.problem))}.</b> ${escape(sentence(c.fix))}${c.fix ? "." : ""}</p>`
    : "";
  // A part compared on a design started from another, which that design rules out: said so,
  // and never offered as a part to start the design from (a ruled-out part leads nowhere).
  const out = c.id !== underTest() && (!c.result || c.level === "fail");
  const restart = out
    ? `<p class="quiet small">The design was started from another part and is not moved by this one.</p>`
    : "";
  const parts = [problem, restart, motionLine(c), checksBlock(c), gateBlock(c), needsFold(c)];
  const body = `<div class="cand-body">${parts.join("")}</div>`;
  const open = c.id === focused()?.id ? " open" : "";
  const level = levelClass(verdictOf(c).level);
  // A part alone has no rank among others: its three figures lead, and its findings follow,
  // with nothing to open first.
  if (all.length < 2) return `<div class="candidate alone ${level}">${keyFigures(c)}\n${body}</div>`;
  return `<details class="candidate ${level}"${open}>${candidateSummary(c, k, false)}\n${body}</details>`;
}

/** The first answer's figures come in once, after the headline; never again on a redraw. */
let figuresShown = false;

/** The third figure: how far the design is from its limit, as the load the part carries
 *  against the usual one, limited by what it names; where no such load is asked for (the
 *  user's own, a mission), the efficiency. */
function marginCell(c: Candidate): { html: string; efficiency: boolean } {
  const html = marginOf(c);
  return { html, efficiency: html.includes(">Efficiency<") };
}

function marginOf(c: Candidate): string {
  const { state } = app;
  const own = state.loadTouched || !!state.mission;
  const now = own ? null : proposalNow();
  if (now) {
    const p = now.answer instanceof Refused ? null : now.answer;
    if (!now.answer)
      return readout(
        "Load margin",
        "…",
        "finding the load it carries",
        "",
        "How many times the usual load this part carries.",
      );
    if (!p) return readout("Load margin", "under 1×", "no load of this kind passes", "fail");
    const limit = p.open || p.binding.limit === "none" ? "nothing limits it within 16×" : `limit: ${p.binding.words}`;
    const why = `This part carries up to ${ratio(p.scale)}× the usual ${p.label.toLowerCase()} load: ${limitedBy(p)}.`;
    return readout("Load margin", `${ratio(p.scale)}×`, limit, p.scale < 1.2 ? "caution" : "", why);
  }
  return readout(
    "Efficiency",
    c.efficiency != null ? percent(c.efficiency) : "–",
    "motor windings included",
    "",
    "Shaft power over the power drawn from the supply, at the design point.",
    deltaTag("efficiency", c.efficiency),
  );
}

/** A part's three figures: what it loses, the hottest its junction gets in any case against
 *  its rating (with where), and how far the design is from its limit. The line that explains
 *  each is on its name; each figure is on the screen once. */
function keyFigures(c: Candidate): string {
  const r = c.result;
  const w = worstJunction(c);
  if (!r || !w) return "";
  const enters = figuresShown || verdictOf(c).motion === "pending" ? "" : " enters";
  figuresShown ||= !enters;
  const left = Math.round(w.rating) - Math.round(w.value);
  const tone = w.value > w.rating ? "fail" : left < 25 ? "caution" : "";
  const third = marginCell(c);
  const efficiency =
    c.efficiency != null && !third.efficiency ? ` Efficiency ${percent(c.efficiency)}, motor windings included.` : "";
  const cells =
    readout(
      "Loss",
      watts(r.loss),
      `${watts(r.conduction)} conducting, ${watts(r.switching)} switching`,
      "",
      `The power stage's loss at the design point, every switch.${efficiency}`,
      deltaTag("loss", r.loss),
    ) +
    readout(
      "Tj max",
      degrees(w.value),
      `${left >= 0 ? `${left} K under` : `${-left} K over`} ${degrees(w.rating)} · ${w.where}` +
        (w.settled ? "" : " · motion …"),
      tone,
      casesSaid(w),
      w.settled ? deltaTag("tjmax", w.value) : "",
    ) +
    third.html;
  return `<dl class="key-figures${enters}">${cells}</dl>`;
}

/** What following the motion added to the verdict at the design point: the reason it is
 *  graver, with the way to the motion; or that the motion is still being followed. */
function motionLine(c: Candidate): string {
  const v = verdictOf(c);
  const see = `<button type="button" class="link" data-tab="motion">See the motion</button>`;
  // The line stands from the first answer to the last, so the page does not move when the
  // motion has been followed: its words change, its place does not.
  // Where nothing is to be acted on, the line under the headline says it already.
  const acts = c.checks.some((x) => x.level === "fail" || isAction(x));
  // While the motion is followed the line holds its place, so the findings under it do not move
  // when it is done.
  if (v.motion === "pending") return acts ? `<p class="quiet small motion-note">Following the motion…</p>` : "";
  if (!v.why && v.motion === "followed")
    return acts ? `<p class="quiet small motion-note">Holds over the whole motion.</p>` : "";
  if (v.motion === "unworked")
    return (
      `<p class="quiet small motion-note">The motion was not worked out, as no answer came: ` +
      `this verdict is of the design point alone.</p>`
    );
  if (!v.why) return "";
  const lead = v.motion === "refused" ? "The motion cannot be followed." : "Over the motion.";
  return `<p class="fix"><b>${lead}</b> ${escape(sentence(v.why))}. ${see}</p>`;
}

/** The headings over the columns of the table of devices. */
const CAND_HEAD =
  '<div class="cand-head" aria-hidden="true"><span></span><span>Device</span><span class="num">Loss</span>' +
  '<span class="num">Junction</span>' +
  '<span class="num" title="Standstill: the hottest junction holding the same torque with the motor stopped, ' +
  'where one switch carries the current without rest">Standstill</span>' +
  "<span>Verdict</span></div>";

export function proposalTab(): string {
  if (!app.state.devices.length) {
    const said = "No device is chosen. Go back to step 1 and tick the part you want to test.";
    return `<p class="empty">${icon("cpu")}${said}</p>`;
  }
  const proposal = res.proposal;
  if (!proposal) return notReady();
  const rows = proposal.candidates.map(candidateRow).join("");
  const single = proposal.candidates.length === 1;
  // The order is by loss among the parts that pass, and a caution does not move a part down it.
  // The verdict itself is the line above the tabs; what more the engine said of it is here.
  const order = single
    ? ""
    : '<p class="quiet small">In order of modelled loss among the parts that pass. ' +
      "A caution does not change the order: read it before choosing.</p>";
  const more = single ? "" : proposal.explain.map((l) => `<p>${escape(l)}</p>`).join("");
  const lead = more || order ? `<div class="explain">${more}${order}</div>\n` : "";
  // What the Standstill column is, said on its head (a part alone says it on its figure).
  const still = "";
  // The load the verdict is on, set against the load the part can carry.
  const cycle = res.cycle && !(res.cycle instanceof Refused) ? res.cycle : null;
  // A part alone says the load it carries as its third key figure: the line would say it again.
  const own = app.state.loadTouched || !!app.state.mission;
  const load = single && !own ? "" : resultsLoadLine(cycle);
  const head = single ? "" : CAND_HEAD;
  const loadBlock = load ? `<div class="results-load">${load}</div>` : "";
  return `${lead}${recommendBlock()}${loadBlock}${head}${rows}${still}${frontEndLine()}${adviceBlock()}`;
}
