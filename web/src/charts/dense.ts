// A series with more samples than its chart has pixels, drawn as it can be seen: the scope's
// own drawing (control/envelope.ts) on a chart of the results. Sparse, it is the plain line it
// always was. Dense, each pixel column keeps its first, lowest, highest and last sample; and
// where it turns back on itself faster than a line can be read (a junction's temperature
// swinging with every turn of the motor, through a long motion) it is drawn as the band from its
// lowest to its highest, in its own ink, in place of a solid block of line.

import { shape } from "../control/envelope";
import type { Box, Scale } from "./frame";

/** A series at the size it is drawn: its line as a path's d, and its band as markup in the
 *  tone's ink (empty where it has none). `attrs` is set on the band as it is on the line. */
export function dense(
  tone: string,
  [xs, ys]: [number[], (number | null)[]],
  scales: [Scale, Scale],
  box: Box,
  attrs = "",
): { line: string; band: string } {
  const drawn = shape(xs, ys, scales, [box.x, box.w]);
  return {
    line: drawn.line,
    band: drawn.band ? `<path class="series-env ${tone}"${attrs} d="${drawn.band}"/>` : "",
  };
}

/** The samples from one instant to another, with the one on each side: a chart that shows a
 *  stretch of a series gathers its columns from that stretch alone. */
export function stretch(xs: number[], ys: (number | null)[], from: number, to: number): [number[], (number | null)[]] {
  let a = 0;
  while (a < xs.length - 1 && xs[a + 1] < from) a++;
  let b = xs.length;
  while (b > a + 1 && xs[b - 2] > to) b--;
  return [xs.slice(a, b), ys.slice(a, b)];
}
