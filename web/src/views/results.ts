// What only the results draw: the four tabs and the comparison under them. Fetched once the
// page has first been drawn, so that a first visit opens on step 1 without waiting for it.

import { compareArea } from "./comparebar";
import { limitsTab } from "./tabs/limits";
import { lossesTab } from "./tabs/losses";
import { motionTab } from "./tabs/motion";
import { proposalTab } from "./tabs/verdict";

export const TAB_BODY = {
  proposal: proposalTab,
  losses: lossesTab,
  motion: motionTab,
  limits: limitsTab,
};

export { compareArea };
export * as eventPlots from "../eventplot/view";
export { openMotion } from "../charts/motionfull";
export { openLimit } from "../charts/limitfull";
export { openPwm } from "../charts/pwmfull";
