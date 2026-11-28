import { NotWorkedOut, notRefused, Refused } from "../../api";
import type { Cycle, LoadPreset } from "../../api";
import { minutesSaid, overlayChart, timeChart } from "../../charts/motion";
import { series } from "../../compare";
import type { Series } from "../../compare";
import { degrees, eng, escape, fig, num, percent, sentence, watts } from "../../format";
import { icon } from "../../icons";
import { LOAD, STEPS } from "../../steps";
import { app, focused, res } from "../../store";
import { checkList, findingList, foldBlock, legendOf, refusal, tip, waiting, whenAnswered } from "../html";
import { notReady } from "./ready";

/** A large count in words, to two figures. */
const big = (v: number): string =>
  v >= 1e12
    ? `${num(v / 1e12, 2)} trillion`
    : v >= 1e9
      ? `${num(v / 1e9, 2)} billion`
      : v >= 1e6
        ? `${num(v / 1e6, 2)} million`
        : v >= 1e3
          ? `${num(v / 1e3, 2)} thousand`
          : num(v, 2);

/** The application's own use in a year, where the load is one: its runs or its hours. */
function usageOf(): LoadPreset["usage"] | null {
  if (app.state.mission) return null;
  return res.presets?.list.find((p) => p.id === app.state.loadKind)?.usage ?? null;
}

/** Past this many years of its own use, a product is worn out by something else first: the
 *  life is said to be beyond it, never as a count no product reaches. */
export const BEYOND_YEARS = 50;
/** The same, run back to back where no use a year is known: about eleven years without a stop. */
export const BEYOND_HOURS = 100_000;

/** How long the part lasts in years of the application's usual use, or null where it has none. */
function yearsOf(l: Cycle["life"], repeats: number): number | null {
  const use = usageOf();
  if (!use) return null;
  return use.unit === "runs" ? repeats / use.per_year : l.hours !== null ? l.hours / use.per_year : null;
}

/** How many repeats the part lasts, and in years of its use; past what any product lasts, only that. */
function countLines(l: Cycle["life"], repeats: number): string {
  const use = usageOf();
  const years = yearsOf(l, repeats);
  const per = use ? `At ${num(use.per_year)} ${use.unit} a year (${escape(use.said)}), ` : "";
  if (years !== null && years > BEYOND_YEARS) {
    return (
      `<li>${per}these swings would take <b>more than ${BEYOND_YEARS} years</b> to wear the part out: ` +
      "far longer than such a product lasts, so thermal cycling does not limit its life.</li>"
    );
  }
  if (years === null && l.hours !== null && l.hours > BEYOND_HOURS) {
    return (
      `<li>Run back to back, these swings would take <b>more than ${big(BEYOND_HOURS)} hours</b> ` +
      "(over eleven years without a stop) to wear the part out: thermal cycling does not limit its life.</li>"
    );
  }
  const hours = l.hours !== null ? `, which back to back is about ${big(l.hours)} hours` : "";
  const inYears = years !== null ? `<li>${per}that is <b>about ${big(years)} years</b>.</li>` : "";
  return `<li>About <b>${big(repeats)}</b> repeats of this motion${hours}.</li>${inYears}`;
}

/** How many repeats the part lasts, and which swing of which chip wears it out. */
function lifeLines(l: Cycle["life"], repeats: number): string {
  const count = countLines(l, repeats);
  const chip = l.chip ? `The chip that wears out first is the ${escape(l.chip)}. ` : "";
  const swing = l.within_turn
    ? `a swing of ${num(l.swing, 2)} K on every turn of the motor`
    : `one swing of ${num(l.swing, 2)} K`;
  const smaller = l.within_turn ? " Turning faster, or a larger chip, makes that swing smaller." : "";
  const wear =
    `${percent(l.swing_share, 0)} of its wear comes from ${swing}, with the junction at about ` +
    `${Math.round(l.swing_mean)} °C on average through it. ` +
    `A smaller swing lasts far longer: halving it gives about thirty times the life.${smaller}`;
  return `${count}<li>${chip}${wear}</li>`;
}

/** Whether some instants of the motion could not be followed: the motor cannot do them. */
const followedInPart = (c: Cycle): boolean => c.p_stage.some((p) => p === null);

/** Thermal-cycling life, from the swings of the temperature trace. Not given for a motion
 *  followed only in part: the swings of what was not followed are not in it. */
export function lifeBlock(c: Cycle): string {
  const l = c.life;
  if (!l) return "";
  if (followedInPart(c)) {
    const title = '<h4>Life under thermal cycling <span class="quiet">a rough indicator</span></h4>';
    const said =
      "<li>Not given: the motor cannot follow part of this motion, and the swings of the part not " +
      "followed would be in it.</li>";
    return `${title}<ul class="plain small">${said}</ul>`;
  }
  const body =
    l.repeats === null
      ? "<li>The junction temperature swings by less than 1 K through this motion: " +
        "this thermal-cycling model counts the wear from a swing that small as negligible.</li>"
      : lifeLines(l, l.repeats);
  // Shown, since it is what the swings on the chart above cost; named for what it is, a generic model.
  const model =
    "<li>A generic model for modules with aluminium bond wires (LESIT), applied to discrete parts too. " +
    "A real part may last several times longer or shorter; " +
    "use the maker's power-cycling curve where there is one.</li>" +
    (l.extrapolated && l.fitted
      ? `<li>The model was fitted to swings of ${num(l.fitted[0], 2)} to ${num(l.fitted[1], 2)} K: ` +
        `this one's ${num(l.swing, 2)} K is outside them, so the figure is an extrapolation.</li>`
      : "");
  const title = '<h4>Life under thermal cycling <span class="quiet">a rough indicator</span></h4>';
  return `${title}<ul class="plain small">${body}${model}</ul>`;
}

/** The junction of each thing compared on one chart, with those still on their way said so. */
function overlay(list: Series[]): string {
  const cycles = res.cycles;
  const drawn = list
    .map((x) => ({ x, g: cycles.get(x.key) }))
    .filter((p): p is { x: Series; g: Cycle } => notRefused(p.g) !== null);
  if (!drawn.length) return waiting("Following each one through its motion.");
  const lines = drawn.map((p) => ({ name: p.x.name, time: p.g.time, tj: p.g.tj }));
  const limit = Math.max(...drawn.map((p) => p.g.summary.tj_max ?? 150));
  const rest = list.some((x) => !cycles.has(x.key)) ? waiting("Following the others through the motion.") : "";
  return overlayChart(lines, limit) + legendOf(drawn.map((p) => p.x.name)) + rest;
}

/** The comparison on top: every motion on one chart, then those that could not be followed. */
function comparedMotion(): string {
  const list = series();
  if (list.length < 2) return "";
  const title = {
    devices: "Each device through the motion",
    loads: "Each load's motion",
    motors: "Each motor through the motion",
    sweep: "The motion at each value",
  }[app.state.compare];
  // A motion the engine refused is a warning; one with no answer at all is said as not worked out.
  const said = (x: Series) => escape(sentence((res.cycles.get(x.key) as Refused).reason));
  const answered = list.filter((x) => res.cycles.get(x.key) instanceof Refused);
  const refused = answered
    .filter((x) => !(res.cycles.get(x.key) instanceof NotWorkedOut))
    .map((x) => `<p class="fact warn">${icon("alert-triangle")}<span>${escape(x.name)}: ${said(x)}.</span></p>`)
    .join("");
  const unworked = answered
    .filter((x) => res.cycles.get(x.key) instanceof NotWorkedOut)
    .map((x) => `<p class="quiet small">${icon("info-circle")}${escape(x.name)}: not worked out. ${said(x)}.</p>`)
    .join("");
  return `<h3>${title}</h3>${overlay(list)}${refused}${unworked}`;
}

/** How the drive got the load going: the start current and how long it held, the junction's
 *  own peak in the start-up, and a run-up at the current limit. */
function startupNote(c: Cycle): string {
  const s = c.startup;
  if (!s) return "";
  const limit = s.at_limit && s.limit !== null ? `, at the drive's limit of ${num(s.limit)} A` : "";
  const lines = [
    `<li><b>Start current ${num(s.current)} A for ${num(s.time, 2)} s</b>${limit}.</li>`,
    s.tj_peak !== null
      ? `<li>The junction peaks at ${degrees(s.tj_peak)} in the start-up, ${minutesSaid(s.tj_at ?? 0)} in.</li>`
      : "",
    s.run_up !== null && s.run_up_reached
      ? `<li>The inertia is run up at the current limit in ${num(s.run_up, 2)} s, ` +
        "against the break-away and what the load asks.</li>"
      : s.run_up_reached === false
        ? "<li>At its current limit the drive cannot bring the load to speed: " +
          "the ramp is followed as written, past the limit.</li>"
        : "",
  ];
  return `<h4>Start-up</h4><ul class="plain small">${lines.join("")}</ul>`;
}

/** Where each phase held until steady got steady, and how the heatsink is followed. */
function steadyNote(c: Cycle): string {
  const held = (c.steady_at ?? []).map((h) => {
    const what = h.phase ? `The ${escape(h.phase)} phase` : "The motion";
    return h.reached
      ? `<li>${what} is <b>steady after ${minutesSaid(h.after)}</b>, the junction at ${degrees(h.tj)}: ` +
          "it moves by less than 0.5 °C a minute.</li>"
      : `<li>${what} is not steady within its time: the junction still moves by 0.5 °C a minute or more.</li>`;
  });
  const w = c.worst_swing;
  const swing = w
    ? `<li>The worst swing within one period is ${num(w.swing, 2)} K, ` +
      `${w.phase ? `in the ${escape(w.phase)} phase, ` : ""}` +
      `at ${minutesSaid(w.time)}${w.f_e ? `, where the output runs at ${num(w.f_e, 2)} Hz` : ""}.</li>`
    : "";
  const m = c.method;
  const how = m
    ? `<li>${escape(sentence(m.said))}.` +
      `${m.assumed ? " Give your heatsink's heat capacity in step 4 to replace it." : ""}</li>`
    : "";
  if (!held.length && !swing && !how) return "";
  return `<h4>Steady state</h4><ul class="plain small">${held.join("")}${swing}${how}</ul>`;
}

/** The figures of the whole motion: how long, the losses, the energy each way. */
function motionFacts(s: Cycle["summary"]): string {
  const fact = (label: string, value: string) => `<div><dt>${label}</dt><dd>${value}</dd></div>`;
  const facts = [
    fact("Lasts", minutesSaid(s.duration ?? 0)),
    fact("Mean loss, power stage", watts(s.mean_loss)),
    fact("Torque, rms", `${num(s.rms_torque)} N·m`),
    fact("Energy to the shaft", eng(s.shaft_energy, "J")),
    fact("Energy lost, power stage and motor", eng(s.loss_energy, "J")),
    fact("Returned by braking", eng(s.returned ?? 0, "J")),
  ];
  return `<dl class="facts">${facts.join("")}</dl>`;
}

/** How the drive gets the motor going, where the kind of motor has something to say of it. */
function startingNote(cycle: Cycle): string {
  if (!(cycle.start.applies !== "none" || app.state.kind === "stepper")) return "";
  const lines = cycle.start.lines.map((l) => `<li>${escape(sentence(l))}</li>`).join("");
  return `<h4>Starting</h4><ul class="plain small">${lines}</ul>`;
}

/** What charging the DC link at power-up stores, and the current it draws. */
function inrushNote(cycle: Cycle): string {
  const inrush = cycle.inrush;
  if (!inrush) return "";
  const stored =
    `<li>The link stores ${fig(inrush.energy)} J, ` +
    "and whatever limits the charging current absorbs as much again.</li>";
  const peak =
    inrush.peak !== null
      ? `Through your precharge resistance the current peaks at ${num(inrush.peak)} A ` +
        `and the link is charged in about ${eng(inrush.time, "s")}.`
      : "With no precharge resistance given, only the supply and the wiring limit the current. " +
        "Give one in step 4 to see the peak.";
  return `<h4>Charging the DC link at power-up</h4><ul class="plain small">${stored}<li>${peak}</li></ul>`;
}

/** The hottest junction through the motion, beside what a steady solution would have said.
 *  Of a motion followed only in part it is said to be of that part. */
function peakNote(s: Cycle["summary"], partly: boolean): string {
  const saved = (s.forever ?? 0) - (s.peak ?? 0);
  const steady =
    saved > 0.5
      ? ` Solving each instant as if it lasted forever would say ${degrees(s.forever)}: ` +
        "short peaks do not have time to heat the chip fully."
      : "";
  if (partly) {
    return (
      `<p class="fact warn">${icon("alert-triangle")}<span>The motor cannot follow part of this motion. ` +
      `In the part it can, the hottest junction reaches ${degrees(s.peak)}; the rest is not known.</span></p>`
    );
  }
  const why = steady.trim() || "The hottest junction through the motion.";
  return `<p class="motion-peak">${tip("Tj peak", why)} <b>${degrees(s.peak)}</b></p>`;
}

/** The engine's reason the motion cannot be followed, and the button back to the load. A
 *  motion with no answer at all is said as not worked out: nothing in the load is at fault. */
function refusedMotion(r: Refused): string {
  if (r instanceof NotWorkedOut) return refusal(r);
  const label = `Go to ${escape(STEPS[LOAD].name.toLowerCase())} to change it`;
  const button = `<button type="button" class="ghost" data-step="${LOAD}">${icon("arrow-left")}${label}</button>`;
  return `${refusal(r)}<p>${button}</p>`;
}

export function motionTab(): string {
  if (!focused()?.result) return notReady();
  return whenAnswered("cycle", res.cycle, "Following the motion through time.", throughMotion, refusedMotion);
}

/** The checks over the whole motion: what does not pass or asks for a change, in the open, one
 *  line each; the checks that pass counted and folded. */
function motionChecks(cycle: Cycle): string {
  const raised = cycle.checks.filter((x) => x.level !== "ok");
  const passed = cycle.checks.filter((x) => x.level === "ok");
  const open = raised.length ? `<h4>Over the whole motion</h4>${findingList(raised, "motion-checks")}` : "";
  const count = `${passed.length} ${passed.length === 1 ? "check passes" : "checks pass"} over the whole motion`;
  const folded = passed.length
    ? `<details class="more" data-fold="motion-passed"><summary>${icon("circle-check")}${count}` +
      `<span class="quiet">${escape(passed.map((x) => x.topic).join(", "))}</span></summary>` +
      `${checkList(passed)}</details>`
    : "";
  return `<section class="finding-group">${open}${folded}</section>`;
}

/** The device on the drawing through the motion, once it has been followed. */
function throughMotion(cycle: Cycle): string {
  const s = cycle.summary;
  const parts = [
    `${comparedMotion()}<h3>${escape(focused()!.name)} through the motion</h3>`,
    peakNote(s, followedInPart(cycle)),
    timeChart(cycle),
    motionFacts(s),
    motionChecks(cycle),
    foldBlock("m-startup", startupNote(cycle), cycle.startup ? `${num(cycle.startup.current)} A` : ""),
    foldBlock("m-steady", steadyNote(cycle)),
    foldBlock("m-starting", startingNote(cycle)),
    foldBlock("m-inrush", inrushNote(cycle), cycle.inrush ? `${fig(cycle.inrush.energy)} J` : ""),
    foldBlock("m-life", lifeBlock(cycle)),
  ];
  return parts.join("\n");
}
