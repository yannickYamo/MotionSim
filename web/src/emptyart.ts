// The drawings of an empty place, in the product's own line language: schematic strokes in
// bone at 1.4 with round ends, hairline frames, and orange as the one accent, on the one thing
// the place waits for. Each draws itself in once in a visit, and stands still after; under
// reduced motion it is simply there. Shared by the page and the control lab.

/** Which empty places there are. */
export type Empty = "part" | "compare" | "run" | "signals";

/** The places already drawn in this visit: drawn in once, then shown standing. */
const drawn = new Set<Empty>();

/** A stroke of the drawing. `tone`: "" bone 2, "dim" bone 3, "accent" orange, "rule" a hairline. */
const stroke = (d: string, tone = "", dashed = false): string =>
  `<path class="ea-l${tone ? ` ${tone}` : ""}${dashed ? " dashed" : ""}" d="${d}"${dashed ? "" : ' pathLength="1"'}/>`;

/** A datasheet handed to a transistor: the part to bring. */
function part(): string {
  const sheet =
    stroke("M14 10h44l12 12v86h-56z") +
    stroke("M58 10v12h12") +
    stroke("M22 26h26", "dim") +
    stroke("M22 40h14M42 40h20M22 50h14M42 50h20M22 60h14M42 60h20", "dim") +
    stroke("M22 74v24h40", "rule") +
    stroke("M24 96c8-2 12-14 18-16s10 6 18 6", "dim");
  // An n-channel MOSFET as it is drawn: gate and its plate, the channel in three, drain up,
  // source down with the body tied to it, and the body diode beside them.
  const fet =
    stroke("M146 60h14M160 46v28") +
    stroke("M166 42v10M166 55v10M166 68v10") +
    stroke("M166 46h16v-24M166 74h16v24M166 60h16v14") +
    stroke("M172 56l-5 4 5 4", "dim") +
    stroke("M182 32h16v16M182 88h16v-16M192 64l6-8 6 8zM192 56h12", "dim");
  const hand = stroke("M80 60h54", "accent", true) + stroke("M128 54l7 6-7 6", "accent");
  return svg("part", "0 0 216 118", sheet + hand + fet);
}

/** A comparison of one column: the design's, and the place a second one comes. */
function compare(): string {
  const one =
    stroke("M12 14h70v92h-70z") +
    stroke("M12 30h70", "rule") +
    stroke("M20 22h30", "dim") +
    stroke("M12 50h70M12 70h70M12 90h70", "rule") +
    stroke("M56 40h18M50 60h24M60 80h14M54 100h20");
  const two = stroke("M96 14h70v92h-70z", "dim", true) + stroke("M131 50v20M121 60h20", "accent");
  return svg("compare", "0 0 178 120", one + two);
}

/** A scope with nothing run: its grid, and a step answer still to come. */
function run(): string {
  const frame =
    stroke("M10 12h188v86h-188z") + stroke("M10 33.5h188M10 55h188M10 76.5h188M57 12v86M104 12v86M151 12v86", "rule");
  const asked = stroke("M24 80h22v-40h152", "dim", true);
  const answer = stroke("M46 80c6-48 14-46 22-42s12 4 22 2 40 0 108 0", "dim");
  const go = stroke("M18 72l10 8-10 8z", "accent");
  return svg("run", "0 0 208 110", frame + asked + answer + go);
}

/** A wire of the diagram with a probe over it, and a scope strip waiting for its trace. */
function signals(): string {
  const block = stroke("M10 22h40v28h-40z") + stroke("M18 40c4-12 8-12 12 0s8 12 12 0", "dim");
  const wire = stroke("M50 36h86") + stroke("M136 36l-6-4v8z");
  const probe = stroke("M92 36l18-20h26", "dim") + stroke("M136 10h26v12h-26z", "dim");
  const dot = `<circle class="ea-dot accent" cx="92" cy="36" r="3.5"/>`;
  const strip = stroke("M10 66h188v34h-188z", "rule") + stroke("M18 83h172", "dim", true);
  return svg("signals", "0 0 208 108", block + wire + probe + strip + dot);
}

/** The drawing's frame: decoration to a screen reader, drawn in once in the visit. */
function svg(kind: Empty, view: string, body: string): string {
  const first = !drawn.has(kind);
  drawn.add(kind);
  return (
    `<svg class="empty-art${first ? " draws" : ""}" data-empty="${kind}" viewBox="${view}" ` +
    `aria-hidden="true" focusable="false">${body}</svg>`
  );
}

/** The drawing of an empty place. */
export function emptyArt(kind: Empty): string {
  return { part, compare, run, signals }[kind]();
}

/** For tests: forget what was drawn, as a new visit would. */
export function forgetDrawn(): void {
  drawn.clear();
}
