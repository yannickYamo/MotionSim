// A device's model laid open for checking against its datasheet: its tables as charts, and
// each thing read with its page.

import type { ModelTable, Reading } from "../api";
import { tableChart } from "../charts";
import { escape, num, percent, sentence } from "../format";
import { icon } from "../icons";
import { app, ui } from "../store";

type DatasheetRead = NonNullable<Reading["reading"]>;
type ReadValue = DatasheetRead["values"][number];
type ReadFigure = DatasheetRead["figures"][number];
type SetAside = { what: string; page: number; why: string };

const READ_NAMES: Record<string, string> = {
  vce_sat: "On-state voltage",
  vf: "Diode forward voltage",
  e_on: "Turn-on energy",
  e_off: "Turn-off energy",
  e_rr: "Diode recovery energy",
  rth_jc_switch: "Thermal resistance, switch",
  rth_jc_diode: "Thermal resistance, diode",
  v_rated: "Voltage rating",
  i_rated: "Current rating",
  tj_max: "Highest junction temperature",
  rds_on: "On-resistance",
  v_sd: "Reverse (body-diode) voltage",
  v_th: "Gate threshold",
  q_gs: "Gate-source charge",
  q_gd: "Gate-drain charge",
  q_g_th: "Gate charge at threshold",
  q_oss: "Output charge",
  q_rr: "Recovery charge",
  c_oss: "Output capacitance",
  g_fs: "Transconductance",
  v_plateau: "Gate plateau voltage",
  t_d_off: "Turn-off delay",
  t_f: "Fall time",
  vce_curve: "On-state voltage curve",
  vf_curve: "Diode forward curve",
  e_on_rg_curve: "Turn-on energy against gate resistance",
  e_off_rg_curve: "Turn-off energy against gate resistance",
  rg_on_test: "Gate resistor of the switching test, turn-on",
  rg_off_test: "Gate resistor of the switching test, turn-off",
  e_on_curve: "Turn-on energy curve",
  e_off_curve: "Turn-off energy curve",
  e_rr_curve: "Recovery energy curve",
  zth_jc_switch: "Thermal impedance, switch",
  zth_jc_diode: "Thermal impedance, diode",
  gate_charge_curve: "Gate-charge curve",
  c_oss_curve: "Output-capacitance curve",
  rds_norm_curve: "On-resistance against temperature",
};
const readName = (what: string): string => READ_NAMES[what] ?? what.replace(/_/g, " ");

/** The temperature a curve was drawn at, where the datasheet gives one. */
const atTemperature = (tj: number | null) => (tj !== null ? ` at ${num(tj)} °C` : "");

/** One thing set aside by a check: what it is, its page and why. */
export const setAsideItem = (a: SetAside) => `<li>${escape(a.what)}, page ${a.page}: ${escape(a.why)}</li>`;

/** The title of the review and the button that closes it. */
function reviewHead(name: string, id: string): string {
  const close = `<button type="button" class="ghost" data-review="${escape(id)}">${icon("x")}Close</button>`;
  return `<div class="review-head"><h3>What the model of ${escape(name)} rests on</h3>${close}</div>`;
}

/** One table of the model as a chart, with where it came from. */
function tableRead(title: string, t: ModelTable | null): string {
  if (!t || !t.curves?.length) return "";
  const basis =
    t.basis === "point" ? "From table values; the line between them is assumed." : "From the datasheet's curve.";
  const page = t.page ? ` Page ${t.page}.` : "";
  const assumption = t.assumption ? ` ${escape(sentence(t.assumption))}.` : "";
  const note = `<p class="small quiet">${basis}${page}${assumption}</p>`;
  return `<div class="read-item">${tableChart(title, t)}${note}</div>`;
}

/** Every table the model holds, each as a chart. */
const reviewCharts = (data: Reading): string =>
  tableRead("on-state voltage", data.conduction) +
  tableRead("diode voltage", data.diode) +
  tableRead("reverse voltage", data.reverse) +
  tableRead("turn-on energy", data.e_on) +
  tableRead("turn-off energy", data.e_off) +
  tableRead("recovery energy", data.e_rr);

/** The values and curves a check did not pass, which the model leaves out. */
function setAside(r: DatasheetRead): SetAside[] {
  const values = r.values
    .filter((v) => v.flags.length)
    .map((v) => ({ what: readName(v.what), page: v.page, why: v.flags.join("; ") }));
  const figures = r.figures
    .filter((f) => f.flags.length)
    .map((f) => ({
      what: `${readName(f.what)}${atTemperature(f.tj)} (${f.label})`,
      page: f.page,
      why: f.flags.join("; "),
    }));
  return [...values, ...figures];
}

/** The list of what was set aside, or nothing when every check passed. */
function setAsideBlock(aside: SetAside[]): string {
  if (!aside.length) return "";
  const why = `<p class="quiet small">A check did not pass, so the model does not use these.</p>`;
  return `<h4>Set aside</h4>${why}<ul class="plain small">${aside.map(setAsideItem).join("")}</ul>`;
}

/** One curve the model uses: its page, how close it runs to the table value, how it was read. */
function curveUsed(f: ReadFigure): string {
  const within = f.within !== null ? `: within ${percent(f.within, 0)} of the table value` : "";
  const note = f.notes.length ? `. ${escape(sentence(f.notes[0]))}` : "";
  const traced = f.method === "picture" ? ". Traced from a picture" : "";
  return `<li>${escape(readName(f.what))}${atTemperature(f.tj)}, page ${f.page}${within}${note}${traced}</li>`;
}

/** The curves the model uses, or nothing when there are none. */
const curvesUsedBlock = (used: ReadFigure[]): string =>
  used.length ? `<h4>Curves used</h4><ul class="plain small">${used.map(curveUsed).join("")}</ul>` : "";

/** One value read from a table of the datasheet, as printed, with its page. */
function valueRow(v: ReadValue): string {
  const cells =
    `<td>${escape(readName(v.what))}</td><td>${escape(v.printed)}</td>` +
    `<td>${escape(v.at)}</td><td class="num">${v.page}</td>`;
  return `<tr${v.flags.length ? ' class="aside-row"' : ""}>${cells}</tr>`;
}

/** The table of every value read from the datasheet. */
function valuesTable(values: ReadValue[]): string {
  const head =
    `<thead><tr><th scope="col">Value</th><th scope="col">As printed</th><th scope="col">At</th>` +
    `<th scope="col" class="num">Page</th></tr></thead>`;
  const rows = values.map(valueRow).join("");
  return `<div class="scroll-x"><table class="data">${head}<tbody>${rows}</tbody></table></div>`;
}

/** What the datasheet was, and how to hold the reading against it. */
function readFrom(r: DatasheetRead): string {
  const pictures = r.from_images
    ? ` ${r.from_images} pages are pictures with no text; their values were read from the picture.`
    : "";
  return (
    `<p class="quiet">Read from ${escape(r.document)}, ${r.pages} pages. ` +
    `Hold these against the datasheet: the page of each is given.${pictures}</p>`
  );
}

/** A device model laid open: its tables as charts, and each thing read from the datasheet
 *  with its page, so the user can hold it against the datasheet. */
export function reviewBlock(): string {
  const review = ui.review;
  if (!review) return "";
  const name = app.setup.devices.find((d) => d.id === review.id)?.name ?? "";
  const head = reviewHead(name, review.id);
  if (review.failed) {
    return `<section class="review" id="review">${head}<p class="quiet">${escape(review.failed)}</p></section>`;
  }
  const data = review.data;
  if (!data) return `<section class="review" id="review">${head}<p class="waiting">Opening the model</p></section>`;
  const charts = reviewCharts(data);
  const r = data.reading;
  if (!r) {
    const said =
      `<p class="quiet">This part came as a device file, so there is no datasheet reading to show. ` +
      `These are the tables in the file.</p>`;
    return `<section class="review" id="review">${head}${said}<div class="read-grid">${charts}</div></section>`;
  }
  const used = r.figures.filter((f) => !f.flags.length);
  return `<section class="review" id="review">${head}
${readFrom(r)}
<div class="read-grid">${charts}</div>
${setAsideBlock(setAside(r))}
${curvesUsedBlock(used)}
<h4>Table values read</h4>
${valuesTable(r.values)}
</section>`;
}
