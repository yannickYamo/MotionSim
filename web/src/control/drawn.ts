// What a drawing of a scheme is made of: the sizes its blocks and wires are set out with,
// and the blocks, the wires, the trunks and the junctions as they are handed to what draws them.

import type { Sym } from "./symbols";
import type { Block } from "./types";

/** Every block is as tall as this; its width is its symbol's, and every block of a column
 *  is as wide as the widest of them, so that the drawing stands on a grid. */
export const BLOCK_H = 88;
/** The size its short name is set at, in the drawing's units: at least 12 px on the screen
 *  once the drawing of the usual scheme is fitted to a laptop's window. */
export const CAPTION_PX = 15;
/** The size a symbol's letters are set at. */
export const SYMBOL_PX = 21;
export const GAIN = /^(k[pid](_|$)|gain|weight|bandwidth)/;
/** From one lane to the next, in a gap between two columns. */
export const LANE = 8;
/** From one level lane to the next, in a channel between two rows: the lines that come back
 *  from the motor run side by side for most of the drawing's width, and are told apart only
 *  with room between them (about 12 px on the screen once the drawing is fitted to a laptop). */
export const CHANNEL_LANE = 13;
/** Between a block's edge and the nearest lane: room for the arrow, the name and the bus mark. */
export const ENTRY = 40;
export const PAD = 12;
export const SUM_R = 12;
/** From a summing junction's circle to its block: the error's own arrow. */
export const SUM_OUT = 20;
/** What a summing junction takes of the gap before its block: its circle and its arrow. */
export const SUM_ROOM = 2 * SUM_R + SUM_OUT;
export const BAND_HEAD = 28;
/** The radius of the motor's circle: its wires come to the circle, not to its box. */
export const MACHINE_R = 24;

export type Role = "block" | "reference" | "inverter" | "motor";

export interface Output {
  wire: string;
  name: string;
  unit: string;
  about: string;
}

export interface LNode {
  id: string;
  role: Role;
  kind: string;
  /** The part the registry says the kind plays in a scheme, where it says. */
  hint: string;
  title: string;
  /** False for a kind of block the registry does not describe. */
  known: boolean;
  loop: string;
  /** A regulator: its references and what is measured meet in a summing junction. */
  sum: boolean;
  block: Block | null;
  /** The figures its inspector offers to tune by dragging: its gains, four at most. */
  gains: string[];
  /** What it is drawn as: its symbol and its short name. */
  symbol: Sym;
  inputs: { port: string; wire: string }[];
  outputs: Output[];
  /** The row it stands in: 0 for the forward path, 1 and more for the way back. */
  row: number;
  col: number;
  x: number;
  y: number;
  w: number;
  h: number;
  /** The height its row's line runs at: its wires leave and come in there. */
  axis: number;
}

/** A name on a wire, with what is written small under its line: i and abc. */
export interface Word {
  text: string;
  sub: string;
  /** Asked for, not measured: written with a star, as ω* is. */
  star: boolean;
}

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface LLabel extends Box {
  words: Word[];
}

export interface LEdge {
  id: string;
  /** The first of its wires. */
  wire: string;
  /** The signals that travel in it: more than one makes it a bus. */
  wires: string[];
  ports: string[];
  /** How many lines it stands for. */
  n: number;
  from: string;
  to: string;
  port: string;
  /** Against the flow of the forward path: a wire of the way back. */
  back: boolean;
  /** Measured, at a summing junction: it is taken away from the reference there. */
  minus: boolean;
  /** It ends at its block's summing junction, not at the block. */
  atSum: boolean;
  /** The side of its block it comes in by. */
  into: "side" | "top" | "bottom";
  points: [number, number][];
  /** Its name, on a straight run of its own. */
  label: LLabel | null;
  /** Where a bus is marked with the count of its lines; beside an upright stretch the count is
   *  written on the side its name is not (left, flipped, when the name is on the right). */
  tick: { x: number; y: number; upright: boolean; flip: boolean } | null;
}

/** One stretch of a trunk: straight, with the signals that travel in it and the wires it is part of. */
export interface LSeg {
  a: [number, number];
  b: [number, number];
  n: number;
  edges: string[];
}

/** Everything that leaves one block: a trunk that branches at its dots. */
export interface LNet {
  from: string;
  segs: LSeg[];
  dots: { x: number; y: number; edges: string[] }[];
}

export interface LSum {
  node: string;
  x: number;
  y: number;
  r: number;
  /** Where the error's arrow lands: the regulator's edge. */
  out: number;
  signs: { text: "+" | "−"; x: number; y: number }[];
}

export interface LGroup {
  loop: string;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Where a wire of one trunk crosses a wire of another without joining it: the level one is
 *  broken there, so that a crossing never reads as a junction. */
export interface LCross {
  x: number;
  y: number;
  /** The lines in the upright stretch that goes on through. */
  n: number;
  edges: string[];
}

export interface Layout {
  nodes: LNode[];
  edges: LEdge[];
  nets: LNet[];
  crossings: LCross[];
  sums: LSum[];
  groups: LGroup[];
  width: number;
  height: number;
  /** The block the arrow keys reach from each block, each way. */
  near: Record<string, Partial<Record<"left" | "right" | "up" | "down", string>>>;
}

export const REFERENCE = "cmd";
export const INVERTER = "inverter";
export const MOTOR = "plant";
