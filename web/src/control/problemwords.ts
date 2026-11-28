// A refusal at a figure of a block, said in the words the lab shows the figure by: the engine
// names it by its path (scheme.blocks.current.kp_q), which is said at the field as its label
// (Kp,q); a fix that only says to raise or lower that same figure adds nothing there, and goes.

import { scaleOf } from "./figures";
import { keyWord } from "./keys";
import type { Problem } from "./store";
import type { Param, Value } from "./types";
import { sig } from "../format";

const AT_BLOCK = /^scheme\.blocks\.[^.]+\.([^.]+)$/;
const escaped = (t: string) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** The problem with the figure's path said as its label. */
export function inWords(p: Problem): Problem {
  const at = AT_BLOCK.exec(p.field);
  if (!at) return p;
  const label = keyWord(at[1]);
  const path = new RegExp(escaped(p.field), "gi");
  const reason = p.reason.replace(path, label).replace(/\bcannot\b/g, "can't");
  const fix = p.fix.replace(path, label);
  const same = new RegExp(`^(raise|lower|set|change)\\s+${escaped(label)}\\.?$`, "i").test(fix.trim());
  return { ...p, reason, fix: same ? "" : fix };
}

/** A figure set on a block, held to the bounds the engine gives it: the refusal in words, or null. */
export function outOfBounds(field: string, param: Param | undefined, value: Value): Problem | null {
  if (!param || typeof value !== "number" || !Number.isFinite(value)) return null;
  const name = keyWord(param.name);
  const { unit, k } = scaleOf(param.unit, value);
  const said = (v: number) => `${sig(v * k, 4)}${unit ? ` ${unit}` : ""}`;
  if (param.low !== null && param.low !== undefined && value < param.low)
    return { reason: `${name} can't be below ${said(param.low)}`, fix: "", field };
  if (param.high !== null && param.high !== undefined && value > param.high)
    return { reason: `${name} can't be above ${said(param.high)}`, fix: "", field };
  return null;
}
