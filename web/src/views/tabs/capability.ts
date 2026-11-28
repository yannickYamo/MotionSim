import type { Candidate, Capability } from "../../api";
import { limitChart } from "../../charts";
import { plotPanel } from "../../charts/frame";
import type { Limit } from "../../charts/limitfull";
import { escape, num, percent, sentence, watts } from "../../format";
import { app, focused, res } from "../../store";
import { coolingWords, whenAnswered } from "../html";
import { largestLoad } from "../largest";
import { notReady } from "./ready";

/** What the device holds at the design speed: the torque, the power, the current and what stops it. */
function designFacts(d: Capability["design"]): string {
  const current = d.current === null ? "n/a" : `${num(d.current)} A peak`;
  const facts =
    `<div><dt>Torque at ${num(d.rpm)} rpm</dt><dd>${num(d.torque)} N·m</dd></div>` +
    `<div><dt>Shaft power there</dt><dd>${watts(d.power)}</dd></div>` +
    `<div><dt>Motor current there</dt><dd>${current}</dd></div>` +
    `<div class="wide"><dt>What stops it</dt><dd class="words">${escape(sentence(d.why))}</dd></div>`;
  return `<dl class="facts">${facts}</dl>`;
}

/** The design torque against what the device can hold, and a word where the current passes its rating. */
function roomNote(d: Capability["design"]): string {
  const k = app.state.conditions;
  const room =
    d.share === null
      ? ""
      : d.share <= 1
        ? `Your design torque of ${num(d.torque === 0 ? 0 : k.torque)} N·m is ${percent(d.share, 0)} of that.`
        : `Your design torque of ${num(k.torque)} N·m is above it.`;
  const over =
    d.current !== null && d.current > d.rated
      ? ` At that limit the current is above the device's ${num(d.rated)} A rating: ` +
        "check what case temperature that rating assumes."
      : "";
  return `<p class="quiet after-facts">${room}${over}</p>`;
}

export type LimitWhich = "speed" | "f_sw" | "t_sink";

/** Each limit of the tab: the torque the device can hold against one condition. */
export function limitOf(capable: Capability, which: LimitWhich): Limit {
  const medium = app.state.conditions.cooling === "held" ? "heatsink" : "air";
  if (which === "f_sw")
    return {
      which,
      title: "Against switching frequency",
      xs: capable.f_sw.map((v) => v / 1000),
      ys: capable.by_f_sw.map((x) => x.torque),
      xLabel: "switching frequency, kHz",
      yLabel: "torque, N·m",
    };
  if (which === "t_sink")
    return {
      which,
      title: `Against ${medium} temperature`,
      xs: capable.t_sink,
      ys: capable.by_t_sink.map((x) => x.torque),
      xLabel: `${medium}, °C`,
      yLabel: "torque, N·m",
    };
  return {
    which,
    title: "Across the speed range",
    xs: capable.rpm,
    ys: capable.edge.map((x) => x.torque),
    xLabel: "speed, rpm",
    yLabel: "torque it can hold, N·m",
    mark: { x: capable.design.rpm, y: app.state.conditions.torque, label: "your design point" },
  };
}

/** A limit in its panel, as the graphs of a motion are: named on its header line, saved from
 *  there, and opened full screen by a press on the drawing. */
function limitPanel(l: Limit, wide = false): string {
  const drawing =
    `<button type="button" class="mo-plot" data-limit-full="${l.which}" ` +
    `aria-label="Open full screen: ${escape(l.title)}">` +
    `${limitChart(l.xs, l.ys, l.xLabel, l.yLabel, l.mark, wide)}</button>`;
  // The header line says what the limit is against, short enough for half the panel's width.
  const against = sentence(l.title.replace(/^(Against|Across the) /, ""));
  return plotPanel(["Limits", against], drawing, { title: l.title, under: focused()?.name ?? "" });
}

/** The torque it can hold at each speed, drawn for a wide screen and for a narrow one. */
function speedRange(capable: Capability): string {
  const torque = capable.edge.map((x) => x.torque);
  const wide = limitPanel(limitOf(capable, "speed"), true);
  const narrow = limitPanel(limitOf(capable, "speed"));
  const still =
    capable.edge[0].torque < 0.98 * Math.max(...torque)
      ? " At standstill one switch carries the current without rest, so the limit is lower there."
      : "";
  const caption = `<p class="quiet small caption">Below the line every junction stays within its rating.${still}</p>`;
  return `<div class="when-wide">${wide}</div><div class="when-narrow">${narrow}</div>\n${caption}`;
}

/** How the torque it can hold moves with the switching frequency and with the cooling's temperature. */
function sensitivity(capable: Capability): string {
  return (
    `<div class="read-grid"><div class="read-item">${limitPanel(limitOf(capable, "f_sw"))}</div>\n` +
    `<div class="read-item">${limitPanel(limitOf(capable, "t_sink"))}</div></div>`
  );
}

/** The question turned round: with this device, this motor and this cooling, what can be
 *  driven? The torque it holds at each speed, how that moves, and how much heavier the load
 *  of step 4 could be. */
export function capabilityTab(): string {
  const c = focused();
  if (!c?.result) return notReady();
  return whenAnswered("capability", res.capable, "Finding what this device can hold.", (capable) =>
    canDrive(c, capable),
  );
}

/** What the device on the drawing can drive, once the engine has worked it out. */
function canDrive(c: Candidate, capable: Capability): string {
  const d = capable.design;
  const k = app.state.conditions;
  const parts = [
    `<p class="quiet">${escape(c.name)}, on this motor, at ${num(k.v_dc)} V, ${num(k.f_khz)} kHz ` +
      `and ${coolingWords()}, ` +
      "held without end.</p>",
    designFacts(d),
    roomNote(d),
    speedRange(capable),
    sensitivity(capable),
    `<h4>How much heavier could the load be?</h4><div data-asked>${largestLoad()}</div>`,
  ];
  return parts.join("\n");
}
