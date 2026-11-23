// The device and the operating point of an event, in one line: said on the full-screen plot,
// on its PDF and on its image.

import type { SwitchingEvent } from "../api";
import { degrees, sig } from "../format";

export const pointSaid = (ev: SwitchingEvent) =>
  `${ev.name}, the hottest switch (${ev.position}), at ${sig(ev.v_dc)} V and ${sig(ev.current)} A, ` +
  `junction ${degrees(ev.tj)}`;
