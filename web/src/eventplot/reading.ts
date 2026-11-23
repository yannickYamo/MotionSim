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
  // A trace at rest reads 0, not what the arithmetic left of it (1.89e-59 W): a value under a
  // millionth of the trace's own largest is nothing. The time likewise, against the span.
  const largest = (x: number[]) => x.reduce((m, y) => Math.max(m, Math.abs(y)), 0);
  const read = (value: number, of: number) => sig(Math.abs(value) < 1e-6 * of ? 0 : value);
  const when = Math.abs(t) < 1e-6 * Math.max(Math.abs(v.t0), Math.abs(v.t1)) ? 0 : t * scale;
  return (
    `At ${sig(when, 4)} ${unit}: ${n.v_ds} ${read(at.v_ds, largest(e.v_ds))} V, ` +
    `${n.i} ${read(at.i, largest(e.i))} A, ` +
    `${n.v_gs} ${read(at.v_gs, largest(e.v_gs))} V, ${n.p} ${read(at.p, largest(e.p))} W`
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
