// The design and the control lab, kept in step with the session the server shares with a
// coding agent. Only on a page served on this machine, and only where the server keeps a
// session: the hosted page keeps what was entered in the browser alone, as it always has.
//
// The page writes its state a moment after each save, on the version it last read. When
// anyone else writes (the agent, an undo, another tab), the page reads the session again and
// lays over its own state only the figures that changed since the version it last had: what
// is typed and not yet sent stays. The server does the same with a write made on an old
// version (session.py); the browser's own copy stays as the cache, and as the page's state
// whenever the server cannot be reached.

import { api } from "../api";
import { Unreachable } from "../api/answers";
import { liveLab, livened } from "../control/carry";
import type { LabDoc, LabLive } from "../control/carry";
import { carry, readSaved } from "../control/carry";
import { designOfPage } from "../control/entry";
import { schedule } from "../engine";
import { presetsFor } from "../engine/loads";
import { suggestFor } from "../engine/suggest";
import { fromSetupFile, SETUP_VERSION } from "../restore";
import { onSaved, partsHeld } from "../state";
import { isNewer, onNewer } from "./build";
import type { State } from "../state";
import { LOAD } from "../steps";
import { app, draw, invalidate, res } from "../store";
import { NoSession, sessionApi } from "./client";
import { changedPaths, widened, withPaths } from "./paths";
import type { Path } from "./paths";
import { UNIT_PATHS } from "./units";
import type { Entry, Heard, Written } from "./types";

type Part = "design" | "lab";

/** This tab, as its writes name it: its own changes coming back are not taken as another's. */
export const tab = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);
const copy = <T>(v: T): T => (v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T));

/** Where the user is and how they look at it: this tab's own, never shared, so that neither the
 *  agent nor another tab moves the user's view. Only the design itself is in the session
 *  (the server keeps the same list: pagestate.VIEW). */
export const VIEW = [
  "step",
  "reached",
  "visited",
  "tab",
  "metric",
  "mapAt",
  "pwmPeriods",
  "compare",
  "focus",
  "focusPicked",
] as const satisfies readonly (keyof State)[];

/** The design without this tab's view of it: what is written to the session. */
export function content(raw: unknown): unknown {
  if (!raw || typeof raw !== "object") return raw;
  const out = { ...(raw as Record<string, unknown>) };
  for (const k of VIEW) delete out[k];
  return out;
}

/** A state from the session, seen from where this tab stands. */
function seenHere(next: State): State {
  const here = app.state as unknown as Record<string, unknown>;
  const view = Object.fromEntries(VIEW.map((k) => [k, copy(here[k])]));
  const seen: State = { ...next, ...view };
  // The drawing cannot show a part the design no longer has.
  if (seen.focus && !seen.devices.includes(seen.focus)) Object.assign(seen, { focus: null, focusPicked: false });
  return seen;
}

export const sync = {
  on: false,
  /** A newer build of MotionSim serves this address: this tab writes nothing more to the session. */
  stale: false,
  version: 0,
  /** Each part as the session last held it, as far as this tab knows. */
  synced: { design: null as unknown, lab: null as LabDoc | null },
  /** Labels of the figures the agent changed, by path: to say what a write of the page replaced. */
  labels: new Map<string, string>(),
};

/** Whoever wants to hear what the socket says: the notice, the activity log. */
export const heard = new Set<(said: Heard) => void>();

const WAIT: Record<Part, number> = { design: 300, lab: 400 };
const timers: Partial<Record<Part, ReturnType<typeof setTimeout>>> = {};
let writing = false;
const again = new Set<Part>();
let socket: WebSocket | null = null;
let backoff = 0;
let unsubscribe: (() => void) | null = null;

/** Beside the browser's copy of the design: the session's version that copy was made on, and
 *  whether it holds edits the session has not had yet. */
export const MARK = "motionsim.session.v1";
export interface Mark {
  version: number;
  edited: boolean;
}

export function readMark(): Mark | null {
  try {
    const raw = JSON.parse(localStorage.getItem(MARK) ?? "null") as Partial<Mark> | null;
    if (!raw || typeof raw !== "object" || typeof raw.version !== "number" || !Number.isFinite(raw.version))
      return null;
    return { version: Math.max(0, Math.floor(raw.version)), edited: raw.edited === true };
  } catch {
    return null;
  }
}

function writeMark(mark: Mark): void {
  try {
    localStorage.setItem(MARK, JSON.stringify(mark));
  } catch {
    /* nothing is kept here: the session is all there is */
  }
}

/** The mark as the page now stands against what the session holds. */
function settleMark(): void {
  if (sync.stale) return;
  writeMark({ version: sync.version, edited: !same(content(app.state), sync.synced.design) });
}

/** What changed between two copies of the design, each set of figures that moves as one taken
 *  whole (units.ts): a merge never takes part of one from either side. */
const changed = (before: unknown, after: unknown): Path[] => widened(changedPaths(before, after), UNIT_PATHS);

const overlaps = (p: Path, q: Path): boolean => {
  const n = Math.min(p.length, q.length);
  return p.slice(0, n).every((k, i) => q[i] === k);
};

/** The state the session holds, held to the page's shape; null where it holds none that can be drawn. */
function shaped(raw: unknown): State | null {
  if (!raw || typeof raw !== "object") return null;
  const state = fromSetupFile({ app: "MotionSim", setup: SETUP_VERSION, state: raw }, app.setup);
  if (!state) return null;
  const known = new Set(app.setup.devices.map((d) => d.id));
  state.devices = state.devices.filter((d) => known.has(d));
  state.added = state.added.filter((d) => known.has(d));
  if (state.focus && !known.has(state.focus)) state.focus = null;
  partsHeld(state);
  return state;
}

/** Whether the parts as the page now holds them are other than the session's: a part set the
 *  page mended (parts on the page and none ticked) is written back, for the agent to see too. */
function mended(raw: unknown): boolean {
  const r = (raw ?? {}) as { devices?: unknown; lead?: unknown };
  return !same(r.devices, app.state.devices) || (r.lead ?? "") !== app.state.lead;
}

/** Parts named that this page's list of parts does not have yet: the list is asked again. */
async function partsKnown(raw: unknown): Promise<void> {
  const r = raw as { devices?: unknown; added?: unknown } | null;
  const lists: unknown[][] = [r?.devices, r?.added].map((x) => (Array.isArray(x) ? (x as unknown[]) : []));
  const named = lists.flat().map(String);
  const known = new Set(app.setup.devices.map((d) => d.id));
  if (!named.some((d) => !known.has(d))) return;
  try {
    app.setup = await api.setup();
  } catch {
    /* drawn without them; the next change asks again */
  }
}

/** A state put on the page in place of the one there, keeping the page's own undo and folds. */
export function adoptDesign(given: State): void {
  const next = seenHere(given);
  if (same(next, app.state)) return;
  app.state = next;
  res.suggestion = null;
  invalidate("all");
  draw.rail();
  draw.panel(true);
  draw.stage();
  void suggestFor();
  if (next.step >= LOAD) void presetsFor();
  schedule();
}

/** Start keeping the page in step with the session, where the server keeps one. */
export async function startSession(): Promise<void> {
  if (api.mode() !== "server" || sync.on) return;
  // What the page holds as the read begins: an edit made while it is under way is the newer.
  const before = content(copy(app.state));
  const labBefore = carry.epoch();
  let current;
  try {
    current = await sessionApi.read();
  } catch {
    return; // an older server, or none: the browser's copy is all there is
  }
  sync.on = true;
  const mark = readMark();
  await partsKnown(current.doc.design);
  const remote = shaped(current.doc.design);
  const now = content(app.state);
  if (!remote) {
    sync.version = current.version;
    void write("design");
  } else if (mark?.edited) {
    // The browser's copy holds edits the session never had (a tab closed, or reloaded, before
    // they were written): they are written now, on the version they were made on. The server
    // lays them over what changed since; the page then takes up the whole of what it holds.
    sync.version = Math.min(mark.version, current.version);
    sync.synced.design = null;
    void write("design");
  } else {
    sync.version = current.version;
    sync.synced.design = content(copy(current.doc.design));
    const mine = changed(before, now);
    // Edited while the session was being read (a Reset, a figure typed): those figures stay.
    const merged = mine.length ? shaped(withPaths(sync.synced.design, now, mine)) : null;
    adoptDesign(merged ?? remote);
    if (merged || mended(current.doc.design)) void write("design");
    else settleMark();
  }
  sync.synced.lab = copy(current.doc.lab ?? null);
  // A Reset or a setup opened while the session was read: the lab takes that up, not the session's.
  if (carry.epoch() === labBefore && readSaved(current.doc.lab)) carry.open(current.doc.lab);
  onSaved.add(saved);
  const lab = liveLab();
  if (lab) listen(lab);
  livened.add(listen);
  addEventListener("pagehide", flush);
  document.addEventListener("visibilitychange", hidden);
  connect();
}

/** The lab's code has come: its changes are written, and it hears the session's. */
function listen(lab: LabLive): void {
  unsubscribe?.();
  unsubscribe = lab.subscribe(() => soon("lab"));
}

/** The page saved its design: written in a moment, and marked as edited until it is. */
const saved = () => {
  if (!sync.on || sync.stale) return;
  if (!same(content(app.state), sync.synced.design)) writeMark({ version: sync.version, edited: true });
  soon("design");
};

function soon(part: Part): void {
  if (!sync.on || sync.stale) return;
  clearTimeout(timers[part]);
  timers[part] = setTimeout(() => {
    timers[part] = undefined;
    void write(part);
  }, WAIT[part]);
}

/** The page is closing, or hidden (and may be closed unseen): what waits goes now, by a request
 *  the browser finishes even once the page has gone. */
export function flush(): void {
  if (!sync.on || sync.stale) return;
  for (const part of ["design", "lab"] as const) {
    clearTimeout(timers[part]);
    timers[part] = undefined;
    void write(part, true);
  }
}

const hidden = () => {
  if (document.visibilityState === "hidden") flush();
};

const valueOf = (part: Part): unknown => (part === "design" ? content(app.state) : (liveLab()?.read() ?? null));

/** A write taken: the version it made, the mark beside the browser's copy, and any figure of
 *  the agent's that it replaced, said. */
async function written(part: Part, done: Written): Promise<void> {
  if (done.rebased) await pull();
  else sync.version = Math.max(sync.version, done.version);
  if (part === "design") settleMark();
  const theirs = done.overwrote.filter((o) => o.by === "agent");
  if (!theirs.length) return;
  overwrote(theirs.map((o) => sync.labels.get(o.path) ?? o.path.split(".").pop()).join(", "));
}

/** Write one part, where it differs from what the session holds. One write at a time; a write
 *  made as the page closes goes at once, beside one under way, and outlives the page. */
async function write(part: Part, closing = false): Promise<void> {
  const value = valueOf(part);
  if (!sync.on || sync.stale || (part === "lab" && value === null) || same(value, sync.synced[part])) return;
  if (writing && !closing) {
    again.add(part);
    return;
  }
  const own = !writing;
  writing = true;
  const sent = copy(value);
  try {
    const done = await sessionApi.write(sync.version, { [part]: sent }, tab, closing);
    sync.synced[part] = sent as never;
    await written(part, done);
  } catch (e) {
    if (e instanceof NoSession) sync.on = false;
    else if (!(e instanceof Unreachable)) sync.synced[part] = sent as never; // refused: not sent again as is
  } finally {
    if (own) writing = false;
  }
  if (!own) return;
  const next = [...again];
  again.clear();
  for (const p of next) void write(p);
}

let saidOverwrote: (names: string) => void = () => undefined;
const overwrote = (names: string) => saidOverwrote(names);
/** How the page says its own write replaced what the agent had set: the notice's. */
export function onOverwrote(say: (names: string) => void): void {
  saidOverwrote = say;
}

/** Read the session again, and lay over the page what changed in it since this tab's last
 *  version: never over a figure edited on the page after the read began. */
export async function pull(source = ""): Promise<void> {
  const before = content(copy(app.state));
  let current;
  try {
    current = await sessionApi.read();
  } catch {
    return;
  }
  sync.version = Math.max(sync.version, current.version);
  const design = content(current.doc.design);
  const here = content(app.state);
  const mine = changed(before, here);
  // Where this tab knows nothing of what the session held, everything that differs is the session's.
  const known = sync.synced.design ?? here;
  const moved = changed(known, design).filter((p) => !mine.some((q) => overlaps(p, q)));
  sync.synced.design = copy(design);
  if (moved.length && design) {
    await partsKnown(design);
    const merged = shaped(withPaths(app.state, design, moved));
    if (merged) adoptDesign(merged);
  }
  if (mine.length || (design && mended(design))) void write("design");
  else settleMark();
  const lab = current.doc.lab ?? null;
  const labMoved = changedPaths(sync.synced.lab, lab).length > 0;
  sync.synced.lab = copy(lab);
  if (!labMoved || !lab) return;
  const live = liveLab();
  if (live) {
    live.adopt(lab, source);
    // The lab as it now stands is the session's: taking it up is not a change to write back.
    sync.synced.lab = copy(live.read());
  } else if (readSaved(lab)) carry.open({ ...lab, key: designOfPage().key });
}

/** What the socket said. */
export function hear(said: Heard): void {
  if (said.type === "session") {
    for (const f of said.change?.figures ?? []) sync.labels.set(f.path, f.label);
    if (said.client !== tab) void pull(said.source);
  } else if (said.type === "behind") void pull();
  heard.forEach((h) => h(said));
}

function connect(): void {
  if (typeof WebSocket === "undefined") return;
  const url = new URL("ws/session", location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  let open: WebSocket;
  try {
    open = new WebSocket(url.href);
  } catch {
    return;
  }
  socket = open;
  open.onopen = () => {
    backoff = 0;
  };
  open.onmessage = (m: MessageEvent) => {
    try {
      const said = JSON.parse(String(m.data)) as Heard;
      // Coming back after a drop: what changed meanwhile is read once.
      if (said.type === "hello") {
        if (isNewer(said.build)) return;
        if (said.version !== sync.version) void pull();
        return;
      }
      hear(said);
    } catch {
      /* not a message of the session's */
    }
  };
  open.onclose = () => {
    if (socket !== open || !sync.on) return;
    socket = null;
    backoff = Math.min(30000, backoff ? backoff * 2 : 1000);
    setTimeout(connect, backoff);
  };
}

/** Undo one of the agent's changes. The refusal, where it cannot be, is the caller's to say. */
export async function undoChange(entry: Entry): Promise<Written> {
  const done = await sessionApi.undo(entry.id, tab);
  // The undo is written under this tab's name, so the socket's word of it is not read back
  // here: this tab takes up what it put back itself.
  await pull();
  return done;
}

/** Everything put back as before: for the tests. */
export function stopSession(): void {
  sync.on = false;
  sync.stale = false;
  removeEventListener("pagehide", flush);
  document.removeEventListener("visibilitychange", hidden);
  sync.version = 0;
  sync.synced = { design: null, lab: null };
  sync.labels.clear();
  for (const part of ["design", "lab"] as const) {
    clearTimeout(timers[part]);
    timers[part] = undefined;
  }
  writing = false;
  again.clear();
  unsubscribe?.();
  unsubscribe = null;
  onSaved.delete(saved);
  livened.delete(listen);
  const s = socket;
  socket = null;
  s?.close();
  heard.clear();
}

/** A newer build serves this address: this tab stops writing, and what waits to be written is
 *  let go. The page says so and offers to reload (build.ts). */
onNewer(() => {
  sync.stale = true;
  for (const part of ["design", "lab"] as const) {
    clearTimeout(timers[part]);
    timers[part] = undefined;
  }
  again.clear();
});
