import type { Candidate, Check, GateUsed } from "../../api";
import { degrees, eng, escape, sentence, sig, watts } from "../../format";
import { icon } from "../../icons";
import { SUPPLY } from "../../steps";
import { app, focused, res, underTest, verdictOf } from "../../store";
import { checkList, leadButton, levelClass, verdict } from "../html";
import { notReady } from "./ready";

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

/** The checks that need reading stay in the open; those that passed are counted and folded. */
function checksBlock(c: Candidate): string {
  if (!c.checks.length) return "";
  // A check that fails is not one to read and weigh: it is said under its own heading.
  const failed = c.checks.filter((x) => x.level === "fail");
  const raised = c.checks.filter((x) => x.level !== "ok" && x.level !== "fail");
  const passed = c.checks.filter((x) => x.level === "ok");
  const rest = passedFold(c, passed);
  const mount = mountingButton(c, raised);
  const fails = failed.length ? `<h4>Does not pass</h4>${checkList(failed)}` : "";
  return `${fails}${raised.length ? `<h4>To read</h4>${checkList(raised)}${mount}` : ""}${rest}`;
}

/** The gate drive in a few words: the resistors and the voltage, or where they came from. */
function gateHead(g: GateUsed): string {
  const ohm = (v: number | null) => (v === null ? "" : `${sig(v, 2)} Ω`);
  if (g.kind === "built in") return "Inside the module";
  if (g.kind === "datasheet") {
    if (!g.rg_on) return "As the datasheet measured with";
    const both = g.rg_off && g.rg_off !== g.rg_on;
    return `${both ? `${ohm(g.rg_on)} on, ${ohm(g.rg_off)} off` : ohm(g.rg_on)}, as the datasheet measured with`;
  }
  return `${ohm(g.rg_on)} on, ${ohm(g.rg_off)} off, at ${sig(g.v_drive ?? 0, 2)} V drive`;
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
  return `<summary data-focus="${escape(c.id)}">${rank}${name}${cells}${verdict(verdictOf(c).level)}</summary>`;
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
  // A part compared on a design started from another, which that design rules out, can
  // have the design started from it instead.
  const out = c.id !== underTest() && (!c.result || c.level === "fail");
  const restart = out
    ? `<p class="quiet small">The design was started from another part and is not moved by this one.</p>` +
      `<p>${leadButton(c.id, c.name)}</p>`
    : "";
  const parts = [problem, restart, motionLine(c), checksBlock(c), gateBlock(c), needsFold(c)];
  const body = `<div class="cand-body">${parts.join("")}</div>`;
  const open = c.id === focused()?.id ? " open" : "";
  const level = levelClass(verdictOf(c).level);
  // A part alone has no rank among others, and is not set off from them as a card.
  const alone = all.length < 2;
  const cls = `candidate ${level}${alone ? " alone" : ""}`;
  return `<details class="${cls}"${open}>${candidateSummary(c, k, alone)}\n${body}</details>`;
}

/** What following the motion added to the verdict at the design point: the reason it is
 *  graver, with the way to the motion; or that the motion is still being followed. */
function motionLine(c: Candidate): string {
  const v = verdictOf(c);
  const see = `<button type="button" class="link" data-tab="motion">See the motion</button>`;
  // The line stands from the first answer to the last, so the page does not move when the
  // motion has been followed: its words change, its place does not.
  if (v.motion === "pending")
    return `<p class="quiet small motion-note">The motion is still being followed: the verdict may change.</p>`;
  if (!v.why && v.motion === "followed")
    return `<p class="quiet small motion-note">It holds over the whole motion too.</p>`;
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
  '<span class="num" title="The hottest junction holding the same torque at standstill">Standstill</span>' +
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
  const more = single
    ? ""
    : proposal.explain
        .slice(1)
        .map((l) => `<p>${escape(l)}</p>`)
        .join("");
  const lead = more || order ? `<div class="explain">${more}${order}</div>\n` : "";
  const still =
    '<p class="quiet small">Standstill: the hottest junction holding the same torque with the motor stopped, ' +
    "where one switch carries the current without rest.</p>";
  return `${lead}${CAND_HEAD}${rows}${still}${adviceBlock()}`;
}
