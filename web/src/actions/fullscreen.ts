// The graphs of the results full screen: their code comes with the results' own, when one is opened.

import { notRefused } from "../api";
import { app, focused, res } from "../store";
import { loadResults } from "../views/resultsload";
import { limitOf } from "../views/tabs/capability";
import type { LimitWhich } from "../views/tabs/capability";

const named = () => focused()?.name ?? "the device";

/** A chart of the motion. */
export async function openMotionFull(el: HTMLElement): Promise<void> {
  const cycle = notRefused(res.cycle);
  if (!cycle) return;
  const { openMotion } = await loadResults();
  openMotion(cycle, el.dataset.motionFull as "tj" | "rpm" | "torque" | "i_peak", named());
}

/** The switching chart. */
export async function openPwmFull(): Promise<void> {
  const c = focused();
  if (!c?.pwm) return;
  const { openPwm } = await loadResults();
  openPwm(c.pwm, app.state.pwmPeriods, c.name);
}

/** A limit of what the device can drive. */
export async function openLimitFull(el: HTMLElement): Promise<void> {
  const capable = notRefused(res.capable);
  if (!capable) return;
  const { openLimit } = await loadResults();
  openLimit(limitOf(capable, el.dataset.limitFull as LimitWhich), named());
}
