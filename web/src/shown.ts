// What the results show of their own accord, for this visit only: the map once it is asked
// for, a change of what is compared waiting on the user's word, a column just taken out.

import type { State } from "./state";

/** What is compared, by what the + Add menu offers. */
export type Kind = State["compare"];

/** An addition that would clear what is compared now, held until the user says yes or no. */
export interface Switch {
  to: Kind;
  /** The load picked, where a load was added. */
  preset?: string;
}

/** What was compared before a column was taken out: put back as it was by Undo. */
export interface Removed {
  name: string;
  compare: Kind;
  devices: string[];
  focus: string | null;
  focusPicked: boolean;
  loadSet: State["loadSet"];
  motorSet: State["motorSet"];
  sweep: State["sweep"];
}

/** What a small dialog is editing: a copy of the motor with a change, or a setting tried. */
export type Editing = { kind: "motor"; id: string | null } | { kind: "sweep"; key: string } | null;

export const shown = {
  /** The map under the losses: solved and drawn only once it is asked for. */
  map: false,
  confirm: null as Switch | null,
  removed: null as Removed | null,
  editing: null as Editing,
  /** What the small dialog says of what was typed into it, by box. */
  wrong: {} as Record<string, string>,
  /** What step 1 last said of a part brought, as the device dialog was opened: not said again
   *  in the dialog, which says only what is brought in it. */
  readBefore: null as unknown,
};
