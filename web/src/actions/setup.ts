// The whole of what was entered, as one state: put in place, cleared, saved as a setup file,
// opened from one, and kept in step with the page open in another tab.

import { api, partsOf } from "../api";
import { carry } from "../control/carry";
import type { KeptPart } from "../api";
import { dropInFlight, schedule } from "../engine";
import { resetEvent } from "../eventask";
import { fitFor } from "../engine/fit";
import { presetsFor } from "../engine/loads";
import { suggestFor } from "../engine/suggest";
import { resetColumns } from "../events/columns";
import { resetUndo } from "../events/undo";
import { fromSetupFile, restore, SETUP_VERSION } from "../restore";
import { DEVICES_KEY, holdSaving, initial, KEY, save, STALE_KEYS } from "../state";
import type { State } from "../state";
import { LOAD, MOTOR } from "../steps";
import { app, draw, invalidate, res, ui } from "../store";
import { $, say } from "../views/html";
import { download, partsMoved } from "./reports";

/** Put a whole state in place of the one on the page, as a reload would, but with the page
 *  and its engine kept running: in the browser the engine is not started a second time. */
export function applyState(next: State): void {
  // Nothing on its way for the state before lands on this one.
  dropInFlight();
  resetEvent();
  resetUndo();
  resetColumns();
  partsMoved();
  ui.savingMd = 0;
  ui.savedMd = "";
  ui.reportFault = null;
  ui.resizing = null;
  app.state = next;
  holdSaving(false);
  ui.otherTab = false;
  save(next);
  ui.notes.clear();
  ui.folds.clear();
  ui.reading = ui.review = ui.followed = null;
  ui.missionFault = ui.typedRefused = null;
  ui.typedWrong = {};
  ui.typedNotes = {};
  ui.typedOpen = false;
  ui.fetchFault = null;
  ui.missionNotes = [];
  res.suggestion = null;
  res.blocked = res.fault = res.waiting = null;
  res.stage = null;
  res.proposal = null;
  invalidate("all");
  history.replaceState({ step: next.step }, "");
  draw.rail();
  draw.panel();
  draw.stage();
  void suggestFor();
  if (next.step >= LOAD) void presetsFor();
  if (next.step === MOTOR) fitFor(true);
  schedule();
}

/** Reset pressed: asked first, in the page's own small dialog under the bar's menu (never the
 *  browser's unstyled confirm), with Keep on the keyboard so a stray Enter clears nothing. */
export function startOver(): void {
  const ask = document.querySelector<HTMLElement>("#reset-confirm");
  if (!ask) return;
  document.querySelector<HTMLElement>("#top-more")?.hidePopover?.();
  ask.showPopover?.();
  ask.hidden = false;
  ask.querySelector<HTMLElement>("[data-reset-keep]")?.focus();
}

/** Keep pressed: the question shuts and nothing changes. */
export function keepEverything(): void {
  const ask = document.querySelector<HTMLElement>("#reset-confirm");
  ask?.hidePopover?.();
  document.querySelector<HTMLElement>(".more-button")?.focus();
}

/** Clear everything entered and start again, in place: the parts brought, the motor, the
 *  load and every figure. Only what this page kept is cleared. */
export function clearEverything(): void {
  document.querySelector<HTMLElement>("#reset-confirm")?.hidePopover?.();
  for (const id of app.state.added) api.forget(id);
  try {
    // Only what this page kept: other pages served from the same address keep their own.
    for (const key of [KEY, DEVICES_KEY, ...STALE_KEYS]) localStorage.removeItem(key);
  } catch {
    /* a private window: nothing was kept */
  }
  ui.setupNote = null;
  // The control lab starts again too: its scheme, edits and test are of what was cleared.
  carry.clear();
  applyState(initial(app.setup));
  say("Everything entered was cleared: step 1 is open.");
  $("#panel").querySelector<HTMLElement>("h2")?.focus();
}

/** The most a setup file may weigh, as the engine's own careful reader holds any file to,
 *  and the most parts it may carry: a page compares five, and has seldom brought more. */
const MOST_SETUP_BYTES = 5 * 1024 * 1024;

const MOST_CARRIED = 20;

/** What a setup file holds, or why it is not opened: unread when it is too large to be one. */
async function setupData(file: File): Promise<{ data: unknown; state: State } | { why: string }> {
  if (file.size > MOST_SETUP_BYTES) {
    return { why: `${file.name} is larger than 5 MB, which no setup file saved from this page is` };
  }
  let data: unknown = null;
  try {
    data = JSON.parse(await file.text());
  } catch {
    /* not JSON: refused below with the rest */
  }
  const state = fromSetupFile(data, app.setup);
  if (state) return { data, state };
  const why = "that file is not a setup saved from this page, or was saved by a later version of it";
  return { why: `${file.name}: ${why}` };
}

/** Whether the part this page holds under a carried part's id is the very model it carries. */
async function heldAlready(part: KeptPart): Promise<boolean> {
  if (!app.setup.devices.some((d) => d.id === part.id)) return false;
  try {
    return (await api.reading(part.id)).file?.text === part.body.text;
  } catch {
    return false; // what this page holds cannot be told: the file's own model is brought
  }
}

interface Carried {
  /** The id each part brought again has now, by the id it had in the file. */
  renamed: Map<string, string>;
  failed: string[];
  /** Parts this page held under the same id with another model: the file's own was brought. */
  replaced: string[];
  left: number;
}

/** Bring again the parts a setup carries, where this page does not already hold the same
 *  model. The setup's meaning is its parts as they were: where this page has another model
 *  under the same id, the file's own is brought, under the id the engine gives it. */
async function bringCarried(raw: unknown): Promise<Carried> {
  const all = partsOf(raw);
  const out: Carried = { renamed: new Map(), failed: [], replaced: [], left: Math.max(0, all.length - MOST_CARRIED) };
  for (const part of all.slice(0, MOST_CARRIED)) {
    if (await heldAlready(part)) continue;
    const clash = app.setup.devices.some((d) => d.id === part.id);
    const device = part.body.device;
    const body = device ? { ...part.body, device: out.renamed.get(device) ?? device } : part.body;
    try {
      const answer = await api.bring({ ...part, body });
      out.renamed.set(part.id, answer.device.id);
      if (clash) out.replaced.push(answer.device.id);
    } catch {
      out.failed.push(part.body.name ?? part.id);
    }
  }
  return out;
}

/** The setup's state with each part under the id it has now, and without those not on the page. */
function withParts(state: State, renamed: Map<string, string>): { state: State; missing: string[] } {
  const to = (id: string) => renamed.get(id) ?? id;
  const known = new Set(app.setup.devices.map((d) => d.id));
  const devices = state.devices.map(to);
  const focus = state.focus ? to(state.focus) : null;
  const next = {
    ...state,
    devices: devices.filter((id) => known.has(id)),
    added: state.added.map(to).filter((id) => known.has(id)),
    focus: focus && known.has(focus) ? focus : null,
  };
  return { state: next, missing: devices.filter((id) => !known.has(id)) };
}

/** What opening the setup came to, in a few sentences. */
function openedNote(name: string, missing: string[], carried: Carried): { bad: boolean; text: string } {
  const lines: string[] = [];
  const nameOf = (id: string) => app.setup.devices.find((d) => d.id === id)?.name ?? id;
  for (const id of carried.replaced) {
    lines.push(`${nameOf(id)} is the model this file carries, not the one this page had under its name.`);
  }
  if (carried.left) lines.push(`${carried.left} more parts it carries were left out: a setup holds ${MOST_CARRIED}.`);
  if (!missing.length) {
    const text = [`${name} is open, with everything it holds.`, ...lines].join(" ");
    return { bad: carried.left > 0, text };
  }
  const [part, it] = missing.length === 1 ? ["a part", "it"] : ["parts", "them"];
  const failed = carried.failed.length ? ` (${carried.failed.join(", ")})` : "";
  const said =
    `${name} is open. It names ${part} it does not carry, or that could not be brought again${failed}: ` +
    `add ${it} again in step 1. The rest of the setup is in place.`;
  return { bad: true, text: [said, ...lines].join(" ") };
}

/** Open a setup saved from this page: everything entered comes back as it was, with the
 *  parts it carries brought again. A file that is not one, or of a version this page does
 *  not know, is refused and changes nothing. Old setup files, which name their parts
 *  without carrying them, still open. */
export async function openSetup(file: File): Promise<void> {
  const read = await setupData(file);
  if ("why" in read) {
    ui.setupNote = { bad: true, text: `${read.why}. Choose a file made by Save setup.` };
    draw.panel(true);
    return;
  }
  ui.setupNote = { bad: false, text: `Opening ${file.name}.` };
  draw.panel(true);
  const carried = await bringCarried((read.data as { parts?: unknown }).parts);
  try {
    // The parts the engine now holds, with those just brought among them.
    if (carried.renamed.size) app.setup = await api.setup();
  } catch (e) {
    const why = `${file.name} could not be opened: the engine did not answer (${(e as Error).message}).`;
    ui.setupNote = { bad: true, text: `${why} Nothing on the page was changed; try again once it answers.` };
    draw.panel(true);
    say(ui.setupNote.text);
    return;
  }
  const { state, missing } = withParts(read.state, carried.renamed);
  // The control lab opens next on what the setup carries of it, or from nothing.
  carry.open((read.data as { control?: unknown }).control);
  applyState(state);
  ui.setupNote = openedNote(file.name, missing, carried);
  draw.panel(true);
  say(ui.setupNote.text);
}

/** Everything entered on the page, as one file to keep, share or open again, with the model
 *  of each part brought on the page: the device file, or the figures typed in as one. */
export async function saveSetup(): Promise<void> {
  const parts = (
    await Promise.all(
      app.state.added.map(async (id) => {
        try {
          const { file } = await api.reading(id);
          return file ? [{ id, route: "/api/device", body: { name: file.name, text: file.text } }] : [];
        } catch {
          return []; // named in the setup, not carried: the page that opens it says so
        }
      }),
    )
  ).flat();
  // The control lab's scheme, edits, test and fidelity, where it has been opened or is waiting.
  const control = carry.saved();
  const file = { app: "MotionSim", setup: SETUP_VERSION, state: app.state, parts, ...(control ? { control } : {}) };
  download(new Blob([JSON.stringify(file, null, 1)], { type: "application/json" }), "motionsim-setup.json");
  say("Saved motionsim-setup.json.");
}

/** The page open in two tabs keeps one saved state. A tab that sees the other change it
 *  stops saving, so as not to write its own setup over the newer one, and offers the choice:
 *  take up the other tab's setup, or keep this one and save it. */
export function followOtherTabs(): void {
  window.addEventListener("storage", (e) => {
    if (e.key !== null && e.key !== KEY) return;
    if (e.newValue === null || e.newValue === JSON.stringify(app.state)) return;
    holdSaving(true);
    ui.otherTab = true;
    draw.panel(true);
  });
}

/** Take up the setup another tab saved, or keep this tab's and save it over that one. */
export function settleOtherTab(el: HTMLElement): void {
  ui.otherTab = false;
  holdSaving(false);
  if (el.dataset.otherTab === "keep") {
    save(app.state);
    draw.panel(true);
    return;
  }
  app.state = restore(app.setup, api.mode() === "browser");
  res.suggestion = null;
  invalidate("all");
  draw.rail();
  draw.panel(true);
  draw.stage();
  void suggestFor();
  schedule();
}
