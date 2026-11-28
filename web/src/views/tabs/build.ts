import { notRefused } from "../../api";
import type { Candidate, Check, Cycle, Recommendation, Result } from "../../api";
import { atLeast, degrees, eng, escape, fig, num, sentence, watts } from "../../format";
import { icon } from "../../icons";
import { app, focused, res } from "../../store";
import { frontEndRipple, frontEndSection } from "../frontend";
import { recRow, whenAnswered } from "../html";
import { notReady } from "./ready";

/** The levels of a check, from the mildest to the worst. */
const LEVELS = ["ok", "caution", "undecided", "fail"];

/** One part of the inverter: its name, the figure to remember, and the lines behind it. */
function section(title: string, glyph: string, head: string, lines: string[]): string {
  return recRow(`rec-${title}`, `${icon(glyph)}${title}`, escape(head), lines.map(escape));
}

/** The worst of the checks on a protective trip, at the design point and over the motion. */
const worstTrip = (c: Candidate, motion: Cycle | null): Check | undefined =>
  [...c.checks, ...(motion?.checks ?? [])]
    .filter((x) => x.topic === "trip")
    .sort((a, b) => LEVELS.indexOf(b.level) - LEVELS.indexOf(a.level))[0];

/** The ripple current the link capacitor has to carry: the worse of the design point and the motion. */
const rippleRms = (c: Candidate, motion: Cycle | null): number =>
  Math.max(c.link?.capacitor_rms ?? 0, motion?.summary.capacitor_rms_worst ?? 0);

/** What the capacitor on the link has to stand: ripple current, voltage, braking energy, charging. */
function capacitorLines(rms: number, motion: Cycle | null): string[] {
  const k = app.state.conditions;
  const s = motion?.summary;
  const cap: string[] = [];
  if (rms > 0) {
    const mean = s?.capacitor_rms
      ? ` (${num(s.capacitor_rms, 2)} A rms averaged over the motion, which is what heats it)`
      : "";
    const rating = `Ripple-current rating of at least ${num(rms, 2)} A rms at ${num(k.f_khz)} kHz${mean}.`;
    const front = frontEndRipple();
    const whole = front === null ? "" : ` With the front end's, ${num(Math.hypot(rms, front), 2)} A rms in all.`;
    cap.push(front === null ? `${rating} The supply's own ripple comes on top.` : `${rating}${whole}`);
  }
  const braking = s?.v_link_peak
    ? `, and above the ${num(s.v_link_peak)} V the link reaches when the motor brakes`
    : "";
  cap.push(`Voltage rating above the ${num(k.v_dc)} V ${app.state.supply === "mains" ? "link" : "supply"}${braking}.`);
  if (s?.c_needed) {
    const needed = eng(s.c_needed, "F", 2);
    cap.push(`At least ${needed} to take the braking energy of this motion on a supply that cannot take it back.`);
  }
  if (motion?.inrush) {
    const peak =
      motion.inrush.peak !== null
        ? `, with ${num(motion.inrush.peak)} A peak through your precharge resistance`
        : "; limit the charging current with a precharge resistance";
    cap.push(`Charging it stores ${fig(motion.inrush.energy)} J${peak}.`);
  }
  return cap;
}

/** The gate resistors and the drive voltage the result was worked out with, in one line. */
function gateUsed(c: Candidate): string {
  const g = c.gate;
  if (g.kind === "built in") return "Inside the module.";
  if (!g.rg_on) return "Start from the gate resistor of the datasheet's switching test.";
  const drive = g.v_drive ? `, ${num(g.v_drive, 2)} V drive` : "";
  const whose =
    g.kind === "chosen"
      ? ", chosen for the lowest loss within the limits"
      : g.kind === "datasheet"
        ? ", as the datasheet measured with"
        : ", yours";
  return `${num(g.rg_on, 2)} Ω on, ${num(g.rg_off ?? g.rg_on, 2)} Ω off${drive}${whose}.`;
}

/** What the gate drive has to be: the resistors, what the device needs around it, the dead time. */
function gateLines(c: Candidate, dead: Recommendation | undefined): string[] {
  return [
    gateUsed(c),
    ...c.needs.slice(1).map((n) => `${sentence(n)}.`),
    ...(dead?.value.t_dead ? [`Dead time of at least ${eng(atLeast(dead.value.t_dead), "s", 2)}.`] : []),
  ];
}

/** What the protection has to catch: a trip, the current a switch turns off, a stalled motor. */
function protectionLines(c: Candidate, trip: Check | undefined): string[] {
  const stage = res.stage;
  const lines: string[] = [];
  if (trip) lines.push(`${sentence(trip.message)}.`);
  if (c.link?.ripple_pp) {
    const off = num(stage ? stage.i_peak + c.link.ripple_pp / 2 : c.link.ripple_pp / 2, 3);
    lines.push(
      `A switch turns off up to ${off} A: the current peak with half the ${num(c.link.ripple_pp, 2)} A ripple ` +
        "on top. Set the overcurrent trip above that and below the device's limit.",
    );
  }
  if (c.stall_tj !== null) {
    lines.push(
      `Holding this torque at standstill, the hottest junction reaches ${degrees(c.stall_tj)}: ` +
        "a stalled motor needs a current limit that holds it there, or a time limit.",
    );
  }
  return lines;
}

/** The device itself: whether it passes, and what to look for when starting from scratch. */
function deviceSection(c: Candidate): string {
  const advice = res.advice;
  const passes = {
    ok: "It passes every check at this design point.",
    caution: "It can do this, with the cautions on the Verdict tab.",
    undecided: "Whether it can do this is not decided by the data: see the Verdict tab.",
    fail: "It does not pass: see the Verdict tab.",
  }[c.level];
  const scratch = advice
    ? [
        `Starting from scratch you would look for at least a ${num(advice.v_minimum)} V part, ` +
          `${num(advice.v_comfortable)} V for margin, for a peak current of ${num(advice.i_peak)} A.`,
      ]
    : [];
  const lines = [`${c.name}, ${c.technology}. ${passes}`, ...scratch];
  return section("Power device", "cpu", c.needs[0] ? sentence(c.needs[0]) : c.name, lines);
}

/** The heatsink: the heat to remove, and the engine's own lines on how large it has to be. */
function heatsinkSection(r: Result, motion: Cycle | null, sinkRec: Recommendation | undefined): string {
  const head = sinkRec?.value.rth_sink ? `${num(sinkRec.value.rth_sink, 2)} K/W or lower` : "See below";
  const mean = motion ? `, ${watts(motion.summary.mean_loss)} averaged over the motion` : "";
  const advised = sinkRec
    ? [...sinkRec.lines.slice(0, 2), ...sinkRec.lines.filter((l) => l.startsWith("With no heatsink"))].map(
        (l) => `${sentence(l)}.`,
      )
    : [];
  const lines = [`${watts(r.loss)} to remove at the design point${mean}.`, ...advised];
  return section("Heatsink", "temperature", head, lines);
}

/** The protection: what a trip does to the link, and the limits to set. */
function protectionSection(c: Candidate, trip: Check | undefined): string {
  const head = trip
    ? {
        ok: "A trip is harmless",
        caution: "A trip charges the link",
        undecided: "A trip may exceed the rating",
        fail: "A trip exceeds the rating",
      }[trip.level]
    : "Overcurrent and stall";
  const protect = protectionLines(c, trip);
  const lines = protect.length
    ? protect
    : ["Set an overcurrent trip above the peak current and below the device's limit."];
  return section("Protection", "alert-triangle", head, lines);
}

/** The inverter this load asks for, on one sheet: the device, what cools it, the capacitor
 *  on the link, the gate drive and the protection. Every line is taken from a result worked
 *  out elsewhere on the page; nothing is worked out here. */
function buildSpec(): string {
  const c = focused();
  const r = c?.result;
  const advised = res.advised;
  if (!c || !r || !(advised instanceof Array)) return "";
  const parallel = app.state.conditions.parallel;
  const sinkRec = advised.find((x) => x.topic === "heatsink");
  const dead = advised.find((x) => x.topic === "dead time");
  const motion = notRefused(res.cycle);
  const trip = worstTrip(c, motion);
  const rms = rippleRms(c, motion);
  const perChannel = parallel > 1 ? `${parallel} gates a channel` : "One gate a channel";
  const gates = c.gate.kind === "built in" ? "Built in" : `${perChannel}`;
  const all = Math.hypot(rms, frontEndRipple() ?? 0);
  const ripple = all > 0 ? `${num(all, 2)} A rms ripple` : "See below";
  const about = `<p class="quiet">With ${escape(c.name)} as the switch. A starting point, not a finished design.</p>`;
  const parts = [
    about,
    deviceSection(c),
    heatsinkSection(r, motion, sinkRec),
    frontEndSection(),
    section("DC-link capacitor", "bolt", ripple, capacitorLines(rms, motion)),
    section("Gate drive", "adjustments", gates, gateLines(c, dead)),
    protectionSection(c, trip),
  ];
  return parts.join("\n");
}

/** The name each starting value goes by on the page. */
const NAMES: Record<string, string> = {
  "gate resistors": "Gate resistors",
  "dead time": "Dead time",
  modulation: "Modulation",
  heatsink: "Heatsink",
  "d-axis current": "Field current",
};

/** The glyph beside each starting value. */
const ICONS: Record<string, string> = {
  "gate resistors": "adjustments",
  "dead time": "ruler-measure",
  modulation: "wave-sine",
  heatsink: "temperature",
  "d-axis current": "engine",
};

/** A starting value as the figure to remember, or that it needs more from the user. */
function startingValue(r: Recommendation): string {
  const v = r.value;
  if (r.topic === "gate resistors" && v.rg_on) return `${num(v.rg_on, 2)} Ω on, ${num(v.rg_off, 2)} Ω off`;
  if (r.topic === "dead time" && v.t_dead) return eng(atLeast(v.t_dead), "s", 2);
  if (r.topic === "heatsink" && v.rth_sink) return `${num(v.rth_sink, 2)} K/W or lower`;
  if (r.topic === "modulation") return v.saving ? `${num(v.saving)} W to save` : "Keep the usual scheme";
  if (r.topic === "d-axis current") return v.saving ? `${num(v.saving)} W to save` : "Keep the least current";
  return "Needs more from you";
}

/** One starting value with the reasons under it; one without a figure is marked as an open question. */
function startingSection(r: Recommendation): string {
  // A topic the page has no name for is the engine's own word: shown as text, like any other.
  const name = Object.hasOwn(NAMES, r.topic) ? NAMES[r.topic] : escape(sentence(r.topic));
  const glyph = icon(Object.hasOwn(ICONS, r.topic) ? ICONS[r.topic] : "settings");
  const open = Object.keys(r.value).length ? "" : " open-question";
  const lines = r.lines.map((l) => escape(sentence(l)));
  return recRow(`start-${r.topic}`, `${glyph}${name}`, escape(startingValue(r)), lines, open);
}

export function settingsTab(): string {
  if (!focused()?.result) return notReady();
  return whenAnswered("recommend", res.advised, "Working out starting values.", (advised) => {
    const about = '<p class="quiet">For a first prototype; settle them on the bench.</p>';
    const head = `${buildSpec()}<h4 class="sub-head">Starting values for ${escape(focused()!.name)}</h4>${about}`;
    return `${head}\n${advised.map(startingSection).join("")}`;
  });
}
