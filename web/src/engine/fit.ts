// Whether the motor as described fits the part, asked at the motor step while it is typed.

import { api, Refused } from "../api";
import { latest } from "../guard";
import { request } from "../state";
import { MOTOR } from "../steps";
import { app, draw, res, underTest } from "../store";
import { plainRefusal } from "../wording";

let fitTimer: ReturnType<typeof setTimeout> | undefined;

/** Ask whether the motor as described fits the part, and keep the answer if it is still the
 *  latest asked for. */
async function askFit(): Promise<void> {
  const { state } = app;
  const device = underTest();
  if (state.step !== MOTOR || !device) return;
  const current = latest("fit");
  const req = request(state);
  const point = { parallel: req.conditions.parallel, rpm: state.conditions.rpm, v_dc: state.conditions.v_dc };
  let fit: typeof res.fit;
  try {
    fit = await api.fit({ motor: req.motor, device, ...point });
  } catch (e) {
    fit = e instanceof Refused ? plainRefusal(e) : null;
  }
  if (!current()) return; // a later figure has been typed since
  res.fit = fit;
  draw.fit();
}

/** Ask again a moment after the motor's figures stop changing, and draw only the note. */
export function fitFor(now = false): void {
  clearTimeout(fitTimer);
  fitTimer = setTimeout(() => void askFit(), now ? 0 : 350);
}

/** Nothing more is asked of the fit for the state on the page. */
export function stopFit(): void {
  clearTimeout(fitTimer);
}
