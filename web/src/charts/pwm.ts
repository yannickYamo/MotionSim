// The switching chart: a few PWM periods of one switch, the current it carries and what it loses.

import type { SwitchingPeriod } from "../api";
import { sig, tickLabels } from "../format";
import { FULL, plotRect, savable, yRule } from "./frame";
import type { Box, Scale } from "./frame";
import { ticks } from "./scale";

/** Where the switching chart draws the current, and where it draws the power lost. */
const PWM_TOP: Box = { x: 56, y: 36, w: 460, h: 46 };
const PWM_BOX: Box = { x: 56, y: 132, w: 460, h: 100 };
const EDGE = 0.07; // of a period: the width a spike is drawn with

/** What is said under the switching chart about the spikes being drawn wider than they are. */
const PWM_CAPTION =
  `<p class="quiet small caption">Shown at the point of the electrical turn where this switch works hardest. ` +
  `A real switching spike lasts under a microsecond, so each is drawn wider here; ` +
  `its area still equals the energy lost.</p>`;

/** How one switching chart is laid out: the share of a period the switch is on, how high each
 *  spike stands, the top of the power scale, and the scales of time, power and current. */
interface PwmLayout {
  on: number;
  peakOn: number;
  peakOff: number;
  yMax: number;
  sx: Scale;
  sy: Scale;
  iy: Scale;
}

/** The layout of the switching chart for one operating point. */
function pwmLayout(p: SwitchingPeriod, periods: number): PwmLayout {
  const top = PWM_TOP;
  const box = PWM_BOX;
  const period = 1 / p.f_sw;
  const on = Math.min(Math.max(p.duty, 0), 1);
  const peakOn = (2 * p.e_on) / (EDGE * period);
  const peakOff = (2 * p.e_off) / (EDGE * period);
  const yMax = Math.max(p.p_on, peakOn, peakOff, 1e-9) * 1.08;
  const sx = (t: number) => box.x + (t / periods) * box.w; // t in periods
  const sy = (v: number) => box.y + box.h - (v / yMax) * box.h;
  const iy = (v: number) => top.y + top.h - (v / Math.max(p.current, 1e-9)) * (top.h - 6);
  return { on, peakOn, peakOff, yMax, sx, sy, iy };
}

/** A switching spike: a triangle standing on zero, centred on the instant the switch turns. */
function spike(at: number, peak: number, sx: Scale, sy: Scale): string {
  const foot = `M${sx(at - EDGE / 2).toFixed(1)} ${sy(0)}`;
  return `${foot}L${sx(at).toFixed(1)} ${sy(peak).toFixed(1)}L${sx(at + EDGE / 2).toFixed(1)} ${sy(0)}Z`;
}

/** The three paths of the switching chart: the current, the conduction blocks and the spikes. */
function pwmPaths(
  p: SwitchingPeriod,
  periods: number,
  m: PwmLayout,
): { current: string; conduction: string; on: string; off: string; at: { on: number[]; off: number[] } } {
  const { on, sx, sy, iy } = m;
  let current = `M${sx(0)} ${iy(0)}`;
  let conduction = "";
  let spikeOn = "";
  let spikeOff = "";
  const at = { on: [] as number[], off: [] as number[] };
  for (let k = 0; k < periods; k++) {
    const a = k + (1 - on) / 2; // on-time centred in the period, as a carrier makes it
    const b = a + on;
    if (on > 0) {
      current += `H${sx(a).toFixed(1)}V${iy(p.current).toFixed(1)}H${sx(b).toFixed(1)}V${iy(0).toFixed(1)}`;
      conduction += `M${sx(a).toFixed(1)} ${sy(0)}V${sy(p.p_on).toFixed(1)}H${sx(b).toFixed(1)}V${sy(0)}Z`;
    }
    if (p.e_on > 0) spikeOn += spike(a, m.peakOn, sx, sy);
    if (p.e_off > 0) spikeOff += spike(b, m.peakOff, sx, sy);
    at.on.push(sx(a));
    at.off.push(sx(b));
  }
  current += `H${sx(periods)}`;
  return { current, conduction, on: spikeOn, off: spikeOff, at };
}

/** The spikes of one kind of edge, as one control: pressed, or Enter or Space on it, it shows
 *  that edge through time under the chart. Each spike carries a wider strip to be pressed by,
 *  since a spike is drawn only a few pixels wide. The edge shown is marked. */
function spikeControl(which: "on" | "off", d: string, at: number[], others: number[], marked: boolean): string {
  if (!d) return "";
  const box = PWM_BOX;
  const name = which === "on" ? "turn-on" : "turn-off";
  // 24 wide around the spike, but never past half way to a spike of the other kind: at a
  // high duty a turn-off stands just before the next turn-on, and each keeps its own press.
  const hits = at
    .map((x) => {
      const left = Math.max(x - 12, ...others.filter((o) => o < x).map((o) => (o + x) / 2));
      const right = Math.min(x + 12, ...others.filter((o) => o > x).map((o) => (o + x) / 2));
      const w = Math.max(right - left, 1).toFixed(1);
      return `<rect class="spike-hit" x="${left.toFixed(1)}" y="${box.y}" width="${w}" height="${box.h}"/>`;
    })
    .join("");
  return (
    `<g class="spike${marked ? " is-shown" : ""}" role="button" tabindex="0" data-event-show="${which}" ` +
    `aria-label="See the ${name} through time"${marked ? ' aria-current="true"' : ""}>` +
    `${hits}<path class="area switching" d="${d}"/></g>`
  );
}

/** The key to the switching chart: the energy lost a period in conduction and in switching. */
function pwmLegend(p: SwitchingPeriod, on: number): string {
  const period = 1 / p.f_sw;
  const eCond = p.p_on * on * period;
  const eSw = p.e_on + p.e_off;
  const micro = (j: number) => `${sig(j * 1e6)} µJ`;
  const share = eCond + eSw > 0 ? Math.round((100 * eSw) / (eCond + eSw)) : 0;
  const cond = `<li><span class="key cond"></span>conduction, ${micro(eCond)} a period</li>`;
  const sw = `<li><span class="key sw"></span>switching, ${micro(eSw)} a period (${share} % of the two)</li>`;
  return `<ul class="legend inline">${cond}${sw}</ul>`;
}

/** The two ends of the time axis under the switching chart: zero, and the time drawn at its frequency. */
function pwmTimeAxis(p: SwitchingPeriod, periods: number): string {
  const box = PWM_BOX;
  const period = 1 / p.f_sw;
  const span = periods * period;
  const time = span < 1e-3 ? `${sig(span * 1e6)} µs` : `${sig(span * 1e3)} ms`;
  const y = box.y + box.h + 16;
  const said = `${time} at ${sig(p.f_sw / 1000)} kHz`;
  const end = `<text class="tick" x="${box.x + box.w}" y="${y}" text-anchor="end">${said}</text>`;
  return `<text class="tick" x="${box.x}" y="${y}">0</text>${end}`;
}

/** Ten PWM periods of one switch, held at the instant it works hardest: the current it
 *  carries above, what it loses below. Conduction is the low block while it is on; each
 *  turn-on and turn-off is a spike whose area is the energy lost in it. A real spike is
 *  far narrower and taller than can be drawn, so the spikes are widened and say so. */
export function pwmChart(p: SwitchingPeriod, periods = 5, shown: "on" | "off" | null = null, under = ""): string {
  const top = PWM_TOP;
  const box = PWM_BOX;
  const m = pwmLayout(p, periods);
  const { current, conduction, on, off, at } = pwmPaths(p, periods, m);
  const share = `${sig(p.current)} A, on ${Math.round(m.on * 100)} % of each period`;
  const said = `${periods} switching periods: current through the switch, ${share}, and the power it loses`;
  const marks = ticks(0, m.yMax, 3);
  const labels = tickLabels(marks);
  const rules = marks.map((v, k) => yRule(box, v, m.sy, labels[k])).join("");
  const heading = `switch current: ${share}`;
  const span = periods === 1 ? "one switching period" : `${periods} switching periods`;
  const title = `Power lost in the switch over ${span}`;
  const svg = `<svg class="chart pwm" viewBox="${FULL.view}" role="group" aria-label="${said}">
<text class="axis" x="${top.x}" y="${top.y - 16}">${heading}</text>
<path class="grid" d="M${top.x} ${m.iy(0)}h${top.w}"/><path class="series current" d="${current}"/>
<text class="axis" x="${box.x}" y="${box.y - 14}">power lost in the switch, W</text>
${rules}
${plotRect(box)}
<path class="area conduction" d="${conduction}"/>
${spikeControl("on", on, at.on, at.off, shown === "on")}${spikeControl("off", off, at.off, at.on, shown === "off")}
${pwmTimeAxis(p, periods)}
</svg>`;
  return `${savable(svg, title, under)}
${pwmLegend(p, m.on)}
${PWM_CAPTION}`;
}
