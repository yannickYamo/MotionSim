// What a box bound to the state takes of what is typed into it, and what it says of it: the
// figure in use, a figure it cannot read or will not take, and whose the figure is from then on.

import { outOfRange } from "./limits";
import { shownAs, shownText } from "./motorentry";
import type { Shown } from "./motorentry";
import { readNumber } from "./parse";
import type { Read } from "./parse";
import { POINT_KEYS } from "./state";
import type { Point } from "./state";
import { LOAD, MOTOR, SUPPLY } from "./steps";
import { app, ui } from "./store";
import type { BoxNote } from "./store";

/** A figure a motor can do without: its box may be left empty. */
function spare(kind: string, key: string): boolean {
  const m = app.setup.motors[kind];
  return !!m?.fields.some((f) => f.key === key && f.required === false) || !!m?.optional?.some((f) => f.key === key);
}

/** A figure of the motor typed by the user: theirs for that kind, which is then the one picked. */
function claimMotor(kind: string, key: string): void {
  const { state } = app;
  state.motorOwn = { ...state.motorOwn, [kind]: [...new Set([...(state.motorOwn[kind] ?? []), key])] };
  if (kind === state.kind) state.kindPicked = true;
}

/** A figure of the load typed by the user. A weight on an arm is inertia as well as a torque:
 *  until the user types an inertia of their own, the load's follows the weight and the arm,
 *  as the sized load's was made. */
function claimLoad(key: string): void {
  const { state } = app;
  if (key === "inertia") state.inertiaOwn = true;
  if ((key === "mass" || key === "arm") && !state.inertiaOwn) {
    const { mass, arm } = state.load;
    if (mass > 0 && arm > 0) state.load.inertia = Number((mass * arm * arm).toPrecision(6));
  }
}

/** Note whose the figure is from now on: typed by the user, it no longer follows the device. */
function claim(keys: string[]): void {
  const { state } = app;
  const last = keys[keys.length - 1];
  if (keys[0] === "motors") claimMotor(keys[1], last);
  if (keys[0] === "conditions" && (POINT_KEYS as readonly string[]).includes(last)) {
    const typed = { [last]: state.conditions[last as keyof Point] };
    state.pointOf = { ...state.pointOf, [state.kind]: { ...state.pointOf[state.kind], ...typed } };
    state.kindPicked = true;
    // The link of a drive on the mains, typed: it is held there, no longer where the stage puts it.
    if (last === "v_dc" && state.supply === "mains") state.conditions.link_own = "1";
  }
  if (keys[0] === "load" || keys[0] === "segments") state.loadTouched = true;
  // A stretch changed by hand: the motion is the stretches as they now stand, no longer a duty's phases.
  if (keys[0] === "segments") state.phases = null;
  if (keys[0] === "load") claimLoad(last);
}

/** What a figure read with a comma came to: said at its box, since the comma could be read
 *  the other way. */
const commaRead = (value: number): string =>
  `Read as ${value}: a comma before anything but three figures is a decimal point.`;

/** A box being typed into: where its figure lives, the figure it holds, and what was typed. */
interface Typed {
  path: string;
  raw: string;
  target: Record<string, unknown>;
  last: string;
  held: unknown;
  motor: boolean;
  /** The figure held, as the box shows it, where the box shows it otherwise than the engine. */
  shownHeld?: string;
}

const inUse = (v: unknown) => (typeof v === "number" || typeof v === "string" ? String(v) : "");
const heldSaid = (t: Typed) => t.shownHeld ?? inUse(t.held);

/** A figure that was read, taken into the state. False when it is outside what the box takes:
 *  the one before it stays, and the box keeps what was typed and says why. */
function takeRead(t: Typed, read: Extract<Read, { ok: true }>): boolean {
  const range = typeof t.held === "number" ? outOfRange(t.path, read.value) : null;
  if (range) {
    ui.notes.set(t.path, {
      raw: t.raw,
      why: `${range} ${heldSaid(t)} is still in use.`,
      unused: true,
      inUse: heldSaid(t),
    });
    return false;
  }
  // The figure is kept as the number it came to, in the box's own unit, and of the box's
  // own kind: a box that holds text (one that may be left empty) keeps it as text, so that
  // the request reads it as it reads any, and the box can be emptied again.
  t.target[t.last] = typeof t.held === "number" || t.motor ? read.value : String(read.value);
  if (read.echo) ui.notes.set(t.path, { raw: t.raw, why: read.echo, echo: true });
  else if (read.comma) ui.notes.set(t.path, { raw: t.raw, why: commaRead(read.value) });
  return true;
}

/** What was typed that cannot be read as a figure. False when the box cannot do without one:
 *  it keeps the figure it had and says so. A figure the page can do without is left out, not
 *  kept unseen. */
function takeUnread(t: Typed, read: Extract<Read, { ok: false }>, keys: string[]): boolean {
  if (typeof t.held === "number" && !(t.motor && spare(keys[1], t.last))) {
    const why = read.empty ? "Empty:" : read.why;
    const note = { raw: t.raw, why: `${why} ${heldSaid(t)} is still in use.`, unused: true, inUse: heldSaid(t) };
    ui.notes.set(t.path, note);
    return false;
  }
  t.target[t.last] = t.motor ? "" : t.raw;
  if (t.motor && !read.empty) {
    ui.notes.set(t.path, { raw: t.raw, why: `${read.why} This box is left out.`, unused: true, inUse: "" });
  }
  return true;
}

/**
 * Takes what was typed into the state. A box the page cannot do without keeps the figure
 * it had when what was typed cannot be read as a number, and says so at the box; a box
 * that may be left empty is then left out. `numeric`: false for a choice from a list.
 */
/** How a motor's box shows its figure, where it shows it otherwise than the engine holds it. */
function motorShown(keys: string[]): Shown | null {
  if (keys[0] !== "motors" || keys.length !== 3) return null;
  return shownAs(keys[1], keys[2], app.state.motorEntry ?? { wiring: "line", constant: {} });
}

/** What was typed into a motor's box that shows its figure in the datasheet's terms: read in
 *  the box's unit, then turned into the engine's figure. False where it is not taken. */
function takeShown(t: Typed, shown: Shown, keys: string[]): boolean {
  const read = readNumber(t.raw, shown.unit || undefined);
  const said = { ...t, shownHeld: String(shownText(shown, t.held as string | number)) };
  if (!read.ok) return takeUnread(said, read, keys);
  const engine = shown.engine(read.value);
  if (typeof engine === "string") return takeUnread(said, { ok: false, empty: false, why: engine }, keys);
  return takeRead(said, { ...read, value: Number(engine.toPrecision(12)) });
}

export function setPath(path: string, raw: string, numeric = true, unit?: string): void {
  const keys = path.split(".");
  const last = keys[keys.length - 1];
  let target = app.state as unknown as Record<string, unknown>;
  for (const k of keys.slice(0, -1)) target = target[k] as Record<string, unknown>;
  const typed: Typed = { path, raw, target, last, held: target[last], motor: keys[0] === "motors" };
  ui.notes.delete(path);
  // A cooling figure the tool sized is the user's own once it is edited.
  const c = app.state.conditions;
  if (c.sized && path === `conditions.${c.sized}`) {
    c.sized = "";
    c.sizedFor = "";
  }
  const shown = numeric ? motorShown(keys) : null;
  if (shown) {
    if (!takeShown(typed, shown, keys)) return;
    return claim(keys);
  }
  const read = readNumber(raw, unit);
  if (!numeric) target[last] = raw;
  else if (read.ok ? !takeRead(typed, read) : !takeUnread(typed, read, keys)) return;
  claim(keys);
}

/** What a box says of the figure in it, where it has something to say: that it cannot be
 *  read, or that it is outside what the box takes. */
export function noteAt(path: string, value: string | number): { raw?: string; why: string; echo?: boolean } | null {
  const kept = ui.notes.get(path);
  if (kept) return kept;
  const read = readNumber(value);
  if (!read.ok) return read.empty ? null : { why: `${read.why} This box is left out.` };
  if (read.comma) return { why: commaRead(read.value) };
  const range = outOfRange(path, read.value);
  return range ? { why: range } : null;
}

/** The step whose form holds a box, by where the box's figure lives. */
export function stepOfPath(path: string): number {
  const head = path.split(".")[0];
  if (head === "motors") return MOTOR;
  if (head === "conditions") return SUPPLY;
  if (["load", "segments", "sink", "start"].includes(head)) return LOAD;
  return -1;
}

/** Entries that were not used, with the step each belongs to: said on the results and in
 *  the rail, so that a verdict is never read as the answer for a figure it did not take. */
export function unusedEntries(): { path: string; step: number; note: BoxNote }[] {
  return [...ui.notes.entries()]
    .filter(([, note]) => note.unused)
    .map(([path, note]) => ({ path, step: stepOfPath(path), note }))
    .filter((x) => x.step >= 0);
}
