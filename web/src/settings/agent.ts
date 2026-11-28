// The settings' part for a coding agent: the access code it connects with, the command that
// connects Claude Code, and the log of what the agent did, each change with its Undo. Drawn
// only on a page served on this machine whose server keeps a shared session.

import { Refused } from "../api/answers";
import { escape, sentence } from "../format";
import { icon } from "../icons";
import { sessionApi } from "../session/client";
import { heard, sync, undoChange } from "../session/sync";
import type { AgentSettings, Entry, Heard } from "../session/types";

const shown = {
  settings: null as AgentSettings | null,
  items: [] as Entry[],
  reveal: false,
  fault: "",
  /** What a press came to, said under the log or the code: copied, a new code, an undo refused. */
  said: "",
  busy: false,
};

const host = () => document.querySelector<HTMLElement>("#settings-agent");
const MASK = "•".repeat(12);
const wired = new WeakSet<HTMLElement>();

/** When a change was made, as the log says it: the time today, else the day and the time. */
export function when(at: number): string {
  const d = new Date(at * 1000);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString()
    ? time
    : `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}

const SOURCE: Record<string, string> = { agent: "Agent", undo: "Undo", page: "You" };

function entryRow(e: Entry): string {
  const after = e.undone
    ? `<span class="agent-log-state">Undone</span>`
    : e.undoable
      ? `<button type="button" class="link" data-agent-undo="${escape(e.id)}">Undo</button>`
      : "";
  const lost = e.overwritten ? `<span class="agent-log-state">Replaced by your edit</span>` : "";
  return (
    `<li><time datetime="${new Date(e.at * 1000).toISOString()}">${escape(when(e.at))}</time>` +
    `<span class="agent-log-who">${SOURCE[e.source] ?? escape(e.source)}</span>` +
    `<span class="agent-log-what">${escape(e.what)}</span>${lost}${after}</li>`
  );
}

/** The section as it stands. */
export function agentBody(): string {
  const title = `<h3>Coding agent</h3>`;
  if (shown.fault) {
    return `${title}<p class="settings-note">${icon("info-circle")}<span>${escape(shown.fault)}</span></p>`;
  }
  const s = shown.settings;
  if (!s) return `${title}<p class="settings-state"><span class="quiet">Asking how an agent connects.</span></p>`;
  const state =
    `<p class="settings-state">${icon("plug")}<span>` +
    `<b>Your agent can change this design and the control lab.</b> ` +
    `Each change is said on the page, and each can be undone.</span></p>`;
  const code = shown.reveal ? s.code : MASK;
  const command = shown.reveal ? s.command : s.command.replace(s.code, MASK);
  const off = shown.busy ? " disabled" : "";
  const codeField =
    `<div class="field"><label for="agent-code">Access code</label>` +
    `<div class="control agent-copyable"><input id="agent-code" readonly value="${escape(code)}" ` +
    `aria-describedby="agent-code-help" spellcheck="false"/>` +
    `<button type="button" class="ghost" data-agent-reveal aria-pressed="${shown.reveal}">` +
    `${icon("eye")}${shown.reveal ? "Hide" : "Show"}</button>` +
    `<button type="button" class="ghost" data-agent-copy="code">${icon("copy")}Copy</button></div>` +
    `<p class="help" id="agent-code-help">An agent connects only with this code. It is kept on this machine, ` +
    `readable by your account alone.</p></div>`;
  const commandField =
    `<div class="field"><label for="agent-command">Connect Claude Code</label>` +
    `<div class="control agent-copyable"><input id="agent-command" readonly value="${escape(command)}" ` +
    `aria-describedby="agent-command-help" spellcheck="false"/>` +
    `<button type="button" class="ghost" data-agent-copy="command">${icon("copy")}Copy</button></div>` +
    `<p class="help" id="agent-command-help">Run it once in a terminal. Any other agent connects to ` +
    `${escape(s.url)} with the code as a bearer token.</p></div>`;
  const renew =
    `<p class="dialog-actions">` + `<button type="button" class="ghost" data-agent-new${off}>New code</button></p>`;
  const said = shown.said ? `<p class="help" role="status">${escape(shown.said)}</p>` : "";
  const log = shown.items.length
    ? `<ol class="agent-log">${shown.items.map(entryRow).join("")}</ol>`
    : `<p class="quiet">Nothing yet: what your agent changes is listed here, the latest first.</p>`;
  return `${title}${state}${codeField}${commandField}${renew}${said}<h3>Agent activity</h3>${log}`;
}

function redraw(): void {
  const el = host();
  if (!el) return;
  const focused = document.activeElement as HTMLElement | null;
  const which = focused && el.contains(focused) ? focusKey(focused) : null;
  el.innerHTML = agentBody();
  if (which) el.querySelector<HTMLElement>(which)?.focus();
}

/** A press kept the keyboard where it was, across a redraw. */
function focusKey(el: HTMLElement): string | null {
  for (const name of ["agentReveal", "agentCopy", "agentNew", "agentUndo"]) {
    const v = el.dataset[name];
    if (v === undefined) continue;
    const attr = name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
    return v ? `[data-${attr}="${CSS.escape(v)}"]` : `[data-${attr}]`;
  }
  return null;
}

async function copied(text: string, what: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    shown.said = `The ${what} is copied.`;
  } catch {
    shown.said = `The ${what} could not be copied here: show it, then select it and copy it.`;
  }
  redraw();
}

async function pressed(e: Event): Promise<void> {
  const b = (e.target as HTMLElement).closest<HTMLButtonElement>("button");
  if (!b || !shown.settings) return;
  const s = shown.settings;
  if (b.dataset.agentReveal !== undefined) {
    shown.reveal = !shown.reveal;
    return redraw();
  }
  if (b.dataset.agentCopy) return copied(b.dataset.agentCopy === "code" ? s.code : s.command, b.dataset.agentCopy);
  if (b.dataset.agentNew !== undefined) return renewed();
  const id = b.dataset.agentUndo;
  const entry = id ? shown.items.find((x) => x.id === id) : undefined;
  if (!entry) return;
  b.disabled = true;
  try {
    await undoChange(entry);
    shown.said = `Undone: ${entry.what}`;
  } catch (err) {
    shown.said =
      err instanceof Refused
        ? `Not undone: ${err.reason}.${err.fix ? ` ${sentence(err.fix)}.` : ""}`
        : "Not undone: the server did not answer.";
  }
  await listed();
}

async function renewed(): Promise<void> {
  const sure =
    "Make a new access code? An agent connected with the old one is refused from now on, until it is " +
    "connected again with the new one.";
  if (!window.confirm(sure)) return;
  shown.busy = true;
  redraw();
  try {
    shown.settings = await sessionApi.newCode();
    shown.said = "A new code is made. Connect your agent again with it.";
  } catch {
    shown.said = "No new code was made: the server did not answer.";
  }
  shown.busy = false;
  redraw();
}

async function listed(): Promise<void> {
  try {
    shown.items = await sessionApi.activity();
  } catch {
    /* the log stays as it was */
  }
  redraw();
}

/** The log follows what the socket says while the dialog is open. */
function heardIt(said: Heard): void {
  const open = document.querySelector<HTMLDialogElement>("#settings-dialog")?.open;
  if (!open) return;
  if ((said.type === "session" && said.change) || said.type === "activity") void listed();
}

/** Fill the section, once the dialog opens. */
export async function openAgent(): Promise<void> {
  const el = host();
  // Only where the server keeps a session shared with an agent: an older one has no way in for one.
  if (!el || !sync.on) return;
  if (!wired.has(el)) {
    wired.add(el);
    el.addEventListener("click", (e) => void pressed(e));
    heard.add(heardIt);
  }
  Object.assign(shown, { reveal: false, fault: "", said: "" });
  redraw();
  try {
    const settings = await sessionApi.agent();
    if (typeof settings?.code !== "string" || typeof settings.command !== "string") throw new Error("unreadable");
    shown.settings = settings;
    shown.items = await sessionApi.activity();
  } catch (e) {
    shown.settings = null;
    shown.fault =
      e instanceof Error && e.message.includes("no shared session")
        ? "The program serving this page has no way in for a coding agent: start it again from this version."
        : "How an agent connects could not be asked: the server did not answer.";
  }
  redraw();
}
