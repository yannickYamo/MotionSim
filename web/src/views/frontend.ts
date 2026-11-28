// The front end of a drive fed from the mains, as the page shows it: one line on the supply
// step with the stage recommended and why, the others a press away; and in the results, its
// line under the verdict and its sheet among the parts to build.

import { frontEndNow } from "../actions/frontend";
import { Refused } from "../api";
import type { FrontEndAnswer, FrontEndChoice, FrontEndResult } from "../api";
import { eng, escape, num, sentence, watts } from "../format";
import { icon } from "../icons";
import type { FrontEndDrawn } from "../schematic/frontend";
import { loadSwings } from "../state";
import { app, underTest } from "../store";
import { field, recRow, select, waiting } from "./html";

/** A switching frequency as it is typed: 65, 16, 62.5. */
const khz = (hz: number): string => String(Number((hz / 1000).toPrecision(3)));

const percent = (share: number): string => `${(100 * share).toFixed(share > 0.9995 ? 2 : 1)} %`;

/** What one stage costs on this design, in a line: its loss, or why it cannot be. */
function costOf(c: FrontEndChoice): string {
  if (c.refused) return `Cannot be: ${sentence(c.refused)}.`;
  const limit = c.within_limit === false ? ", over the harmonic limits" : "";
  const fails = c.level === "fail" ? ", does not pass with this part" : "";
  return `${watts(c.loss ?? 0)} lost, ${percent(c.efficiency ?? 1)} efficient${limit}${fails}`;
}

/** One stage in the list to choose from. */
function choiceRow(c: FrontEndChoice, a: FrontEndAnswer): string {
  const picked = a.chosen === c.id;
  const off = c.refused ? " disabled" : "";
  const tag = c.id === a.recommended ? ' <span class="tag">Recommended</span>' : "";
  return (
    `<label class="fe-choice${picked ? " is-picked" : ""}">` +
    `<input type="radio" name="front-end" data-bind="conditions.front_end" value="${escape(c.id)}"` +
    `${picked ? " checked" : ""}${off}>` +
    `<span class="fe-choice-text"><span class="fe-name"><b>${escape(c.name)}</b>${tag}</span>` +
    `<span class="quiet small">${escape(c.about)}</span>` +
    `<span class="small fe-cost">${escape(costOf(c))}</span></span></label>`
  );
}

/** The link held lower, where the motor needs less than the stage holds; or the way back to
 *  the stage's own figure where the user typed one. */
function linkLine(a: FrontEndAnswer): string {
  if (a.lever) {
    const l = a.lever;
    const said =
      `The motor needs ${num(l.need)} V at this point. Holding the link at ${num(l.v_dc)} V in place of ` +
      `${num(l.from)} V saves ${watts(l.saves)} in the two stages together.`;
    const press =
      `<button type="button" class="ghost" data-hold-link="${l.v_dc}">` +
      `${icon("check")}Hold ${num(l.v_dc)} V</button>`;
    return `<div class="fe-lever"><p>${escape(said)}</p>${press}</div>`;
  }
  if (a.v_dc_given) {
    const press = `<button type="button" class="link" data-free-link>Let the front end set it</button>`;
    return `<p class="quiet small fe-lever">The link is held at ${num(a.v_dc)} V, as typed. ${press}</p>`;
  }
  return "";
}

/** A part rated under the link the mains makes: said in a line, with the way back to a supply it
 *  can stand. Nothing where the part stands the link. */
function ratingLine(link: number): string {
  const part = app.setup.devices.find((d) => d.id === underTest());
  if (!part?.v_max || link <= part.v_max) return "";
  const said =
    `This part is rated ${num(part.v_max)} V and cannot stand the ${num(link)} V link this mains makes: ` +
    `every stage is ruled out with it. Choose a part rated above the link, or run this one from a DC supply.`;
  const press =
    `<button type="button" class="ghost" data-leave-mains>` + `${icon("arrow-left")}Back to a DC supply</button>`;
  return `<div class="fe-lever fe-rating" role="status"><p>${escape(said)}</p>${press}</div>`;
}

/** The front end on the supply step: the stage, what it costs, why it is the one; the others
 *  and its switching frequency under one press. */
export function frontEndCard(): string {
  if (app.state.supply !== "mains") return "";
  const answer = frontEndNow();
  const head = "<h3>Front end</h3>";
  if (!answer || answer === "asking") {
    const wait = waiting("Working out the stage between the mains and the link.");
    return `<section class="front-end">${head}${wait}</section>`;
  }
  if (answer instanceof Refused) {
    const fix = answer.fix ? ` ${escape(sentence(answer.fix))}.` : "";
    const said = `<p class="fix" role="status">${escape(sentence(answer.message))}.${fix}</p>`;
    return `<section class="front-end">${head}${said}</section>`;
  }
  const c = app.state.conditions;
  const r = answer.result;
  const own = answer.chosen !== answer.recommended;
  const tag = own ? "" : ' <span class="tag">Recommended</span>';
  const line =
    `<p class="fe-line"><b>${escape(r.name)}</b>${tag} ` +
    `<span class="fe-figures">${escape(watts(r.loss))} lost · holds the link at ${escape(num(r.v_dc))} V</span></p>`;
  const back = `<button type="button" class="link" data-recommended-stage>Use the one recommended</button>`;
  const over = ratingLine(r.v_dc);
  const why = over
    ? over
    : own
      ? `<p class="quiet small">Your choice. ${back}</p>`
      : `<p class="quiet small">${escape(answer.why)}</p>`;
  const usual = r.f_sw ? `Empty: ${khz(r.f_sw)} kHz, the usual for this part.` : "";
  const box = field("conditions.fe_f_khz", "Front end's switching frequency", c.fe_f_khz, "kHz", usual);
  // A stage with a control of its own is tied to the motor's: told the power about to be drawn.
  const tie = tieChoice();
  const frequency = r.f_sw ? `<div class="fields">${box}${tie}</div>` : "";
  const list = answer.choices.map((x) => choiceRow(x, answer)).join("");
  const change =
    `<details class="fe-change" data-fold="front-end"><summary id="fe-change">Change the front end</summary>` +
    `<div class="fe-choices" role="radiogroup" aria-label="Front end">${list}</div>${frequency}</details>`;
  return `<section class="front-end">${head}${line}${why}${linkLine(answer)}${change}</section>`;
}

/** The front end as the plate draws it: the stage in hand, or the one asked for while it is
 *  being worked out; nothing where the drive is not fed from the mains. */
export function frontEndDrawn(): FrontEndDrawn | null {
  if (app.state.supply !== "mains") return null;
  const c = app.state.conditions;
  const mains = {
    volts: Number(c.mains_v) || null,
    hertz: Number(c.mains_f) || 50,
    phases: c.mains_phases === "3" ? 3 : 1,
  };
  const a = solved();
  if (!a) return { id: c.front_end, name: null, recommended: false, loss: null, ...mains };
  return { id: a.chosen, name: a.result.name, recommended: a.chosen === a.recommended, loss: a.result.loss, ...mains };
}

/** The answer in hand for the results, or nothing where the drive is not fed from the mains
 *  or the answer has not come. */
function solved(): FrontEndAnswer | null {
  if (app.state.supply !== "mains") return null;
  const answer = frontEndNow();
  return !answer || answer === "asking" || answer instanceof Refused ? null : answer;
}

/** The front end's control and the motor's, tied or not: the one that suits the load is the
 *  one recommended, and the other is the user's to take. */
function tieChoice(): string {
  const swings = loadSwings(app.state);
  const options: [string, string][] = swings
    ? [
        ["", "Each on its own (recommended)"],
        ["on", "Tied: told the motor's power"],
      ]
    : [
        ["", "Tied: told the motor's power (recommended)"],
        ["off", "Each on its own"],
      ];
  const help = swings
    ? "This load swings within a turn. Tied, the front end would draw that swing from the mains and bend " +
      "its current; on its own, the link capacitor takes it."
    : "Tied, the front end raises its power as the load comes on, and the link does not have to fall first.";
  return select("conditions.fe_tie", "Its control and the motor's", app.state.conditions.fe_tie, options, help);
}

/** How many of the front end's checks ask something of the design: they count in the verdict's
 *  headline as design actions, so a pass never reads clean over a mains limit that is missed. */
export function frontEndActions(): number {
  return solved()?.result.checks.filter((x) => x.level !== "ok").length ?? 0;
}

/** The front end under the verdict: that it passes, or what does not, with the way to it. */
export function frontEndLine(): string {
  const a = solved();
  if (!a) return "";
  const r = a.result;
  const see = `<button type="button" class="link" data-tab="limits">See the front end</button>`;
  const raised = r.checks.filter((x) => x.level !== "ok");
  if (!raised.length) {
    return (
      `<p class="quiet small fe-note">Front end (${escape(r.name)}): passes its checks, ` +
      `${escape(watts(r.loss))} lost on top of the inverter's. ${see}</p>`
    );
  }
  const worst = raised.find((x) => x.level === "fail") ?? raised[0];
  return `<p class="fix"><b>Front end (${escape(r.name)}).</b> ${escape(sentence(worst.message))}. ${see}</p>`;
}

/** What the front end adds to the link capacitor's current, A rms, where it is worked out. */
export function frontEndRipple(): number | null {
  return solved()?.result.capacitor.rms ?? null;
}

const amps = (a: number): string => `${num(a, 2)} A`;

function inductorLine(r: FrontEndResult): string[] {
  const l = r.inductor;
  if (!l) return [];
  const each =
    l.count > 1 ? `${l.count} inductors of ${eng(l.henry, "H", 2)} each` : `An inductor of ${eng(l.henry, "H", 2)}`;
  return [
    `${each}, for ${amps(l.i_peak)} peak and ${amps(l.i_rms)} rms: ` +
      `it holds the ripple to ${amps(l.ripple)} peak to peak at its worst instant.`,
  ];
}

function mainsLine(r: FrontEndResult, a: FrontEndAnswer): string {
  const lines = a.mains.phases === 3 ? "each line" : "the line";
  const drawn = `${watts(r.p_in)} from a ${num(a.mains.v)} V mains, ${amps(r.i_line)} rms in ${lines}`;
  const shape =
    r.thd < 0.005
      ? "shaped to a sine, power factor 1"
      : `power factor ${r.power_factor.toFixed(2)}, distortion ${Math.round(100 * r.thd)} %`;
  return `${drawn}, ${shape}.`;
}

function capacitorLine(r: FrontEndResult, a: FrontEndAnswer): string[] {
  const cap = r.capacitor;
  const out: string[] = [];
  if (cap.rms !== null) {
    const slow = cap.slow > 0 && r.f_sw ? `, ${amps(cap.slow)} of it at ${num(2 * a.mains.f)} Hz, twice the mains` : "";
    out.push(`It gives the link capacitor ${amps(cap.rms)} rms${slow}.`);
  }
  if (cap.capacitance && cap.v_ripple) {
    const sized = cap.sized ? " (sized here for a fall of a tenth between two crests)" : "";
    const moves = `the link moves ${num(cap.v_ripple)} V peak to peak at the mains' rhythm`;
    out.push(`With ${eng(cap.capacitance, "F", 2)}${sized} ${moves}.`);
  }
  return out;
}

/** The front end as one part of what to build: the stage and its loss, then its switches,
 *  its inductor, the mains side, what it asks of the capacitor, and what was taken. */
export function frontEndSection(): string {
  const a = solved();
  if (!a) return "";
  const r = a.result;
  const lines: string[] = [];
  if (r.positions > 0 && r.tj_peak !== null) {
    const at = r.f_sw ? ` at ${khz(r.f_sw)} kHz` : "";
    lines.push(
      `${r.positions} of ${r.device}${at}: ${watts(r.loss_switches)} lost, the hottest junction at ` +
        `${num(r.tj_peak)} °C of ${num(r.tj_max)} °C.`,
    );
  }
  if (r.loss_diodes > 0) lines.push(`Its diodes lose ${watts(r.loss_diodes)}.`);
  lines.push(...inductorLine(r), mainsLine(r, a), ...capacitorLine(r, a));
  for (const check of r.checks.filter((x) => x.level !== "ok")) lines.push(`${sentence(check.message)}.`);
  lines.push(...r.notes);
  const head = `${r.name}, ${watts(r.loss)} lost`;
  return recRow("rec-front-end", `${icon("plug")}Front end`, escape(head), lines.map(escape));
}
