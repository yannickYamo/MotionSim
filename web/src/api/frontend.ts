// What the engine answers about the front end of a drive fed from the mains.

import type { Check } from "./types";

/** One stage that can stand between the mains and the DC link, solved on the design: or the
 *  reason it cannot be. */
export interface FrontEndChoice {
  id: string;
  name: string;
  about: string;
  shapes: boolean;
  returns: boolean;
  level: "ok" | "caution" | "undecided" | "fail";
  refused?: string;
  v_dc?: number;
  loss?: number;
  efficiency?: number;
  power_factor?: number;
  within_limit?: boolean | null;
}
/** The front end chosen, in full. */
export interface FrontEndResult {
  topology: string;
  name: string;
  v_dc: number;
  f_sw: number | null;
  p_link: number;
  p_in: number;
  loss: number;
  loss_switches: number;
  loss_diodes: number;
  efficiency: number;
  i_line: number;
  power_factor: number;
  thd: number;
  within_limit: boolean | null;
  harmonics: { order: number; current: number; limit: number | null }[];
  tj_peak: number | null;
  tj_max: number;
  positions: number;
  roles: { name: string; count: number; conduction: number; switching: number; tj_peak: number }[];
  inductor: { henry: number; count: number; i_peak: number; i_rms: number; ripple: number } | null;
  capacitor: {
    rms: number | null;
    slow: number;
    capacitance: number | null;
    sized: boolean;
    v_ripple: number | null;
  };
  notes: string[];
  checks: Check[];
  level: "ok" | "caution" | "undecided" | "fail";
  device: string;
}
export interface FrontEndAnswer {
  mains: { v: number; f: number; phases: number };
  recommended: string;
  why: string;
  chosen: string;
  v_dc: number;
  v_dc_given: boolean;
  choices: FrontEndChoice[];
  result: FrontEndResult;
  /** What holding the link only as high as the motor needs would save in both stages. */
  lever: { v_dc: number; need: number; saves: number; loss: number; from: number } | null;
}
