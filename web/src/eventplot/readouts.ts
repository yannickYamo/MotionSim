// What is read from each edge, beside its drawing: the energy it loses against the loss
// model's, how fast it switches, its peak and its ringing. Then the datasheet's own times
// against the model's, and every figure the event assumed, with the way to the box that
// replaces it.

import type { EventEdge, SwitchingEvent } from "../api";
import { escape, sentence, sig } from "../format";
import { icon } from "../icons";
import type { Which } from "./svg";

/** The box each assumed figure is replaced from: in the event's own fold. */
export const BOX_OF: Record<string, string> = {
  l_loop: "conditions.l_loop_nh",
  l_cs: "event.l_cs_nh",
  l_g: "event.l_g_nh",
  v_on: "conditions.v_drive",
  v_off: "event.v_off",
  rg_on: "conditions.rg_on",
  rg_off: "conditions.rg_off",
};

const ns = (s: number | null) => (s === null ? sig(null) : `${sig(s * 1e9)} ns`);
const perNs = (x: number | null, unit: string) => (x === null ? sig(null) : `${sig(x / 1e9)} ${unit}/ns`);

function row(what: string, figure: string, note = ""): string {
  const said = note ? `<span class="note">${escape(note)}</span>` : "";
  return `<div class="ev-row"><dt>${escape(what)}</dt><dd><b>${figure}</b>${said}</dd></div>`;
}

/** The energy lost, said beside the loss model's; where they part, said with an icon and a word. */
function energyRow(e: EventEdge): string {
  const uj = (j: number) => `${sig(j * 1e6)} µJ`;
  const met = e.met
    ? `loss model ${uj(e.target)}`
    : `${icon("alert-triangle")}<span class="caution-word">Not met:</span> the loss model counts ${uj(e.target)}`;
  const note = `<span class="note">${met}</span>`;
  const cls = e.met ? "ev-row" : "ev-row is-caution";
  return `<div class="${cls}"><dt>Energy lost</dt><dd><b>${uj(e.energy)}</b>${note}</dd></div>`;
}

/** The figures of one edge, in the order a double-pulse test reports them. */
export function edgeFigures(e: EventEdge, which: Which, v_dc: number): string {
  const on = which === "on";
  const rows = [
    energyRow(e),
    row(on ? "Delay, td(on)" : "Delay, td(off)", ns(e.t_delay)),
    on ? row("Current rise, tr", ns(e.t_rise)) : row("Current fall, tf", ns(e.t_fall)),
    on ? row("Voltage fall", ns(e.t_fall)) : row("Voltage rise", ns(e.t_rise)),
    row("di/dt", perNs(e.di_dt, "A")),
    row("dv/dt", perNs(e.dv_dt, "V")),
    on
      ? row("Peak current", `${sig(e.i_peak)} A`, "with what the other switch gives back")
      : row("Peak voltage", `${sig(e.v_peak)} V`, `${sig(e.v_peak - v_dc)} V over the supply`),
    row("Ringing", e.ring ? `${sig(e.ring / 1e6)} MHz` : sig(null)),
  ];
  if (e.tail) rows.push(row("Tail current's time", `${sig(e.tail * 1e6)} µs`));
  rows.push(
    row("Gate-drain charge taken", `${sig(e.factor, 2)} ×`, "of the datasheet's, to lose the loss model's energy"),
  );
  if (on && e.recovery !== undefined && e.recovery !== 1) {
    const note = "of the datasheet's, to lose the loss model's energy";
    rows.push(row("Recovery charge taken", `${sig(e.recovery, 2)} ×`, note));
  }
  return `<dl class="ev-figures">${rows.join("")}</dl>`;
}

/** The model's switching times beside the datasheet's, at the datasheet's own test. */
export function datasheetTable(ev: SwitchingEvent): string {
  const d = ev.datasheet;
  if (!d || !d.rows.length) {
    return `<p class="quiet small">The datasheet gives no switching times to set this event beside.</p>`;
  }
  const body = d.rows
    .map(
      (r) =>
        `<tr><th scope="row">${escape(r.what)}</th><td>${ns(r.model)}</td><td>${ns(r.datasheet)}</td>` +
        `<td>${r.error >= 0 ? "+" : "−"}${sig(Math.abs(r.error) * 100, 2)} %</td></tr>`,
    )
    .join("");
  const test = `${sig(d.v_test)} V, ${sig(d.i_test)} A, ${sig(d.rg_test)} Ω in the gate, at 25 °C`;
  const assumed = d.assumed.length
    ? `<p class="quiet small">Assumed for the test: ${d.assumed.map((a) => escape(sentence(a))).join("; ")}.</p>`
    : "";
  return (
    `<table class="ev-sheet"><caption>Against the datasheet, at its own test: ${test}</caption>` +
    `<thead><tr><th scope="col">Time</th><th scope="col">Model</th><th scope="col">Datasheet</th>` +
    `<th scope="col">Apart</th></tr></thead><tbody>${body}</tbody></table>${assumed}`
  );
}

/** The way to the edge limit, on step 3, from a line that says the limit set a resistor. */
export const RAISE_LIMIT = `<button type="button" class="link" data-edge-limit-go>raise the limit</button>`;

/** Each figure the event assumed, with a way to the box that replaces it where there is one. */
export function assumedList(ev: SwitchingEvent): string {
  const items = ev.assumed
    .map((a) => {
      if (a.field === "edge_limit") return `<li>${escape(sentence(a.text))} — ${RAISE_LIMIT}.</li>`;
      const box = BOX_OF[a.field];
      const go = box ? ` <button type="button" class="link" data-event-box="${escape(box)}">Give yours</button>` : "";
      return `<li>${escape(sentence(a.text.replace(/: give yours\.?$|\. Give yours\.?$/i, "")))}.${go}</li>`;
    })
    .join("");
  return items ? `<ul class="ev-assumed">${items}</ul>` : "";
}

/** What the event says of itself where its energy and the loss model's part. */
export const eventNotes = (ev: SwitchingEvent): string =>
  ev.notes.map((n) => `<p class="quiet small">${escape(n)}</p>`).join("");
