// The heads of the comparison's columns, each with its own menu, and the + Add menu that
// sets one more thing beside the design: a device, a load, the motor with a change, or a
// setting at several values. One kind is compared at a time.

import { series } from "../compare";
import type { Series } from "../compare";
import { escape } from "../format";
import { icon } from "../icons";
import { MOST } from "../steps";
import type { Kind } from "../shown";
import { app, res, underTest } from "../store";

/** One column of the comparison, with what its menu offers. */
export interface Column {
  key: string;
  name: string;
  /** The design itself: never taken out, and said to be the design. */
  design: boolean;
  edit: boolean;
  /** For a device: the design can be started from it instead. */
  lead: boolean;
}

/** The value a setting has in the design, as its column is keyed. */
function designValue(): string {
  const { state } = app;
  const key = state.sweep.key;
  const field = key === "t_sink" && state.conditions.cooling !== "held" ? "t_ambient" : key;
  return `${key}=${Number((state.conditions as Record<string, unknown>)[field])}`;
}

/** Which column is the design, by what is compared. */
function isDesign(x: Series, mode: Kind): boolean {
  if (mode === "devices") return x.key === underTest();
  if (mode === "sweep") return x.key === designValue();
  return x.key === "now";
}

export function columnsOf(list: Series[]): Column[] {
  const mode = app.state.compare;
  return list.map((x) => {
    const design = isDesign(x, mode);
    return {
      key: x.key,
      name: x.name,
      design,
      edit: !design && (mode === "motors" || mode === "sweep"),
      lead: !design && mode === "devices",
    };
  });
}

const item = (attrs: string, words: string, off = false) =>
  `<button type="button" role="menuitem" tabindex="-1" ${attrs}${off ? " disabled" : ""}>${words}</button>`;

/** The menu of one column: edit it, make it the design, take it out. */
function columnMenu(col: Column, k: number): string {
  const key = escape(col.key);
  const items = [
    col.edit ? item(`data-col-edit="${key}"`, `${icon("adjustments")}Edit`) : "",
    col.lead ? item(`data-lead="${key}"`, `${icon("player-play")}Make this the design`) : "",
    col.design ? "" : item(`data-col-remove="${key}"`, `${icon("trash")}Remove`),
  ].join("");
  const label = `aria-label="${escape(col.name)}: what to do with this column"`;
  return (
    `<button type="button" class="col-button" id="col-button-${k}" popovertarget="col-menu-${k}" ` +
    `aria-haspopup="menu" aria-expanded="false" ${label}>${icon("dots-vertical")}</button>` +
    `<div id="col-menu-${k}" class="menu" popover="auto" role="menu" aria-labelledby="col-button-${k}">${items}</div>`
  );
}

/** The head of one column: its name, said to be the design where it is, and its menu. */
export function columnHead(col: Column, k: number): string {
  const tag = col.design ? '<span class="col-tag">your design</span>' : "";
  const menu = col.design && !col.edit ? "" : columnMenu(col, k);
  return (
    `<th scope="col" data-col="${escape(col.key)}" tabindex="-1"><span class="col-head">` +
    `<span class="col-name">${escape(col.name)}${tag}</span>${menu}</span></th>`
  );
}

/** The loads the + Add menu offers: the five kinds, less those on the page, and the load of
 *  step 4 kept as it is now. */
function loadItems(full: boolean): string {
  const { state } = app;
  const offered = (res.presets?.list ?? []).filter(
    (p) => p.id !== state.loadKind && !(state.compare === "loads" && state.loadSet.some((x) => x.id === p.id)),
  );
  const kinds = offered.map((p) => item(`data-adding="load" data-preset="${escape(p.id)}"`, escape(p.label), full));
  const own = item('data-adding="load" data-preset="own"', "Your load of step 4, kept as it is now", full);
  return (
    `<div role="group" aria-labelledby="add-loads" class="menu-group">` +
    `<p class="menu-title" id="add-loads">Another load</p>${kinds.join("")}${own}</div>`
  );
}

/** The + Add button and its one menu. Where the kind of an item is the one compared and five
 *  are there, the item cannot be chosen, and says why. */
export function addMenu(): string {
  const mode = app.state.compare;
  const many = series().length >= MOST;
  const full = (kind: Kind) => mode === kind && many;
  const most = (kind: Kind) => (full(kind) ? '<span class="quiet">five is the most</span>' : "");
  const items = [
    item('data-adding="device"', `${icon("cpu")}Another device…${most("devices")}`, full("devices")),
    loadItems(full("loads")),
    item('data-adding="motor"', `${icon("engine")}This motor, with a change…${most("motors")}`, full("motors")),
    item('data-adding="sweep"', `${icon("adjustments")}A setting at several values…`),
  ].join("");
  return (
    `<button type="button" class="ghost add-button" id="add-button" data-add-menu popovertarget="add-menu" ` +
    `aria-haspopup="menu" aria-expanded="false">${icon("plus")}Add</button>` +
    `<div id="add-menu" class="menu" popover="auto" role="menu" aria-labelledby="add-button">${items}</div>`
  );
}
