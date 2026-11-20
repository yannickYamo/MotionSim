// Bringing a part: from a file dropped or chosen, typed in from its datasheet, or laid open
// to be checked against it.

import { api, Refused } from "../api";
import type { ReadOutcome } from "../api";
import { startWaiting } from "../elapsed";
import { schedule } from "../engine";
import { suggestFor } from "../engine/suggest";
import { latest, once } from "../guard";
import { typedFigures } from "../parse";
import { DEVICE, MOST, RESULTS } from "../steps";
import { fieldsOf, kindOf, sentFigures } from "../typedkind";
import { app, draw, ownDevices, res, ui } from "../store";
import { refusalOf } from "../wording";
import { partsMoved } from "./reports";

/** Lay a device's model open beside its datasheet reading, or fold it away again. An answer
 *  for a model that has been folded away, or given way to another, is dropped. */
export async function openReview(id: string): Promise<void> {
  const current = latest("review");
  if (ui.review?.id === id) {
    ui.review = null;
    draw.panel(true);
    return;
  }
  ui.review = { id };
  draw.panel(true);
  let review: NonNullable<typeof ui.review>;
  try {
    review = { id, data: await once(`reading:${id}`, () => api.reading(id)) };
  } catch (e) {
    review = { id, failed: `The model could not be opened: ${(e as Error).message}` };
  }
  if (!current()) return;
  ui.review = review;
  draw.panel(true);
  document.querySelector("#review")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

/** Put a part just brought among the parts under test, in place of a made-up one. */
function takeIn(id: string, replaceMadeUp: boolean): void {
  const { state, setup } = app;
  const made = replaceMadeUp ? new Set(setup.devices.filter((d) => d.example).map((d) => d.id)) : new Set<string>();
  state.devices = [...new Set([...state.devices.filter((d) => !made.has(d)), id])].slice(-MOST);
  state.added = [...new Set([...state.added.filter((d) => !made.has(d)), id])];
}

/** Take the keyboard to the first box of the typed part that is wrong, in the form's order. */
function toFirstWrong(): void {
  const to =
    document.querySelector<HTMLElement>("details.typed .field.is-wrong input, details.typed .field.is-wrong select") ??
    document.querySelector<HTMLElement>("details.typed .refusal");
  if (!to) return;
  // A wrong box among the optional figures is inside a fold: it is opened to be seen.
  const fold = to.closest("details:not(.typed)");
  if (fold instanceof HTMLDetailsElement) fold.open = true;
  to.scrollIntoView({ block: "center" });
  to.focus();
}

/** Add the part typed in from its datasheet figures. What the page can check itself is
 *  checked at once, every box together, before the engine is asked: in the browser the
 *  engine may still be starting, and that is said while it is waited for. */
export async function addTyped(): Promise<void> {
  const { state } = app;
  ui.typedRefused = null;
  ui.typedOpen = true;
  const kind = kindOf(state.typed, app.setup.typed);
  // A GaN transistor has no reverse recovery: its charge may be nought, or left empty.
  const nought = new Set(kind === "gan" ? ["q_rr"] : []);
  const checked = typedFigures(state.typed, fieldsOf(kind, app.setup.typed), nought);
  ui.typedWrong = checked.wrong;
  ui.typedNotes = checked.notes;
  if (Object.keys(checked.wrong).length) {
    draw.panel(true);
    toFirstWrong();
    return;
  }
  ui.typedBusy = true;
  draw.panel(true);
  try {
    const figures = sentFigures(kind, checked.figures, app.setup.typed);
    const answer = await api.addTyped(figures);
    const from = ui.typedFrom;
    const read = { values: 0, curves: 0, flagged: [] };
    ui.reading = { name: answer.name, outcome: { device: answer.device, read }, file: answer.text };
    partsMoved();
    app.setup = await api.setup();
    const id = answer.device.id;
    if (from && state.devices.includes(from)) {
      // Given again with a figure the tool took, the part takes the place of the one before it,
      // where it stood: the design stays the design, the drawing stays on it, and a column
      // keeps its place, with nothing else in the table moved or dropped.
      state.devices = [...new Set(state.devices.map((d) => (d === from ? id : d)))];
      state.added = [...new Set([...state.added, id])];
      if (state.lead === from) state.lead = id;
      if (state.focus === from) state.focus = id;
    } else {
      // Typed in on the results, to compare, it stands beside the parts there, made-up or not.
      takeIn(id, !(state.step === RESULTS || state.reached > DEVICE));
    }
    // Its figures as typed are kept with it, for a figure the tool took to be given later.
    state.typedOf = { ...state.typedOf, [id]: { ...state.typed, kind } };
    ui.typedFrom = null;
    state.typed = {};
    ui.typedNotes = {};
    ui.typedOpen = false;
    void suggestFor();
    schedule();
  } catch (e) {
    ui.typedRefused = refusalOf(e, (message) => new Refused(message, "check the figures and try again", ""));
  }
  ui.typedBusy = false;
  draw.panel(true);
  draw.rail();
  draw.stage();
  if (ui.typedRefused) return toFirstWrong();
  const done = document.querySelector<HTMLElement>(".read-result");
  done?.scrollIntoView({ block: "center" });
  done?.focus();
}

/** A file that is none of the three kinds a part is brought as: said as what it is, with
 *  where it belongs when it belongs somewhere else on the page. */
function notAPart(name: string): Refused {
  // A datasheet is offered only where this page can read one.
  const reads = api.mode() !== "browser" && app.setup.can_read;
  const kinds = reads ? "a .yaml, .json or .pdf file" : "a .yaml or .json file";
  if (/\.(csv|tsv|txt)$/i.test(name)) {
    const fix = `a mission profile is brought in step 4, under the load; a part is ${kinds}`;
    return new Refused("that looks like a table of figures, not a part", fix, "");
  }
  const fix = reads
    ? "bring a device file (.yaml), your measurements (.json) or the datasheet (.pdf)"
    : "bring a device file (.yaml) or your measurements (.json)";
  return new Refused("that file is not one this page can take a part from", fix, "");
}

/** Hand the file to whatever reads its kind: measurements, a device file, or a datasheet. */
async function readPart(file: File): Promise<ReadOutcome> {
  const { state, setup } = app;
  const none = { values: 0, curves: 0, flagged: [] };
  if (/\.json$/i.test(file.name)) {
    // Measurements belong to the device on the drawing where the user chose one, else to the first ticked.
    const picked = [state.focusPicked ? state.focus : null, ...state.devices];
    const target = picked.find((id) => id && !id.endsWith("-measured")) ?? ownDevices()[0]?.id;
    if (!target) {
      const fix = "add the device's datasheet or device file first, then drop the measurements";
      throw new Refused("measurements need the device they were taken on", fix, "");
    }
    return { ...(await api.addMeasurement(target, file)), read: none };
  }
  if (/\.ya?ml$/i.test(file.name)) return { ...(await api.addDevice(file)), read: none };
  if (!/\.pdf$/i.test(file.name)) throw notAPart(file.name);
  if (api.mode() === "browser") {
    const fix = "see below for how to turn it into a device file on your own machine";
    throw new Refused("a datasheet PDF cannot be read on this page", fix, "");
  }
  if (!setup.can_read) {
    const fix = "see below for the key to set before starting motionsim again";
    throw new Refused("reading a datasheet PDF needs a language model's key, and none is set", fix, "");
  }
  return api.read(file);
}

/** Take in whatever the user dropped: a datasheet, a device file, or their own measurements. */
export async function addPart(file: File): Promise<void> {
  const { state } = app;
  ui.reading = { name: file.name, at: startWaiting() };
  draw.panel(true);
  try {
    const outcome = await readPart(file);
    partsMoved();
    ui.reading = { name: file.name, outcome };
    app.setup = await api.setup();
    if (res.suggestion?.id === outcome.device.id) res.suggestion = null;
    if (ui.review?.id === outcome.device.id) {
      ui.review = null;
      void openReview(outcome.device.id);
    }
    // On the first step the part just brought is the part under test, in place of a made-up
    // one. Added on the results, it stands beside whatever is there, to be compared with it.
    takeIn(outcome.device.id, !(state.step === RESULTS || state.reached > DEVICE));
    if (!api.keeps()) ui.unsaved = true;
    void suggestFor();
    schedule();
  } catch (e) {
    const fix =
      api.mode() === "server" ? "check the terminal that runs motionsim serve" : "check the file and try again";
    ui.reading = {
      name: file.name,
      refused: refusalOf(e, (message) => new Refused(message, fix, "")),
    };
  }
  draw.panel(true);
  draw.rail();
  draw.stage();
  // What was added is said where the keyboard now is: the place it was dropped on lets go.
  if (ui.reading?.outcome) document.querySelector<HTMLElement>("#panel .read-result")?.focus({ preventScroll: true });
}
