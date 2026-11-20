import { notRefused } from "../../api";
import type { Candidate, Result } from "../../api";
import { compareBars, lossBar } from "../../charts";
import { resultOf, series } from "../../compare";
import type { Series } from "../../compare";
import { degrees, escape, sentence, sig, whole } from "../../format";
import { icon } from "../../icons";
import { shown } from "../../shown";
import { app, focused, res } from "../../store";
import { mapTab } from "./map";
import { notReady } from "./ready";

/** The loss and the junction of each switch position, where the stage has more than one. */
function positionsTable(r: Result): string {
  if (r.positions.length <= 1) return "";
  const head =
    '<thead><tr><th scope="col">Position</th><th scope="col" class="num">Loss</th>' +
    '<th scope="col" class="num">Junction</th></tr></thead>';
  const rows = r.positions
    .map(
      (p) =>
        `<tr><td>${p.count} × ${escape(p.name)}</td><td class="num">${sig(p.total)} W</td>` +
        `<td class="num">${degrees(p.tj)}</td></tr>`,
    )
    .join("");
  return `<h4>By position</h4><table class="data">${head}<tbody>${rows}</tbody></table>`;
}

/** How far the datasheet's own data carries the result, in a sentence. */
const supportWords = (r: Result): string =>
  ({
    interpolated: "Inside the datasheet's own curves.",
    extrapolated: "Partly outside the datasheet's data.",
    assumed: "Partly on table points with an assumed shape between them.",
  })[r.validity] ?? r.validity;

/** A folded list with its count on the face, left out when it is empty. */
function countedList(title: string, items: string[]): string {
  if (!items.length) return "";
  const summary = `<summary>${title}<span class="count">${items.length}</span></summary>`;
  const lines = `<ul class="plain small">${items.map((n) => `<li>${escape(sentence(n))}</li>`).join("")}</ul>`;
  return `<details class="more counted">${summary}${lines}</details>`;
}

/** Conduction and switching loss of each thing compared, as stacked bars. */
function lossBars(compared: Series[]): string {
  const title = { devices: "Loss of each device", motors: "Loss with each motor", sweep: "Loss at each value" }[
    app.state.compare as "devices"
  ];
  const rows = compared.map((x) => ({
    name: x.name,
    parts: [
      { value: resultOf(x)?.result?.conduction ?? 0, tone: "cond" },
      { value: resultOf(x)?.result?.switching ?? 0, tone: "sw" },
    ],
  }));
  const legend =
    '<ul class="legend inline"><li><span class="key cond"></span>conduction</li>' +
    '<li><span class="key sw"></span>switching</li></ul>';
  return `<h3>${title}</h3>${compareBars(rows, "W")}${legend}`;
}

/** The mean loss through each load's motion, as bars. */
function loadBars(compared: Series[]): string {
  const rows = compared.map((x) => {
    const g = res.cycles.get(x.key);
    return {
      name: x.name,
      parts: [{ value: notRefused(g)?.summary.mean_loss ?? 0, tone: "cond" }],
    };
  });
  return `<h3>Mean loss under each load</h3>${compareBars(rows, "W")}`;
}

/** What is compared, set above the one device's own losses. */
function comparedLosses(): string {
  const compared = series();
  if (compared.length < 2) return "";
  return app.state.compare !== "loads" ? lossBars(compared) : loadBars(compared);
}

/** What the result rests on: how far the data carries it, then the notes, each kind folded. */
function restsOn(r: Result): string {
  const sound = r.validity === "interpolated";
  const glyph = icon(sound ? "circle-check" : "alert-triangle");
  const fact = `<p class="fact ${sound ? "" : "warn"}">${glyph}<span>${supportWords(r)}</span></p>`;
  const lists =
    countedList("Where the data runs out", r.notes) +
    countedList("Thermal values the tool had to compute", r.assumptions) +
    countedList("Left out of the model", r.limits) +
    countedList("Rating warnings", r.warnings);
  return `<h4>What this rests on</h4>${fact}\n${lists}`;
}

/** The map of the losses over the motor's whole range: it takes a while to solve, so it is
 *  solved and drawn only once it is asked for, under the losses at the design point. */
function mapSection(name: string): string {
  const press = (on: boolean, words: string) =>
    `<button type="button" class="ghost" data-show-map="${on ? "hide" : "show"}" aria-expanded="${on}" ` +
    `aria-controls="map-section">${icon("chart-bar")}${words}</button>`;
  // The map is solved only when asked for, and is not kept across a reload, like the largest load.
  if (shown.map) {
    const hide = `<p>${press(true, "Hide the map")}</p>`;
    return `<section id="map-section" class="tab-section" data-asked>${mapTab()}${hide}</section>`;
  }
  const about =
    '<p class="quiet">The loss, the junction temperature or the efficiency at every speed and torque the motor ' +
    "can reach. Solving it takes a little while.</p>";
  return (
    `<section id="map-section" class="tab-section" data-asked><h3>${escape(name)} over the motor's range</h3>${about}` +
    `<p>${press(false, "Show the map")}</p></section>`
  );
}

/** Said in place of the losses when the device on the drawing has no result. */
function noLosses(c: Candidate | null): string {
  const said = c?.problem
    ? escape(sentence(c.problem)) + ". " + escape(sentence(c.fix)) + "."
    : "Choose a device to see where its loss goes.";
  return `<p class="empty">${icon("flame")}${said}</p>`;
}

export function lossesTab(): string {
  const c = focused();
  const r = c?.result;
  if (!r && (res.blocked || res.fault || !res.proposal)) return notReady();
  if (!r) return noLosses(c);
  const hasDiode = r.hottest.diode_conduction + r.hottest.diode_recovery > 0;
  const times = whole(app.state.conditions.f_khz * 1000);
  const about =
    '<p class="quiet">The hottest position. Conduction is the price of carrying current; ' +
    `switching is paid ${times} times a second.</p>`;
  const head = `<h3>${escape(c.name)}: one switch position</h3>${about}`;
  const here = `${comparedLosses()}${head}\n${lossBar(r.hottest, hasDiode)}${positionsTable(r)}\n${restsOn(r)}`;
  return `${here}\n${mapSection(c.name)}`;
}
