// The probes: the wires the scope draws, as a control engineer names them (ω_m, T_e, i_dq), and
// the ink each is drawn in. Every wire of the diagram is a probe: pressed, it is added to the
// scope or taken out of it. Ink, not orange: the scope's traces take the switching event's
// colours (bone, lilac, teal, then a quieter bone), and what was asked for is dashed in the
// ink of what answers it, so ω* lies over ω_m in one colour.

import { sentence } from "../format";
import type { Word } from "./drawn";
import { wordOf } from "./layout";
import { commanded } from "./naming";
import type { LabState } from "./store";
import { tracesOf } from "./store";
import type { StripTrace } from "./plots";
import type { Run, Series, Wire } from "./types";
import { withUnits } from "./units";
import { asked, grouped, usualWires } from "./wires";
import type { Group } from "./wires";

/** The wires the scope draws: those picked, or the ones the test is usually read by. */
export const probesOf = (s: LabState): string[] => s.plotted ?? usualWires(s);

/** How a trace is drawn: its ink (0 bone, 1 lilac, 2 teal, 3 quiet bone), and its dash (0 solid,
 *  1 dashed, 2 dotted), for what was asked for. */
export interface Ink {
  ink: number;
  dash: number;
}

const portOf = (name: string): string => name.slice(name.indexOf(".") + 1);
const INKS = 4;

/** The ink of every trace, strip by strip: what was simulated in bone, lilac and teal in turn;
 *  what was asked for dashed in the ink of what answers it (the same port), else the first. */
export function inked(groups: Group[]): Map<string, Ink> {
  const out = new Map<string, Ink>();
  for (const g of groups) {
    const measured = g.traces.filter((t) => !asked(t.name));
    measured.forEach((t, k) => out.set(t.name, { ink: k % INKS, dash: 0 }));
    const taken = new Map<number, number>();
    let alone = 0;
    for (const t of g.traces.filter((x) => asked(x.name))) {
      const match = measured.find((m) => portOf(m.name) === portOf(t.name)) ?? measured[0];
      const ink = match ? out.get(match.name)!.ink : alone++ % INKS;
      const before = taken.get(ink) ?? 0;
      taken.set(ink, before + 1);
      out.set(t.name, { ink, dash: 1 + (before % 2) });
    }
  }
  return out;
}

const knownMemo = new WeakMap<object, { scheme: unknown; wires: Wire[] }>();

/** The units the wires are known by: the run's, or before one, the engine's sources; a
 *  transform's outputs in the unit of what goes into it, where the engine gives none. */
export function knownOf(s: LabState): Wire[] {
  const ran = s.run.answer && !(s.run.status === "running" && s.run.partial);
  const from: object | undefined = ran ? s.run.answer!.wires : s.presets?.sources;
  if (!from) return [];
  const had = knownMemo.get(from);
  if (had && had.scheme === s.scheme) return had.wires;
  const raw = ran ? s.run.answer!.wires : (s.presets?.sources ?? []).map((w) => ({ ...w, block: "" }));
  const wires = withUnits(raw, ran ? (s.run.answer!.scheme ?? s.scheme) : s.scheme, s.presets?.blocks);
  knownMemo.set(from, { scheme: s.scheme, wires });
  return wires;
}

/** The strips the scope draws: one for each quantity, in the order the test is read in. */
export function stripsOf(probes: string[], known: Wire[], series: Series, scenario: string): Group[] {
  return grouped(probes, known, series, scenario);
}

let memo: { key: unknown[]; inks: Map<string, Ink> } | null = null;

/** The ink of each probe as the scope draws it now; empty before anything has run. */
export function inksOf(s: LabState): Map<string, Ink> {
  const series = tracesOf(s);
  const key = [s.plotted, s.scheme, series, s.scenario, s.run.answer];
  if (memo && memo.key.every((k, n) => k === key[n])) return memo.inks;
  const inks = series ? inked(stripsOf(probesOf(s), knownOf(s), series, s.scenario)) : new Map<string, Ink>();
  memo = { key, inks };
  return inks;
}

/** A wire's name as an engineer writes it: ω_m for the shaft speed, T_e for the motor's torque,
 *  T_L for the load's, a star on what was asked for. */
export function signalWords(name: string, unit: string): Word {
  const port = portOf(name);
  const star = asked(name) || name.startsWith("cmd.");
  if (port === "torque") return { text: "T", sub: star ? "" : "e", star };
  if (port === "load_torque") return { text: "T", sub: "L", star: false };
  if (port === "omega_load") return { text: "ω", sub: "L", star: false };
  if (port === "speed") return { text: "ω", sub: name.startsWith("cmd.") ? "cmd" : star ? "" : "m", star };
  // A regulator's parts as its picture names them: P, I and FF, on their axis.
  const part = /^(prop|int|ff)(?:_(\w+))?$/.exec(port);
  if (part) return { text: { prop: "P", int: "I", ff: "FF" }[part[1]]!, sub: part[2] ?? "", star: false };
  if (/^(limited|clamped|saturated)$/.test(port))
    return { text: port === "clamped" ? "clamped" : "at limit", sub: "", star: false };
  const err = /^err(?:or)?(?:_(\w+))?$/.exec(port);
  if (err) return { text: "e", sub: err[1] ?? "", star: false };
  // A pair of axes with no unit given is read as currents: the frames are changed on the way back.
  return commanded(name, wordOf(port, unit, star, !unit));
}

/** The name in plain letters, for a list or a label read aloud: "ω m", "i q*". */
export const plainWords = (w: Word): string => `${w.text}${w.sub ? ` ${w.sub}` : ""}${w.star ? "*" : ""}`;

/** The block a wire comes from, as it is titled: the motor and the test for the kernel's own. */
export function sourceTitle(wire: string, s: Pick<LabState, "scheme" | "presets">): string {
  const block = wire.slice(0, wire.indexOf("."));
  if (block === "plant") return "the motor";
  if (block === "cmd") return "the test";
  if (block === "time") return "the clock";
  const b = s.scheme?.blocks.find((x) => x.name === block);
  return (b && s.presets?.blocks[b.kind]?.title) || block.replace(/_/g, " ");
}

const SUBSCRIPT: Record<string, string> = {
  a: "ₐ",
  e: "ₑ",
  h: "ₕ",
  i: "ᵢ",
  j: "ⱼ",
  k: "ₖ",
  l: "ₗ",
  m: "ₘ",
  n: "ₙ",
  o: "ₒ",
  p: "ₚ",
  r: "ᵣ",
  s: "ₛ",
  t: "ₜ",
  u: "ᵤ",
  v: "ᵥ",
  x: "ₓ",
  "0": "₀",
  "1": "₁",
  "2": "₂",
  "3": "₃",
  "+": "₊",
  "-": "₋",
};

/** A name in plain text, for where no markup can go (a list's option): a number as a
 *  subscript, letters after an underscore as engineers type them. Every phase and axis is then
 *  written one way (a has a small letter of its own, b and q have none). */
export function typedWords(w: Word): string {
  const sub = w.sub ? (/^[0-9+-]+$/.test(w.sub) ? [...w.sub].map((c) => SUBSCRIPT[c]).join("") : `_${w.sub}`) : "";
  return `${w.text}${sub}${w.star ? "*" : ""}`;
}

/** A signal in a list: the block it is of, what it is, and its symbol where it has one that is
 *  more than its own code name ("skip", "i dc 1" say nothing its words do not). */
export function optionWords(block: string, about: string, symbol: string, wire: string): string {
  const bare = (x: string) => x.replace(/[ _]/g, "").toLowerCase();
  const coded = bare(symbol) === bare(portOf(wire));
  if (!about) return `${block}: ${sentence(coded ? portOf(wire).replace(/_/g, " ") : symbol)}`;
  return `${block}: ${sentence(about)}${coded ? "" : ` · ${symbol}`}`;
}

/** Wires no one reads as a signal of the drive: the clock and the nought an open input reads. */
export const unshown = (wire: string): boolean => wire === "time.t" || wire.startsWith("const.");

/** Each strip's traces in their inks, run A's under them in the quietest. */
export function tracedOf(groups: Group[], inks: Map<string, Ink>, ghost: Run | null, series: Series): StripTrace[][] {
  return groups.map((g) => [
    ...(ghost
      ? g.traces
          .filter((t) => !asked(t.name) && ghost.series.wires[t.name])
          .map((t) => ({
            name: `${t.name}, run A`,
            values: ghost.series.wires[t.name],
            t: ghost.series.t,
            lo: ghost.series.lo?.[t.name],
            hi: ghost.series.hi?.[t.name],
            ink: 3,
            dash: 0,
            ghost: true,
          }))
      : []),
    ...g.traces.map((t) => ({
      name: t.name,
      values: t.values,
      lo: series.lo?.[t.name],
      hi: series.hi?.[t.name],
      ...(inks.get(t.name) ?? { ink: 0, dash: 0 }),
    })),
  ]);
}
