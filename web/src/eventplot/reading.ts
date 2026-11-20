// What the traces read at an instant, said as a line beside the plot, inline and full screen.

import { sig } from "../format";
import { names, valuesAt } from "./plot";
import { timeUnit } from "./zoom";
import type { Span } from "./zoom";

/** What the traces read at an instant, as the line under the plot says it. */
export function readingAt(kind: string, e: Parameters<typeof valuesAt>[0], t: number, v: Span): string {
  const at = valuesAt(e, t);
  const n = names(kind);
  const { unit, scale } = timeUnit(v);
  return (
    `At ${sig(t * scale, 4)} ${unit}: ${n.v_ds} ${sig(at.v_ds)} V, ${n.i} ${sig(at.i)} A, ` +
    `${n.v_gs} ${sig(at.v_gs)} V, ${n.p} ${sig(at.p)} W`
  );
}

/** Where a point on the screen falls in time on a plot drawn `viewW` wide whose plot runs
 *  from `x0` for `w`, in drawing units, and whether it is inside the plot. */
export function timeAt(
  clientX: number,
  rect: { left: number; width: number },
  v: Span,
  box: { x: number; w: number },
  viewW: number,
): { t: number; inside: boolean } {
  const x = ((clientX - rect.left) / rect.width) * viewW;
  const f = (x - box.x) / box.w;
  return { t: v.t0 + f * (v.t1 - v.t0), inside: f >= 0 && f <= 1 };
}
