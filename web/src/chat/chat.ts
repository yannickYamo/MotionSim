// The page's chat, at the side: a question about MotionSim answered, or a design set from a
// request. The server answers it (app/chat.py) through the same tools the coding agent has, so
// every change goes through the session's checks and shows in the notice with Undo.

import { built, HEADER } from "../session/build";
import { icon } from "../icons";
import { openSettings } from "../settings/actions";
import "./chat.css";

export const CHAT_PATH = "/api/session/chat";
const MOST_MESSAGE = 4000;

export interface Said {
  who: "you" | "it";
  text: string;
  model?: string | null;
  cost?: number;
  changes?: number;
}

export const chat = { log: [] as Said[], busy: false, unready: null as string | null };

const WORDS: Record<string, string> = { "claude-haiku-5-5": "Haiku", "claude-sonnet-5-5": "Sonnet" };

/** The button in the bar: shown only on a page that has the panel (chat.css). */
export const CHAT_BUTTON =
  `<button type="button" class="top-button chat-button" data-chat-open ` +
  `aria-label="Ask about MotionSim or your design" ` +
  `title="Ask">${icon("message-circle")}<span>Ask</span></button>`;

export const CHAT_PANEL =
  `<dialog id="chat-panel" class="chat-panel" aria-labelledby="chat-title">` +
  `<div class="dialog-head"><h2 id="chat-title">Ask</h2><div class="chat-head-actions">` +
  `<button type="button" class="ghost" data-chat-forget title="Start a new conversation">New</button>` +
  `<button type="button" class="close" data-chat-close aria-label="Close the chat">${icon("x")}</button></div></div>` +
  `<div class="chat-log" id="chat-log" role="log" aria-live="polite"></div>` +
  `<form class="chat-form" data-chat-form><label class="sr-only" for="chat-box">Your question or request</label>` +
  `<textarea id="chat-box" rows="2" maxlength="${MOST_MESSAGE}" ` +
  `placeholder="Ask how something works, or say what to change"></textarea>` +
  `<button type="submit">Send</button></form></dialog>`;

const escape = (s: string): string =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Under an answer: the model that gave it, what it changed, and what it cost. */
export function metaOf(said: Said): string {
  if (said.who !== "it" || !said.model) return "";
  const parts = [WORDS[said.model] ?? said.model];
  if (said.changes) parts.push(`${said.changes} change${said.changes === 1 ? "" : "s"}, undo from the notice`);
  if (said.cost !== undefined) parts.push(said.cost < 0.001 ? "under $0.001" : `$${said.cost.toFixed(3)}`);
  return `<span class="chat-meta">${escape(parts.join(" · "))}</span>`;
}

/** The verdict in words, as the screen shows it: what it said and why. */
const VERDICT_ASKED: Record<string, (where: string) => string> = {
  "ruled out": (where) => `Why is it ruled out${where}?`,
  "needs a change": (where) => `Why does it need a change${where}?`,
  "undecided on this data": (where) => `What would decide it${where}?`,
};

/** Questions to start from, each asked with a press: about the lab's run where one is shown,
 *  else the page's verdict, else MotionSim itself. Read off the screen, so they follow it. */
export function examples(): string[] {
  const read = (q: string) => document.querySelector(q)?.textContent?.trim() ?? "";
  const run = read(".lab .lab-verdict .lab-vword-word").toLowerCase();
  const test = read(".lab .lab-test-words > span:first-child");
  const word = (run || read("#panel .verdict-line .v-word")).toLowerCase();
  const where = run && test ? ` on ${test.charAt(0).toLowerCase()}${test.slice(1)}` : "";
  const first = !word
    ? "What does MotionSim check of a design?"
    : word.startsWith("passes")
      ? run
        ? `What limits this scheme${where}?`
        : "What limits this design?"
      : (VERDICT_ASKED[word]?.(where) ?? `Why does the verdict say ${word}?`);
  const second =
    word && !word.startsWith("passes")
      ? "What is the smallest change that makes it pass?"
      : "Where is the margin thinnest?";
  return [first, second, "Choose the scheme for a compressor and run a load step."];
}

const empty = (): string =>
  `<div class="chat-empty">Ask about MotionSim or your design, or say what to change.<ul>` +
  examples()
    .map((q) => `<li><button type="button" class="chat-example" data-chat-example>${escape(q)}</button></li>`)
    .join("") +
  `</ul></div>`;

/** Said before anything is typed where it cannot answer: why, and the way to put it right. */
const unreadyHtml = (why: string): string =>
  `<div class="chat-unready" role="status">${icon("alert-triangle")}<div><strong>Needs a key</strong>` +
  `<p>${escape(why)}</p><button type="button" class="ghost" data-chat-settings>Open settings</button></div></div>`;

export function logHtml(): string {
  const message = (s: Said) => `<div class="chat-msg ${s.who}">${escape(s.text)}${metaOf(s)}</div>`;
  const items = chat.log.map(message);
  if (chat.busy) items.push(`<div class="chat-msg it working">Working on it…</div>`);
  const head = chat.unready ? unreadyHtml(chat.unready) : "";
  return head + (items.length ? items.join("") : chat.unready ? "" : empty());
}

/** Whether it can answer, asked of the server as the panel opens; nothing is said if it cannot tell. */
async function checkReady(): Promise<void> {
  try {
    const response = await fetch(CHAT_PATH, { method: "GET" });
    const said = (await response.json()) as { ready?: boolean; why?: string | null };
    chat.unready = said.ready === false && typeof said.why === "string" ? said.why : null;
  } catch {
    chat.unready = null;
  }
  redraw();
}

function redraw(): void {
  const log = document.getElementById("chat-log");
  if (!log) return;
  log.innerHTML = logHtml();
  log.scrollTop = log.scrollHeight;
  const send = document.querySelector<HTMLButtonElement>(".chat-form button[type=submit]");
  if (send) send.disabled = chat.busy;
}

async function posted(method: "POST" | "DELETE", body?: unknown): Promise<Record<string, unknown>> {
  const build = built();
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(build ? { [HEADER]: build } : {}) };
  const response = await fetch(CHAT_PATH, {
    method,
    headers,
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const said = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok)
    throw new Error(typeof said.refused === "string" ? said.refused : `the server answered ${response.status}`);
  return said;
}

/** Send one message and show the answer. */
export async function send(message: string): Promise<void> {
  const text = message.trim().slice(0, MOST_MESSAGE);
  if (!text || chat.busy) return;
  chat.log.push({ who: "you", text });
  chat.busy = true;
  redraw();
  try {
    const out = await posted("POST", { message: text });
    chat.log.push({
      who: "it",
      text: typeof out.reply === "string" ? out.reply : "",
      model: typeof out.model === "string" ? out.model : null,
      cost: typeof out.cost === "number" ? out.cost : undefined,
      changes: Array.isArray(out.changes) ? out.changes.length : 0,
    });
  } catch (e) {
    chat.log.push({ who: "it", text: `Not answered: ${e instanceof Error ? e.message : String(e)}. Try again.` });
  }
  chat.busy = false;
  redraw();
}

export async function forget(): Promise<void> {
  if (chat.busy) return;
  chat.log = [];
  redraw();
  await posted("DELETE").catch(() => undefined);
}

let opener: HTMLElement | null = null;

/** Where the panel opens: inside a dialog open as a modal (the control lab), which leaves the
 *  rest of the page inert, or on the page itself. */
function hostOf(): HTMLElement | null {
  const modal = [...document.querySelectorAll<HTMLDialogElement>("dialog[open]")]
    .reverse()
    .find((d) => d.id !== "chat-panel" && modal_(d));
  return modal ?? document.getElementById("app") ?? document.body;
}

function modal_(d: HTMLDialogElement): boolean {
  try {
    return d.matches(":modal");
  } catch {
    return false;
  }
}

export function openChat(el?: HTMLElement): void {
  const panel = document.getElementById("chat-panel") as HTMLDialogElement | null;
  if (!panel) return;
  wireChat();
  const host = hostOf();
  if (host && panel.parentElement !== host) {
    if (panel.open) panel.close();
    host.appendChild(panel);
    // Opened over the lab, it shuts with the lab and goes back to the page: never found open
    // the next time the lab is.
    if (host instanceof HTMLDialogElement)
      host.addEventListener(
        "close",
        () => {
          closeChat(false);
          (document.getElementById("app") ?? document.body).appendChild(panel);
        },
        { once: true },
      );
  }
  opener = el ?? null;
  if (!panel.open) panel.show();
  redraw();
  void checkReady();
  document.getElementById("chat-box")?.focus();
}

export function closeChat(refocus = true): void {
  const panel = document.getElementById("chat-panel") as HTMLDialogElement | null;
  panel?.close();
  if (refocus && opener?.isConnected) opener.focus();
  opener = null;
}

/** The form's own keys: Enter sends, Shift+Enter starts a new line, Escape closes. */
export function wireChat(): void {
  const form = document.querySelector<HTMLFormElement>("[data-chat-form]");
  if (!form || form.dataset.wired) return;
  form.dataset.wired = "1";
  // The panel answers its own presses and keys: opened over the lab it is outside the page,
  // whose presses are listened for on the page alone.
  const panel = form.closest("dialog");
  panel?.addEventListener("click", (e) => {
    const el = (e.target as HTMLElement).closest<HTMLElement>(
      "[data-chat-close], [data-chat-forget], [data-chat-settings], [data-chat-example]",
    );
    if (!el) return;
    if (el.dataset.chatClose !== undefined) closeChat();
    else if (el.dataset.chatSettings !== undefined) void openSettings(el);
    else if (el.dataset.chatExample !== undefined) void send(el.textContent ?? "");
    else void forget();
  });
  panel?.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    // Escape shuts the panel, not the lab under it.
    e.preventDefault();
    e.stopPropagation();
    closeChat();
  });
  const box = form.querySelector<HTMLTextAreaElement>("textarea");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!box) return;
    const text = box.value;
    box.value = "";
    void send(text);
  });
  box?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
}
