// What suits the device under test: the motor and the point start there, where the user has
// not typed their own.

import { api } from "../api";
import type { Suggest } from "../api";
import { leaveMains, settle } from "../follow";
import { latest, once } from "../guard";
import { presetsFor } from "./loads";
import { save, usualLoad } from "../state";
import { LOAD, MOTOR, SUPPLY } from "../steps";
import { app, draw, res, ui, underTest } from "../store";

/** Put what the user has not typed where the device under test starts it. Says what moved,
 *  once the user has seen the figures that moved. Returns whether anything did. */
function startFrom(id: string, suggest: Suggest): boolean {
  const { state, setup } = app;
  // A part put under test while the drive is on the mains, which it cannot stand: off the mains first.
  const left = leaveMains(state, suggest);
  const changes = [...(left ? [left] : []), ...settle(state, setup, suggest)];
  usualLoad.swings = suggest?.application?.swings === true;
  const start = suggest?.application?.start;
  // Sealed in its shell, a compressor's motor has no sensor: the made-up part's application
  // brings how such products start, until the user picks a load of their own.
  if (start && !state.loadPicked && ["pmsm", "bldc", "synrm"].includes(state.kind)) state.start.method = start;
  if (!changes.length) return false;
  const device = setup.devices.find((d) => d.id === id)?.name ?? "the device under test";
  ui.followed = state.reached >= MOTOR ? { device, changes } : null;
  res.fit = null;
  ui.notes.clear();
  save(state);
  return true;
}

/**
 * Ask what suits the device under test, and start the motor and the point there: the
 * recommended kind of motor, its example wound for the supply the device suits, and that
 * supply, each only where the user has not typed their own. An answer for a device that is
 * no longer the one under test is dropped. Returns whether any figure moved.
 */
export async function suggestFor(): Promise<boolean> {
  const { state } = app;
  const id = underTest();
  const current = latest("suggest");
  if (!id) {
    res.suggestion = null;
    return false;
  }
  if (res.suggestion?.id === id) return false;
  let data: Suggest;
  try {
    data = await once(`suggest:${id}`, () => api.suggest(id));
  } catch {
    return false; // nothing is known of what suits it: the figures stay as they are
  }
  if (!current() || underTest() !== id) return false; // the choice moved on while this was asked
  if (res.suggestion?.id === id) return false; // another asking of the same has already been taken
  res.suggestion = { id, data };
  const moved = startFrom(id, data);
  // Loads that were sized before this was known are sized again, for the application it names.
  if (state.step >= LOAD) void presetsFor();
  if (state.step === MOTOR || state.step === SUPPLY) draw.panel(true);
  draw.stage();
  return moved;
}
