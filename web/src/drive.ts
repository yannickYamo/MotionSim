// Whose drive a verdict is on. Until the user has set or confirmed the motor, the point or the
// load, those are assumed for them (sized to the part, or the example's), and every verdict
// says so: a pass on an invented drive is not a pass on theirs. Opening a step is not consent;
// a figure changed, a kind chosen, a mission brought or "Use this load" pressed is.

import type { State } from "./state";

/** Whether any of the motor, the point and the load is still the user's own choice. */
export function driveSet(state: State): boolean {
  return (
    state.kindPicked ||
    state.supplyOwn ||
    state.loadTouched ||
    !!state.mission ||
    Object.values(state.motorOwn).some((keys) => keys.length > 0) ||
    Object.values(state.pointOf).some((typed) => Object.keys(typed).length > 0)
  );
}

/** The drive is assumed: nothing of the motor, the point or the load has been set by the user. */
export const driveAssumed = (state: State): boolean => !driveSet(state);
