// A first figure for the commutation loop's inductance, from the board's geometry: the loop
// laid out as a strip going out on one layer and back on the one beneath, the two parted by
// the board between them. Its inductance is that of two parallel plates, μ0·l·h/w, which
// holds when the strip is several times wider than the layers are apart; the packages' own
// inductance is added, since the loop runs through both switches.

export const MU0 = 4e-7 * Math.PI; // H/m

export interface Geometry {
  /** How far the loop runs, out and back, mm. */
  length: number;
  /** The width of the strips, mm. */
  width: number;
  /** How far apart the two layers are, mm. */
  spacing: number;
  /** Both packages' own inductance, nH. */
  packages: number;
}

export interface Estimate {
  /** The board's part, nH. */
  board: number;
  /** The board and the packages, nH. */
  total: number;
  /** Where the geometry is outside what the formula holds for, why; else empty. */
  caution: string;
}

/** The loop inductance of the geometry, or null where a figure is missing or not above zero. */
export function loopInductance(g: Partial<Geometry>): Estimate | null {
  const { length, width, spacing } = g;
  const packages = g.packages ?? 0;
  const ok = (x: number | undefined): x is number => typeof x === "number" && Number.isFinite(x) && x > 0;
  if (!ok(length) || !ok(width) || !ok(spacing) || !(packages >= 0)) return null;
  const board = ((MU0 * length * spacing) / width) * 1e6; // mm·mm/mm = mm → ×1e-3 m, H → ×1e9 nH
  const caution =
    width < 3 * spacing
      ? "The strips are less than three times wider than the layers are apart: the field spreads past their " +
        "edges, and the figure is low."
      : "";
  return { board, total: board + packages, caution };
}
