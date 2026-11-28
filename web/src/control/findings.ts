// What a run found, set where it is seen: each finding as a chip of one symbol and one figure,
// and drawn on the trace it was read from as a labelled region (a band of values, a stretch of
// time, a limit, an instant). Everything here is read from the engine's answer; nothing is
// worked out anew. A fail is never softened: its chip leads, in its own colour, with its word.

import { sig } from "../format";
import { written } from "./figures";
import type { Finding, Run, Scheme } from "./types";
import { groupOf } from "./wires";

export type Tone = "fail" | "improve" | "note" | "good";

/** Where a finding is seen: a strip of the scope, a loop of the Laplace lens, or the cost. */
export type Target =
  | { kind: "strip"; group: string; wire: string; note: string }
  | { kind: "laplace"; loop: "current_q" | "speed" }
  | { kind: "cost" };

export interface Chip {
  id: string;
  /** The symbol, as an engineer writes it: PM, THD, Tj. */
  label: string;
  /** The figure with its unit: 68.5°. Empty where the finding has none. */
  figure: string;
  tone: Tone;
  /** The findings the chip opens: one, or every passing one for the count. */
  findings: Finding[];
  target: Target | null;
}

/** A finding drawn on a strip, in the strip's own units. */
export type Note =
  | { kind: "band"; id: string; lo: number; hi: number; label: string; tone: Tone; wire?: string }
  | { kind: "span"; id: string; from: number; to: number; label: string; tone: Tone }
  | { kind: "level"; id: string; value: number; both: boolean; label: string; tone: Tone }
  | { kind: "tick"; id: string; t: number; label: string; tone: Tone };

export const toneOf = (f: Finding): Tone =>
  f.tag === "good" ? "good" : f.tag === "note" ? "note" : f.severity >= 3 || f.id === "unstable" ? "fail" : "improve";

const RANK: Record<Tone, number> = { fail: 0, improve: 1, note: 2, good: 3 };

/** The first figure a sentence gives, with its unit: "0.095°" of "angle error 0.095° rms". */
export function firstFigure(said: string): string {
  const m = /(-?\d+(?:\.\d+)?)\s?(%|°C|°|dB|kHz|Hz|mW|W|mA|A|kV|V|ms|µs|s|K|N·m|rpm|rad\/s)?/.exec(said);
  if (!m) return "";
  return m[2] ? `${m[1]}${m[2] === "°" ? "" : " "}${m[2]}` : m[1];
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pc = (share: number | null): string => (share === null ? "" : `${sig(share * 100)} %`);

/** The quality figures a chip reads, where the engine sends them. */
function qualityOf(run: Run) {
  const q = (run.quality ?? {}) as Record<string, unknown>;
  const loops = (q.loops ?? {}) as Record<string, Record<string, unknown> | undefined>;
  const tj = (q.tj ?? {}) as Record<string, unknown>;
  const ripple = (q.ripple ?? {}) as Record<string, unknown>;
  return {
    pmCurrent: num(loops.current?.phase_deg),
    pmSpeed: num(loops.speed?.phase_deg),
    thd: num(ripple.thd) ?? num(run.channels?.thd),
    tjPeak: num(tj.peak),
    tjHigh: num(tj.high),
  };
}

/** The wire a step is read on, and the strip it is drawn in. */
function stepPlace(run: Run): { wire: string; group: string } | null {
  const step = run.step;
  if (!step) return null;
  const unit = run.wires.find((w) => w.name === step.wire)?.unit ?? "";
  return { wire: step.wire, group: groupOf({ name: step.wire, unit }) };
}

type Described = Omit<Chip, "id" | "tone" | "findings">;

/** What a describer is given: the finding, its run, its quality figures, its step's place and
 *  the first figure of its own words. */
interface Seen {
  f: Finding;
  run: Run;
  q: ReturnType<typeof qualityOf>;
  step: { wire: string; group: string } | null;
  fallback: string;
}

const onStep = (s: Seen, note: string): Target | null => (s.step ? { kind: "strip", ...s.step, note } : null);
const degrees = (v: number | null, fallback: string): string => (v === null ? fallback : `${sig(v)}°`);

/** The junction at its worst: the top of the thermal assumptions' spread where it is above the peak. */
function junctionFigure({ q, fallback }: Seen): string {
  const worst = q.tjHigh ?? q.tjPeak;
  if (worst === null) return fallback;
  const spread = q.tjHigh !== null && q.tjPeak !== null && q.tjHigh > q.tjPeak + 0.05;
  return `${spread ? "≤ " : ""}${sig(worst)} °C`;
}

const stepTime = (s: Seen): string =>
  s.run.step?.settling_time != null ? written(s.run.step.settling_time, "s", 3) : s.fallback;

/** One of a trip's figures, as its chip shows it. */
const tripFigure = (s: Seen, key: string, unit: string): string => {
  const v = num((s.run as { trip?: Record<string, unknown> | null }).trip?.[key]);
  if (v === null) return s.fallback;
  // An angle's degree sign sits on its figure, as in 18.7°.
  return unit === "°" ? `${sig(Math.abs(v))}°` : written(Math.abs(v), unit, 3);
};

const ABC: Target = { kind: "strip", group: "abc A", wire: "plant.i_a", note: "ripple" };
const TORQUE: Target = { kind: "strip", group: "N·m", wire: "plant.torque", note: "torque-ripple" };
const ANGLE: Target = { kind: "strip", group: "rad", wire: "observer.error", note: "angle" };

/** The angle in use against the rotor's: the injection's where the scheme injects, else the observer's. */
const angleOf = (s: Seen): Target => {
  const injection = s.run.scheme?.blocks.find((b) => b.kind === "hf_injection");
  return injection ? { ...ANGLE, wire: `${injection.name}.error` } : ANGLE;
};

/** Each kind of finding: its symbol, its figure and where it is seen. */
const DESCRIBE: Record<string, (s: Seen) => Described> = {
  current_margin: (s) => ({
    label: "PM",
    figure: degrees(s.q.pmCurrent, s.fallback),
    target: { kind: "laplace", loop: "current_q" },
  }),
  speed_margin: (s) => ({
    label: "PM ω",
    figure: degrees(s.q.pmSpeed, s.fallback),
    target: { kind: "laplace", loop: "speed" },
  }),
  unstable: () => ({ label: "Unstable", figure: "", target: { kind: "laplace", loop: "current_q" } }),
  thd: (s) => ({ label: "THD", figure: s.q.thd === null ? s.fallback : pc(s.q.thd), target: ABC }),
  torque_ripple: (s) => ({ label: "ΔT", figure: s.fallback, target: TORQUE }),
  junction: (s) => ({ label: "Tj", figure: junctionFigure(s), target: { kind: "cost" } }),
  swing: (s) => ({ label: "ΔTj", figure: s.fallback, target: { kind: "cost" } }),
  loss_split: (s) => ({ label: "Loss", figure: s.fallback, target: { kind: "cost" } }),
  carrier: (s) => ({ label: "fsw/fout", figure: s.fallback, target: null }),
  angle: (s) => ({ label: "θ err", figure: s.fallback, target: angleOf(s) }),
  polarity: () => ({ label: "N/S", figure: "not told", target: null }),
  coupling: (s) => ({ label: "θ load", figure: s.fallback, target: angleOf(s) }),
  overshoot: (s) => ({
    label: "OS",
    figure: s.run.step?.overshoot != null ? pc(s.run.step.overshoot) : s.fallback,
    target: onStep(s, "overshoot"),
  }),
  shunt_unread: (s) => {
    const share = s.run.channels?.unread_share;
    const shunt = s.run.scheme?.blocks.find((b) => b.kind === "shunt_sampling")?.name ?? "sample";
    return {
      label: "Unread",
      figure: typeof share === "number" ? pc(share) : s.fallback,
      target: { kind: "strip", group: "abc A", wire: `${shunt}.i_a`, note: "ripple" },
    };
  },
  load_overshoot: (s) => ({
    label: "OS load",
    figure: s.run.step?.load?.overshoot != null ? pc(s.run.step.load.overshoot) : s.fallback,
    target: { kind: "strip", group: "rpm", wire: "plant.omega_load", note: "overshoot" },
  }),
  settling: (s) => ({ label: "ts", figure: stepTime(s), target: onStep(s, "settling") }),
  start: (s) => ({ label: "Start", figure: stepTime(s), target: onStep(s, "settling") }),
  incomplete: (s) => ({ label: "Not reached", figure: stepTime(s), target: onStep(s, "settling") }),
  disturbance: (s) => ({ label: "Dip", figure: s.fallback, target: onStep(s, "settling") }),
  step_error: (s) => ({ label: "e∞", figure: s.fallback, target: onStep(s, "overshoot") }),
  edit: () => ({ label: "Edits", figure: "", target: null }),
  trip: (s) => ({ label: "Trip", figure: tripFigure(s, "rpm", "rpm"), target: { ...ABC, note: "trip" } }),
  trip_link: (s) => ({
    label: "Into link",
    figure: tripFigure(s, "link_peak", "A"),
    target: { kind: "strip", group: "link A", wire: "inverter.i_link", note: "trip" },
  }),
  trip_seen: (s) => ({ label: "seen", figure: tripFigure(s, "seen_deg", "°"), target: { ...ABC, note: "trip" } }),
  trip_unseen: (s) => ({ label: "unseen", figure: s.fallback, target: { ...ABC, note: "trip" } }),
  trip_fall: (s) => ({
    label: "Fell",
    figure: tripFigure(s, "fall_deg", "°"),
    target: { kind: "strip", group: "rpm", wire: "plant.omega_m", note: "trip" },
  }),
  trip_peak: (s) => ({ label: "Î motor", figure: tripFigure(s, "i_peak", "A"), target: { ...ABC, note: "trip" } }),
  mpc_rate: (s) => ({ label: "MPC", figure: s.fallback, target: null }),
  pulsed: (s) => ({ label: "Î pulse", figure: s.fallback, target: { ...ABC, note: "pulsed" } }),
  floor: (s) => ({
    label: "ω floor",
    figure: s.run.floor ? `${sig(s.run.floor.hardware_rpm)} rpm` : s.fallback,
    target: { kind: "strip", group: "rpm", wire: "plant.omega_m", note: "floor" },
  }),
  motion: (s) => ({
    label: "Motion",
    figure: s.fallback,
    target: s.run.window
      ? {
          kind: "strip",
          group: s.run.window.wire === "plant.torque" ? "N·m" : "rpm",
          wire: s.run.window.wire,
          note: "motion",
        }
      : null,
  }),
};
// The link of a drive fed from the mains: each on the link's own chart.
const LINK: Target = { kind: "strip", group: "link V", wire: "link.v_dc", note: "link" };
const volts = (v: number | undefined, fallback: string) => (v == null ? fallback : `${sig(v)} V`);
DESCRIBE.link_held = (s) => ({ label: "Link", figure: volts(s.run.link?.v_ref, s.fallback), target: LINK });
DESCRIBE.link_sag = (s) => ({ label: "Link min", figure: volts(s.run.link?.v_min, s.fallback), target: LINK });
DESCRIBE.link_over = (s) => ({ label: "Link max", figure: volts(s.run.link?.v_max, s.fallback), target: LINK });
DESCRIBE.link_ripple = (s) => ({ label: "Link ΔV", figure: volts(s.run.link?.ripple, s.fallback), target: LINK });
DESCRIBE.link_distortion = (s) => ({
  label: "Mains THD",
  figure: s.run.link?.thd != null ? pc(s.run.link.thd) : s.fallback,
  target: { kind: "strip", group: "mains A", wire: "link.i_line", note: "link" },
});
DESCRIBE.current_fast = DESCRIBE.current_margin;
DESCRIBE.current_slow = DESCRIBE.current_margin;
DESCRIBE.speed_separation = DESCRIBE.speed_margin;
DESCRIBE.step_ripple = DESCRIBE.torque_ripple;

/** Topics whose own name would not say what was checked: a device's current, beside a trip's. */
const TOPIC_LABEL: Record<string, string> = { current: "Î device" };

/** A check the engine passed on (check_data, check_voltage): named by its topic. */
function byTopic({ f, fallback }: Seen): Described {
  const named = f.topic ? TOPIC_LABEL[f.topic] : undefined;
  const topic = named ?? (f.topic ? f.topic.charAt(0).toUpperCase() + f.topic.slice(1) : "Check");
  const note = f.tag === "note";
  return { label: note ? `${topic} note` : topic, figure: note ? "" : fallback, target: null };
}

/** The symbol, the figure and the place of one finding. */
function described(f: Finding, run: Run): Described {
  const seen: Seen = { f, run, q: qualityOf(run), step: stepPlace(run), fallback: firstFigure(f.said ?? "") };
  return (DESCRIBE[f.id] ?? byTopic)(seen);
}

/** The findings that stand as figures among the passes, first to last. */
const HEADLINE = ["current_margin", "overshoot", "thd", "junction"];

/** The chips of a run: each finding to change or to note on its own, worst first; then the
 *  passing headline figures; then how many pass, which opens them all. */
export function chipsOf(run: Run | null): Chip[] {
  const findings = run?.verdict?.findings ?? [];
  if (!run || !findings.length) return [];
  const own = findings
    .filter((f) => f.tag !== "good")
    .sort((a, b) => RANK[toneOf(a)] - RANK[toneOf(b)] || b.severity - a.severity)
    .map((f) => ({ id: f.id, tone: toneOf(f), findings: [f], ...described(f, run) }));
  const good = findings.filter((f) => f.tag === "good");
  const heads: Chip[] = HEADLINE.flatMap((id) => good.filter((f) => f.id === id).slice(0, 1)).map((f) => ({
    id: f.id,
    tone: "good",
    findings: [f],
    ...described(f, run),
  }));
  const passes: Chip[] = good.length
    ? [{ id: "passes", label: "✓", figure: String(good.length), tone: "good", findings: good, target: null }]
    : [];
  return [...own, ...heads, ...passes];
}

/** Where a finding is seen, for a row that opens it: its chip's place. */
export const targetOf = (f: Finding, run: Run): Target | null => described(f, run).target;

const blockParam = (scheme: Scheme | null | undefined, kind: RegExp, param: string): number | null => {
  for (const b of scheme?.blocks ?? []) {
    if (!kind.test(b.kind)) continue;
    const v = num(b.params[param]);
    if (v !== null && v > 0 && v < 1e11) return v;
  }
  return null;
};

type Put = (group: string, note: Note) => void;
type ToneOf = (ids: string[]) => Tone;

/** The stretch the ripple was read over, on the phase currents, and the torque's ripple band. */
function rippleNotes(run: Run, put: Put, tone: ToneOf): void {
  const ripple = (run as { ripple?: Record<string, number> }).ripple;
  if (!ripple || num(ripple.from) === null || num(ripple.to) === null) return;
  const thd = num(ripple.thd);
  const pp = num(ripple.pp);
  const words = [thd === null ? "" : `THD ${pc(thd)}`, pp === null ? "" : `${written(pp, "A", 3)} pk-pk`];
  put("abc A", {
    kind: "span",
    id: "ripple",
    from: ripple.from,
    to: ripple.to,
    label: words.filter(Boolean).join(" · "),
    tone: tone(["thd"]),
  });
  const tm = num(ripple.torque_mean);
  const tpp = num(ripple.torque_pp);
  if (tm === null || tpp === null || tpp <= 0) return;
  put("N·m", {
    kind: "band",
    id: "torque-ripple",
    lo: tm - tpp / 2,
    hi: tm + tpp / 2,
    label: `ΔT ${written(tpp, "N·m", 3)} pk-pk`,
    // Read on the torque the motor makes: drawn only where that trace is.
    wire: "plant.torque",
    tone: tone(["torque_ripple", "step_ripple"]),
  });
}

/** The limits the control holds to, where it is given them. */
function limitNotes(run: Run, put: Put): void {
  const iLimit = blockParam(run.scheme, /current_reference/, "i_limit");
  if (iLimit !== null) {
    const level = { kind: "level" as const, id: "i-limit", value: iLimit, both: true, tone: "note" as Tone };
    put("abc A", { ...level, label: `limit ±${written(iLimit, "A", 3)}` });
    put("dq A", { ...level, label: `limit ${written(iLimit, "A", 3)}` });
  }
  const tLimit = blockParam(run.scheme, /speed_pi|torque_shaper|speed/, "limit");
  if (tLimit !== null)
    put("N·m", {
      kind: "level",
      id: "t-limit",
      value: tLimit,
      both: true,
      label: `limit ±${written(tLimit, "N·m", 3)}`,
      tone: "note",
    });
}

/** A trip is read from the instant the drive trips: marked there, on the phase currents. */
function tripNote(run: Run, put: Put, tone: ToneOf): boolean {
  const trip = num((run as { trip?: { t_trip?: number } | null }).trip?.t_trip);
  if (trip === null) return false;
  put("abc A", { kind: "tick", id: "trip", t: trip, label: "trip", tone: tone(["trip_link", "trip_peak"]) });
  return true;
}

/** The step: how far over it went, how long it took to settle, and the instant it did. A held
 *  point is read once the engine takes the drive as settled: that instant, marked once. */
function stepNotes(run: Run, put: Put, tone: ToneOf): void {
  if (tripNote(run, put, tone)) return;
  const step = run.step;
  const place = stepPlace(run);
  if (!step || !place) {
    const from = num(run.timing?.analysed_from);
    if (from !== null && from > 0)
      put("rpm", { kind: "tick", id: "settled", t: from, label: "read from here", tone: "good" });
    return;
  }
  const size = step.to - step.from;
  const over = step.overshoot;
  if (step.kind !== "disturbance" && over != null && over > 0 && size !== 0) {
    const peak = step.to + over * size;
    put(place.group, {
      kind: "band",
      id: "overshoot",
      lo: Math.min(step.to, peak),
      hi: Math.max(step.to, peak),
      label: `OS ${pc(over)}`,
      tone: tone(["overshoot"]),
    });
  }
  const back = step.kind === "disturbance";
  const settle = back ? step.recovery_time : step.settling_time;
  if (settle == null || settle <= 0) return;
  const words = `${back ? "recovers" : "settles"} ${written(settle, "s", 3)}`;
  const at = step.t_step + settle;
  put(place.group, {
    kind: "span",
    id: "settling",
    from: step.t_step,
    to: at,
    label: words,
    tone: tone(["settling", "disturbance"]),
  });
  put(place.group, { kind: "tick", id: "settled", t: at, label: "settled", tone: "good" });
}

/** The observer's angle error, as the band its rms spans. */
function sensingNotes(run: Run, put: Put, tone: ToneOf): void {
  const rms = num((run as { sensing?: Record<string, number> }).sensing?.angle_error_rms);
  if (rms === null || rms <= 0) return;
  const rad = (rms * Math.PI) / 180;
  put("rad", { kind: "band", id: "angle", lo: -rad, hi: rad, label: `±${sig(rms)}° rms`, tone: tone(["angle"]) });
}

/** The pulsed rating on the phase currents, and the observer's floor on the speed: lines. */
function ratingNotes(run: Run, put: Put, tone: ToneOf): void {
  const rating = num(run.pulsed?.rating);
  if (rating !== null)
    put("abc A", {
      kind: "level",
      id: "pulsed",
      value: rating,
      both: true,
      label: `pulsed ±${written(rating, "A", 3)}`,
      tone: tone(["pulsed", "check_current"]),
    });
  const floor = num(run.floor?.hardware_rpm);
  if (floor !== null && floor > 0)
    put("rpm", {
      kind: "level",
      id: "floor",
      value: floor,
      both: true,
      label: `observer floor ${sig(floor)} rpm`,
      tone: tone(["floor"]),
    });
}

/** The findings of a run drawn on its strips, by strip: limits as lines, a ripple or a
 *  margin as a band of values, the stretch a figure was read over as a span of time, and
 *  the instant the drive settled as a quiet tick. */
export function notesOf(run: Run | null): Map<string, Note[]> {
  const out = new Map<string, Note[]>();
  if (!run) return out;
  const put: Put = (group, note) => out.set(group, [...(out.get(group) ?? []), note]);
  const findings = run.verdict?.findings ?? [];
  const tone: ToneOf = (ids) => {
    const f = findings.find((x) => ids.includes(x.id));
    return f ? toneOf(f) : "good";
  };
  rippleNotes(run, put, tone);
  limitNotes(run, put);
  stepNotes(run, put, tone);
  sensingNotes(run, put, tone);
  ratingNotes(run, put, tone);
  return out;
}

/** The settled tick goes on the first strip shown when the strip it belongs on is not. */
export function placedNotes(
  all: Map<string, Note[]>,
  groups: { key: string; traces?: { name: string }[] }[],
): Map<string, Note[]> {
  const shown = groups.map((g) => g.key);
  // A note read on one wire goes only on a strip that draws that wire.
  const drawn = (key: string, n: Note) =>
    n.kind !== "band" || !n.wire || (groups.find((g) => g.key === key)?.traces ?? []).some((t) => t.name === n.wire);
  const out = new Map(
    [...all]
      .filter(([k]) => shown.includes(k))
      .map(([k, notes]) => [k, notes.filter((n) => drawn(k, n))] as [string, Note[]]),
  );
  const tick = [...all.values()].flat().find((n) => n.kind === "tick");
  const has = [...out.values()].flat().some((n) => n.kind === "tick");
  if (tick && !has && shown.length) out.set(shown[0], [...(out.get(shown[0]) ?? []), tick]);
  return out;
}
