// The quiet word the page says when the agent changes something: what changed, from what to
// what, with Undo. Not a dialog: it takes no keyboard, covers nothing that matters, and goes
// by itself unless the pointer or the keyboard is on it. The next change takes its place.

import "./notice.css";
import { Refused } from "../api/answers";
import { escape, sentence } from "../format";
import { icon } from "../icons";
import { heard, onOverwrote, undoChange } from "./sync";
import type { Entry, Heard } from "./types";
import { keepClear } from "./clear";

/** How long a notice stays, unless it is pointed at or holds the keyboard. */
export const STAYS = 12000;

const notice = {
  entry: null as Entry | null,
  timer: undefined as ReturnType<typeof setTimeout> | undefined,
  held: false,
};

function host(): HTMLElement {
  let el = document.querySelector<HTMLElement>("#agent-notice");
  if (el) return el;
  el = document.createElement("div");
  el.id = "agent-notice";
  el.className = "agent-notice";
  el.setAttribute("role", "status");
  el.setAttribute("aria-live", "polite");
  el.hidden = true;
  el.addEventListener("click", (e) => void pressed(e));
  el.addEventListener("pointerenter", () => hold(true));
  el.addEventListener("pointerleave", () => hold(false));
  el.addEventListener("focusin", () => hold(true));
  el.addEventListener("focusout", () => hold(false));
  document.body.append(el);
  return el;
}

function hold(on: boolean): void {
  notice.held = on;
  clearTimeout(notice.timer);
  if (!on) notice.timer = setTimeout(hide, STAYS);
}

export function hide(): void {
  clearTimeout(notice.timer);
  notice.entry = null;
  const el = document.querySelector<HTMLElement>("#agent-notice");
  if (!el) return;
  el.hidden = true;
  el.innerHTML = "";
}

function show(body: string, stays = STAYS): void {
  const el = host();
  const close =
    `<button type="button" class="notice-close" data-notice-close aria-label="Dismiss">` + `${icon("x")}</button>`;
  el.innerHTML = `${body}${close}`;
  el.hidden = false;
  keepClear(); // as the newer build's bar: never over the step's own actions
  clearTimeout(notice.timer);
  if (!notice.held) notice.timer = setTimeout(hide, stays);
}

const line = (lead: string, what: string) => `<p><b>${lead}</b> ${escape(what)}</p>`;

/** A change the agent or the chat made, with Undo where it can be undone. */
export function showChange(entry: Entry, by = "agent"): void {
  notice.entry = entry;
  const undo =
    entry.undoable && !entry.undone
      ? `<button type="button" class="ghost notice-undo" data-notice-undo>${icon("arrow-back-up")}Undo</button>`
      : "";
  const lead = by === "chat" ? "Changed from the chat:" : "Changed by your agent:";
  show(`${icon(by === "chat" ? "message-circle" : "plug")}${line(lead, entry.what)}${undo}`);
}

/** The page's own write, made on an older version, replaced what the agent had set. */
export function showOverwrote(names: string): void {
  notice.entry = null;
  show(`${icon("info-circle")}${line("Your edit replaced your agent's change to", `${names}.`)}`);
}

async function pressed(e: Event): Promise<void> {
  const target = (e.target as HTMLElement).closest<HTMLButtonElement>("button");
  if (!target) return;
  if (target.dataset.noticeClose !== undefined) return hide();
  if (target.dataset.noticeUndo === undefined || !notice.entry) return;
  const entry = notice.entry;
  target.disabled = true;
  try {
    await undoChange(entry);
    notice.entry = null;
    show(`${icon("circle-check")}${line("Undone:", entry.what)}`, 5000);
  } catch (err) {
    const why =
      err instanceof Refused
        ? `${sentence(err.reason)}.${err.fix ? ` ${sentence(err.fix)}.` : ""}`
        : "The server did not answer. Try again in a moment.";
    show(`${icon("alert-triangle")}${line("Not undone.", why)}`);
  }
}

function heardIt(said: Heard): void {
  if (said.type === "session" && (said.source === "agent" || said.source === "chat") && said.change)
    showChange(said.change, said.source);
  // Undone elsewhere (the activity log, another tab): the notice no longer offers it.
  if (said.type === "activity" && said.change.undone && notice.entry?.id === said.change.id) hide();
}

/** The notice listens from now on. */
export function startNotice(): void {
  heard.add(heardIt);
  onOverwrote(showOverwrote);
}
