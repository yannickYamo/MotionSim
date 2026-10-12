// Engineering charts drawn as SVG: a ruled plot area, ticks on round numbers, units on the axes.

import type { Cycle, Losses, MapGrid, ModelTable, Segment, SwitchingPeriod } from "./api";
import { escape, sig } from "./format";

/** Round tick values covering [lo, hi]. */
export function ticks(lo: number, hi: number, wanted = 5): number[] {
  if (!(hi > lo)) return [lo];
  const raw = (hi - lo) / wanted;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= raw)!;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Number(v.toPrecision(12)));
  return out;
}

interface Box { x: number; y: number; w: number; h: number }

/** Every drawing that takes the width of the panel is this size, and every one that takes
 *  half of it is that size: charts set one above another line up, axis for axis. */
const FULL = { view: "0 0 540 254", box: { x: 50, y: 28, w: 466, h: 184 } };
const HALF = { view: "0 0 356 220", box: { x: 46, y: 26, w: 286, h: 150 } };

/** A scale on round values that holds everything from lo to hi, with zero always on it. */
function scale(values: number[], wanted = 4): number[] {
  const lo = Math.min(0, ...values), hi = Math.max(0, ...values);
  const yt = ticks(lo, hi > lo ? hi : lo + 1, wanted);
  const step = yt.length > 1 ? yt[1] - yt[0] : 1;
  while (yt[0] > lo - step * 1e-9 && yt[0] > lo) yt.unshift(Number((yt[0] - step).toPrecision(12)));
  while (yt[yt.length - 1] < hi) yt.push(Number((yt[yt.length - 1] + step).toPrecision(12)));
  return yt;
}

/** One quantity against time, on the frame every full-width chart shares. */
function against(time: number[], values: (number | null)[], yLabel: string, tone: string, said: string): string {
  const { view, box } = FULL;
  const tMax = time[time.length - 1] || 1;
  const yt = scale(values.filter((v): v is number => v !== null));
  const lo = yt[0], hi = yt[yt.length - 1];
  const sx = (t: number) => box.x + (t / tMax) * box.w;
  const sy = (v: number) => box.y + box.h - ((v - lo) / (hi - lo || 1)) * box.h;
  const zero = lo < 0 ? `<path class="zero" d="M${box.x} ${sy(0)}h${box.w}"/>` : "";
  return `<svg class="chart" viewBox="${view}" role="img" aria-label="${escape(said)}">
${frame(box, ticks(0, tMax), yt, sx, sy, "time, s", yLabel)}${zero}
<path class="series ${tone}" d="${line(time, values, sx, sy)}"/></svg>`;
}

/** A tick label: whole numbers stay whole. */
const tickText = (v: number) => (Number.isInteger(v) ? String(v) : sig(v, 2));

function frame(box: Box, xt: number[], yt: number[], sx: (v: number) => number, sy: (v: number) => number, xLabel: string, yLabel: string): string {
  const grid =
    xt.map((v) => `<path class="grid" d="M${sx(v)} ${box.y}v${box.h}"/><text class="tick" x="${sx(v)}" y="${box.y + box.h + 16}" text-anchor="middle">${tickText(v)}</text>`).join("") +
    yt.map((v) => `<path class="grid" d="M${box.x} ${sy(v)}h${box.w}"/><text class="tick" x="${box.x - 8}" y="${sy(v) + 4}" text-anchor="end">${tickText(v)}</text>`).join("");
  return `${grid}<rect class="plot" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}"/><text class="axis" x="${box.x + box.w}" y="${box.y + box.h + 34}" text-anchor="end">${escape(xLabel)}</text><text class="axis" x="${box.x}" y="${box.y - 10}">${escape(yLabel)}</text>`;
}

function line(xs: number[], ys: (number | null)[], sx: (v: number) => number, sy: (v: number) => number): string {
  let d = "";
  let pen = false;
  xs.forEach((x, k) => {
    const y = ys[k];
    if (y === null || y === undefined) { pen = false; return; }
    d += `${pen ? "L" : "M"}${sx(x).toFixed(1)} ${sy(y).toFixed(1)}`;
    pen = true;
  });
  return d;
}

/** Where the loss goes in the hottest position: conduction in bone, switching in orange. */
export function lossBar(l: Losses, hasDiode: boolean): string {
  const parts: [string, number, string][] = [
    ["Switch conduction", l.conduction, "cond"],
    ...(hasDiode ? ([["Diode conduction", l.diode_conduction, "cond b"]] as [string, number, string][]) : []),
    ...(l.dead_time > 0 ? ([["Dead time", l.dead_time, "cond c"]] as [string, number, string][]) : []),
    ["Turn-on", l.turn_on, "sw"],
    ["Turn-off", l.turn_off, "sw b"],
    ...(l.recovery + l.diode_recovery > 0 ? ([["Diode recovery", l.recovery + l.diode_recovery, "sw c"]] as [string, number, string][]) : []),
  ];
  const total = Math.max(l.total, 1e-12);
  let x = 0;
  const bar = parts
    .map(([name, value, cls]) => {
      const w = (value / total) * 100;
      const piece = `<rect class="seg ${cls}" x="${x}%" y="0" width="${Math.max(w, 0)}%" height="28"><title>${name}: ${sig(value)} W</title></rect>`;
      x += w;
      return piece;
    })
    .join("");
  const rows = parts
    .map(([name, value, cls]) => `<li><span class="key ${cls}"></span><span>${name}</span><span class="num">${sig(value)} W</span><span class="num dim">${Math.round((value / total) * 100)} %</span></li>`)
    .join("");
  return `<svg class="lossbar" viewBox="0 0 100 28" preserveAspectRatio="none" role="img" aria-label="Loss split of one switch position">${bar}</svg><ul class="legend">${rows}</ul>`;
}

/** A motion, as four drawings of one size on one time axis: the junction temperature against
 *  what each instant would reach if it lasted, then what the motor was asked for (speed,
 *  torque) and what it drew. Each has its own scale and says its unit. */
export function timeChart(c: Cycle): string {
  const { view, box } = FULL;
  const tMax = c.time[c.time.length - 1];
  const temps = [...c.tj, ...c.steady, ...c.t_sink].filter((v): v is number => v !== null);
  const limit = c.summary.tj_max ?? 150;
  const lo = Math.floor((Math.min(...temps) - 2) / 10) * 10;
  const hi = Math.max(Math.ceil((Math.max(...temps) + 4) / 10) * 10, lo + 20);
  const sx = (t: number) => box.x + (t / tMax) * box.w;
  const sy = (v: number) => box.y + box.h - ((v - lo) / (hi - lo)) * box.h;
  const limitLine = limit <= hi ? `<path class="limit" d="M${box.x} ${sy(limit)}h${box.w}"/><text class="tick warn" x="${box.x + box.w - 4}" y="${sy(limit) - 5}" text-anchor="end">rating ${sig(limit)} °C</text>` : "";
  const amps = c.i_peak.map((v) => v ?? 0);
  return `<svg class="chart" viewBox="${view}" role="img" aria-label="Junction temperature against time">
${frame(box, ticks(0, tMax), ticks(lo, hi, 4), sx, sy, "time, s", "junction temperature, °C")}
${limitLine}
<path class="series sink" d="${line(c.time, c.t_sink, sx, sy)}"/>
<path class="series ghost" d="${line(c.time, c.steady, sx, sy)}"/>
<path class="series hot" d="${line(c.time, c.tj, sx, sy)}"/>
</svg>
<ul class="legend inline"><li><span class="key hot"></span>junction, followed through time</li><li><span class="key ghost"></span>junction, if each instant lasted forever</li><li><span class="key sink"></span>${c.sink_name ?? "heatsink"}</li></ul>
${against(c.time, c.rpm, "motor speed, rpm", "speed", "Motor speed against time")}
${against(c.time, c.torque, "motor torque, N·m", "speed", "Motor torque against time")}
${against(c.time, amps, "motor current, A peak", "hot", "Motor current against time")}`;
}

/** Ten PWM periods of one switch, held at the instant it works hardest: the current it
 *  carries above, what it loses below. Conduction is the low block while it is on; each
 *  turn-on and turn-off is a spike whose area is the energy lost in it. A real spike is
 *  far narrower and taller than can be drawn, so the spikes are widened and say so. */
export function pwmChart(p: SwitchingPeriod, periods = 5): string {
  const top = { x: 50, y: 30, w: 466, h: 46 };
  const box = { x: 50, y: 122, w: 466, h: 100 };
  const period = 1 / p.f_sw;
  const on = Math.min(Math.max(p.duty, 0), 1);
  const edge = 0.07; // of a period: the width a spike is drawn with
  const peakOn = (2 * p.e_on) / (edge * period);
  const peakOff = (2 * p.e_off) / (edge * period);
  const yMax = Math.max(p.p_on, peakOn, peakOff, 1e-9) * 1.08;
  const sx = (t: number) => box.x + (t / periods) * box.w; // t in periods
  const sy = (v: number) => box.y + box.h - (v / yMax) * box.h;
  const iy = (v: number) => top.y + top.h - (v / Math.max(p.current, 1e-9)) * (top.h - 6);
  let current = `M${sx(0)} ${iy(0)}`;
  let conduction = "";
  let spikes = "";
  for (let k = 0; k < periods; k++) {
    const a = k + (1 - on) / 2; // on-time centred in the period, as a carrier makes it
    const b = a + on;
    if (on > 0) {
      current += `H${sx(a).toFixed(1)}V${iy(p.current).toFixed(1)}H${sx(b).toFixed(1)}V${iy(0).toFixed(1)}`;
      conduction += `M${sx(a).toFixed(1)} ${sy(0)}V${sy(p.p_on).toFixed(1)}H${sx(b).toFixed(1)}V${sy(0)}Z`;
    }
    if (p.e_on > 0) spikes += `M${sx(a - edge / 2).toFixed(1)} ${sy(0)}L${sx(a).toFixed(1)} ${sy(peakOn).toFixed(1)}L${sx(a + edge / 2).toFixed(1)} ${sy(0)}Z`;
    if (p.e_off > 0) spikes += `M${sx(b - edge / 2).toFixed(1)} ${sy(0)}L${sx(b).toFixed(1)} ${sy(peakOff).toFixed(1)}L${sx(b + edge / 2).toFixed(1)} ${sy(0)}Z`;
  }
  current += `H${sx(periods)}`;
  const eCond = p.p_on * on * period;
  const eSw = p.e_on + p.e_off;
  const micro = (j: number) => `${sig(j * 1e6)} µJ`;
  const share = eCond + eSw > 0 ? Math.round((100 * eSw) / (eCond + eSw)) : 0;
  const span = periods * period;
  const time = span < 1e-3 ? `${sig(span * 1e6)} µs` : `${sig(span * 1e3)} ms`;
  return `<svg class="chart pwm" viewBox="${FULL.view}" role="img" aria-label="${periods} switching periods: current through the switch, and the power it loses">
<text class="axis" x="${top.x}" y="${top.y - 12}">switch current: ${sig(p.current)} A, on ${Math.round(on * 100)} % of each period</text>
<path class="grid" d="M${top.x} ${iy(0)}h${top.w}"/><path class="series current" d="${current}"/>
<text class="axis" x="${box.x}" y="${box.y - 10}">power lost in the switch, W</text>
${ticks(0, yMax, 3).map((v) => `<path class="grid" d="M${box.x} ${sy(v)}h${box.w}"/><text class="tick" x="${box.x - 8}" y="${sy(v) + 4}" text-anchor="end">${Number.isInteger(v) ? v : sig(v, 2)}</text>`).join("")}
<rect class="plot" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}"/>
<path class="area conduction" d="${conduction}"/><path class="area switching" d="${spikes}"/>
<text class="tick" x="${box.x}" y="${box.y + box.h + 16}">0</text><text class="tick" x="${box.x + box.w}" y="${box.y + box.h + 16}" text-anchor="end">${time} at ${sig(p.f_sw / 1000)} kHz</text>
</svg>
<ul class="legend inline"><li><span class="key cond"></span>conduction, ${micro(eCond)} a period</li><li><span class="key sw"></span>switching, ${micro(eSw)} a period (${share} % of the two)</li></ul>
<p class="quiet small caption">Held at the instant of the turn where this switch works hardest. A switching spike lasts well under a microsecond; it is drawn wider, with its area kept equal to the energy lost.</p>`;
}

/** One table of a device model against current, a line a temperature, hottest in orange.
 *  Values that came as single table points are marked, since the line between them is assumed. */
export function tableChart(title: string, t: ModelTable): string {
  const box = { x: 46, y: 26, w: 286, h: 150 };
  const xMax = Math.max(...t.curves.flatMap((c) => c.x), 1e-9);
  const yRaw = Math.max(...t.curves.flatMap((c) => c.y), 1e-12);
  // Energies are stored in joules; show them in the unit a datasheet would.
  const [scale, unit] = t.unit !== "J" ? [1, t.unit] : yRaw < 1e-3 ? [1e6, "µJ"] : [1e3, "mJ"];
  const yt = ticks(0, yRaw * scale * 1.05, 4);
  const yMax = Math.max(yt[yt.length - 1], yRaw * scale);
  const sx = (v: number) => box.x + (v / xMax) * box.w;
  const sy = (v: number) => box.y + box.h - (v / yMax) * box.h;
  const order = [...t.curves].sort((a, b) => a.tj - b.tj);
  const lines = order.map((c, k) => {
    const hot = k === order.length - 1;
    const ys = c.y.map((v) => v * scale);
    const marks = t.basis === "point" ? c.x.map((x, j) => (x > 0 ? `<circle class="mark${hot ? " hot" : ""}" cx="${sx(x).toFixed(1)}" cy="${sy(ys[j]).toFixed(1)}" r="3"/>` : "")).join("") : "";
    return `<path class="series ${hot ? "read-hot" : "read-cold"}" d="${line(c.x, ys, sx, sy)}"/>${marks}`;
  }).join("");
  const legend = order.map((c, k) => `<li><span class="key ${k === order.length - 1 ? "read-hot" : "read-cold"}"></span>${sig(c.tj)} °C</li>`).join("");
  return `<figure class="read-chart"><svg class="chart small" viewBox="0 0 356 212" role="img" aria-label="${escape(title)} against current">
${frame(box, ticks(0, xMax, 4), yt, sx, sy, "current, A", `${title}, ${unit}`)}${lines}</svg>
<ul class="legend inline">${legend}</ul></figure>`;
}

/**
 * One line of a limit against one condition, with a point marked on it where there is one.
 * `wide`: drawn for the full width of the panel, as the main chart of a tab; otherwise for
 * half of it, one of a pair.
 */
export function limitChart(xs: number[], ys: number[], xLabel: string, yLabel: string, mark?: { x: number; y: number; label: string }, wide = false): string {
  const { view, box } = wide ? FULL : HALF;
  const x0 = Math.min(...xs, mark?.x ?? Infinity);
  const x1 = Math.max(...xs, mark?.x ?? -Infinity);
  const top = Math.max(...ys, mark?.y ?? 0, 1e-9);
  // The scale ends on a round value above the highest point, so that a level limit is a
  // line inside the plot and not one drawn over its frame.
  const yt = ticks(0, top * 1.08, 4);
  const step = yt.length > 1 ? yt[1] - yt[0] : top;
  while (yt[yt.length - 1] < top * 1.04) yt.push(Number((yt[yt.length - 1] + step).toPrecision(12)));
  const yMax = yt[yt.length - 1];
  const sx = (v: number) => box.x + ((v - x0) / Math.max(x1 - x0, 1e-9)) * box.w;
  const sy = (v: number) => box.y + box.h - (v / yMax) * box.h;
  let dot = "";
  if (mark) {
    // The label sits under the point, clear of the line it is measured against, and is
    // kept inside the plot; near the foot of the plot it goes above.
    const cx = sx(mark.x), cy = sy(mark.y);
    const below = cy < box.y + box.h - 30;
    const anchor = cx > box.x + box.w - 70 ? "end" : cx < box.x + 70 ? "start" : "middle";
    // No room under it: beside it, on the side with more room, level with the point.
    const left = cx - box.x > box.w / 2 - 20;
    const at = below ? { x: cx, y: cy + 20, anchor } : { x: cx + (left ? -10 : 10), y: cy + 4, anchor: left ? "end" : "start" };
    dot = `<circle class="mark hot" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="4.5"/><text class="tick mark-label" x="${at.x.toFixed(1)}" y="${at.y.toFixed(1)}" text-anchor="${at.anchor}">${escape(mark.label)}</text>`;
  }
  return `<svg class="chart${wide ? "" : " small"}" viewBox="${view}" role="img" aria-label="${escape(yLabel)} against ${escape(xLabel)}">
${frame(box, ticks(x0, x1, wide ? 5 : 4), yt, sx, sy, xLabel, yLabel)}<path class="series read-hot" d="${line(xs, ys, sx, sy)}"/>${dot}</svg>`;
}

/** Junction temperature through the motion for up to five things compared, on one chart. */
export function overlayChart(list: { name: string; time: number[]; tj: (number | null)[] }[], limit: number): string {
  const { view, box } = FULL;
  const tMax = Math.max(...list.map((s) => s.time[s.time.length - 1] ?? 0), 1e-9);
  const temps = list.flatMap((s) => s.tj).filter((v): v is number => v !== null);
  const lo = Math.floor((Math.min(...temps) - 2) / 10) * 10;
  const hi = Math.max(Math.ceil((Math.max(...temps) + 4) / 10) * 10, lo + 20);
  const sx = (t: number) => box.x + (t / tMax) * box.w;
  const sy = (v: number) => box.y + box.h - ((v - lo) / (hi - lo)) * box.h;
  const limitLine = limit <= hi ? `<path class="limit" d="M${box.x} ${sy(limit)}h${box.w}"/><text class="tick warn" x="${box.x + box.w - 4}" y="${sy(limit) - 5}" text-anchor="end">rating ${sig(limit)} °C</text>` : "";
  return `<svg class="chart" viewBox="${view}" role="img" aria-label="Junction temperature against time, for each one compared">
${frame(box, ticks(0, tMax), ticks(lo, hi, 4), sx, sy, "time, s", "hottest junction, °C")}${limitLine}
${list.map((s, k) => `<path class="series s${k}" d="${line(s.time, s.tj, sx, sy)}"/>`).join("")}</svg>`;
}

/** One bar a thing compared, split into its parts, all on one scale. */
export function compareBars(rows: { name: string; parts: { value: number; tone: string }[] }[], unit: string): string {
  const top = Math.max(...rows.map((r) => r.parts.reduce((a, p) => a + p.value, 0)), 1e-9);
  const w = 400;
  return `<div class="bars">${rows.map((r) => {
    let x = 0;
    const total = r.parts.reduce((a, p) => a + p.value, 0);
    const segments = r.parts.map((p) => { const width = (p.value / top) * w; const out = `<rect class="seg ${p.tone}" x="${x.toFixed(1)}" y="2" width="${Math.max(width, 0).toFixed(1)}" height="16"/>`; x += width; return out; }).join("");
    return `<div class="bar-row"><p class="bar-name">${escape(r.name)}</p><svg class="chart bars-chart" viewBox="0 0 540 20" role="img" aria-label="${escape(r.name)}: ${sig(total)} ${unit}">${segments}<text class="tick" x="${(x + 8).toFixed(1)}" y="15">${sig(total)} ${unit}</text></svg></div>`;
  }).join("")}</div>`;
}

export type Metric = "loss" | "tj" | "efficiency";

/** A speed-torque map. Darker is cooler or lower; cells the motor cannot reach are hatched. */
/** How the map's axes are shown: at the motor, or carried through the gearbox to the load. */
export interface MapAxes { speed: number; torque: number; speedLabel: string; torqueLabel: string; speedUnit: string; torqueUnit: string }
export const AT_MOTOR: MapAxes = { speed: 1, torque: 1, speedLabel: "speed, rpm", torqueLabel: "torque, N·m", speedUnit: "rpm", torqueUnit: "N·m" };

export function heatMap(g: MapGrid, metric: Metric, axes: MapAxes = AT_MOTOR, compact = false): string {
  const box = { x: 52, y: 22, w: 440, h: 300 };
  const data = g[metric];
  const flat = data.flat().filter((v): v is number => v !== null);
  if (!flat.length) return `<p class="quiet">The motor reaches no point of this range. Lower the top speed or torque.</p>`;
  const lo = Math.min(...flat);
  const hi = Math.max(...flat);
  const nx = g.rpm.length;
  const ny = g.torque.length;
  const cw = box.w / nx;
  const ch = box.h / ny;
  const unit = metric === "loss" ? "W" : metric === "tj" ? "°C" : "%";
  const scale = metric === "efficiency" ? 100 : 1;
  const cells = data
    .map((row, a) =>
      row
        .map((v, b) => {
          const x = box.x + b * cw;
          const y = box.y + box.h - (a + 1) * ch;
          if (v === null) return `<rect class="cell none" x="${x}" y="${y}" width="${cw}" height="${ch}"><title>${sig(g.rpm[b] * axes.speed)} ${axes.speedUnit}, ${sig(g.torque[a] * axes.torque)} ${axes.torqueUnit}: ${g.reason[a][b] === "motor" ? "the motor cannot reach this" : "no stable temperature"}</title></rect>`;
          // For efficiency, high is good, so the scale runs the other way.
          const t = hi > lo ? (v - lo) / (hi - lo) : 0.5;
          const level = metric === "efficiency" ? 1 - t : t;
          const over = metric === "tj" && v > g.tj_max;
          const text = cw > 40 && !compact ? `<text class="cell-text" x="${x + cw / 2}" y="${y + ch / 2 + 4}" text-anchor="middle">${sig(v * scale, metric === "efficiency" ? 3 : 2)}</text>` : "";
          return `<rect class="cell${over ? " over" : ""}" style="--level:${level.toFixed(3)}" x="${x}" y="${y}" width="${cw}" height="${ch}"><title>${sig(g.rpm[b] * axes.speed)} ${axes.speedUnit}, ${sig(g.torque[a] * axes.torque)} ${axes.torqueUnit}: ${sig(v * scale)} ${unit}</title></rect>${text}`;
        })
        .join(""),
    )
    .join("");
  // Every row and column is labelled with its own value: a rounded label on a cell is a wrong label.
  const exact = (v: number) => String(Number(v.toPrecision(3)));
  const everyX = nx <= 8 ? 1 : Math.ceil(nx / 6);
  const everyY = ny <= 8 ? 1 : Math.ceil(ny / 6);
  const xl = g.rpm.map((v, b) => (b % everyX === 0 || b === nx - 1 ? `<text class="tick" x="${box.x + (b + 0.5) * cw}" y="${box.y + box.h + 16}" text-anchor="middle">${exact(v * axes.speed)}</text>` : "")).join("");
  const yl = g.torque.map((v, a) => (a % everyY === 0 || a === ny - 1 ? `<text class="tick" x="${box.x - 8}" y="${box.y + box.h - (a + 0.5) * ch + 4}" text-anchor="end">${exact(v * axes.torque)}</text>` : "")).join("");
  const title = metric === "loss" ? "power-stage loss" : metric === "tj" ? "hottest junction" : "shaft power over DC power";
  return `<svg class="chart map" viewBox="0 0 520 362" role="img" aria-label="${title} over speed and torque">
<defs><pattern id="hatch-map" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><path d="M0 0v8" class="hatch-line"/></pattern></defs>
${cells}<rect class="plot" x="${box.x}" y="${box.y}" width="${box.w}" height="${box.h}"/>${xl}${yl}
${compact ? "" : `<text class="axis" x="${box.x + box.w}" y="${box.y + box.h + 34}" text-anchor="end">${axes.speedLabel}</text><text class="axis" x="${box.x}" y="${box.y - 8}">${axes.torqueLabel}</text>`}</svg>
<p class="scale"><span>${sig(lo * scale)} ${unit}</span><span class="ramp${metric === "efficiency" ? " reverse" : ""}"></span><span>${sig(hi * scale)} ${unit}</span><span class="swatch none"></span><span>cannot be reached</span></p>`;
}

/** The motion the user drew: load speed against time. */
export function motionPreview(segments: Segment[]): string {
  const { view, box } = HALF;
  const total = segments.reduce((s, g) => s + Math.max(g.duration, 0), 0) || 1;
  const yt = scale(segments.flatMap((g) => [g.speed_start, g.speed_end]));
  const lo = yt[0], hi = yt[yt.length - 1];
  const sx = (t: number) => box.x + (t / total) * box.w;
  const sy = (v: number) => box.y + box.h - ((v - lo) / (hi - lo || 1)) * box.h;
  let t = 0;
  let d = "";
  segments.forEach((g, k) => {
    d += `${k ? "L" : "M"}${sx(t)} ${sy(g.speed_start)}`;
    t += Math.max(g.duration, 0);
    d += `L${sx(t)} ${sy(g.speed_end)}`;
  });
  return `<svg class="chart small" viewBox="${view}" role="img" aria-label="Load speed against time">
${frame(box, ticks(0, total, 4), yt, sx, sy, "time, s", "load speed, rpm")}
<path class="series hot" d="${d}"/></svg>`;
}
