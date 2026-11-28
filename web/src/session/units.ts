// Figures of the design that only make sense together: each set moves as one in every merge,
// on the page (sync.ts) and on the server (session.py, which keeps the same list:
// pagestate.UNITS). A read that brings one of them brings all of them, and an edit of one of
// them keeps all of them: never the parts on the page from one version and the parts ticked
// from another, which leaves a part on the page that is not ticked and nothing to go on with.

import type { Path } from "./paths";

// Between the markers, the list is JSON: the server's tests read it to hold the two the same.
// units:begin
export const UNITS: readonly (readonly string[])[] = [
  ["devices", "added", "lead"],
  ["typed", "typedOf"],
  ["kind", "kindPicked", "motors", "motorOwn"],
  ["supply", "supplyOwn"],
  [
    "load",
    "loadKind",
    "loadPicked",
    "loadUsual",
    "loadTouched",
    "loadTouchedBefore",
    "inertiaOwn",
    "segments",
    "phases",
    "mission",
  ],
  ["conditions.cooling", "conditions.rth_sink", "conditions.board_area", "conditions.sized", "conditions.sizedFor"],
];
// units:end

export const UNIT_PATHS: readonly (readonly Path[])[] = UNITS.map((u) => u.map((p) => p.split(".")));
