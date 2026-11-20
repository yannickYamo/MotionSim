// The limits of the design: what has to be built around the device, and what the device can
// drive, each under its own heading on one tab.

import { capabilityTab } from "./capability";
import { settingsTab } from "./build";
import { focused } from "../../store";
import { notReady } from "./ready";

export function limitsTab(): string {
  if (!focused()?.result) return notReady();
  return (
    `<section class="tab-section" aria-labelledby="limits-build"><h3 id="limits-build">What to build</h3>` +
    `${settingsTab()}</section>\n` +
    `<section class="tab-section" aria-labelledby="limits-drive"><h3 id="limits-drive">What it can drive</h3>` +
    `${capabilityTab()}</section>`
  );
}
