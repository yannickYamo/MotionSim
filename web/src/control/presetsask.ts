// The one question the page itself asks of the control addresses, before the lab is opened:
// which scheme suits this design.

import { send } from "../api/transport";
import type { Presets } from "./types";

export const askPresets = (design: Record<string, unknown>, signal: AbortSignal): Promise<Presets> =>
  send<Presets>("/api/control/presets", design, signal);
