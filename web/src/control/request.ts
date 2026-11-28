// The design as every request asks it of the engine: the page's design, with the motor and load
// as simulated where they differ from the controller's model (a shaft that twists, iron that
// saturates). The same in a run, the loops, a comparison, an exploration and the C.

import type { LabState } from "./store";

export function designOf(s: Pick<LabState, "design" | "plant">): Record<string, unknown> {
  const { coupling, iron } = s.plant;
  const plant = { ...(coupling ? { coupling } : {}), ...(iron ? { iron } : {}) };
  return Object.keys(plant).length ? { ...s.design, plant } : s.design;
}
