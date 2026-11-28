// The cursor's flags: beside the hairline, at each series, a small tag with the series' value
// at that instant, in the mono face. Markup made once with the drawing, then moved and written
// as the pointer moves; two flags on one side of the hairline never lie on each other.

import type { Box } from "./frame";

/** A flag's height, the gap it keeps from the hairline, and about how wide a figure's letter is. */
export const FLAG_H = 16;
const GAP = 7;
const LETTER = 7;

export const flagWidth = (text: string): number => [...text].length * LETTER + 22;

/** One flag, hidden until the cursor is on the plot: its ground, a square of the series'
 *  colour, and its figure. `cls` is the series' own class, which colours the square. */
export const flagMarkup = (cls: string): string =>
  `<g class="plot-flag ${cls}" visibility="hidden"><rect height="${FLAG_H}" rx="2"/>` +
  `<rect class="plot-sw ${cls}" x="5" y="5" width="6" height="6" rx="1"/>` +
  `<text x="16" y="12"></text></g>`;

/** Where one flag points: how high its series is there (null where it has no value), what it
 *  reads, and the plot it must stay inside. */
export interface FlagAt {
  y: number | null;
  text: string;
  box: Box;
}

/** A flag's place: left of the hairline or right of it, and its top edge. */
export interface FlagPlace {
  left: boolean;
  x: number;
  y: number;
  w: number;
}

const within = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));

/** Where each flag goes for a hairline at `x` (in the drawing's units): by turns left and right
 *  of it, on the side that has room, level with its series and clear of the flags before it. */
export function flagPlaces(at: FlagAt[], x: number): (FlagPlace | null)[] {
  const taken: FlagPlace[] = [];
  return at.map((f, k) => {
    if (f.y === null || !Number.isFinite(f.y)) return null;
    const w = flagWidth(f.text);
    let left = k % 2 === 0;
    if (left && x - GAP - w < f.box.x) left = false;
    else if (!left && x + GAP + w > f.box.x + f.box.w) left = true;
    const lo = f.box.y + 1;
    const hi = f.box.y + f.box.h - FLAG_H - 1;
    let y = within(f.y - FLAG_H / 2, lo, hi);
    for (const t of taken) {
      if (t.left !== left || Math.abs(t.y - y) >= FLAG_H + 2) continue;
      // Under the one in its way where there is room, else over it.
      const under = t.y + FLAG_H + 2;
      y = under <= hi ? under : within(t.y - FLAG_H - 2, lo, hi);
    }
    const place = { left, x: left ? -GAP - w : GAP, y, w };
    taken.push(place);
    return place;
  });
}

/** Move the flags of a cursor (a group already moved to the hairline) and write their figures. */
export function setFlags(flags: Element[], at: FlagAt[], x: number): void {
  flagPlaces(at, x).forEach((p, k) => {
    const g = flags[k];
    if (!g) return;
    if (!p) return void g.setAttribute("visibility", "hidden");
    g.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`);
    g.setAttribute("visibility", "inherit");
    g.querySelector("rect")?.setAttribute("width", p.w.toFixed(1));
    const text = g.querySelector("text");
    if (text && text.textContent !== at[k].text) text.textContent = at[k].text;
  });
}
