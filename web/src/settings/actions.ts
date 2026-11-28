// What the settings dialog does: it asks how the settings stand, saves a key, forgets it.
// The key is read from its box when Save is pressed and is kept nowhere on the page: the box
// is emptied as soon as the key is saved, and when the dialog shuts.

import { api, Refused } from "../api";
import { settingsApi } from "../api/settings";
import type { Settings } from "../api/settings";
import { app, draw } from "../store";
import { openAgent } from "./agent";
import { settingsBody } from "./view";
import type { SettingsShown } from "./view";

const shown: SettingsShown = { settings: null, fault: "", refused: null, busy: false };

/** What opened the dialog, for the keyboard to go back to. */
let opener: HTMLElement | null = null;
const wired = new WeakSet<HTMLDialogElement>();

const dialogNow = () => document.querySelector<HTMLDialogElement>("#settings-dialog");
const box = () => document.querySelector<HTMLInputElement>("#settings-key");

/** Draw the dialog again as the settings now stand. What is typed in the box stays in it,
 *  unless it has just been saved. */
function redraw(keep = true): void {
  const body = document.querySelector<HTMLElement>("#settings-body");
  if (!body) return;
  const typed = keep ? (box()?.value ?? "") : "";
  body.innerHTML = settingsBody(shown);
  const input = box();
  if (input) input.value = typed;
}

/** Why the settings could not be asked or changed, in the words there are for it. */
const why = (e: unknown): string => (e instanceof Error && e.message ? e.message : "The settings did not answer.");

/** The first screen says whether a datasheet can be read: asked again once a key is saved
 *  or forgotten, so the step that takes a datasheet says what is now true. */
async function refreshFirstScreen(): Promise<void> {
  try {
    const fresh = await api.setup();
    if (app.setup && app.setup.can_read !== fresh.can_read) {
      app.setup.can_read = fresh.can_read;
      draw.panel(true);
    }
  } catch {
    /* the step keeps what it said until the page asks again */
  }
}

function wire(dialog: HTMLDialogElement): void {
  if (wired.has(dialog)) return;
  wired.add(dialog);
  // Enter in the box saves, as the button does.
  dialog.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.isComposing || (e.target as HTMLElement).id !== "settings-key") return;
    e.preventDefault();
    void saveKey();
  });
  // Shut by its button or by Escape: the box is emptied, and the keyboard goes back to
  // what opened the dialog.
  dialog.addEventListener("close", () => {
    const input = box();
    if (input) input.value = "";
    shown.refused = null;
    opener?.focus();
    opener = null;
  });
}

/** Open the settings. Only a page served on this machine has them. */
export async function openSettings(el?: HTMLElement): Promise<void> {
  const dialog = dialogNow();
  if (api.mode() !== "server" || !dialog) return;
  // Opened from the bar's menu, which shuts: the keyboard goes back to the menu's button.
  opener = el && !el.closest("[popover]") ? el : document.querySelector<HTMLElement>('[popovertarget="top-more"]');
  Object.assign(shown, { fault: "", refused: null, busy: false });
  wire(dialog);
  redraw(false);
  if (!dialog.open) dialog.showModal();
  void openAgent();
  box()?.focus();
  try {
    shown.settings = await settingsApi.read();
  } catch (e) {
    shown.settings = null;
    shown.fault = why(e);
  }
  const held = document.activeElement === box();
  redraw();
  if (shown.fault) dialog.querySelector<HTMLElement>("[data-dialog-close]")?.focus();
  else if (held) box()?.focus();
}

/** One request that changes the settings, with the buttons held while it is on its way. A
 *  refusal is said at the box, anything else in place of the form. */
async function change(work: () => Promise<Settings>, done: () => void): Promise<void> {
  if (shown.busy) return;
  shown.busy = true;
  shown.refused = null;
  redraw();
  try {
    shown.settings = await work();
    done();
  } catch (e) {
    if (e instanceof Refused) shown.refused = { reason: e.reason, fix: e.fix };
    else shown.fault = why(e);
  }
  shown.busy = false;
  redraw();
  if (shown.fault) dialogNow()?.querySelector<HTMLElement>("[data-dialog-close]")?.focus();
  else box()?.focus();
  if (!shown.refused && !shown.fault) void refreshFirstScreen();
}

/** Save what is in the box as the key. An empty box is said to be empty, and nothing is sent. */
export async function saveKey(): Promise<void> {
  const input = box();
  if (!input) return;
  // Pasted with a line end or a space after it, as a key copied from a page often is.
  const key = input.value.trim();
  if (!key) {
    shown.refused = { reason: "no key was given", fix: "paste the key into the box" };
    redraw();
    box()?.focus();
    return;
  }
  await change(
    () => settingsApi.saveKey(key),
    () => {
      const now = box();
      if (now) now.value = "";
    },
  );
}

/** Take the saved key off this machine. */
export async function forgetKey(): Promise<void> {
  await change(
    () => settingsApi.forgetKey(),
    () => undefined,
  );
}
