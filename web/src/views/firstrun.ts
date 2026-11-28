// The first visit asks one question: your part, or a made-up one. A made-up part is chosen
// from its list and walked through every step, on its usual motor, point and load. Your part is dropped as a file
// or given as the few figures a verdict needs, in a compact symbol, value, unit table that
// takes a pasted datasheet row; everything else is assumed and said to be.

import { api } from "../api";
import { escape, sentence } from "../format";
import { icon } from "../icons";
import { app, ui } from "../store";
import type { TypedField } from "../typedkind";
import { fieldsOf, kindOf } from "../typedkind";
import { dropZone, examplePick, howToRead, lastOutcome, spareExamples } from "./device";
import { kindSwitch } from "./typed";
import { waiting } from "./html";

/** Whether step 1 shows the first visit's question, or the ways to bring your part. */
export const firstRunShown = (): boolean => ui.firstRun && !app.state.devices.length;

/** The first made-up part on the list: whether there is one to offer. */
const madeUp = () => spareExamples()[0];

/** The question: two choices, your part first (the next action), a made-up part beside it. */
function question(): string {
  const d = madeUp();
  const yours =
    `<button type="button" class="choice is-next" data-your-part>` +
    `<span class="choice-mark">${icon("upload")}</span>` +
    `<span class="choice-name">Your part${icon("arrow-right")}</span>` +
    `<span class="choice-said">Datasheet PDF, device file, a pasted row, or nine figures</span></button>`;
  // A made-up part is chosen where it is offered: the list is on this screen, and the press
  // beside it brings the part shown onto step 1, to walk through every step with it.
  const go = `<button type="button" class="ghost pick-go" data-first-try>` + `Try it${icon("arrow-right")}</button>`;
  const tryIt = d
    ? `<section class="choice choice-pick" aria-labelledby="example-pick-label">` +
      `<span class="choice-mark">${icon("bolt")}</span>` +
      `<span class="choice-name">Try a made-up part</span>` +
      `<span class="choice-said">Not a real part: each opens on its usual application, ` +
      `then each step in turn.</span>` +
      `<div class="choice-body">${examplePick(spareExamples(), "Made-up part", go)}</div></section>`
    : "";
  return (
    `<h2 tabindex="-1" class="first-title">Will your part survive your drive?</h2>` +
    `<p class="lead">Loss, Tj and the limit that sets them, on your motor, point and duty.</p>` +
    `<div class="choices">${yours}${tryIt}</div>`
  );
}

/** Each figure's symbol as a datasheet prints it, with its subscript. */
const SYMBOL: Record<string, [string, string]> = {
  v_rated: ["V", "DS"],
  i_rated: ["I", "D"],
  tj_max: ["T", "j,max"],
  rth_jc: ["R", "th(j-c)"],
  rds_on: ["R", "DS(on)"],
  v_th: ["V", "GS(th)"],
  v_plateau: ["V", "plateau"],
  q_gs: ["Q", "gs"],
  q_gd: ["Q", "gd"],
  rth_jc_diode: ["R", "th(j-c),D"],
  vce_sat: ["V", "CE(sat)"],
  vce_current: ["I", "C"],
  v_ce0: ["V", "CE0"],
  vf: ["V", "F"],
  vf_current: ["I", "F"],
  v_f0: ["V", "F0"],
  e_on: ["E", "on"],
  e_off: ["E", "off"],
  e_rr: ["E", "rr"],
  e_current: ["I", "test"],
  e_voltage: ["V", "test"],
  hot_tj: ["T", "j,hot"],
};

/** An IGBT's own symbols where a MOSFET's would be wrong. */
const IGBT_SYMBOL: Record<string, [string, string]> = { v_rated: ["V", "CES"], i_rated: ["I", "C"] };

/** One row of the compact table: symbol, value, unit, and the figure's name in small print. */
function row(f: TypedField, igbt: boolean): string {
  const id = `t-${f.key}`;
  const [base, sub] = (igbt && IGBT_SYMBOL[f.key]) || SYMBOL[f.key] || [f.label, ""];
  const wrong = ui.typedWrong[f.key];
  const note = !wrong ? ui.typedNotes[f.key] : "";
  const said = wrong
    ? `<span class="q-said said-wrong" id="${id}-w">${escape(wrong)}</span>`
    : note
      ? `<span class="q-said" id="${id}-c">${escape(note)}</span>`
      : "";
  const assumed = f.required ? "" : `<span class="q-assumed">assumed if empty</span>`;
  const value = escape(app.state.typed[f.key] ?? "");
  const input =
    `<input id="${id}" data-typed="${f.key}" autocomplete="off" spellcheck="false" value="${value}" ` +
    `aria-label="${escape(f.label)}, ${escape(f.unit)}"${wrong ? ' aria-invalid="true"' : ""}` +
    `${said ? ` aria-describedby="${id}-${wrong ? "w" : "c"}"` : ""}/>`;
  return (
    `<tr${wrong ? ' class="is-wrong"' : ""}><th scope="row">` +
    `<span class="sym">${escape(base)}<sub>${escape(sub)}</sub></span>` +
    `<span class="q-name">${escape(f.label)}${assumed}</span></th>` +
    `<td class="q-value">${input}</td><td class="q-unit">${escape(f.unit)}</td>` +
    `<td class="q-note">${said}</td></tr>`
  );
}

/** The figures a verdict needs, as a table to type or paste into; the rest is assumed. */
function quickTable(): string {
  const form = app.setup.typed;
  const kind = kindOf(app.state.typed, form);
  const fields = fieldsOf(kind, form);
  const main = fields.filter((f) => f.required || f.main);
  const rest = fields.length - main.length;
  const paste =
    `<label class="paste" for="paste-row">${icon("clipboard")}` +
    `<span>Paste a datasheet row or table</span></label>` +
    `<textarea id="paste-row" data-paste rows="2" spellcheck="false" ` +
    `placeholder="VDS 100 V   RDS(on) 4.5 5.8 mΩ   Qgd 12 nC   RthJC 0.9 K/W">${escape(ui.pasted)}</textarea>`;
  const table =
    `<table class="quick"><caption class="sr">The figures of your part</caption><tbody>` +
    `${main.map((f) => row(f, kind === "igbt")).join("")}</tbody></table>`;
  const busy = ui.typedBusy;
  const count = Object.keys(ui.typedWrong).length;
  const wrong = count
    ? `<p class="help said-wrong" role="alert">` +
      `${count === 1 ? "One figure needs" : `${count} figures need`} a change.</p>`
    : "";
  // The engine's refusal, unless a row of the table says it at its box.
  const atBox = main.some((f) => f.key === ui.typedRefused?.field && ui.typedWrong[f.key]);
  const refused =
    ui.typedRefused && !atBox
      ? `<p class="help said-wrong" role="alert">${escape(sentence(ui.typedRefused.reason))}.</p>`
      : "";
  const go =
    `<button type="button" class="primary" data-quick-add ${busy ? 'disabled aria-busy="true"' : ""}>` +
    `${busy ? "Building the part" : "Add this part"}${icon("arrow-right")}</button>`;
  const assumed =
    `<p class="quiet small">${rest} more figures, the motor, the point and the load: ` +
    `assumed, each said with the verdict.</p>`;
  return (
    `<section class="path quick-path"><h3>Or its figures</h3>${paste}${kindSwitch(kind)}${table}${assumed}` +
    `${wrong}${refused}${busy && ui.starting ? waiting("Waiting for the engine to start in this browser.") : ""}` +
    `<div class="actions quick-actions"><button type="button" class="link" data-first-back>` +
    `${icon("arrow-left")}Back</button>${go}</div></section>`
  );
}

/** Your part: drop it, or give its figures. */
function yourPart(): string {
  const local = api.mode() === "browser";
  const canRead = !local && app.setup.can_read;
  return (
    `<h2 tabindex="-1">Your part</h2>` +
    `<section class="path path-first">${dropZone(canRead, local)}${lastOutcome()}` +
    `${howToRead(canRead, local)}</section>` +
    quickTable()
  );
}

/** Step 1 on a first visit. */
export function firstRunPanel(): string {
  return ui.yourPart ? yourPart() : question();
}
