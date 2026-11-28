// What of the control lab a setup file carries, and what a Reset clears of it: the scheme
// picked, its edits, the test, its figures and the fidelity. This file is all the page itself
// holds of it; the lab's own code is fetched when it is first opened, and reads what is waiting
// here when it opens on a design.

import type { Plant } from "./types";

/** The lab's part of a setup file. Versioned; every field may be absent in a file. */
export interface ControlSaved {
  v: 1;
  /** The design the edits were made on: they are carried only onto the same design. */
  key: string;
  scheme: string;
  /** The scheme as edited, where it was edited; null where it was as tuned. */
  edits: unknown;
  scenario: string;
  figures: Record<string, Record<string, string>>;
  fidelity: string;
  /** The motor and load as simulated, where they differ from the controller's model. */
  plant?: Plant;
}

const text = (v: unknown): string => (typeof v === "string" ? v : "");

/** A saved part read back, tolerant of what is missing or not of its shape; null where
 *  nothing usable is there. */
export function readSaved(raw: unknown): ControlSaved | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (r.v !== undefined && r.v !== 1) return null;
  const figures = figuresOf(r.figures);
  const saved: ControlSaved = {
    v: 1,
    key: text(r.key),
    scheme: text(r.scheme),
    edits: isScheme(r.edits) ? r.edits : null,
    scenario: text(r.scenario),
    figures,
    fidelity: text(r.fidelity),
    plant: plantOf(r.plant),
  };
  return saved.scheme || saved.scenario || saved.fidelity || Object.keys(figures).length ? saved : null;
}

/** The motor and load a setup carried: a shaft's figures as numbers, the iron as a word. */
export function plantOf(raw: unknown): Plant {
  if (!raw || typeof raw !== "object") return {};
  const r = raw as Record<string, unknown>;
  const plant: Plant = {};
  if (r.coupling && typeof r.coupling === "object") {
    const figures = Object.entries(r.coupling as Record<string, unknown>).filter(
      ([, v]) => typeof v === "number" && Number.isFinite(v),
    ) as [string, number][];
    if (figures.some(([k]) => k === "resonance_hz")) plant.coupling = Object.fromEntries(figures);
  }
  if (r.iron === "saturating") plant.iron = "saturating";
  return plant;
}

const isScheme = (v: unknown): boolean =>
  !!v && typeof v === "object" && Array.isArray((v as { blocks?: unknown }).blocks);

/** The test's figures as typed, test by test: text alone is kept. */
function figuresOf(raw: unknown): ControlSaved["figures"] {
  const figures: ControlSaved["figures"] = {};
  if (!raw || typeof raw !== "object") return figures;
  for (const [test, values] of Object.entries(raw as Record<string, unknown>)) {
    if (!values || typeof values !== "object") continue;
    const kept = Object.entries(values as Record<string, unknown>).filter(([, v]) => typeof v === "string");
    figures[test] = Object.fromEntries(kept) as Record<string, string>;
  }
  return figures;
}

/** The lab as the session shared with a coding agent holds it: what a setup carries, with the
 *  wires probed and the last run's summary. Every field may be absent. */
export interface LabDoc extends Partial<ControlSaved> {
  plotted?: string[] | null;
  last_run?: LastRun | null;
}

export interface LastRun {
  id: string;
  source: "page" | "agent";
  at: number;
  scheme: string;
  scenario: string;
  fidelity: string;
  level: string;
  summary: string;
  findings: unknown[];
}

/** The lab, once loaded, as the session reads and writes it. */
export interface LabLive {
  read(): LabDoc | null;
  subscribe(heard: () => void): () => void;
  /** A lab written by the agent (or an undo of it) put in place in the lab as it stands. */
  adopt(doc: LabDoc, source: string): void;
}

let live: LabLive | null = null;

/** The lab says how the session reads it, once its code has come. */
export function goLive(lab: LabLive): void {
  live = lab;
  livened.forEach((heard) => heard(lab));
}

export const liveLab = (): LabLive | null => live;

/** Who waits for the lab's code to come. */
export const livened = new Set<(lab: LabLive) => void>();

type Waiting = ControlSaved | "fresh" | null;

let snapshot: (() => ControlSaved | null) | null = null;
let waiting: Waiting = null;
/** Counted up at each setup opened and each Reset: what was read of the session before one is older. */
let opened = 0;

export const carry = {
  /** The lab, once loaded, says how to read what it holds. */
  register(read: () => ControlSaved | null): void {
    snapshot = read;
  },
  /** What a setup saved now carries of the lab: what waits to be opened, else what it holds. */
  saved(): ControlSaved | null {
    if (waiting === "fresh") return null;
    return waiting ?? snapshot?.() ?? null;
  },
  /** A setup was opened: the lab takes this up the next time it opens. */
  open(raw: unknown): void {
    waiting = readSaved(raw) ?? "fresh";
    opened += 1;
  },
  /** Reset: the lab starts again from nothing the next time it opens. */
  clear(): void {
    waiting = "fresh";
    opened += 1;
  },
  /** How many setups were opened and Resets made: to tell whether one came since. */
  epoch: (): number => opened,
  /** What waits for the lab, taken once. */
  take(): Waiting {
    const was = waiting;
    waiting = null;
    return was;
  },
};
