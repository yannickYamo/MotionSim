// The event's own fold: the figures it rests on that the user can give. The loop inductance,
// the gate resistors and the drive level are the design's own, shared with step 3 and the
// losses; the common-source and gate-loop inductances and the driver's low level are the
// event's alone. A layout file gives the board's figures at once, the board's own design file
// is read for them where the engine is on this machine, and a first figure for the loop can
// be worked out from the board's geometry.

import { api } from "../api";
import { boardPanel, ELSEWHERE } from "../board/panel";
import { board } from "../board/reading";
import { app } from "../store";
import { escape, sig } from "../format";
import { icon } from "../icons";
import { field, idOf } from "../views/html";
import { loopInductance } from "./estimate";
import type { Geometry } from "./estimate";

/** The id a box of the fold goes by: its own, so that it never takes the id of the same
 *  figure's box on step 3, which may be on the page with it. */
export const boxId = (path: string) => `ev-${idOf(path)}`;

/** A box bound to the state as any other, under the fold's own ids. */
function box(path: string, label: string, value: string, unit: string, help = ""): string {
  return field(path, label, value, unit, help).split(idOf(path)).join(boxId(path));
}

/** The geometry typed into the estimate, as typed: kept while the page is open. */
export const geometry: Record<keyof Geometry, string> = { length: "", width: "", spacing: "", packages: "" };

const read = (s: string) => (s.trim() === "" ? undefined : Number(s.replace(",", ".")));

/** The figure the geometry comes to, with Use this, or what is still missing. */
export function estimateSaid(): string {
  const e = loopInductance({
    length: read(geometry.length),
    width: read(geometry.width),
    spacing: read(geometry.spacing),
    packages: read(geometry.packages),
  });
  if (!e) return `<p class="quiet small" id="ev-estimate">Give the length, the width and the spacing.</p>`;
  const caution = e.caution ? `<p class="help caution-note">${icon("alert-triangle")}${escape(e.caution)}</p>` : "";
  return (
    `<div id="ev-estimate"><p>About <b>${sig(e.total)} nH</b>: ${sig(e.board)} on the board, ` +
    `${sig(e.total - e.board)} in the packages.</p>${caution}` +
    `<button type="button" class="ghost" data-event-use="${Number(e.total.toPrecision(3))}">` +
    `Use this as the loop inductance</button></div>`
  );
}

function geoBox(key: keyof Geometry, label: string, unit: string, help = ""): string {
  const id = `ev-geo-${key}`;
  const below = help ? `<p class="help" id="${id}-h">${escape(help)}</p>` : "";
  return (
    `<div class="field"><label for="${id}">${escape(label)}</label><div class="control">` +
    `<input id="${id}" data-geo="${key}" inputmode="decimal" autocomplete="off" value="${escape(geometry[key])}"` +
    `${help ? ` aria-describedby="${id}-h"` : ""}/><span class="unit">${unit}</span></div>${below}</div>`
  );
}

function estimator(): string {
  return (
    `<details class="more ev-geo" data-fold="event-geometry"><summary>${icon("ruler-measure")}` +
    `Estimate the loop from the board</summary>` +
    `<p class="quiet small">The loop as a strip out on one layer and back on the one beneath: ` +
    `μ0 · length · spacing / width, as two parallel plates, with the packages' own added.</p>` +
    `<div class="fields">${geoBox("length", "Loop length, out and back", "mm")}` +
    geoBox("width", "Strip width", "mm") +
    geoBox("spacing", "Layers apart", "mm", "The board between the two layers.") +
    geoBox("packages", "Both packages' own", "nH", "A few nH each for leaded parts, under 1 for chip-scale.") +
    `</div>${estimateSaid()}</details>`
  );
}

/** A board's own file, by its name: a layout file is the one kind that ends otherwise. */
const ofBoard = (name: string) => /\.(kicad_pcb|xml|cvg)$/i.test(name);

/** Where the board's figures are given: a layout file, or the board's own design file where
 *  the engine on this machine reads it. One control takes either. */
function layoutFile(): string {
  const { event } = app.state;
  const local = api.mode() === "browser";
  const name = `<b>${escape(event.layout_name || "layout.yaml")}</b>`;
  const wins = "A box above that is filled wins over the file.";
  const yaml =
    `A YAML file of the board's loop figures; <code>motionsim template layout</code> writes one to fill. ` + wins;
  const hint = local
    ? `<p class="quiet small">${yaml}${board.elsewhere ? "" : ` ${ELSEWHERE}`}</p>`
    : `<p class="quiet small">The board's own file (KiCad <code>.kicad_pcb</code>, or IPC-2581 <code>.xml</code> ` +
      `or <code>.cvg</code>) is read for its loop figures. Or give them in a YAML file; ` +
      `<code>motionsim template layout</code> writes one to fill. ${wins}</p>`;
  const held = event.layout
    ? `<p>${ofBoard(event.layout_name) ? `The figures read from ${name} are` : `Layout file ${name}`} in use, ` +
      `under the boxes above. <button type="button" class="link" data-event-layout-drop>Stop using it</button></p>`
    : hint;
  const accept = local ? ".yaml,.yml,.txt" : ".kicad_pcb,.xml,.cvg,.yaml,.yml,.txt";
  // While a board is being read the control waits: one file at a time.
  const busy = board.since ? " disabled" : "";
  return (
    `<div class="ev-layout">${held}<label class="ghost">${icon("upload")}` +
    `${local ? "Open a layout file" : "Open a board or layout file"}` +
    `<input type="file" class="sr" accept="${accept}" data-event-layout${busy}/></label></div>${boardPanel()}`
  );
}

/** The fold, open where a way to one of its boxes was pressed, or where the user left it. */
export function detailFold(): string {
  const c = app.state.conditions;
  const e = app.state.event;
  const shared =
    box("conditions.l_loop_nh", "Loop inductance", c.l_loop_nh, "nH", "Shared with step 3 and the losses.") +
    box("conditions.v_drive", "Gate drive voltage", c.v_drive, "V") +
    box("conditions.rg_on", "Turn-on gate resistance", c.rg_on, "Ω") +
    box("conditions.rg_off", "Turn-off gate resistance", c.rg_off, "Ω");
  const own =
    box("event.l_cs_nh", "Common-source inductance", e.l_cs_nh, "nH", "0 with a Kelvin source pin.") +
    box("event.l_g_nh", "Gate-loop inductance", e.l_g_nh, "nH") +
    box("event.v_off", "Driver's low level", e.v_off, "V", "0, or below for a negative turn-off.");
  return (
    `<details class="more ev-detail" data-fold="event-detail"><summary>${icon("settings")}Event detail</summary>` +
    `<div class="fields">${shared}${own}</div>${layoutFile()}${estimator()}</details>`
  );
}
