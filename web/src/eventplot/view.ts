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
import { pointSaid } from "./point";
import { assumedList, datasheetTable, edgeFigures, eventNotes } from "./readouts";
import { edgeOf, holdEvent, plotSvg } from "./spans";
import type { Which } from "./svg";

export { detailFold, estimateSaid, geometry } from "./detail";
export { forgetEvent, resetSpan } from "./spans";

const INDICATIVE = "the datasheet's energy is matched with a large correction, so the shape is indicative.";

/** Where the energy was met only by moving a datasheet figure far: said on the plot, with an icon and a word. */
export function indicative(e: EventEdge): string {
  if (!e.corrected) return "";
  return (
    `<p class="ev-indicative">${icon("alert-triangle")}<span class="caution-word">Indicative:</span> ` +
    `${INDICATIVE}</p>`
  );
}

/** Where both edges are only indicative, it is said once above the two, not on each. */
const bothIndicative = (ev: SwitchingEvent) =>
  ev.turn_on.corrected && ev.turn_off.corrected
    ? `<p class="ev-indicative">${icon("alert-triangle")}<span class="caution-word">Indicative:</span> ` +
      `on both edges ${INDICATIVE}</p>`
    : "";

/** The switch and the point the event is worked out at: four figures in a row, not a sentence. */
function pointFacts(ev: SwitchingEvent): string {
  const fact = (what: string, figure: string) => `<div><dt>${what}</dt><dd>${escape(figure)}</dd></div>`;
  return (
    `<dl class="ev-point" aria-label="The switch and the operating point">` +
    fact("Hottest switch", `${sentence(ev.position)}, ${ev.name}`) +
    fact("Supply", `${sig(ev.v_dc)} V`) +
    fact("Current", `${sig(ev.current)} A`) +
    fact("Junction", degrees(ev.tj)) +
    `</dl>`
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

function edgePanel(ev: SwitchingEvent, which: Which, marked: boolean, both: boolean): string {
  const name = which === "on" ? "Turn-on" : "Turn-off";
  const keys = "+ and − zoom, the arrows move, 0 goes back, Enter opens it full screen";
  return (
    `<figure class="ev-edge${marked ? " is-marked" : ""}" data-key="ev-${which}">` +
    `<figcaption><h4>${name}</h4><div class="ev-edge-actions">${fullButtons(which, name)}` +
    `<button type="button" class="ghost" data-event-reset="${which}">Reset zoom</button>` +
    `<button type="button" class="ghost ev-save" data-save-png="${name} of one switching event" ` +
    `data-under="${escape(pointSaid(ev))}" aria-label="Save the ${name.toLowerCase()} plot as a PNG image" ` +
    `title="Save as PNG">${icon("photo-down")}</button></div>` +
    `</figcaption>` +
    (both ? "" : indicative(edgeOf(ev, which))) +
    `<div class="ev-plot" tabindex="0" role="group" data-edge-plot="${which}" ` +
    `aria-label="${name} plot: ${keys}" aria-describedby="ev-read-${which}">${plotSvg(ev, which)}</div>` +
    `<output class="ev-read quiet small" id="ev-read-${which}">Point at the plot to read each trace.</output>` +
    edgeFigures(edgeOf(ev, which), which, ev.v_dc) +
    `</figure>`
  );
}

/** How the two plots are worked, said once for both. */
const HOW =
  `<p class="ev-how quiet small">Press a plot to open it full screen. Wheel or pinch to zoom, ` +
  `drag to move, double-press to go back.</p>`;

/** The whole event, with the edge the user came from marked. */
export function eventView(ev: SwitchingEvent, mark: Which | null): string {
  holdEvent(ev);
  wirePlots();
  const both = bothIndicative(ev);
  return (
    `<section class="ev" aria-labelledby="ev-h"><h3 id="ev-h" tabindex="-1">One switching event, zoomed in</h3>` +
    pointFacts(ev) +
    `<p class="quiet small">Each edge is drawn to lose exactly the energy the loss model counts.</p>` +
    heldNote(ev) +
    both +
    HOW +
    `<div class="ev-edges">${edgePanel(ev, "on", mark === "on", !!both)}` +
    `${edgePanel(ev, "off", mark === "off", !!both)}</div>` +
    signatureLine(ev) +
    eventNotes(ev) +
    `<h4>Against the datasheet</h4>${datasheetTable(ev)}` +
    `<h4>What was assumed</h4>${assumedList(ev)}` +
    detailFold() +
    `</section>`
  );
}
