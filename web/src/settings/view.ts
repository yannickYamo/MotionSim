// The settings of a page served on this machine: the key the datasheet reader is given.
// Drawn from how the settings stand; the key itself is never among what is drawn.

import "./settings.css";
import type { Settings } from "../api/settings";
import { escape, sentence } from "../format";
import { icon } from "../icons";

/** What the dialog shows besides the box: how the settings stand, or why that is not known,
 *  what was refused at the box, and whether a request is on its way. */
export type SettingsShown = {
  settings: Settings | null;
  fault: string;
  refused: { reason: string; fix: string } | null;
  busy: boolean;
};

/** The entry in the bar. It shows only on a page that has the dialog: see settings.css. */
/** The entry in the bar's menu, with its word. */
export const SETTINGS_ITEM =
  `<button type="button" class="settings-entry" data-settings>` + `${icon("settings")}Settings</button>`;

/** The dialog, there from the moment the page knows its engine is a server on this machine,
 *  and filled when opened. */
export const SETTINGS_DIALOG =
  `<dialog id="settings-dialog" class="settings-dialog" aria-labelledby="settings-title">` +
  `<div class="dialog-head"><h2 id="settings-title">Settings</h2>` +
  `<button type="button" class="close" data-dialog-close aria-label="Close settings">${icon("x")}</button></div>` +
  `<div id="settings-body"></div><div id="settings-agent"></div></dialog>`;

export const KEPT =
  "The key is kept in a file on this machine that only your account can read, and it leaves the machine " +
  "only when a datasheet is read or the chat answers you: then it goes to the model's maker and nowhere else.";

/** How the key stands, in a sentence, with the mark that goes with it. */
function stateLine(settings: Settings): string {
  const { key, source, saved } = settings.reader;
  if (key === "unset") {
    return `${icon("info-circle")}<span><b>No key is set.</b> A datasheet PDF cannot be read until one is.</span>`;
  }
  if (source === "environment") {
    const kept = saved
      ? "The key saved here is kept, and is used only when that one is gone."
      : "A key saved here would be used only when that one is gone.";
    return (
      `${icon("circle-check")}<span><b>A key is set in the environment</b> of the program that serves this ` +
      `page, and it is the one used. ${kept}</span>`
    );
  }
  return `${icon("circle-check")}<span><b>A key is saved on this machine.</b> Datasheets are read with it.</span>`;
}

/** The reader's libraries are not installed: a key alone will not read a datasheet. */
const NOT_INSTALLED =
  `<p class="settings-note">${icon("alert-triangle")}<span>The libraries that read a PDF are not installed ` +
  `where this page is served, so a datasheet cannot be read yet, with or without a key. The README says ` +
  `how to add them.</span></p>`;

export function settingsBody(shown: SettingsShown): string {
  const { settings, fault, refused, busy } = shown;
  const title = `<h3>Datasheet reader</h3>`;
  if (fault) {
    return `${title}<div class="fault" role="alert">${icon("info-circle")}<div><p>${escape(fault)}</p></div></div>`;
  }
  const state = settings
    ? `<p class="settings-state is-${settings.reader.key}" role="status">${stateLine(settings)}</p>`
    : `<p class="settings-state" role="status"><span class="quiet">Asking how the settings stand.</span></p>`;
  const missing = settings && !settings.reader.available ? NOT_INSTALLED : "";
  const said = refused
    ? `<p class="help unread" id="settings-key-said" role="alert">${escape(sentence(refused.reason))}.` +
      `${refused.fix ? ` ${escape(sentence(refused.fix))}.` : ""}</p>`
    : "";
  const described = `aria-describedby="${refused ? "settings-key-said " : ""}settings-key-kept"`;
  // A password box: what is pasted is not shown, and the browser is told it is no log-in to keep.
  const input =
    `<input id="settings-key" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" ` +
    `${refused ? 'aria-invalid="true" ' : ""}${described}/>`;
  const field =
    `<div class="field${refused ? " is-unread" : ""}"><label for="settings-key">Anthropic API key</label>` +
    `<div class="control">${input}</div>${said}` +
    `<p class="help" id="settings-key-kept">${KEPT}</p></div>`;
  const off = busy ? " disabled" : "";
  const forget = settings?.reader.saved
    ? `<button type="button" class="ghost" data-settings-forget${off}>Forget the key</button>`
    : "";
  const save = `<button type="button" class="primary" data-settings-save${off}>Save the key</button>`;
  return `${title}${state}${missing}${field}<p class="dialog-actions">${forget}${save}</p>`;
}
