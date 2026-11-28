// Loss split into its parts, as a bar: for one switch position, and for each thing compared.

import type { Losses } from "../api";
import { escape, sig } from "../format";

/** One part of a loss: its name, its watts, and the class it is coloured by. */
type Part = [string, number, string];

/** One line of the key to the loss split: a part's name, its watts and its share of the total.
 *  `k` ties the line to its block, so pointing at either lights both. */
function lossRow([name, value, cls]: Part, total: number, k: number): string {
  const share = `<span class="num dim">${Math.round((value / total) * 100)} %</span>`;
  const watts = `<span class="num">${sig(value)} W</span>`;
  return `<li data-k="${k}"><span class="key ${cls}"></span><span>${name}</span>${watts}${share}</li>`;
}

/** One block of the bar: its share printed inside at its leading edge where it fits, and its
 *  name, watts and share on hover. A block at nought draws nothing. */
function lossBlock([name, value, cls]: Part, total: number, k: number): string {
  if (!(value > 0)) return "";
  const share = (value / total) * 100;
  const pct = `${Math.round(share)} %`;
  // A block too narrow for its share prints none: the key and the readout still give it.
  const fits = share >= 7 ? `<span class="lb-in">${pct}</span>` : "";
  const narrow = share < 16 ? " narrow" : "";
  const said = `<span class="lb-tip" role="tooltip"><b>${name}</b> ${sig(value)} W · ${pct}</span>`;
  return (
    `<span class="lb-seg ${cls}${narrow}" data-k="${k}" style="flex-grow:${share.toFixed(3)}">` +
    `${fits}${said}</span>`
  );
}

/** A group of the bar named over it, with a bracket the width of its blocks: conduction on the
 *  left, switching on the right (the Two Inks Rule). */
function lossGroup(name: string, value: number, total: number, from: number, tone: string, end: boolean): string {
  if (!(value > 0)) return "";
  const share = (value / total) * 100;
  const place = `left:${from.toFixed(3)}%;width:${share.toFixed(3)}%`;
  const words = `${name} <b>${sig(value)} W</b> <span class="dim">${Math.round(share)} %</span>`;
  const cls = `lb-group ${tone}${end ? " end" : ""}`;
  return `<span class="${cls}" style="${place}"><span class="lb-name">${words}</span></span>`;
}

/** Where the loss goes in the hottest position: conduction in bone, switching in orange, as one
 *  segmented bar whose blocks part on the ground, named by group over it and listed under it. */
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
  const total = Math.max(
    parts.reduce((a, [, v]) => a + Math.max(v, 0), 0),
    1e-12,
  );
  const cond = parts.filter(([, , c]) => c.startsWith("cond")).reduce((a, [, v]) => a + Math.max(v, 0), 0);
  const sw = parts.filter(([, , c]) => c.startsWith("sw")).reduce((a, [, v]) => a + Math.max(v, 0), 0);
  const groups =
    lossGroup("Conduction", cond, total, 0, "cond", false) +
    lossGroup("Switching", sw, total, (cond / total) * 100, "sw", true);
  const blocks = parts.map((part, k) => lossBlock(part, total, k)).join("");
  const rows = parts.map((part, k) => lossRow(part, total, k)).join("");
  const said =
    `Loss split of one switch position: ${sig(l.total)} W in all; ` +
    parts.map(([name, value]) => `${name} ${sig(value)} W`).join(", ");
  return (
    `<figure class="lossbar-fig"><div class="lb-groups" aria-hidden="true">${groups}</div>` +
    `<div class="lossbar" role="img" aria-label="${escape(said)}">${blocks}</div>` +
    `<ul class="legend">${rows}</ul></figure>`
  );
}

/** The bar of one thing compared: its parts end to end, then their total written after them. */
function compareRow(r: { name: string; parts: { value: number; tone: string }[] }, top: number, unit: string): string {
  const w = 400;
  let x = 0;
  const total = r.parts.reduce((a, p) => a + p.value, 0);
  // The parts part on the ground by 2 units, the gap taken from the part before it.
  const shown = r.parts.filter((p) => p.value > 0);
  const segments = shown
    .map((p, k) => {
      const width = (p.value / top) * w;
      const gap = k < shown.length - 1 && width > 4 ? 2 : 0;
      const size = `width="${Math.max(width - gap, 0).toFixed(1)}" height="16"`;
      const title = `<title>${sig(p.value)} ${unit}</title>`;
      const out = `<rect class="seg ${p.tone}" x="${x.toFixed(1)}" y="2" ${size} rx="2">${title}</rect>`;
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
