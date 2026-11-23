// One of the event's four plots full screen (dialog.ts): it opens at the zoom the plot under
// the loss chart is at and leaves that plot at the zoom it was brought to, and the keyboard
// goes back to the plot it was opened from.

import { openPlot } from "./dialog";
import type { Plottable } from "./dialog";
import { partSvg, partTitle, TRACES } from "./part";
import type { Part, PartDrawn } from "./part";
import { exportPdf, pointSaid } from "./pdf";
import { valuesAt as readValues, yOf } from "./plot";
import { readingAt } from "./reading";
import { edgeOf, eventNow, resetSpan, setSpan, spanOf } from "./spans";
import type { Which } from "./svg";
import { firstSpan, NARROWEST, whole } from "./zoom";

/** Open an edge's pair of traces full screen. */
export function openFull(which: Which, part: Part): void {
  const ev = eventNow();
  if (!ev) return;
  const edge = () => edgeOf(eventNow() ?? ev, which);
  const p: Plottable<PartDrawn> = {
    // Read afresh at each drawing: a later answer drawn behind the dialog is named as it is drawn.
    get title() {
      return partTitle((eventNow() ?? ev).kind, which, part);
    },
    get said() {
      return pointSaid(eventNow() ?? ev);
    },
    narrowest: NARROWEST,
    span: () => spanOf(which, edge()),
    whole: () => whole(edge()),
    first: () => firstSpan(edge()),
    set: (v) => setSpan(which, v), // the plot under the loss chart follows, so closing keeps the zoom
    reset: () => resetSpan(which),
    draw: (v, w, h) => partSvg(eventNow() ?? ev, which, part, v, w, h),
    read: (t, v, drawn) => {
      const e = edge();
      const [a, b] = TRACES[part];
      const at = readValues(e, t);
      return {
        ys: [yOf(drawn.box, drawn.ranges[0])(at[a]), yOf(drawn.box, drawn.ranges[1])(at[b])],
        text: readingAt(ev.kind, e, t, v),
      };
    },
    pdf: (v) => exportPdf(eventNow() ?? ev, which, part, v),
    back: () => document.querySelector<HTMLElement>(`[data-edge-plot="${which}"]`),
    meta: { which, part },
  };
  openPlot(p);
}
