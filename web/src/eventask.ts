// The switching event under the loss chart, from the page's side: asked of the engine only
// once the user opens it, asked again a moment after a figure it rests on changes, and drawn
// by code fetched only then. Until it is opened the page carries none of it.

import { api, NotWorkedOut, Refused } from "./api";
import type { Candidate, SwitchingEvent } from "./api";
import { forgetBoard, layoutOrBoard } from "./board/reading";
import { setPath } from "./boxes";
import { schedule } from "./engine";
import { request, save } from "./state";
import { app, draw, ui } from "./store";
import { escape } from "./format";
import { icon } from "./icons";
import { loadResults, resultsNow } from "./views/resultsload";
import { idOf, refusal } from "./views/html";

type Plots = typeof import("./eventplot/view");
type Which = "on" | "off";

// The event's code comes with the results' (which the page fetches once it is first drawn),
// in one chunk with them: never with the page's own, and never as a chunk of its own, which
// would split what the page and the results share into more files for the first screen.
const plots = {
  now: (): Plots | null => resultsNow()?.eventPlots ?? null,
  get: (): Promise<Plots> => loadResults().then((r) => r.eventPlots),
};

/** The event as the page holds it: whether it is open, the edge the user came from, the
 *  inputs the answer on hand is for, and the answer or why there is none. */
export const ev = {
  open: false,
  mark: null as Which | null,
  key: "",
  answer: null as SwitchingEvent | Refused | null,
  asking: "",
  stop: null as AbortController | null,
  codeFailed: false,
  /** The device the answer on hand is of: an answer is never shown under another device. */
  device: "",
  /** Where the keyboard goes once the event is first drawn after it was opened. */
  focusTo: "",
};

/** The event shut and forgotten, with what was on its way for it: a design put in place of
 *  another (Reset, a setup opened) never shows the event, the answer or the zoom of the last. */
export function resetEvent(): void {
  ev.stop?.abort();
  Object.assign(ev, {
    open: false,
    mark: null,
    key: "",
    answer: null,
    asking: "",
    stop: null,
    device: "",
    focusTo: "",
  });
  plots.now()?.forgetEvent();
  forgetBoard();
  ui.pwmOpen = null;
}

/** The keyboard to the edge pressed, once it is on the page: tried after each drawing of the stage. */
export function focusOnce(): void {
  const el = ev.focusTo ? document.querySelector<HTMLElement>(ev.focusTo) : null;
  if (!el) return;
  ev.focusTo = "";
  el.focus();
}

/** What the event is asked with: the design's request, the device and the event's own figures. */
export const eventBody = (c: Candidate) => ({ ...request(app.state), device: c.id, event: app.state.event });

export const eventKey = (c: Candidate) => JSON.stringify(eventBody(c));

/** Ask for the event of these inputs; an answer for inputs since moved is dropped. */
export function askEvent(c: Candidate): void {
  const key = eventKey(c);
  if (ev.asking === key) return;
  ev.stop?.abort();
  const stop = new AbortController();
  ev.stop = stop;
  ev.asking = key;
  api.event(eventBody(c), stop.signal).then(
    (answer) => landed(key, answer),
    (e: unknown) => {
      if (stop.signal.aborted) return;
      landed(key, e instanceof Refused ? e : new NotWorkedOut(String((e as Error)?.message ?? e)));
    },
  );
}

function landed(key: string, answer: SwitchingEvent | Refused): void {
  if (ev.asking !== key) return;
  ev.asking = "";
  ev.stop = null;
  ev.key = key;
  ev.device = (JSON.parse(key) as { device: string }).device;
  ev.answer = answer;
  draw.stage();
  focusOnce();
}

/** A figure the event rests on is being typed: asked again once the typing pauses. */
const PAUSE_MS = 400;
let soon = 0;
export function askSoon(c: Candidate): void {
  clearTimeout(soon);
  soon = window.setTimeout(() => {
    askEvent(c);
    draw.stage();
  }, PAUSE_MS);
}

/** Open the event, from a spike on the loss chart or its own button: the code that draws it
 *  is fetched, and the keyboard goes to the edge pressed once it is drawn. */
export function openEvent(which: Which | null): void {
  ev.open = true;
  ev.mark = which;
  ev.codeFailed = false;
  ev.focusTo = which ? `[data-edge-plot="${which}"]` : "#ev-h";
  ui.pwmOpen = true;
  draw.stage();
  void plots.get().then(
    () => {
      draw.stage();
      focusOnce();
    },
    () => {
      ev.codeFailed = true;
      draw.stage();
    },
  );
}

/** Go to the box that replaces an assumed figure: the event's fold opens on it. */
export function toEventBox(path: string): void {
  ui.folds.set("event-detail", true);
  draw.stage();
  const box = document.getElementById(`ev-${idOf(path)}`);
  box?.scrollIntoView({ block: "center" });
  box?.focus();
}

/** A layout file chosen: its text is sent with the event, under its name. A board's own file
 *  chosen in its place is read for the figures instead, and nothing of the event moves until
 *  the user takes them. */
export async function takeLayout(file: File): Promise<void> {
  const layout = await layoutOrBoard(file);
  if (layout === null) return;
  app.state.event.layout = layout;
  app.state.event.layout_name = file.name;
  ui.unsaved = !save(app.state);
  draw.stage();
}

export function dropLayout(): void {
  app.state.event.layout = "";
  app.state.event.layout_name = "";
  ui.unsaved = !save(app.state);
  draw.stage();
}

/** Back to the span an edge was first shown over. */
export const resetEdge = (which: Which) => plots.now()?.resetSpan(which);

/** The loop inductance worked out from the board's geometry, put in its box as the user's own. */
export function useEstimate(nh: string): void {
  setPath("conditions.l_loop_nh", nh);
  ui.unsaved = !save(app.state);
  schedule();
  draw.stage();
  document.getElementById(`ev-${idOf("conditions.l_loop_nh")}`)?.focus();
}

/** A figure of the board's geometry typed: the estimate under it follows at once. */
export function geometryTyped(el: HTMLInputElement): void {
  const view = plots.now();
  if (!view) return;
  view.geometry[el.dataset.geo as keyof typeof view.geometry] = el.value;
  const said = document.getElementById("ev-estimate");
  if (said) said.outerHTML = view.estimateSaid();
}

/** A figure only the event uses typed: kept, and the event asked again once the typing pauses. */
export function eventTyped(el: HTMLInputElement, c: Candidate | null): void {
  const unit = el.parentElement?.querySelector(".unit")?.textContent?.trim();
  setPath(el.dataset.bind!, el.value, true, unit);
  ui.unsaved = !save(app.state);
  if (c) askSoon(c);
}

const opener = () =>
  `<p class="ev-open"><button type="button" class="ghost" data-event-show="">${icon("wave-sine")}` +
  `See one switching event through time</button>` +
  `<span class="quiet small">Or press a spike above.</span></p>`;

/** Where the event was refused, its fold stays, so the figure at fault can be changed there. */
const detailOnly = (view: Plots) => view.detailFold();

/** The event's own boxes alone, where the design they belong to is refused: the figure at
 *  fault may be one of them, and is put right where it was typed. */
export function eventBoxes(): string {
  const view = plots.now();
  return ev.open && view ? `<section class="ev">${view.detailFold()}</section>` : "";
}

const waiting = (what: string) => `<p class="waiting quiet" role="status">${escape(what)}</p>`;

/** The event's place under the loss chart: what to press to open it, the event once it has
 *  come, or what it is waiting for. A figure moved since the answer on hand asks again. */
export function eventSlot(c: Candidate): string {
  if (!ev.open) return opener();
  if (ev.codeFailed) {
    return (
      `<p class="fault" role="status">The event's code did not come. ` +
      `<button type="button" class="link" data-event-show="">Try again</button></p>`
    );
  }
  const key = eventKey(c);
  if (ev.key !== key && ev.asking !== key) {
    if (ev.answer) askSoon(c);
    else askEvent(c);
  }
  const view = plots.now();
  const busy = ev.asking || ev.key !== key ? waiting("Working out the switching event…") : "";
  if (!view || !ev.answer || ev.device !== c.id) return busy || waiting("Working out the switching event…");
  if (ev.answer instanceof Refused) return busy + refusal(ev.answer) + (view ? detailOnly(view) : "");
  const stale = ev.key !== key ? " is-stale" : "";
  // Named, so that a redraw keeps it, and the box being typed in inside it, as the line
  // that says it is being worked out comes and goes before it.
  return `${busy}<div class="ev-wrap${stale}" data-key="ev-wrap">${view.eventView(ev.answer, ev.mark)}</div>`;
}
