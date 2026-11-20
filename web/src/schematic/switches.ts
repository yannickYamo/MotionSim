// One switch as it is drawn: its symbol, its diode, its gate and the glow of its heat, and
// the packages drawn round the switches.

import { escape } from "../format";
import { RAIL_BOTTOM, RAIL_TOP } from "./geometry";

/** How the part is packaged: what is drawn around the switches and at their gates. */
export interface Packaging {
  positions: number;
  driver: boolean;
}

/** One switch as it is drawn: where it is, its name, how warm it runs, what is written beside
 *  it, whether it is over its rating or ruled out, and what kind of part and package it is. */
interface SwitchDrawn {
  x: number;
  y: number;
  id: string;
  level: number;
  text: string;
  over: boolean;
  fet: boolean;
  pack: Packaging | null;
  ruledOut: boolean;
}

/** The glow behind a switch that is losing power: wider and warmer as its junction heats. */
function glowOf({ x, y, level, over, ruledOut }: SwitchDrawn, order: number): string {
  const warmth = Math.min(level, 1);
  const name = `heat${over ? " over" : ruledOut ? " ruled-out" : ""}`;
  return level > 0
    ? `<circle class="${name}" cx="${x}" cy="${y}" r="${22 + 8 * warmth}" ` +
        `style="--heat:${warmth.toFixed(3)};--i:${order}"/>`
    : "";
}

/** The symbol of a field-effect transistor: its gate, its channel in three parts, and its arrow. */
function fetBody(x: number, y: number): string {
  const lines = [
    `M${x - 22} ${y}h10`,
    `M${x - 12} ${y - 13}v26`,
    `M${x - 7} ${y - 15}v8`,
    `M${x - 7} ${y - 4}v8`,
    `M${x - 7} ${y + 7}v8`,
    `M${x - 7} ${y - 11}h9v-12`,
    `M${x - 7} ${y + 11}h9v12`,
    `M${x - 7} ${y}h9v11`,
  ].join("");
  return `<path d="${lines}"/><path class="solid" d="M${x - 6} ${y}l6 -3v6z"/>`;
}

/** The symbol of a bipolar switch: its gate, its collector and emitter, and the emitter's arrow. */
function bipolarBody(x: number, y: number): string {
  const lines = [
    `M${x - 22} ${y}h11`,
    `M${x - 11} ${y - 13}v26`,
    `M${x - 11} ${y - 6}l13 -9v-8`,
    `M${x - 11} ${y + 6}l13 9v8`,
  ].join("");
  return `<path d="${lines}"/><path class="solid" d="M${x + 2} ${y + 15}l-7 -1l4 -6z"/>`;
}

/** The diode across a switch, drawn to its right. */
function diodeOf(x: number, y: number): string {
  const leads = `M${x + 2} ${y - 23}h16v15M${x + 18} ${y + 23}h-16M${x + 18} ${y + 23}v-15`;
  const arrow = `<path class="solid" d="M${x + 12} ${y + 6}h12l-6 -11z"/>`;
  return `<path d="${leads}"/>${arrow}<path d="M${x + 12} ${y - 5}h12"/>`;
}

/** What is drawn at a switch's gate: a driver inside the package, or a resistor and a terminal. */
function gateOf(x: number, y: number, pack: Packaging | null): string {
  if (!pack) return "";
  if (pack.driver) {
    const block = `<rect class="driver" x="${x - 42}" y="${y - 9}" width="18" height="18" rx="2"/>`;
    const pulse = `<path class="driver-mark" d="M${x - 39} ${y + 4}h3v-8h6v8h3"/>`;
    return `${block}${pulse}<path d="M${x - 24} ${y}h2M${x - 48} ${y}h6"/>`;
  }
  const resistor = `<path d="M${x - 50} ${y}h4l2 -4l4 8l4 -8l4 8l4 -8l2 4h4"/>`;
  return `${resistor}<circle class="pin" cx="${x - 53}" cy="${y}" r="3"/>`;
}

export function transistor(s: SwitchDrawn): string {
  const { x, y, id, text, pack } = s;
  // In the order of their names, Q1 first, for the glows to come on one after another.
  const glow = glowOf(s, Number(id.slice(1)) - 1 || 0);
  // Gate from the left, channel in the middle, diode on the right.
  const body = s.fet ? fetBody(x, y) : bipolarBody(x, y);
  const diode = diodeOf(x, y);
  const label = text ? `<text class="reading" x="${x + 34}" y="${y + 5}">${escape(text)}</text>` : "";
  // A gate driven from outside: its gate resistor, drawn as a resistor, then the terminal
  // the driver connects to. A driver inside the package: a block marked with a pulse.
  const gate = gateOf(x, y, pack);
  const symbol = `<g class="symbol">${body}${diode}${gate}</g>`;
  const refX = x - (pack && !pack.driver ? 31 : 26);
  const ref = `<text class="ref" x="${refX}" y="${y - 18}" text-anchor="end">${id}</text>`;
  return `<g class="switch" data-level="${s.level.toFixed(2)}">${glow}${symbol}${ref}${label}</g>`;
}

/** The outline of each package: one a switch, one a leg, or one round the whole bridge. */
export function packages(legs: number[], pack: Packaging): { drawing: string; count: number } {
  const top = RAIL_TOP + 68;
  const bottom = RAIL_BOTTOM - 68;
  const box = (x0: number, y0: number, x1: number, y1: number) =>
    `<rect class="package" x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" rx="5"/>`;
  if (pack.positions < 2) {
    const each = legs.flatMap((x) => [top, bottom].map((y) => box(x - 25, y - 30, x + 30, y + 30)));
    return { drawing: each.join(""), count: each.length };
  }
  const span = Math.max(1, Math.floor(pack.positions / 2)); // legs in one package
  // A driver inside the package is within its outline; a gate resistor is outside it.
  const left = pack.driver ? 54 : 25;
  const groups: string[] = [];
  for (let k = 0; k < legs.length; k += span) {
    const last = legs[Math.min(k + span, legs.length) - 1];
    groups.push(box(legs[k] - left, top - 32, last + 30, bottom + 32));
  }
  return { drawing: groups.join(""), count: groups.length };
}

/** The package in words, for the plate's title. */
export function packageName(pack: Packaging, count: number): string {
  const many = count > 1;
  if (pack.positions < 2) return `${count} discrete parts`;
  const kind = pack.driver
    ? "IPM"
    : pack.positions >= 6
      ? "six-pack module"
      : pack.positions >= 4
        ? "two-leg module"
        : "half-bridge module";
  const drivers = pack.driver ? ", gate drivers built in" : "";
  return `${many ? count : "one"} ${kind}${many ? "s" : ""}${drivers}`;
}
