// The two small rooms the + Add menu opens: one to bring another device by the same three
// ways as step 1, and one to set the motor with a change, or a setting at several values.

import { SWEEPS, sweepOf, sweepValues } from "../compare";
import type { Field } from "../api";
import { escape, sig } from "../format";
import { icon } from "../icons";
import { shownAs, shownText } from "../motorentry";
import { shown } from "../shown";
import { request } from "../state";
import { app } from "../store";
import { deviceRoutes } from "./device";
import { put } from "./morph";

/** The two dialogs, there from the first moment and filled when opened. */
export const DIALOGS =
  `<dialog id="device-dialog" class="add-dialog" aria-labelledby="device-dialog-title">` +
  `<div id="device-dialog-body"></div></dialog>\n` +
  `<dialog id="variant-dialog" class="add-dialog small" aria-labelledby="variant-dialog-title">` +
  `<div id="variant-dialog-body"></div></dialog>`;

const head = (id: string, title: string) =>
  `<div class="dialog-head"><h2 id="${id}">${escape(title)}</h2>` +
  `<button type="button" class="close" data-dialog-close aria-label="Close">${icon("x")}</button></div>`;

/** Another device to compare, brought by the ways step 1 offers: the parts on the page to
 *  tick, a datasheet or a device file to drop, or figures to type. */
function deviceBody(): string {
  // The ways of step 1, without its heading or its way on, and the way to bring another laid
  // open: a part brought here is ticked to compare, and the design stays as it is.
  const routes = deviceRoutes();
  const lead =
    '<p class="lead">Tick a part to set it beside the design, or bring another. The design is not moved by ' +
    "it: each part is worked out on the motor and load you set.</p>";
  const done = `<p class="dialog-actions"><button type="button" class="primary" data-dialog-close>Done</button></p>`;
  const title = head("device-dialog-title", "Another device to compare");
  return `${title}${lead}<div class="device-routes">${routes}</div>${done}`;
}

/** One box of the small dialog: its label, the figure, its unit, and what it says of the figure. */
function box(path: string, label: string, value: string | number, unit = ""): string {
  const id = `v-${path.replace(/\W+/g, "-")}`;
  const why = shown.wrong[path];
  const said = why ? `<p class="help unread" id="${id}-n">${escape(why)}</p>` : "";
  const input =
    `<input id="${id}" data-variant="${escape(path)}" inputmode="decimal" autocomplete="off" ` +
    `value="${escape(String(value))}"${why ? ` aria-invalid="true" aria-describedby="${id}-n"` : ""}/>`;
  const tail = unit ? `<span class="unit">${escape(unit)}</span>` : "";
  return (
    `<div class="field${why ? " is-unread" : ""}"><label for="${id}">${escape(label)}</label>` +
    `<div class="control">${input}${tail}</div>${said}</div>`
  );
}

/** A list of the small dialog: a choice among the values a figure can take. */
function choice(path: string, label: string, value: string, options: [string, string][]): string {
  const id = `v-${path.replace(/\W+/g, "-")}`;
  const opts = options
    .map(([v, name]) => `<option value="${escape(v)}"${v === value ? " selected" : ""}>${escape(name)}</option>`)
    .join("");
  return (
    `<div class="field"><label for="${id}">${escape(label)}</label>` +
    `<div class="control"><select id="${id}" data-variant="${escape(path)}">${opts}</select></div></div>`
  );
}

/** The motor and its point as a copy holds them, or as step 2 and step 3 hold them. */
export function motorOf(id: string | null): { motor: Record<string, string | number>; point: Record<string, number> } {
  const { state } = app;
  const kept = id ? state.motorSet.find((m) => m.id === id) : undefined;
  const k = state.conditions;
  const point = kept?.conditions ?? k;
  return {
    // As the engine is asked for it: the boxes left empty are left out, as on step 2.
    motor: kept?.motor ?? (request(state).motor as Record<string, string | number>),
    point: { v_dc: Number(point.v_dc), rpm: Number(point.rpm), torque: Number(point.torque) },
  };
}

/** A figure of the motor, in the terms step 2 shows it: line to line or per phase, in mH or
 *  mΩ, as Kv or Kt, as the user chose there. */
function entryBox(kind: string, f: Field, engine: string | number | undefined): string {
  const as = shownAs(kind, f.key, app.state.motorEntry, f.label, f.help);
  return box(`motor.${f.key}`, as?.label ?? f.label, shownText(as, engine ?? ""), as?.unit ?? f.unit);
}

/** The motor's own figures and its design point, to change in the copy. */
function motorBody(id: string | null): string {
  const { state, setup } = app;
  const kind = setup.motors[state.kind];
  const { motor, point } = motorOf(id);
  const fields = kind.fields.map((f: Field) =>
    f.options
      ? choice(
          `motor.${f.key}`,
          f.label,
          String(motor[f.key] ?? ""),
          f.options.map((o) => [o, o]),
        )
      : entryBox(state.kind, f, motor[f.key]),
  );
  const at = [
    box("point.v_dc", "Supply voltage", sig(point.v_dc), "V"),
    box("point.rpm", "Speed", sig(point.rpm), "rpm"),
    box("point.torque", "Torque", sig(point.torque), "N·m"),
  ];
  const title = id ? "Edit this motor" : "This motor, with a change";
  const lead =
    `<p class="quiet">A copy of the ${escape(kind.label.toLowerCase())} of step 2, set beside it as a column. ` +
    "Change what you want to compare: the motor of step 2 stays as it is.</p>";
  return (
    `${head("variant-dialog-title", title)}${lead}<div class="fields">${fields.join("")}</div>` +
    `<h3>At the design point</h3><div class="fields">${at.join("")}</div>${saveBar(id ? "Save" : "Add this motor")}`
  );
}

/** A setting, and the values it is tried at, one column each. */
function sweepBody(key: string): string {
  const { state } = app;
  const settings = Object.keys(SWEEPS).map((k) => [k, sweepOf(k).label] as [string, string]);
  const values =
    state.compare === "sweep" && key === state.sweep.key
      ? sweepValues()
          .map((v) => sig(v))
          .join("; ")
      : "";
  const lead =
    '<p class="quiet">One column for each value, everything else as you set it. Two to five values, parted ' +
    "by semicolons or spaces. Left empty, the value you set is tried with half and double of it.</p>";
  return (
    `${head("variant-dialog-title", "A setting at several values")}${lead}<div class="fields">` +
    `${choice("sweep.key", "Setting", key, settings)}${box("sweep.values", "Values", values, sweepOf(key).unit)}` +
    `</div>${saveBar(state.compare === "sweep" ? "Save" : "Try these values")}`
  );
}

const saveBar = (words: string) =>
  `<p class="dialog-actions"><button type="button" class="link" data-dialog-close>Cancel</button>` +
  `<button type="button" class="primary" data-variant-save>${escape(words)}</button></p>`;

/** The device dialog drawn again where it is open: a part read meanwhile shows in its list. */
export function renderDialogs(): void {
  const device = document.querySelector<HTMLDialogElement>("#device-dialog");
  if (device?.open) put(document.querySelector("#device-dialog-body")!, deviceBody(), "device-dialog");
}

/** The small dialog, filled for what it edits. Drawn when it opens, and when the setting it
 *  tries is changed in it; not as the page redraws, which would move what is being typed. */
export function drawVariant(): void {
  const editing = shown.editing;
  const body = document.querySelector("#variant-dialog-body");
  if (!editing || !body) return;
  put(body, editing.kind === "motor" ? motorBody(editing.id) : sweepBody(editing.key), "variant-dialog");
}
