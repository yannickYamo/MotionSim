// What the page holds while it is open: what the user entered, what the engine answered,
// and the few things about the screen itself that outlive a redraw. One place, so that
// "these figures are not of these inputs" has one meaning everywhere.

import { NotWorkedOut, Refused } from "./api";
import type { Advice, Candidate, Capability, Cycle, DeviceSummary, KeptPart, Largest, Level, LoadPreset } from "./api";
import type { MapGrid, Probe, Proposal, Reading, ReadOutcome, Recommendation, Setup, Stage, Suggest } from "./api";
import type { CoolingOffer } from "./api";
import type { Change } from "./follow";
import type { State } from "./state";
import { LOAD, MOTOR, SUPPLY } from "./steps";

/** The engine's first answer and what the user has entered. Set once the page starts. */
export const app = { setup: null as unknown as Setup, state: null as unknown as State };

export interface BoxNote {
  raw: string;
  why: string;
  unused?: boolean;
  /** What a figure typed with a unit or a prefix came to: said at the box, not a fault. */
  echo?: boolean;
  label?: string;
  unit?: string;
  inUse?: string;
}

export interface FitNote {
  lines: { level: string; text: string }[];
}

/** Everything the engine has answered for the inputs as they stand. */
export const res = {
  stage: null as Stage | null,
  advice: null as Advice | null,
  proposal: null as Proposal | null,
  /** The inputs cannot work: the engine's reason, and the field at fault. */
  blocked: null as Refused | null,
  /** A figure the design cannot be worked out without, not given yet: asked for at its box. */
  waiting: null as Refused | null,
  /** The engine itself failed: nothing on screen is an answer for these inputs. */
  fault: null as string | null,
  /** The fault is the local server not answering: asked again until it does. */
  offline: false,
  cycle: null as Cycle | Refused | null,
  grid: null as MapGrid | Refused | null,
  advised: null as Recommendation[] | Refused | null,
  /** What the device under test can drive. */
  capable: null as Capability | Refused | null,
  /** How far the load could be scaled up. */
  biggest: null as Largest | Refused | "working" | null,
  /** When the largest load was asked for, how to stop it, and its probes so far. */
  biggestAsked: null as { at: number; stop: AbortController; probes: Probe[] } | null,
  /** The cooling figure the tool offers where the chosen cooling's own is left empty, for
   *  the inputs it was worked out for. */
  offer: null as { key: string; answer: CoolingOffer | Refused | "asking" } | null,
  /** Whether the motor as described fits the part: asked of the engine at the motor step. */
  fit: null as FitNote | Refused | null,
  /** What suits the device under test: the supply, and how each kind of motor fits it. */
  suggestion: null as { id: string; data: Suggest } | null,
  /** Kinds of load this motor usually drives, sized from its design point. */
  presets: null as { key: string; list: LoadPreset[] } | null,
  /** The motion followed for each thing compared (a device, or a load). */
  cycles: new Map<string, Cycle | Refused>(),
  /** Each compared device's map. */
  grids: new Map<string, MapGrid | Refused>(),
  /** Results for the motors and settings compared, each worked out with its own request. */
  variants: new Map<string, Candidate | Refused>(),
  /** The answers being worked out now, by key. */
  loading: new Set<string>(),
  /** When each slower answer was asked for, to say how long it has been on its way. */
  started: new Map<string, number>(),
  /** When the figures on screen stopped being those of the inputs. */
  staleSince: 0,
  /** The inputs the slower results were worked out for. */
  resultsOf: "",
  /** The inputs have moved since the figures on screen were worked out, and the answer for
   *  them as they now stand has not come yet. */
  stale: false,
};

export interface PartRead {
  name: string;
  /** When it was dropped, to say how long it has been read for. */
  at?: number;
  outcome?: ReadOutcome;
  refused?: Refused;
  file?: string;
}

/** What the screen remembers that is neither an input nor an answer. */
export const ui = {
  /** Another tab saved a newer setup: this tab has stopped saving until the user chooses. */
  otherTab: false,
  /** The part being added, or the last one added or refused. */
  reading: null as PartRead | null,
  typedRefused: null as Refused | null,
  /** Every box of the typed part the page itself found it cannot use, with why. */
  typedWrong: {} as Record<string, string>,
  /** What a box of the typed part says of a figure it took. */
  typedNotes: {} as Record<string, string>,
  typedBusy: false,
  /** The typed part whose figures were brought back to give one the tool took: the part
   *  added from them takes its place. */
  typedFrom: null as string | null,
  typedOpen: false,
  /** The device whose model is laid open for checking against its datasheet. */
  review: null as { id: string; data?: Reading; failed?: string } | null,
  missionFault: null as Refused | null,
  /** What was done to the mission file on the way in: how commas were read, what was left out. */
  missionNotes: [] as string[],
  /** Whether the user has the period drawing open; null: not chosen, so by screen width. */
  pwmOpen: null as boolean | null,
  /** What the engine is doing while it loads in the browser. */
  starting: null as string | null,
  /** Which of the engine's three stages of starting it is at, and when the page began loading. */
  startStage: 1,
  startAt: 0,
  savingMd: 0, // when the .md report was asked for, while it is being written
  savedMd: "", // the file the last .md report was saved as
  /** What opening a setup file came to, said above the step: opened, or why not. */
  setupNote: null as { bad: boolean; text: string } | null,
  /** A part just taken off the page, for a few seconds, with what it takes to put it back:
   *  the lists as they were, the device on the drawing, and where among the parts this
   *  browser keeps it was kept. */
  forgotten: null as null | {
    id: string;
    name: string;
    devices: string[];
    added: string[];
    focus: string | null;
    focusPicked: boolean;
    kept: { part: KeptPart; at: number }[];
  },
  /** A report that could not be written: said beside its button, the engine being well. */
  reportFault: null as string | null,
  /** A cooling being sized again for the design point as it now stands, or why it was not. */
  resizing: null as null | { asking: true } | { why: string },
  /** The part just made the design: the keyboard goes to its column once the table shows it. */
  toColumn: null as string | null,
  /** The results' own code did not come: said in their place, with Try again. */
  resultsFailed: false,
  /** The equations' or the printed report's code did not come: said above the step, with Try again. */
  fetchFault: null as null | { what: "equations" | "report"; text: string },
  /** The folds the user has opened or closed, kept through redraws: true is open. */
  folds: new Map<string, boolean>(),
  /** Boxes whose text is not what the state holds: what was typed, and what the box says of it.
   *  unused: what was typed is not in use, and the figure before it is (or the box is left
   *  out); the results say so, and its step is not done. label, unit: the box's own. */
  notes: new Map<string, BoxNote>(),
  /** What moved when the starting point followed the device under test, until it is dismissed. */
  followed: null as { device: string; changes: Change[] } | null,
  /** What was kept from an earlier visit could not be drawn, and was cleared. */
  cleared: false,
  /** The browser would not keep what was entered: the page works, and forgets on reload. */
  unsaved: false,
  /** What is said once to a screen reader: the verdict when it changes, and little else. */
  announced: "",
};

export type Scope = "all" | "deep" | "compared" | "motion";

/** No largest load is asked for any more, and none is shown: a request on its way is stopped. */
export function stopLargest(): void {
  res.biggestAsked?.stop.abort();
  res.biggestAsked = null;
  res.biggest = null;
}

/** Drop what was worked out, by how much of it the change behind the call can have moved.
 *  all: every answer that hangs on the inputs. deep: the slower results of the open tabs.
 *  compared: what is set side by side. motion: what follows the load through time. */
export function invalidate(scope: Scope): void {
  if (scope === "all" || scope === "deep") {
    ui.savedMd = ""; // saved for the inputs as they stood: not said of new ones
    res.cycle = res.grid = res.advised = null;
    res.capable = null;
    stopLargest();
    res.cycles.clear();
    res.grids.clear();
    res.variants.clear();
  }
  if (scope === "compared") {
    res.cycles.clear();
    res.variants.clear();
  }
  if (scope === "motion") {
    res.cycle = null;
    res.cycles.clear();
  }
}

/** What the results are of: every input, and nothing of where the user is looking. An
 *  answer is kept only if this reads the same when it arrives as when it was asked for,
 *  and everything worked out is dropped when it no longer reads as it did. */
export const inputsNow = (): string =>
  JSON.stringify({
    ...app.state,
    step: 0,
    reached: 0,
    tab: "",
    metric: "",
    mapAt: "",
    pwmPeriods: 0,
    typed: null,
    focus: null,
    focusPicked: false,
    added: null,
    // Whose a figure is says nothing of what it is.
    kindPicked: false,
    supplyOwn: false,
    motorOwn: null,
    pointOf: null,
    loadPicked: "",
  });

/** The inputs of the design itself: what is set beside it to compare is left out, so that
 *  changing only what is compared does not work out the design's own results again. */
export const designNow = (): string =>
  JSON.stringify({ ...JSON.parse(inputsNow()), compare: "", motorSet: null, loadSet: null, sweep: null });

/** The device the design starts from: the motor, the supply and the point follow it. It is
 *  the first device brought, and stays so while it is ticked: a device added to compare is
 *  compared on the design the user is looking at and never moves it. Only when it is
 *  unticked or taken away does the design follow another, the first ticked as the list
 *  shows them; or when the user asks to start the design from another part. */
export function underTest(): string | undefined {
  const { state } = app;
  if (state.lead && state.devices.includes(state.lead)) return state.lead;
  const next = app.setup.devices.find((d) => state.devices.includes(d.id))?.id ?? state.devices[0];
  state.lead = next ?? "";
  return next;
}

/** The devices ticked, in the order the list shows them. */
export const chosenDevices = (): DeviceSummary[] => app.setup.devices.filter((d) => app.state.devices.includes(d.id));

/** The candidate the drawing shows: the user's choice, else the first that could be run. */
export function focused(): Candidate | null {
  const list = res.proposal?.candidates ?? [];
  return list.find((c) => c.id === app.state.focus) ?? list.find((c) => c.result) ?? null;
}

/** Results are shown once the device, the motor and the conditions have all been given. */
export const conditionsGiven = (): boolean => app.state.reached >= LOAD && app.state.devices.length > 0;

/** The inputs have moved and their answer has not come: nothing worked out for the inputs as
 *  they were (a verdict, a figure, a word to a screen reader) may stand on the page, since it
 *  would read as the answer for the inputs it is beside. */
export const pending = (): boolean => res.stale && conditionsGiven();

/** The step whose form holds the input that was refused. */
export function blockedStep(): number {
  if (!res.blocked || app.state.reached < SUPPLY) return -1;
  const motorKeys = app.setup.motors[app.state.kind].fields.map((f) => f.key);
  return motorKeys.includes(res.blocked.field) ? MOTOR : SUPPLY;
}

/** The parts the user has brought. Whatever else sits in the folder the page is served
 *  from, only what this user added here is shown: the tool does not put parts in front of
 *  anyone. The made-up one appears only if they asked for it. */
export const ownDevices = (): DeviceSummary[] => app.setup.devices.filter((d) => app.state.added.includes(d.id));

/** Every part under test has its gate drivers inside the package. */
export function driversBuiltIn(): boolean {
  const chosen = chosenDevices();
  return chosen.length > 0 && chosen.every((d) => d.integrated_driver);
}

/** Whether a chosen device has no tabulated switching energy, so needs its gate drive described. */
export const needsGate = (): boolean =>
  app.setup.devices.some((d) => app.state.devices.includes(d.id) && d.needs_gate_drive);

const LEVELS: Level[] = ["ok", "caution", "undecided", "fail"];

/** The gravest of several levels. */
export const worst = (levels: Level[]): Level =>
  levels.reduce((a, b) => (LEVELS.indexOf(b) > LEVELS.indexOf(a) ? b : a), "ok" as Level);

export interface Verdict {
  level: Level;
  /** How far the motion has been followed for this verdict. unworked: no answer came for
   *  it (the server or the engine did not answer), which says nothing of the design. */
  motion: "none" | "pending" | "followed" | "refused" | "unworked";
  /** What over the motion made the verdict graver than at the design point, where it did. */
  why: string | null;
}

/**
 * The verdict on a device: at the design point and, for the device on the drawing, through
 * the motion too. A motion the motor cannot follow, or a check that fails over it, rules
 * the design out however well the design point alone would pass. A caution over the
 * motion is read on its own tab and does not change the word.
 */
export function verdictOf(c: Candidate): Verdict {
  if (!c.result || c.id !== focused()?.id) return { level: c.level, motion: "none", why: null };
  const cycle = res.cycle;
  if (cycle === null) return { level: c.level, motion: "pending", why: null };
  // No answer is not a refusal: the verdict stays the design point's own.
  if (cycle instanceof NotWorkedOut) return { level: c.level, motion: "unworked", why: null };
  if (cycle instanceof Refused) return { level: "fail", motion: "refused", why: cycle.reason };
  // Of the checks that fail over the motion, that the motor cannot follow it comes first: a
  // trip or a temperature on the part that was followed is a consequence, not the reason.
  const fails = c.level === "fail" ? [] : cycle.checks.filter((x) => x.level === "fail");
  const failed = fails.find((x) => x.topic === "motion") ?? fails[0];
  const why = failed ? `${failed.topic}: ${failed.message}` : null;
  return { level: failed ? "fail" : c.level, motion: "followed", why };
}

/** Draw again the open step, the rail and the drawing: what a change of the parts on the page moves. */
export function redrawAll(): void {
  draw.panel(true);
  draw.rail();
  draw.stage();
}

/** What the page asks to have redrawn. Set by the views; the engine side calls them without
 *  knowing what a redraw is, and so can be run and tested with no page at all. */
export const draw = {
  panel: (keepFocus = false): void => void keepFocus,
  stage: (): void => undefined,
  rail: (): void => undefined,
  preview: (): void => undefined,
  outputs: (): void => undefined,
  fit: (): void => undefined,
  /** Something is being worked out, whether or not the open tab shows it. */
  busy: (on: boolean): void => void on,
  /** Mark the figures on screen as waiting for a new answer, or take the mark away. */
  stale: (): void => undefined,
};
