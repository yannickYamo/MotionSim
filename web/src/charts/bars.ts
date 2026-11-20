// Loss split into its parts, as a bar: for one switch position, and for each thing compared.

import type { Losses } from "../api";
import { escape, sig } from "../format";

/** One part of a loss: its name, its watts, and the class it is coloured by. */
type Part = [string, number, string];

/** One line of the key to the loss split: a part's name, its watts and its share of the total. */
function lossRow([name, value, cls]: Part, total: number): string {
  const share = `<span class="num dim">${Math.round((value / total) * 100)} %</span>`;
  const watts = `<span class="num">${sig(value)} W</span>`;
  return `<li><span class="key ${cls}"></span><span>${name}</span>${watts}${share}</li>`;
}

/** Where the loss goes in the hottest position: conduction in bone, switching in orange. */
export function lossBar(l: Losses, hasDiode: boolean): string {
  const parts: Part[] = [
    ["Switch conduction", l.conduction, "cond"],
    ...(hasDiode ? ([["Diode conduction", l.diode_conduction, "cond b"]] as Part[]) : []),
    ...(l.dead_time > 0 ? ([["Dead time", l.dead_time, "cond c"]] as Part[]) : []),
    ["Turn-on", l.turn_on, "sw"],
    ["Turn-off", l.turn_off, "sw b"],
    ...(l.recovery + l.diode_recovery > 0
      ? ([["Diode recovery", l.recovery + l.diode_recovery, "sw c"]] as Part[])
      : []),
  ];
  const total = Math.max(l.total, 1e-12);
  let x = 0;
  const bar = parts
    .map(([name, value, cls]) => {
      const w = (value / total) * 100;
      const title = `<title>${name}: ${sig(value)} W</title>`;
      const piece = `<rect class="seg ${cls}" x="${x}%" y="0" width="${Math.max(w, 0)}%" height="28">${title}</rect>`;
      x += w;
      return piece;
    })
    .join("");
  const rows = parts.map((part) => lossRow(part, total)).join("");
  const svg = `<svg class="lossbar" viewBox="0 0 100 28" preserveAspectRatio="none" role="img"`;
  const said = `Loss split of one switch position: ${sig(l.total)} W in all`;
  return `${svg} aria-label="${said}">${bar}</svg><ul class="legend">${rows}</ul>`;
}

/** The bar of one thing compared: its parts end to end, then their total written after them. */
function compareRow(r: { name: string; parts: { value: number; tone: string }[] }, top: number, unit: string): string {
  const w = 400;
  let x = 0;
  const total = r.parts.reduce((a, p) => a + p.value, 0);
  const segments = r.parts
    .map((p) => {
      const width = (p.value / top) * w;
      const size = `width="${Math.max(width, 0).toFixed(1)}" height="16"`;
      const out = `<rect class="seg ${p.tone}" x="${x.toFixed(1)}" y="2" ${size}/>`;
      x += width;
      return out;
    })
    .join("");
  const said = `${escape(r.name)}: ${sig(total)} ${unit}`;
  const sum = `<text class="tick" x="${(x + 8).toFixed(1)}" y="15">${sig(total)} ${unit}</text>`;
  const svg = `<svg class="chart bars-chart" viewBox="0 0 540 20" role="img" aria-label="${said}">`;
  return `<div class="bar-row"><p class="bar-name">${escape(r.name)}</p>${svg}${segments}${sum}</svg></div>`;
}

/** One bar a thing compared, split into its parts, all on one scale. */
export function compareBars(rows: { name: string; parts: { value: number; tone: string }[] }[], unit: string): string {
  const top = Math.max(...rows.map((r) => r.parts.reduce((a, p) => a + p.value, 0)), 1e-9);
  return `<div class="bars">${rows.map((r) => compareRow(r, top, unit)).join("")}</div>`;
}
