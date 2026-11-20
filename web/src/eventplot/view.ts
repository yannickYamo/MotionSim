// The switching event under the loss chart: its turn-on and its turn-off side by side (one
// above the other on a phone), each zoomed on its own, with what is read from it beside it,
// the datasheet's times against the model's, what was assumed, and the event's own fold.
// This code is fetched only once the event is first asked for.

import "./event.css";
import type { EventEdge, SwitchingEvent } from "../api";
import { degrees, escape, sentence, sig } from "../format";
import { icon } from "../icons";
import { detailFold } from "./detail";
import type { Part } from "./part";
import { wirePlots } from "./pointer";
import { assumedList, datasheetTable, edgeFigures, eventNotes } from "./readouts";
import { edgeOf, holdEvent, plotSvg } from "./spans";
import type { Which } from "./svg";

export { detailFold, estimateSaid, geometry } from "./detail";
export { resetSpan } from "./spans";

/** Where the energy was met only by moving a datasheet figure far: said on the plot, with an icon and a word. */
export function indicative(e: EventEdge): string {
  if (!e.corrected) return "";
  return (
    `<p class="ev-indicative">${icon("alert-triangle")}<span class="caution-word">Indicative:</span> ` +
    `the datasheet's energy is matched with a large correction, so the shape is indicative.</p>`
  );
}

/** Where the edge limit is what slows the part: said above the edges, with the way to it. */
export const heldNote = (ev: SwitchingEvent) =>
  ev.held ? `<p class="ev-held">${icon("bolt")}<span>${escape(sentence(ev.held))}.</span></p>` : "";

/** The one line that names what sets this kind of switch apart. */
export const signatureLine = (ev: SwitchingEvent) =>
  ev.signature ? `<p class="ev-signature">${escape(ev.signature.line)}</p>` : "";

const TRACE_WORDS: Record<Part, string> = { vi: "voltage and current", gp: "gate and power" };

/** The two buttons that open an edge's plots full screen, each named by its upper trace:
 *  the voltage (with the current), the gate (with the power). */
function fullButtons(which: Which, name: string): string {
  const one = (part: Part, said: string) =>
    `<button type="button" class="ghost ev-full-open" data-full-open="${which}:${part}" ` +
    `aria-label="Open the ${name.toLowerCase()}'s ${TRACE_WORDS[part]} full screen">` +
    `${icon("maximize")}${escape(said)}</button>`;
  const both = one("vi", "Voltage") + one("gp", "Gate");
  return `<div class="ev-full-opens" role="group" aria-label="Full screen">${both}</div>`;
}

function edgePanel(ev: SwitchingEvent, which: Which, marked: boolean): string {
  const name = which === "on" ? "Turn-on" : "Turn-off";
  const keys = "+ and − zoom, the arrows move, 0 goes back, Enter opens it full screen";
  return (
    `<figure class="ev-edge${marked ? " is-marked" : ""}" data-key="ev-${which}">` +
    `<figcaption><h4>${name}</h4><div class="ev-edge-actions">${fullButtons(which, name)}` +
    `<button type="button" class="ghost" data-event-reset="${which}">Reset zoom</button></div>` +
    `</figcaption>` +
    indicative(edgeOf(ev, which)) +
    `<div class="ev-plot" tabindex="0" role="group" data-edge-plot="${which}" ` +
    `aria-label="${name} plot: ${keys}" aria-describedby="ev-read-${which}">${plotSvg(ev, which)}</div>` +
    `<output class="ev-read quiet small" id="ev-read-${which}">Press a plot to open it full screen. Rest the ` +
    `pointer on it, then wheel or pinch to zoom; drag to move; double-press to go back.</output>` +
    edgeFigures(edgeOf(ev, which), which, ev.v_dc) +
    `</figure>`
  );
}

/** The whole event, with the edge the user came from marked. */
export function eventView(ev: SwitchingEvent, mark: Which | null): string {
  holdEvent(ev);
  wirePlots();
  const said =
    `${escape(sentence(ev.position))}, the hottest switch of ${escape(ev.name)}, at ${sig(ev.v_dc)} V and ` +
    `${sig(ev.current)} A, junction ${degrees(ev.tj)}. ` +
    `Each edge is made to lose the energy the loss model counts.`;
  return (
    `<section class="ev" aria-labelledby="ev-h"><h3 id="ev-h" tabindex="-1">One switching event, zoomed in</h3>` +
    `<p class="quiet">${said}</p>` +
    heldNote(ev) +
    `<div class="ev-edges">${edgePanel(ev, "on", mark === "on")}${edgePanel(ev, "off", mark === "off")}</div>` +
    signatureLine(ev) +
    eventNotes(ev) +
    `<h4>Against the datasheet</h4>${datasheetTable(ev)}` +
    `<h4>What was assumed</h4>${assumedList(ev)}` +
    detailFold() +
    `</section>`
  );
}
