// The drawing and the figures beside it: what is being tested and, once there is an answer,
// what it loses and how hot it runs.

import { keepDrawing } from "./thumb";
import { emptyArt } from "../emptyart";
import { deltaTag } from "../pin";
import { notRefused } from "../api";
import type { Candidate, DeviceSummary, Result } from "../api";
import { pwmChart } from "../charts";
import { saveButton } from "../charts/frame";
import { degrees, escape, num, percent, sentence, watts } from "../format";
import { icon } from "../icons";
import { schematic } from "../schematic";
import { MOTOR, RESULTS, STEPS, SUPPLY, ZOOMS } from "../steps";
import {
  app,
  blockedStep,
  chosenDevices,
  conditionsGiven,
  focused,
  pending,
  res,
  ui,
  underTest,
  verdictOf,
  worst,
} from "../store";
import { ev, eventBoxes, eventSlot, focusOnce } from "../eventask";
import { renderCompareArea } from "./comparebar";
import { frontEndDrawn } from "./frontend";
import { renderBarStatus } from "./rail";
import { put } from "./morph";
import { $, packaging, readout, reduced } from "./html";
import { verdictMarkup } from "../verdictwords";
import { whereOf, wordsOf } from "./verdictline";

/** The engine refused the inputs and the user has been far enough to be told. */
const refusedNow = (): boolean => !!res.blocked && app.state.reached >= SUPPLY;

let glowsShown = false;

/** The drawing's scale on the screen, for its words to be set at a size on the screen. */
let sized = false;
function sizePlate(plate: HTMLElement): void {
  if (sized || typeof ResizeObserver === "undefined") return;
  sized = true;
  new ResizeObserver(() => {
    const svg = plate.querySelector("svg");
    const box = svg?.viewBox.baseVal;
    if (svg && box?.width) plate.style.setProperty("--plate-scale", String(svg.clientWidth / box.width || 1));
  }).observe(plate);
}

function drawPlate(c: Candidate | null, shown: DeviceSummary | undefined, wait: boolean): void {
  sizePlate($("#plate"));
  // While the answer is on its way the drawing shows the inputs, and no figure of the
  // answer it had: those were for other inputs.
  $("#plate").classList.toggle("is-waiting", wait);
  // The first answer of the visit brings the glows on, once; later answers change them in place.
  const result = wait ? null : (c?.result ?? null);
  if (result && !glowsShown) {
    glowsShown = true;
    $("#plate").classList.add("is-first");
    setTimeout(() => $("#plate").classList.remove("is-first"), 1200);
  }
  // The first drawing of the visit draws its wires in, once: the bench switching on.
  const first = !wiresDrawn && !reduced();
  wiresDrawn = true;
  const drawing = schematic({ ...deviceDrawn(c, shown, wait), ...supplyDrawn(), rotor: rotorDrawn() });
  keepDrawing(drawing);
  put(
    $("#plate"),
    (first ? drawing.replace(/<path class="wire"/g, '<path class="wire" pathLength="1"') : drawing) +
      saveButton("The power stage", c?.name ?? ""),
  );
  if (first) {
    $("#plate").classList.add("draws-in");
    setTimeout(() => $("#plate").classList.remove("draws-in"), 900);
  }
}

/** Whether the drawing has been drawn in yet on this visit. */
let wiresDrawn = false;

/** The device on the drawing, and what of its answer is drawn: nothing while the answer is on
 *  its way, since what it had was for other inputs. */
function deviceDrawn(c: Candidate | null, shown: DeviceSummary | undefined, wait: boolean) {
  const { state } = app;
  return {
    kind: state.kind,
    stage: state.reached >= SUPPLY && !wait ? res.stage : null,
    result: wait ? null : (c?.result ?? null),
    fet: shown ? !shown.technology.includes("IGBT") : false,
    blocked: refusedNow(),
    ruledOut: !wait && !!c?.result && verdictOf(c).level === "fail",
    deviceName: shown?.name ?? null,
    pack: shown ? { positions: shown.positions, driver: shown.integrated_driver } : null,
  };
}

/** The supply, the cooling and the speed on the drawing, as far as the user has set them. */
function supplyDrawn() {
  const { state } = app;
  const k = state.conditions;
  return {
    tSink: k.cooling === "held" ? k.t_sink : k.t_ambient,
    vdc: state.reached >= SUPPLY ? k.v_dc : null,
    motorKnown: state.reached >= MOTOR,
    parallel: state.reached >= SUPPLY ? Math.max(1, Math.round(Number(k.parallel) || 1)) : 1,
    battery: state.supply === "battery",
    frontEnd: state.reached >= SUPPLY ? frontEndDrawn() : null,
    // The rotor turns only while the user is at or past the point where they set the
    // speed. Going back to the motor or the device stops it.
    // It stands still while the page says the design cannot be worked out.
    rpm: state.step >= SUPPLY && !res.fault ? k.rpm : 0,
  };
}

/** The rotor of the motor on the drawing. */
function rotorDrawn() {
  const { state } = app;
  const motor = state.motors[state.kind];
  return {
    kind: state.kind,
    magnets: String(motor.magnets ?? "surface"),
    polePairs: Number(motor.pole_pairs) || 1,
    steps: Number(motor.steps_per_rev) || 200,
  };
}

/** Holding the torque with the rotor still is what the verdict turns on: one switch carries
 *  the current without rest, and runs hotter than any does while the motor turns. */
const stillDecides = (c: Candidate, r: Result): boolean =>
  c.stall_tj != null &&
  c.stall_tj > r.tj_peak &&
  c.checks.some((x) => x.topic === "standstill" && x.level === worst(c.checks.map((k) => k.level)) && x.level !== "ok");

const stillNote = (c: Candidate, r: Result): string => {
  const over = Math.round(c.stall_tj! - r.tj_max);
  const against = over > 0 ? `${over} K above the rating` : `${-over} K under the rating`;
  return `holding this torque still, ${against}; ${degrees(r.tj_peak)} while turning`;
};

/** The figures of a result: the loss, its two kinds, the junction the verdict turns on, the
 *  efficiency. */
function resultCells(c: Candidate, r: Result, many: boolean): string {
  const each = `${num(r.loss / (res.stage?.positions ?? 6))} W a switch`;
  const share = (w: number) => percent(w / Math.max(r.loss, 1e-9), 0);
  return (
    readout(
      "Power-stage loss",
      watts(r.loss),
      each,
      "",
      `${many ? "" : `${c.name}: `}every switch and diode together; under it, a switch on average.`,
      deltaTag("loss", r.loss),
    ) +
    readout(
      "Conduction",
      watts(r.conduction),
      share(r.conduction),
      "",
      "Loss while a switch or diode conducts.",
      deltaTag("conduction", r.conduction),
    ) +
    // Orange is switching loss wherever loss is split on the page; the readout says so once.
    readout(
      "Switching",
      watts(r.switching),
      share(r.switching),
      "accent",
      "Loss at the edges, over the turn: orange in the loss bars.",
      deltaTag("switching", r.switching),
    ) +
    junctionCell(c, r) +
    (c.efficiency != null
      ? readout(
          "η DC to shaft",
          percent(c.efficiency),
          "",
          "",
          "Motor windings included.",
          deltaTag("efficiency", c.efficiency),
        )
      : "")
  );
}

/** How far the junction is from its rating, or across the thermal assumptions where they part,
 *  with the heatsink's temperature where it settles by itself. */
function junctionNote(r: Result): string {
  const spread = r.tj_range && Math.round(r.tj_range[0]) !== Math.round(r.tj_range[1]);
  const range = spread
    ? `${Math.round(r.tj_range![0])} to ${Math.round(r.tj_range![1])} °C across the thermal assumptions`
    : `${Math.round(r.tj_max) - Math.round(r.tj_peak)} K under the rating`;
  const settled =
    app.state.conditions.cooling === "heatsink" && r.t_sink != null ? `heatsink at ${Math.round(r.t_sink)} °C, ` : "";
  return settled + range;
}

/** The junction the verdict turns on: at standstill where holding still decides it, else the
 *  hottest, with the motion's where it differs. */
function junctionCell(c: Candidate, r: Result): string {
  if (stillDecides(c, r))
    return readout(
      "Junction at standstill",
      degrees(c.stall_tj),
      stillNote(c, r),
      "fail",
      "",
      deltaTag("still", c.stall_tj),
    );
  const hot = r.tj_peak > r.tj_max ? "fail" : r.tj_max - (r.tj_range?.[1] ?? r.tj_peak) < 25 ? "caution" : "";
  const through = motionThrough(c, r);
  const label = through ? "Tj peak, design point" : "Tj peak";
  const left = Math.round(r.tj_max) - Math.round(r.tj_peak);
  const short = `${left >= 0 ? `${left} K under` : `${-left} K over`} ${Math.round(r.tj_max)} °C`;
  const why = `The hottest junction: ${junctionNote(r)}${through}.`;
  return readout(label, degrees(r.tj_peak), short, hot, why, deltaTag("tj", r.tj_peak));
}

/** The motion's hottest junction, said beside the design point's where the two differ by a
 *  degree or more; empty where they do not. */
function motionThrough(c: Candidate, r: Result): string {
  // Where the motion has been followed and runs hotter or cooler than the design point, the
  // readout says which of the two it is, and gives the other beside it. Only on the results,
  // where the motion is always followed: elsewhere one kept from an earlier visit would make
  // the readout depend on where the user had been, and a reload would not show it.
  const onResults = app.state.step === RESULTS;
  const kept = onResults && c.id === focused()?.id ? res.cycle : null;
  const cycle = notRefused(kept);
  const motionPeak = cycle?.summary.peak ?? null;
  const differs = motionPeak != null && Math.abs(motionPeak - r.tj_peak) >= 1;
  const partly = cycle ? cycle.p_stage.some((p) => p === null) : false;
  return differs ? `; through the motion${partly ? ", in the part followed" : ""}: ${degrees(motionPeak)}` : "";
}

/** The part is known; what it must do is not yet. Say what the part is, then what the
 *  motor asks of it, and nothing about losses. */
function partCells(d: DeviceSummary, others: number): string {
  const { state } = app;
  const more = others > 0 ? `, and ${others} more to compare` : "";
  let cells =
    readout("Device under test", d.name, `${d.technology}. ${packaging(d)}${more}`) +
    readout("Rated", `${num(d.v_max)} V`, `${num(d.i_nominal)} A, ${Math.round(d.tj_max)} °C junction`);
  if (state.reached >= SUPPLY && res.stage) {
    const over = res.stage.i_peak > d.i_nominal;
    const note = over ? `peak, above this part's ${num(d.i_nominal)} A rating` : "peak in the windings";
    // A supply above the part's rating is said here as it is at its field: these are the
    // motor's figures, and no word on the part.
    const high = Number(state.conditions.v_dc) > d.v_max;
    const from = `from ${num(state.conditions.v_dc)} V${high ? `, above this part's ${num(d.v_max)} V rating` : ""}`;
    cells +=
      readout("The motor asks for", `${num(res.stage.i_peak)} A`, note, over ? "caution" : "") +
      readout("Shaft power", watts(res.stage.p_shaft), from, high ? "caution" : "");
  } else {
    const next = state.reached < MOTOR ? "The motor" : "Supply and point";
    cells += readout("Next", next, "Losses appear once the conditions are set.");
  }
  return cells;
}

const STARTING_KEPT =
  "Your part and what you entered are kept in this browser, and come back when the engine has started.";
const STARTING_FIRST =
  "The first time, about 14 MB of Python runtime comes with this page and about 20 MB of numerical " +
  "libraries from cdn.jsdelivr.net; your browser keeps both. Nothing you enter leaves this page. Carry on meanwhile.";

/** What stands beside the drawing: by how far the user has come and what the engine said. */
function cellsFor(
  c: Candidate | null,
  chosen: DeviceSummary[],
  shown: DeviceSummary | undefined,
  many: boolean,
): string {
  return cellsBeforeParts(chosen) ?? cellsForParts(c, chosen, shown, many);
}

/** What stands beside the drawing before there is a part on the page, or while its figures
 *  are worked out; null once a part is there and nothing is being worked out. */
function cellsBeforeParts(chosen: DeviceSummary[]): string | null {
  const { state } = app;
  if (pending() && chosen.length) {
    return (
      readout("Power stage", "Working out…", "the figures for the inputs as they now stand") +
      readout("Power-stage loss", "–", "") +
      readout("Hottest junction", "–", "")
    );
  }
  // A part kept from an earlier visit is not on the page until the engine has it again.
  if (!chosen.length && ui.starting && state.devices.length) {
    return readout("Starting the engine", ui.starting, STARTING_KEPT);
  }
  if (!chosen.length) {
    // The empty place drawn: a datasheet handed to a transistor, beside what to do.
    return (
      `<div class="readout start-empty"><dt>Start here</dt><dd>${emptyArt("part")}` +
      `<span class="figure words">Choose the device to test</span>` +
      `<span class="note">Step 1. Nothing is worked out until you have brought a part.</span></dd></div>`
    );
  }
  return null;
}

/** With the engine failed or the server gone: the last figures stay, said to be from before;
 *  with none, nothing is shown as a figure. */
function faultCells(c: Candidate | null, fault: string, many: boolean): string {
  const r = c?.result ?? null;
  if (r)
    return (
      readout("Power stage", "Not worked out", "these figures are from before it stopped") + resultCells(c!, r, many)
    );
  const why = res.offline ? "The local motionsim server is not answering; asked again by itself." : fault;
  return readout("Power stage", "Not available", why) + readout("Power-stage loss", "–", "");
}

/** What stands beside the drawing once a part is on the page: what the engine said of it. */
function cellsForParts(
  c: Candidate | null,
  chosen: DeviceSummary[],
  shown: DeviceSummary | undefined,
  many: boolean,
): string {
  const { state } = app;
  const r = c?.result ?? null;
  // With the engine failed or the server gone, there is no answer for these inputs: said so,
  // never as the next step to take.
  if (res.fault && state.reached >= SUPPLY) return faultCells(c, res.fault, many);
  if (res.waiting && state.reached >= SUPPLY) {
    return readout("Power stage", "One figure needed", `${sentence(res.waiting.reason)}: step 3, under Cooling.`);
  }
  if (refusedNow()) {
    const at = STEPS[blockedStep() < 0 ? SUPPLY : blockedStep()].name.toLowerCase();
    const where = state.step === RESULTS ? `go back to ${at} and change it` : "change an input on the right";
    return readout("Power stage", "No solution", where);
  }
  if (r) return resultCells(c!, r, many);
  if (ui.starting) return readout("Starting the engine", ui.starting, STARTING_FIRST);
  if (conditionsGiven() && c?.problem) {
    return readout("Power stage", "Cannot be worked out", `${sentence(c.problem)}. ${sentence(c.fix)}`);
  }
  return partCells(shown!, chosen.length - 1);
}

/** Under the figures: where the two kinds of loss come from, period by period. */
function pwmBlock(c: Candidate): string {
  const n = app.state.pwmPeriods;
  const open = (ui.pwmOpen ?? !matchMedia("(max-width: 860px)").matches) ? " open" : "";
  const zoom = (way: "in" | "out", label: string, off: boolean) =>
    `<button type="button" class="ghost" data-zoom="${way}" aria-label="${label}" ${off ? "disabled" : ""}>` +
    `${icon(`zoom-${way}`)}</button>`;
  const head =
    // An h2: the drawing's column comes before the panel's, under the page's h1 (heading order).
    `<div class="pwm-head"><h2>${n === 1 ? "One switching period" : `${n} switching periods`}</h2>` +
    `<div class="zoom" role="group" aria-label="How many periods are shown">` +
    zoom("in", "Zoom in: fewer periods", n <= ZOOMS[0]) +
    zoom("out", "Zoom out: more periods", n >= ZOOMS[ZOOMS.length - 1]) +
    `</div></div>`;
  const said = `<p class="quiet">${escape(sentence(c.pwm!.position))}, the hottest switch of ${escape(c.name)}.</p>`;
  const summary = `<summary>${icon("adjustments")}Where the loss comes from, period by period</summary>`;
  const chart = pwmChart(
    c.pwm!,
    n,
    ev.open ? ev.mark : null,
    `${sentence(c.pwm!.position)}, the hottest switch of ${c.name}`,
  );
  return `<details class="pwm-fold"${open}>${summary}${head}${said}${chart}${eventSlot(c)}</details>`;
}

/** The devices that can be put on the drawing, when more than one was run. */
function switcher(c: Candidate | null): string {
  const run = res.proposal!.candidates.filter((x) => x.result);
  const chip = (x: Candidate) =>
    `<button type="button" class="chip${x.id === c?.id ? " is-on" : ""}" data-focus="${escape(x.id)}" ` +
    `aria-pressed="${x.id === c?.id}">${escape(x.name)}</button>`;
  return `<span class="switcher-label">On the drawing</span>${run.map(chip).join("")}`;
}

/** On a narrow screen the verdict is a long way below the drawing: its word is said first,
 *  with the way down to the reasons. It repeats the panel, so it is kept from screen readers. */
function verdictStrip(c: Candidate | null, wait: boolean): string {
  if (app.state.step !== RESULTS || !c?.level || res.blocked || res.fault) return "";
  if (wait) return `<span class="verdict waiting-word">Working out…</span>`;
  const why = `<a class="link" href="#panel" tabindex="-1">Why${icon("chevron-down")}</a>`;
  return `${verdictMarkup(wordsOf(c), whereOf(c))}${why}`;
}

/** The loss chart with the switching event under it. While the answer for a figure just typed
 *  is on its way they stay, marked as not yet of the inputs: a box of the event being typed
 *  in is never taken from under the keyboard. A design refused keeps the event's boxes, to
 *  put the figure right in. */
function drawPwm(c: Candidate | null, r: Result | null, wait: boolean): void {
  const pwm = $("#pwm");
  if (r && c?.pwm && !refusedNow()) put(pwm, pwmBlock(c));
  else if (!(wait && ev.open && pwm.childElementCount)) put(pwm, refusedNow() ? eventBoxes() : "");
}

export function renderStage(): void {
  const { setup } = app;
  const wait = pending();
  const c = conditionsGiven() ? focused() : null;
  const r = wait ? null : (c?.result ?? null);
  const chosen = chosenDevices();
  const shown = setup.devices.find((d) => d.id === (c?.id ?? underTest() ?? chosen[0]?.id));
  put($("#verdict-strip"), verdictStrip(c, wait));
  drawPlate(c, shown, wait);
  const many = !wait && conditionsGiven() && (res.proposal?.candidates.filter((x) => x.result).length ?? 0) > 1;
  put($("#switcher"), many ? switcher(c) : "");
  const cells = cellsFor(c, chosen, shown, many);
  const before = [...document.querySelectorAll<HTMLElement>("#readouts [data-roll]")].map((e) => e.textContent ?? "");
  // The things compared are set side by side under the results' tabs: the figures beside
  // the drawing are always those of the design.
  put($("#readouts"), cells);
  if (app.state.step === RESULTS) renderCompareArea();
  drawPwm(c, r, wait);
  focusOnce();
  marked(before);
  renderBarStatus();
}

/** A figure that changed comes up from a little dimmer in 120 ms, the changed one only: never
 *  counted from its old value, so that every figure on the screen is readable at every
 *  moment (the deltas say how far it moved). */
function marked(before: string[]): void {
  document.querySelectorAll<HTMLElement>("#readouts [data-roll]").forEach((el, k) => {
    const was = before[k];
    if (!was || was === el.textContent || typeof el.animate !== "function") return;
    el.animate([{ opacity: 0.6 }, { opacity: 1 }], { duration: 120, easing: "ease-out" });
  });
}
