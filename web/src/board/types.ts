// What POST /api/board sends back, as the page uses it: the legs found on a board, what else
// could have been taken for the loop, and the six figures of a layout file, each with the
// range it is believed in and what it rests on.

/** One figure: a value in its unit with the range it is believed in, or all three null where
 *  it could not be worked out, and then `rests_on` opens with why. */
export type BoardFigure = {
  value: number | null;
  low: number | null;
  high: number | null;
  unit: string;
  /** A share of the value is the usual of a kind of part, not read from the board. */
  assumed?: boolean;
  rests_on: string[];
  /** The loop inductance alone: its shares on the board and in the packages. */
  parts?: { board_nh?: number; package_nh?: number };
};

/** The six figures, by the names a layout file gives them. */
export const FIGURES = ["l_loop_nh", "l_cs_nh", "l_gate_nh", "r_loop_mohm", "c_dc_uf", "esl_nh"] as const;
export type FigureName = (typeof FIGURES)[number];

/** One leg found on the board, or chosen: its switches and the capacitors taken for its loop. */
export type Bridge = {
  leg: string;
  switch_node: string;
  high_side: string[];
  low_side: string[];
  capacitors: string[];
  series?: string[];
  figures?: Partial<Record<FigureName, BoardFigure>>;
};

export type BoardRead = {
  format?: string;
  name: string;
  stackup?: { assumed?: boolean; said?: string };
  nets?: { count?: number; dc_plus?: string; dc_minus?: string };
  parts?: number;
  bridges: Bridge[];
  candidates: {
    /** The pairs of nets that could be the supply, the likeliest first. */
    rails?: { dc_plus: string; dc_minus: string; capacitors?: number; legs?: number }[];
    switch_nodes?: string[];
    switches?: string[];
    capacitors?: { ref: string; value?: string }[];
    /** For each leg, by its switch node, the switches that fit each of its sides. */
    high_side?: Record<string, string[]>;
    low_side?: Record<string, string[]>;
  };
  /** The leg `figures` and `layout` are of. */
  taken?: string;
  figures: Partial<Record<FigureName, BoardFigure>>;
  /** The text of a layout file, as the switching event takes it. */
  layout: string;
  warnings: string[];
};

/** What is taken in place of what the reader guessed, as the route's "choose" holds it. */
export type Choose = {
  dc_plus?: string;
  dc_minus?: string;
  switch_nodes?: string[];
  leg?: string;
  high_side?: string[];
  low_side?: string[];
  capacitors?: string[];
};
