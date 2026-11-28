// The power stage, drawn as a circuit diagram that carries the result: each switch warms
// towards orange as its junction heats, and the motor is drawn as the kind of machine it is.

import type { Position, Result, Stage } from "./api";
import { degrees, escape, sig } from "./format";
import { FRONT_END_ROOM, frontEnd, frontEndSpoken } from "./schematic/frontend";
import type { FrontEndDrawn } from "./schematic/frontend";
import { H, LEFT, MID, RAIL_BOTTOM, RAIL_TOP, tapY, W } from "./schematic/geometry";
import { motor, motorName } from "./schematic/motor";
import type { Rotor } from "./schematic/motor";
import { packageName, packages, transistor } from "./schematic/switches";
import type { Packaging } from "./schematic/switches";

interface Drawn {
  letters: string[];
  legs: number[];
  label: string;
}

function layout(kind: string): Drawn {
  const bridge = kind === "dc" || kind === "dc_series";
  const count = bridge ? 2 : kind === "stepper" ? 4 : 3;
  const first = 232;
  const last = kind === "stepper" ? 520 : 500;
  const legs = Array.from({ length: count }, (_, k) => first + (k * (last - first)) / Math.max(count - 1, 1));
  const letters = kind === "stepper" ? ["A+", "A−", "B+", "B−"] : ["A", "B", "C", "D"].slice(0, count);
  const label = bridge ? "H-bridge" : kind === "stepper" ? "Two H-bridges" : "Three-phase inverter";
  return { letters, legs, label };
}

/** The result row that describes one drawn switch. */
function positionFor(result: Result | null, leg: number, side: "high" | "low", kind: string): Position | null {
  if (!result) return null;
  const all = result.positions;
  if (all.length === 1) return all[0];
  const letter = "ABCD"[leg];
  return (
    all.find((p) => p.name.includes(`leg ${letter} ${side}`)) ??
    all.find((p) => p.name.startsWith(side)) ??
    (kind === "stepper" ? all[0] : null)
  );
}

function heat(position: Position | null, result: Result | null, tSink: number): number {
  if (!position || !result) return 0;
  const span = Math.max(result.tj_max - tSink, 1);
  return Math.min(Math.max((position.tj - tSink) / span, 0), 1.15);
}

interface SchematicInput {
  kind: string;
  stage: Stage | null;
  result: Result | null;
  tSink: number;
  vdc: number | null; // null until the user has given the supply
  fet: boolean;
  blocked: boolean;
  /** The part on the drawing is ruled out at this design point. */
  ruledOut?: boolean;
  deviceName: string | null;
  battery: boolean;
  /** The stage between the mains and the link, where the drive is fed from the mains. */
  frontEnd?: FrontEndDrawn | null;
  pack: Packaging | null;
  parallel: number; // devices side by side at each switch
  motorKnown: boolean; // false until the user has reached the motor step
  rotor: Rotor;
  rpm: number;
}

/** The cells of a battery, where the supply stands. */
const CELLS =
  `<path d="M${LEFT - 76} ${MID - 14}h32M${LEFT - 68} ${MID - 5}h16` +
  `M${LEFT - 76} ${MID + 5}h32M${LEFT - 68} ${MID + 14}h16"/>`;

/** The circle of a supply that only delivers, with its plus and minus. */
const SOURCE_CIRCLE =
  `<circle class="source-ring" cx="${LEFT - 60}" cy="${MID}" r="14"/>` +
  `<path d="M${LEFT - 60} ${MID - 9}v6M${LEFT - 63} ${MID - 6}h6M${LEFT - 63} ${MID + 7}h6"/>`;

/** The wires from the rails to the supply, and the capacitor across the rails beside it. */
const SOURCE_WIRES =
  `<path class="wire" d="M${LEFT - 60} ${RAIL_TOP}V${MID - 14}` + `M${LEFT - 60} ${MID + 14}V${RAIL_BOTTOM}"/>`;
const CAPACITOR =
  `<path class="wire" d="M${LEFT} ${RAIL_TOP}V${MID - 6}M${LEFT} ${MID + 6}V${RAIL_BOTTOM}"/>` +
  `<path d="M${LEFT - 13} ${MID - 6}h26M${LEFT - 13} ${MID + 6}h26"/>`;

/** The link split in two capacitors about its midpoint, as a three-level front end needs it. */
const CAPACITOR_SPLIT =
  `<path class="wire" d="M${LEFT} ${RAIL_TOP}V${MID - 66}M${LEFT} ${MID - 54}V${MID + 54}` +
  `M${LEFT} ${MID + 66}V${RAIL_BOTTOM}"/>` +
  `<path d="${[-66, -54, 54, 66].map((y) => `M${LEFT - 13} ${MID + y}h26`).join("")}"/>` +
  `<circle class="node" cx="${LEFT}" cy="${MID}" r="3"/>`;

/** The supply at the left of the drawing, with its voltage once that is known. */
function sourceOf(battery: boolean, vdc: number | null, fed: FrontEndDrawn | null): string {
  if (fed) {
    // Fed from the mains: the stage stands where the supply would, and the voltage is the link's.
    const split = fed.id === "vienna";
    const y = split ? MID - 80 : MID + 5;
    const link =
      vdc === null ? "" : `<text x="${LEFT - 20}" y="${y}" text-anchor="end" class="reading">${sig(vdc)} V</text>`;
    return `${frontEnd(fed)}<g class="source">${link}${split ? CAPACITOR_SPLIT : CAPACITOR}</g>`;
  }
  // A battery is drawn as cells; a supply that only delivers, as a source circle.
  const symbol = battery ? CELLS : SOURCE_CIRCLE;
  const volts =
    vdc === null ? "" : `<text x="${LEFT - 68}" y="${MID + 38}" text-anchor="end" class="reading">${sig(vdc)} V</text>`;
  return `<g class="source">${SOURCE_WIRES}${symbol}${volts}${CAPACITOR}</g>`;
}

/** The loss and junction temperature written beside a switch. */
const reading = (p: Position | null) => (p ? `${sig(p.total)} W  ${degrees(p.tj)}${p.count > 1 ? "  each" : ""}` : "");

/** One switch of leg k, warmed by its result and with its reading where that is written. */
function legSwitch(input: SchematicInput, legs: number[], k: number, side: "high" | "low"): string {
  const { kind, result } = input;
  const p = positionFor(result, k, side, kind);
  const over = !!(p && result && p.tj > result.tj_max);
  // On a part ruled out, the hottest switch glows in the colour of a failure, not of heat.
  const failing = !!(input.ruledOut && p && result && p.tj >= result.tj_peak - 0.5);
  // A reading is written once for a run of switches that share it, on the last of the run.
  const shown = k === legs.length - 1 || positionFor(result, k + 1, side, kind) !== p ? reading(p) : "";
  const y = side === "high" ? RAIL_TOP + 68 : RAIL_BOTTOM - 68;
  const id = `Q${2 * k + (side === "high" ? 1 : 2)}`;
  return transistor({
    x: legs[k],
    y,
    id,
    level: heat(p, result, input.tSink),
    text: shown,
    over,
    fet: input.fet,
    pack: input.pack,
    ruledOut: failing,
  });
}

/** A dot where wires join. */
const node = (x: number, y: number) => `<circle class="node" cx="${x}" cy="${y}" r="3"/>`;

/** Leg k of the stage: its wires between the rails, its two switches, its joints and its letter. */
function legOf(input: SchematicInput, drawn: Drawn, k: number): string {
  const { legs, letters } = drawn;
  const x = legs[k];
  const tap = tapY(k, legs.length);
  const top = legSwitch(input, legs, k, "high");
  const bottom = legSwitch(input, legs, k, "low");
  const path =
    `M${x} ${RAIL_TOP}V${RAIL_TOP + 45}M${x} ${RAIL_TOP + 91}V${RAIL_BOTTOM - 91}` +
    `M${x} ${RAIL_BOTTOM - 45}V${RAIL_BOTTOM}`;
  const wires = `<path class="wire" d="${path}"/>`;
  const nodes = node(x, tap) + node(x, RAIL_TOP) + node(x, RAIL_BOTTOM);
  const name = `<text class="leg" x="${x - 9}" y="${tap - 8}" text-anchor="end">${letters[k]}</text>`;
  return wires + top + bottom + nodes + name;
}

/** The plate's title: what the stage is and how it is built, and the device under it. */
function captionOf(label: string, built: string, deviceName: string | null, x: number): string {
  const part = deviceName
    ? escape(deviceName.length > 64 ? `${deviceName.slice(0, 63)}…` : deviceName)
    : "no device chosen yet";
  const title = `<text class="plate-title" x="${x}" y="32">${label} · ${built}</text>`;
  return `${title}<text class="plate-title part" x="${x}" y="52">${part}</text>`;
}

/** The plate's notes: the modulation scheme at the left, the motor and its peak current at the right. */
function notesOf(input: SchematicInput): string {
  const { stage } = input;
  const what = motorName(input.rotor);
  // Clear of the stage's name where a front end is drawn, at the left edge otherwise.
  const [x, y] = input.frontEnd ? [LEFT + 40, H - 28] : [34, H - 44];
  const scheme = `<text class="plate-note" x="${x}" y="${y}">${stage ? escape(stage.scheme) : ""}</text>`;
  const said = `${input.motorKnown ? `Motor: ${what}` : ""}${stage ? ` · ${sig(stage.i_peak)} A peak` : ""}`;
  return `${scheme}<text class="plate-note" x="${W - 34}" y="${H - 28}" text-anchor="end">${said}</text>`;
}

/** The panel laid over a stage that cannot run, saying so. */
const BLOCKED =
  `<g class="blocked"><rect x="26" y="46" width="${W - 52}" height="${H - 92}"/>` +
  `<text x="${W / 2}" y="${MID + 6}" text-anchor="middle">This combination cannot run</text></g>`;

/** The hatching the drawing can be filled with. */
const HATCH =
  `<defs><pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">` +
  `<path d="M0 0v10" class="hatch-line"/></pattern></defs>`;

/** The opening tag of the drawing, with the stage and its result in words for a screen reader. */
function openingTag(input: SchematicInput, label: string, built: string): string {
  const { stage, result, blocked } = input;
  const state = `${blocked ? " is-blocked" : ""}${stage ? " is-live" : ""}`;
  const outcome = result ? `, total loss ${sig(result.loss)} watts, hottest junction ${degrees(result.tj_peak)}` : "";
  const fed = input.frontEnd ?? null;
  const spoken = `${label}, ${built}${fed ? escape(frontEndSpoken(fed)) : ""}${outcome}`;
  const x0 = fed ? -FRONT_END_ROOM : 0;
  const mains = fed ? " has-front-end" : "";
  return `<svg class="schematic${state}${mains}" viewBox="${x0} 0 ${W - x0} ${H}" role="img" aria-label="${spoken}">`;
}

export function schematic(input: SchematicInput): string {
  const { kind, blocked, pack } = input;
  const drawn = layout(kind);
  const { legs } = drawn;
  // The kind of stage follows from the motor; before that it is not named.
  const stage = input.motorKnown ? drawn.label : "Power stage";
  // Fed from the mains, the plate is both stages: the front end is named first.
  const label = input.frontEnd?.name ? `${input.frontEnd.name} and ${stage.toLowerCase()}` : stage;
  const right = legs[legs.length - 1];
  const rails = `<path class="wire" d="M${LEFT - 60} ${RAIL_TOP}H${right}M${LEFT - 60} ${RAIL_BOTTOM}H${right}"/>`;
  const source = sourceOf(input.battery, input.vdc, input.frontEnd ?? null);
  const switches = legs.map((_, k) => legOf(input, drawn, k)).join("");
  const outline = pack ? packages(legs, pack) : null;
  const beside = input.parallel > 1 ? `, ${input.parallel} in parallel at each switch` : "";
  const built = (outline ? packageName(pack!, outline.count) : `${legs.length * 2} switches`) + beside;
  // The title stands at the plate's left edge, which is further left where a front end is drawn.
  const caption = captionOf(label, built, input.deviceName, 34 - (input.frontEnd ? FRONT_END_ROOM : 0));
  const machine = motor(input.rotor, blocked ? 0 : input.rpm, legs, input.motorKnown);
  const plate = caption + (outline?.drawing ?? "") + rails + source;
  const stop = blocked ? BLOCKED : "";
  return (
    openingTag(input, label, built) +
    "\n" +
    HATCH +
    "\n" +
    plate +
    switches +
    machine +
    notesOf(input) +
    stop +
    "</svg>"
  );
}
