import type { Candidate, Capability } from "../../api";
import { limitChart } from "../../charts";
import { escape, percent, sentence, sig, watts } from "../../format";
import { app, focused, res } from "../../store";
import { coolingWords, whenAnswered } from "../html";
import { largestLoad } from "../largest";
import { notReady } from "./ready";

/** What the device holds at the design speed: the torque, the power, the current and what stops it. */
function designFacts(d: Capability["design"]): string {
  const current = d.current === null ? "n/a" : `${sig(d.current)} A peak`;
  const facts =
    `<div><dt>Torque at ${sig(d.rpm)} rpm</dt><dd>${sig(d.torque)} N·m</dd></div>` +
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
        ? `Your design torque of ${sig(d.torque === 0 ? 0 : k.torque)} N·m is ${percent(d.share, 0)} of that.`
        : `Your design torque of ${sig(k.torque)} N·m is above it.`;
  const over =
    d.current !== null && d.current > d.rated
      ? ` At that limit the current is above the device's ${sig(d.rated)} A rating: ` +
        "check what case temperature that rating assumes."
      : "";
  return `<p class="quiet after-facts">${room}${over}</p>`;
}

/** The torque it can hold at each speed, drawn for a wide screen and for a narrow one. */
function speedRange(capable: Capability): string {
  const d = capable.design;
  const torque = capable.edge.map((x) => x.torque);
  const mark = () => ({ x: d.rpm, y: app.state.conditions.torque, label: "your design point" });
  const wide = limitChart(capable.rpm, torque, "speed, rpm", "torque it can hold, N·m", mark(), true);
  const narrow = limitChart(capable.rpm, torque, "speed, rpm", "torque it can hold, N·m", mark());
  const still =
    capable.edge[0].torque < 0.98 * Math.max(...torque)
      ? " At standstill one switch carries the current without rest, so the limit is lower there."
      : "";
  const caption = `<p class="quiet small caption">Below the line every junction stays within its rating.${still}</p>`;
  return `<div class="when-wide">${wide}</div><div class="when-narrow">${narrow}</div>\n${caption}`;
}

/** How the torque it can hold moves with the switching frequency and with the cooling's temperature. */
function sensitivity(capable: Capability): string {
  const medium = app.state.conditions.cooling === "held" ? "heatsink" : "air";
  const byFrequency = limitChart(
    capable.f_sw.map((v) => v / 1000),
    capable.by_f_sw.map((x) => x.torque),
    "switching frequency, kHz",
    "torque, N·m",
  );
  const byTemperature = limitChart(
    capable.t_sink,
    capable.by_t_sink.map((x) => x.torque),
    `${medium}, °C`,
    "torque, N·m",
  );
  return (
    `<div class="read-grid"><div class="read-item"><h4>Against switching frequency</h4>${byFrequency}</div>\n` +
    `<div class="read-item"><h4>Against ${medium} temperature</h4>${byTemperature}</div></div>`
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
    `<p class="quiet">${escape(c.name)}, on this motor, at ${sig(k.v_dc)} V, ${sig(k.f_khz)} kHz ` +
      `and ${coolingWords()}, ` +
      "held without end.</p>",
    designFacts(d),
    roomNote(d),
    "<h4>Across the speed range</h4>",
    speedRange(capable),
    sensitivity(capable),
    `<h4>How much heavier could the load be?</h4><div data-asked>${largestLoad()}</div>`,
  ];
  return parts.join("\n");
}
