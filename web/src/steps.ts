// The path through the page. The user arrives with a power device to test. The motor, the
// conditions and the load say what it has to survive; nothing is said about losses until
// all of that is given.

import type { Tab } from "./state";

export const STEPS = [
  { name: "Device", icon: "cpu", about: "The part you want to test" },
  { name: "Motor", icon: "engine", about: "What it has to drive" },
  { name: "Supply and point", icon: "bolt", about: "Voltage, speed, torque" },
  { name: "Load", icon: "weight", about: "What the motor moves" },
  { name: "Results", icon: "chart-bar", about: "Does it suit, and why" },
] as const;

export const DEVICE = 0;
export const MOTOR = 1;
export const SUPPLY = 2;
export const LOAD = 3;
export const RESULTS = 4;

export const TABS: [Tab, string][] = [
  ["proposal", "Verdict"],
  ["losses", "Losses"],
  ["motion", "Motion"],
  ["limits", "Limits"],
];

/** Devices, or loads, compared at once: more cannot be told apart on one chart. */
export const MOST = 5;

/** Switching periods the drawing under the result can show. */
export const ZOOMS = [1, 2, 5, 10, 20];
