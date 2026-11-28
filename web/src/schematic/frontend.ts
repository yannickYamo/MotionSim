// The stage between the mains and the DC link, drawn at the left of the plate where a DC
// supply would stand: the mains as a source, the stage's own circuit, and its name under it.

import { escape, sig } from "../format";
import { LEFT, MID, RAIL_BOTTOM, RAIL_TOP } from "./geometry";

/** How much wider the plate is drawn to the left where a front end stands on it. */
export const FRONT_END_ROOM = 200;

/** The front end as the plate draws it. */
export interface FrontEndDrawn {
  /** The stage: rectifier, boost, interleaved, totem_pole, six_pulse, vienna, active. */
  id: string;
  /** Its name, or nothing while it is being worked out. */
  name: string | null;
  /** Whether it is the one recommended, or the user's own choice. */
  recommended: boolean;
  /** Its loss in W, once known. */
  loss: number | null;
  volts: number | null;
  hertz: number | null;
  phases: number;
}

const LAST_LEG = 40; // the leg of the stage nearest the link
const PITCH = 46; // between its legs
const HIGH = RAIL_TOP + 68;
const LOW = RAIL_BOTTOM - 68;
const RAILS_FROM = LEFT - 60; // where the plate's own rails begin

const wire = (d: string) => `<path class="wire" d="${d}"/>`;
const node = (x: number, y: number) => `<circle class="node" cx="${x}" cy="${y}" r="3"/>`;

/** A diode on a wire that runs up, conducting upwards. */
const diodeUp = (x: number, y: number) =>
  `<path class="solid" d="M${x - 6} ${y + 5}h12l-6 -10z"/><path d="M${x - 6} ${y - 5}h12"/>`;

/** A diode on a wire that runs to the right, conducting to the right. */
const diodeRight = (x: number, y: number) =>
  `<path class="solid" d="M${x - 5} ${y - 6}v12l10 -6z"/><path d="M${x + 5} ${y - 6}v12"/>`;

/** A switch on a wire that runs up: its gate, its channel and its two leads. */
const switchUp = (x: number, y: number) =>
  `<path d="M${x - 15} ${y}h8M${x - 7} ${y - 8}v16M${x - 3} ${y - 10}v20M${x - 3} ${y - 6}H${x}V${y - 15}` +
  `M${x - 3} ${y + 6}H${x}V${y + 15}"/><path class="solid" d="M${x - 2} ${y}l5 -3v6z"/>`;

/** An inductor on a wire that runs to the right, from x: three turns, 30 long. */
const inductor = (x: number, y: number) => `<path d="M${x} ${y}${"a5 5 0 0 1 10 0".repeat(3)}"/>`;

/** An inductor on a rail, its turns under the wire (clear of the plate's title). */
const railInductor = (x: number, y: number) => `<path d="M${x} ${y}${"a5 5 0 0 0 10 0".repeat(3)}"/>`;

/** One leg between the rails: two diodes, or two switches, and the wire through them. */
function leg(x: number, switched: boolean): string {
  const reach = switched ? 15 : 5;
  const part = switched ? switchUp : diodeUp;
  const through =
    `M${x} ${RAIL_TOP}V${HIGH - reach}M${x} ${HIGH + reach}V${LOW - reach}` + `M${x} ${LOW + reach}V${RAIL_BOTTOM}`;
  return wire(through) + part(x, HIGH) + part(x, LOW) + node(x, RAIL_TOP) + node(x, RAIL_BOTTOM);
}

/** Where line k of n leaves its leg. */
const tap = (k: number, n: number) => MID + (k - (n - 1) / 2) * (n === 2 ? 80 : 24);

/** The mains at x: one source between two lines, or three in a star, and what it is. */
function mains(x: number, f: FrontEndDrawn): string {
  const wave = (cx: number, cy: number, w: number) => `<path d="M${cx - w} ${cy}q${w / 2} ${-w} ${w} 0t${w} 0"/>`;
  const said = [f.volts === null ? "" : `${sig(f.volts)} V`, f.hertz === null ? "" : `${Math.round(f.hertz)} Hz`]
    .filter(Boolean)
    .join(" · ");
  // Under the source, from its left edge: it never runs off the plate.
  const text = `<text class="reading" x="${x - (f.phases === 3 ? 22 : 14)}" y="${MID + 62}">${escape(said)}</text>`;
  if (f.phases === 3) {
    const rings = [0, 1, 2]
      .map((k) => `<circle class="source-ring" cx="${x}" cy="${tap(k, 3)}" r="9"/>${wave(x, tap(k, 3), 5)}`)
      .join("");
    const star =
      wire(`M${x - 22} ${tap(0, 3)}V${tap(2, 3)}`) + [0, 1, 2].map((k) => wire(`M${x - 22} ${tap(k, 3)}h13`)).join("");
    return rings + star + node(x - 22, MID) + text;
  }
  return `<circle class="source-ring" cx="${x}" cy="${MID}" r="14"/>${wave(x, MID, 7)}${text}`;
}

/** The lines from the mains at x to the legs, each with its inductor where the stage has one. */
function lines(x: number, legs: number[], f: FrontEndDrawn, choke: boolean): string {
  const n = legs.length;
  return legs
    .map((at, k) => {
      const y = tap(k, n);
      // One phase: the source stands between the two lines. Three: each line has its own.
      const from = f.phases === 3 ? `M${x + 9} ${y}` : k === 0 ? `M${x} ${MID - 14}V${y}` : `M${x} ${MID + 14}V${y}`;
      const coil = choke && (f.phases === 3 || k === 0);
      const start = x + 30;
      const run = coil ? `${from}H${start}M${start + 30} ${y}H${at}` : `${from}H${at}`;
      return wire(run) + (coil ? inductor(start, y) : "") + node(at, y);
    })
    .join("");
}

/** A stage whose legs stand on the mains' side: a bridge of diodes, or of switches. */
function bridge(f: FrontEndDrawn, switched: boolean[], choke: boolean): { drawing: string; left: number } {
  const n = switched.length;
  const legs = switched.map((_, k) => LAST_LEG - PITCH * (n - 1 - k));
  // The mains stands far enough to the left for what is written under it to clear the first leg.
  const x = legs[0] - 96;
  // A six-pulse rectifier's choke stands on the link's rail, between the bridge and the capacitor.
  const linked = f.id === "six_pulse";
  const top = linked
    ? wire(`M${legs[0]} ${RAIL_TOP}H${LAST_LEG + 1}M${LAST_LEG + 31} ${RAIL_TOP}H${RAILS_FROM}`) +
      railInductor(LAST_LEG + 1, RAIL_TOP)
    : wire(`M${legs[0]} ${RAIL_TOP}H${RAILS_FROM}`);
  const rails = top + wire(`M${legs[0]} ${RAIL_BOTTOM}H${RAILS_FROM}`);
  const drawing = rails + legs.map((at, k) => leg(at, switched[k])).join("") + lines(x, legs, f, choke) + mains(x, f);
  return { drawing, left: x };
}

/** A boost stage behind a bridge of diodes: its inductor, its switch across the link and its
 *  diode; interleaved, a second cell beside the first, joined before and after. */
function boost(f: FrontEndDrawn): { drawing: string; left: number } {
  const legs = [-70, -70 + PITCH];
  const x = legs[0] - 96;
  const top = RAIL_TOP;
  const cell = (y: number, at: number) =>
    wire(
      `M-14 ${y}H-6M24 ${y}H55M65 ${y}H${y === top ? RAILS_FROM : 68}` +
        `M${at} ${y}V${MID - 15}M${at} ${MID + 15}V${RAIL_BOTTOM}`,
    ) +
    railInductor(-6, y) +
    switchUp(at, MID) +
    diodeRight(60, y) +
    node(at, y) +
    node(at, RAIL_BOTTOM);
  const rails = wire(`M${legs[0]} ${top}H-14M${legs[0]} ${RAIL_BOTTOM}H${RAILS_FROM}`);
  // The second cell stands under the first: it leaves the rail before the inductor and joins it after the diode.
  const under = top + 34;
  const second =
    f.id === "interleaved"
      ? wire(`M-14 ${top}V${under}M68 ${under}V${top}`) + cell(under, 50) + node(-14, top) + node(68, top)
      : "";
  const drawing =
    rails + legs.map((l) => leg(l, false)).join("") + cell(top, 28) + second + lines(x, legs, f, false) + mains(x, f);
  return { drawing, left: x };
}

/** Where the midpoint's wire of a Vienna stage runs up to the split link capacitor. */
const MID_BUS = 58;

/** A Vienna stage: a bridge of diodes, and from each line a switch that conducts both ways to
 *  the midpoint of the link, which is split in two capacitors (drawn by the plate). */
function vienna(f: FrontEndDrawn): { drawing: string; left: number } {
  const base = bridge(f, [false, false, false], true);
  const legs = [0, 1, 2].map((k) => LAST_LEG - PITCH * (2 - k));
  const blades = legs
    .map((at, k) => {
      const y = tap(k, 3);
      return wire(`M${at} ${y}H44M54 ${y}H${MID_BUS}`) + `<path class="blade" d="M44 ${y}l9 -5"/>` + node(MID_BUS, y);
    })
    .join("");
  const bus = wire(`M${MID_BUS} ${tap(0, 3)}V${tap(2, 3)}M${MID_BUS} ${MID}H${LEFT}`);
  return { drawing: base.drawing + blades + bus, left: base.left };
}

/** The circuit of each stage. */
const STAGES: Record<string, (f: FrontEndDrawn) => { drawing: string; left: number }> = {
  rectifier: (f) => bridge(f, [false, false], false),
  six_pulse: (f) => bridge(f, [false, false, false], false),
  boost,
  interleaved: boost,
  // A fast leg that switches at the carrier, and a slow one that turns with the mains.
  totem_pole: (f) => bridge(f, [true, true], true),
  vienna,
  active: (f) => bridge(f, [true, true, true], true),
};

/** The stage's name under its circuit, and whether it is the one recommended. */
function named(f: FrontEndDrawn): string {
  const whose = f.name === null ? "" : f.recommended ? " · recommended" : " · your choice";
  const lost = f.loss === null ? "" : ` · ${sig(f.loss)} W`;
  const name = `${f.name ?? "Front end, being worked out"}${whose}${lost}`;
  // From the plate's left edge, under the circuit.
  const x = 34 - FRONT_END_ROOM;
  return `<text class="reading" x="${x}" y="${RAIL_BOTTOM + 22}">${escape(name)}</text>`;
}

/** The front end at the left of the plate: the mains, the stage's circuit up to the plate's
 *  rails, and its name. */
export function frontEnd(f: FrontEndDrawn): string {
  const draw = STAGES[f.id] ?? STAGES[f.phases === 3 ? "six_pulse" : "rectifier"];
  return `<g class="source front-end-stage" data-stage="${escape(f.id)}">${draw(f).drawing}${named(f)}</g>`;
}

/** The front end in words, for a screen reader. */
export const frontEndSpoken = (f: FrontEndDrawn): string =>
  `, fed from the mains through ${f.name ? `a ${f.name}` : "a front end"}`;
