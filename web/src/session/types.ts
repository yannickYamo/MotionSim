// The session a page served on this machine shares with a coding agent: its shapes, as the
// server sends them (src/motionsim/app/shared.py).

import type { LabDoc } from "../control/carry";

export interface Figure {
  path: string;
  label: string;
  unit: string;
  old: unknown;
  new: unknown;
  had: boolean;
}

/** One thing the agent did, or an undo of it. */
export interface Entry {
  id: string;
  /** Seconds since 1970. */
  at: number;
  source: "agent" | "chat" | "undo" | "page";
  kind: "change" | "undo" | "action";
  /** The change in one line, with its figures before and after. */
  what: string;
  figures: Figure[];
  version: number | null;
  undone: { at: number; by: string | null } | null;
  undoes: string | null;
  overwritten: { at: number; by: string; figures: string[] } | null;
  undoable: boolean;
}

export interface SessionDoc {
  design: unknown;
  lab: LabDoc | null;
}

export interface Current {
  version: number;
  doc: SessionDoc;
}

export interface Written {
  version: number;
  changed: string[];
  rebased: boolean;
  overwrote: { path: string; was: unknown; by: string }[];
  change: Entry | null;
}

export interface AgentSettings {
  code: string;
  url: string;
  command: string;
  write: boolean;
}

/** What the socket says: a write, an entry marked, or that the page fell behind. */
export type Heard =
  | { type: "hello"; version: number; build?: string }
  | ({ type: "session"; source: string; client: string } & Written)
  | { type: "activity"; change: Entry }
  | { type: "behind" };
