// The switching chart: a few PWM periods of one switch, the current it carries and what it loses.

import type { SwitchingPeriod } from "../api";
import { eng, escape, sig, tickLabels } from "../format";
import { icon } from "../icons";
import { fitted } from "./fit";
import { plotPanel, plotRect, yRule } from "./frame";
import type { Box, Scale } from "./frame";
import { ticks } from "./scale";

/** Where the switching chart draws the current, and where it draws the power lost, in a
 *  drawing as wide as it is shown: the current's strip above, the power's plot under it. */
export interface PwmFrame {
  w: number;
  h: number;
  top: Box;
  box: Box;
}
/** The frame for a width, and for a height where the drawing has one to fill (full screen). The
 *  current's plot and the power's are the same height: the one reads against the other. */
export function pwmFrame(width: number, height?: number): PwmFrame {
  const w = Math.max(280, Math.round(width));
  const narrow = w < 420;
  // Narrow, the current's heading takes two lines over its strip.
  const y = narrow ? 42 : 28;
  const each = height ? Math.max(90, (height - y - 44 - 30) / 2) : narrow ? 120 : 150;
  const top: Box = { x: 52, y, w: w - 52 - 14, h: each };
  const box: Box = { x: top.x, y: top.y + top.h + 44, w: top.w, h: each };
  return { w, h: box.y + box.h + 30, top, box };
}
const EDGE = 0.07; // of a period: the width a spike is drawn with

/** What is said under the switching chart about the spikes being drawn wider than they are. */
const PWM_CAPTION =
  `<p class="quiet small caption">Shown at the point of the electrical turn where this switch works hardest. ` +
  `A real switching spike lasts under a microsecond, so each is drawn wider here; ` +
  `its area still equals the energy lost.</p>`;

/** How one switching chart is laid out: the share of a period the switch is on, how high each
 *  spike stands, the top of the power scale, and the scales of time, power and current. */
export interface PwmLayout {
  on: number;
  peakOn: number;
  peakOff: number;
  yMax: number;
  sx: Scale;
  sy: Scale;
  iy: Scale;
}

/** The layout of the switching chart for one operating point. */
export function pwmLayout(p: SwitchingPeriod, periods: number, { top, box }: PwmFrame): PwmLayout {
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
function spikeControl(
  box: Box,
  which: "on" | "off",
  [d, at, others]: [string, number[], number[]],
  marked: boolean,
): string {
  if (!d) return "";
  const name = which === "on" ? "turn-on" : "turn-off";
  // 24 wide around the spike, but never past half way to a spike of the other kind: at a
  // high duty a turn-off stands just before the next turn-on, and each keeps its own press.
  const hits = at
    .map((x) => {
      // Written to a tenth, and a tenth short of the strip beside it: as written, the two never meet.
      const left = Math.ceil(Math.max(x - 12, ...others.filter((o) => o < x).map((o) => (o + x) / 2)) * 10) / 10;
      const right = Math.floor(Math.min(x + 12, ...others.filter((o) => o > x).map((o) => (o + x) / 2)) * 10) / 10;
      const w = Math.max(right - left - 0.1, 1).toFixed(1);
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
  // In the unit it reads best in: 7.96 mJ, never 7963 µJ.
  const micro = (j: number) => eng(j, "J");
  const share = eCond + eSw > 0 ? Math.round((100 * eSw) / (eCond + eSw)) : 0;
  const cond = `<li><span class="key cond"></span>conduction, ${micro(eCond)} a period</li>`;
  // The share at this point of the turn, not the readout's, which is over the whole turn.
  const sw =
    `<li><span class="key sw"></span>switching, ${micro(eSw)} a period ` +
    `(${share} % of the two at this point of the turn)</li>`;
  return `<ul class="legend inline">${cond}${sw}</ul>`;
}

/** The two ends of the time axis under the switching chart: zero, and the time drawn at its frequency. */
function pwmTimeAxis(p: SwitchingPeriod, periods: number, box: Box): string {
  const period = 1 / p.f_sw;
  const span = periods * period;
  const time = span < 1e-3 ? `${sig(span * 1e6)} µs` : `${sig(span * 1e3)} ms`;
  const y = box.y + box.h + 15;
  const said = `${time} at ${sig(p.f_sw / 1000)} kHz`;
  const end = `<text class="tick" x="${box.x + box.w}" y="${y}" text-anchor="end">${said}</text>`;
  return `<text class="tick" x="${box.x}" y="${y}">0</text>${end}`;
}

/** Ten PWM periods of one switch, held at the instant it works hardest: the current it
 *  carries above, what it loses below. Conduction is the low block while it is on; each
 *  turn-on and turn-off is a spike whose area is the energy lost in it. A real spike is
 *  far narrower and taller than can be drawn, so the spikes are widened and say so. */
export function pwmChart(p: SwitchingPeriod, periods = 5, shown: "on" | "off" | null = null, under = ""): string {
  const span = periods === 1 ? "one switching period" : `${periods} switching periods`;
  const title = `Power lost in the switch over ${span}`;
  const drawing = fitted("pwm", (width) => pwmSvg(p, periods, shown, pwmFrame(width)));
  const on = Math.min(Math.max(p.duty, 0), 1);
  const full =
    `<button type="button" class="plot-act is-icon" data-pwm-full data-under="${escape(under)}" ` +
    `aria-label="Open full screen: ${escape(title)}" title="Full screen">${icon("maximize")}</button>`;
  const more = { foot: pwmLegend(p, on), actions: full };
  return `${plotPanel(["Switch", "Power lost"], drawing, { title, under }, more)}
${PWM_CAPTION}`;
}

/** The switching chart's drawing, in a frame as wide as it is shown. Full screen (`plain`) the
 *  spikes are drawn only: the press that shows an edge through time is the page's. */
export function pwmSvg(
  p: SwitchingPeriod,
  periods: number,
  shown: "on" | "off" | null,
  f: PwmFrame,
  plain = false,
): string {
  const { top, box } = f;
  const m = pwmLayout(p, periods, f);
  const { current, conduction, on, off, at } = pwmPaths(p, periods, m);
  const share = `${sig(p.current)} A, on ${Math.round(m.on * 100)} % of each period`;
  const said = `${periods} switching periods: current through the switch, ${share}, and the power it loses`;
  const marks = ticks(0, m.yMax, 4);
  const labels = tickLabels(marks);
  const rules = marks.map((v, k) => yRule(box, v, m.sy, labels[k])).join("");
  // Too long for one line across a phone: there its second half goes under its first.
  const [lead, rest] = [`switch current: ${sig(p.current)} A,`, ` on ${Math.round(m.on * 100)} % of each period`];
  const head =
    top.w < 300
      ? `<text class="axis" x="${top.x}" y="${top.y - 24}">${lead}<tspan x="${top.x}" dy="14">${rest}</tspan></text>`
      : `<text class="axis" x="${top.x}" y="${top.y - 10}">${lead}${rest}</text>`;
  const size = `viewBox="0 0 ${f.w} ${f.h}" width="${f.w}" height="${f.h}"`;
  const spikes = plain
    ? `<path class="area switching" d="${on}${off}"/>`
    : spikeControl(box, "on", [on, at.on, at.off], shown === "on") +
      spikeControl(box, "off", [off, at.off, at.on], shown === "off");
  return `<svg class="chart pwm" ${size} role="group" aria-label="${said}">
${head}
<path class="grid zero" d="M${top.x} ${m.iy(0)}h${top.w}"/><path class="series current" d="${current}"/>
<text class="axis" x="${box.x}" y="${box.y - 10}">power lost in the switch, W</text>
${rules}
${plotRect(box)}
<path class="area conduction" d="${conduction}"/>
${spikes}
${pwmTimeAxis(p, periods, box)}
</svg>`;
}
