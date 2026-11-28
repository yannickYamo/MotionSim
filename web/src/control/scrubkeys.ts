// The scope by keyboard alone, on the cursor's slider: Shift with an arrow moves a fiftieth of
// what is shown (an arrow alone moves a thousandth, and Page Up and Page Down a tenth, as a
// slider does); + looks twice as close around the cursor, - twice as far, 0 at the whole run.

type View = [number, number] | null;

/** What a key does: the cursor moved, or the stretch shown changed; null for a key it leaves. */
export function scrubKey(
  { key, shift }: { key: string; shift: boolean },
  t: number,
  view: View,
  whole: [number, number],
): { t: number } | { view: View } | null {
  const [a, b] = view ?? whole;
  if (shift && (key === "ArrowRight" || key === "ArrowLeft")) {
    const step = (b - a) / 50;
    const to = t + (key === "ArrowRight" ? step : -step);
    return { t: Number(Math.min(b, Math.max(a, to)).toFixed(12)) };
  }
  if (key === "0") return { view: null };
  if (key !== "+" && key !== "=" && key !== "-") return null;
  const width = (b - a) * (key === "-" ? 2 : 0.5);
  if (width >= whole[1] - whole[0]) return { view: null };
  const start = Math.min(whole[1] - width, Math.max(whole[0], t - width / 2));
  const round = (v: number) => Number(v.toFixed(12));
  return { view: [round(start), round(start + width)] };
}
