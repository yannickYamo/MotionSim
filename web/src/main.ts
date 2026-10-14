import "./style.css";
import { api, boot, Refused } from "./api";
import type { Candidate, Capability, Position, Result, Check, Cycle, Largest, LoadPreset, MapGrid, ModelTable, Proposal, Reading, ReadOutcome, Recommendation, Setup, Stage, Suggest, Advice } from "./api";
import { AT_MOTOR, compareBars, heatMap, limitChart, lossBar, mapScale, sharedRange, motionPreview, overlayChart, pwmChart, tableChart, timeChart } from "./charts";
import type { MapAxes } from "./charts";
import { degrees, eng, escape, fig, percent, sentence, sig, watts } from "./format";
import { equationsPage } from "./equations";
import { icon } from "./icons";
import { schematic } from "./schematic";
import { KEY, motionRequest, request, restore, save } from "./state";
import type { LoadItem, State, Tab } from "./state";

// The user arrives with a power device to test. The motor, the conditions and the load say
// what it has to survive; nothing is said about losses until all of that is given.
const STEPS = [
  { name: "Device", icon: "cpu", about: "The part you want to test" },
  { name: "Motor", icon: "engine", about: "What it has to drive" },
  { name: "Supply and point", icon: "bolt", about: "Voltage, speed, torque" },
  { name: "Load", icon: "weight", about: "What the motor moves" },
  { name: "Results", icon: "chart-bar", about: "Does it suit, and why" },
];
const DEVICE = 0;
const MOTOR = 1;
const SUPPLY = 2;
const LOAD = 3;
const RESULTS = 4;
const TABS: [Tab, string][] = [["proposal", "Verdict"], ["losses", "Losses"], ["motion", "Motion"], ["map", "Map"], ["settings", "What to build"], ["capability", "What it can drive"]];

let setup: Setup;
let state: State;
let stage: Stage | null = null;
let advice: Advice | null = null;
let proposal: Proposal | null = null;
let blocked: Refused | null = null;
let fault: string | null = null;
let reportFault: string | null = null; // a report that could not be written: said beside its button, the engine being well
let cycle: Cycle | Refused | null = null;
let grid: MapGrid | Refused | null = null;
let advised: Recommendation[] | Refused | null = null;
let reading: { name: string; outcome?: ReadOutcome; refused?: Refused; file?: string } | null = null;
let typedRefused: Refused | null = null;
let typedBusy = false;
let typedOpen = false;
/** What suits the device under test: the supply, and how each kind of motor fits it. */
let suggestion: { id: string; data: Suggest } | null = null;
// Whether the motor as described fits the part: asked of the engine at the motor step.
let fit: { lines: { level: string; text: string }[] } | Refused | null = null;
let fitTimer = 0;
let fitAsked = 0;

/** A figure and its unit kept on one line. */
const together = (text: string) => text.replace(/(\d) (N·m|A|V|rpm|°C|K\/W|W|kHz|ns|µs)\b/g, "$1\u00a0$2");

/** What the engine says of this motor on this part, before any design point is set. */
function fitBlock(): string {
  if (!fit) return "";
  if (fit instanceof Refused) return `<p class="fact warn" role="alert">${icon("alert-triangle")}<span><b>This motor cannot be worked out yet.</b> ${escape(sentence(fit.reason))}.</span></p>`;
  const raised = fit.lines.filter((x) => x.level !== "ok");
  const fine = fit.lines.filter((x) => x.level === "ok");
  return `${raised.length ? `<div class="fit-raised" role="alert"><h3>${icon("alert-triangle")}This motor does not fit the part as it is</h3>${raised.map((x) => `<p class="fact warn">${icon("alert-triangle")}<span>${together(escape(sentence(x.text)))}.</span></p>`).join("")}</div>` : ""}${fine.map((x) => `<p class="fact fits">${icon("circle-check")}<span>${together(escape(sentence(x.text)))}.</span></p>`).join("")}`;
}

/** The device the motor and the supply are matched to before there are results: the first
 *  ticked as the list shows them, which is the one the drawing names, in whatever order
 *  they were ticked. */
const underTest = (): string | undefined => setup.devices.find((d) => state.devices.includes(d.id))?.id ?? state.devices[0];

/** Ask again a moment after the motor's figures stop changing, and draw only the note. */
function fitFor(now = false): void {
  clearTimeout(fitTimer);
  fitTimer = window.setTimeout(async () => {
    const device = underTest();
    if (state.step !== MOTOR || !device) return;
    const mine = ++fitAsked;
    const req = request(state);
    try {
      fit = await api.fit({ motor: req.motor, device, parallel: req.conditions.parallel, rpm: state.conditions.rpm, v_dc: state.conditions.v_dc });
    } catch (e) {
      fit = e instanceof Refused ? e : null;
    }
    if (mine !== fitAsked) return; // a later figure has been typed since
    const box = document.querySelector<HTMLElement>("#motor-fit");
    if (box) box.innerHTML = fitBlock();
  }, now ? 0 : 350);
}


/** Ask what suits the device under test. Until the user has touched the motor or the
 *  conditions, start them where their device belongs: the recommended kind of motor, its
 *  example wound for the supply the device suits, and that supply. */
async function suggestFor(): Promise<void> {
  const id = underTest();
  if (!id) { suggestion = null; return; }
  let changed = false; // redraw only when there is something new to show
  if (suggestion?.id !== id) {
    changed = true;
    try {
      suggestion = { id, data: await api.suggest(id) };
    } catch {
      suggestion = null;
      return;
    }
  }
  if (underTest() !== id) return; // the choice moved on while this was asked
  const motors = suggestion.data.motors;
  if (changed) {
    for (const [k, m] of Object.entries(motors)) if (!state.motorTouched || !state.motorEdited.includes(k)) state.motors[k] = { ...state.motors[k], ...m.values };
    if (state.motorTouched) { state.pointOf = {}; save(state); } // points kept for other kinds were for the last device
  }
  if (!state.motorTouched && changed) {
    state.kind = Object.keys(motors).find((k) => motors[k].fit === "recommended") ?? state.kind;
    const start = motors[state.kind].start;
    Object.assign(state.conditions, { v_dc: start.v_dc, rpm: start.rpm, torque: start.torque, f_khz: start.f_sw / 1000, pwm: "" });
    save(state);
  }
  if (!changed) return;
  if (state.step === MOTOR || state.step === SUPPLY) renderPanel(true);
  renderStage();
  if (!state.motorTouched) schedule(); // what was worked out before the suggestion came is not of this supply
}

/** Kinds of load this motor usually drives, sized from its design point. */
let presets: { key: string; list: LoadPreset[] } | null = null;

/** A preset as the figures the page holds for a load. */
function figuresOf(p: LoadPreset): State["load"] {
  const l = p.load;
  return {
    gear_ratio: l.gear_ratio ?? 1, gear_efficiency: l.gear_efficiency ?? 1, motor_inertia: l.motor_inertia ?? 0,
    inertia: l.inertia ?? 0, friction_coulomb: l.friction_coulomb ?? 0, friction_viscous: l.friction_viscous ?? 0,
    mass: l.gravity?.mass ?? 0, arm: l.gravity?.arm ?? 0, start_angle_deg: p.start_angle_deg ?? 0,
    constant_torque: l.constant_torque ?? 0, fan_coefficient: l.fan_coefficient ?? 0,
    v_mass: l.vehicle?.mass ?? 0, wheel_radius: l.vehicle?.wheel_radius ?? 0,
    rolling_resistance: l.vehicle?.rolling_resistance ?? 0, drag_area: l.vehicle?.drag_area ?? 0,
    slope_percent: l.vehicle?.slope_percent ?? 0,
  };
}

const itemOf = (p: LoadPreset): LoadItem => ({ id: p.id, label: p.label, loadKind: p.id, load: figuresOf(p), segments: p.segments.map((x) => ({ ...x })) });

function applyPreset(p: LoadPreset): void {
  const l = p.load;
  state.load = {
    gear_ratio: l.gear_ratio ?? 1, gear_efficiency: l.gear_efficiency ?? 1, motor_inertia: l.motor_inertia ?? 0,
    inertia: l.inertia ?? 0, friction_coulomb: l.friction_coulomb ?? 0, friction_viscous: l.friction_viscous ?? 0,
    mass: l.gravity?.mass ?? 0, arm: l.gravity?.arm ?? 0, start_angle_deg: p.start_angle_deg ?? 0,
    constant_torque: l.constant_torque ?? 0, fan_coefficient: l.fan_coefficient ?? 0,
    v_mass: l.vehicle?.mass ?? 0, wheel_radius: l.vehicle?.wheel_radius ?? 0,
    rolling_resistance: l.vehicle?.rolling_resistance ?? 0, drag_area: l.vehicle?.drag_area ?? 0,
    slope_percent: l.vehicle?.slope_percent ?? 0,
  };
  state.segments = p.segments.map((s) => ({ ...s }));
  state.loadKind = p.id;
  cycle = null;
  save(state);
}

let presetTries = 0;
/** Fetch the loads usual for this motor at this design point. Until the user has picked or
 *  edited a load, the most usual one is theirs to start from. */
async function presetsFor(): Promise<void> {
  const c = state.conditions;
  const key = `${state.kind}|${c.rpm}|${c.torque}|${c.v_dc}`;
  if (presets?.key === key) return;
  try {
    presets = { key, list: (await api.loads(state.kind, c.rpm, c.torque, c.v_dc)).loads };
  } catch (e) {
    // A design point that is not a number yet: the step says so itself. Anything else is an
    // engine still starting, and the loads are asked for again until it answers.
    if (!(e instanceof Refused) && presetTries++ < 120 && state.step >= LOAD) window.setTimeout(() => void presetsFor(), 2000);
    return;
  }
  presetTries = 0;
  if (presets.key !== `${state.kind}|${state.conditions.rpm}|${state.conditions.torque}|${state.conditions.v_dc}`) return;
  // The loads are sized from the design point, so when that moves they are sized again:
  // the load the user picked, unless they have put in figures of their own, and the ones
  // set beside it to compare. A load not offered for this motor gives way to the usual one.
  if (!state.loadTouched) applyPreset(presets.list.find((p) => p.id === state.loadKind) ?? presets.list[0]);
  const fresh = presets.list;
  state.loadSet = state.loadSet.flatMap((item) => {
    if (item.id.startsWith("own-")) return [item];
    if (!state.loadTouched && item.id === state.loadKind) return []; // it is the load of step 4 now
    const now = fresh.find((p) => p.id === item.id);
    return now ? [itemOf(now)] : [];
  });
  cycles.clear();
  cycle = null; // the motion followed so far was of the load as it stood before it was sized
  save(state);
  if (state.step === LOAD) { renderPanel(true); renderPreview(); }
  if (state.step === RESULTS) { renderPanel(true); renderStage(); void deep(); }
}

/** The device whose model is laid open for checking against its datasheet. */
let review: { id: string; data?: Reading; failed?: string } | null = null;
/** The motion followed for each thing compared (a device, or a load), and each device's map. */
const cycles = new Map<string, Cycle | Refused>();
const grids = new Map<string, MapGrid | Refused>();
const MOST = 5; // devices, or loads, compared at once: more cannot be told apart on one chart
let capable: Capability | Refused | null = null; // what the device under test can drive
let biggest: Largest | Refused | "working" | null = null; // how far the load could be scaled up
let missionFault: Refused | null = null;
let pwmOpen: boolean | null = null; // whether the user has the period drawing open; null: not chosen, so by screen width
let pending: AbortController | null = null;
let starting: string | null = null; // what the engine is doing while it loads in the browser
let timer = 0;
const loading = new Set<string>();
/** Answers asked for again by a later pass while an earlier asking was still out. */
const askedAgain = new Set<string>();
/** What the results are of: every input, and nothing of where the user is looking. An
 *  answer is kept only if this reads the same when it arrives as when it was asked for,
 *  and everything worked out is dropped when it no longer reads as it did. */
const inputsNow = (): string => JSON.stringify({ ...state, step: 0, reached: 0, tab: "", metric: "", mapAt: "", pwmPeriods: 0, typed: null, focus: null, focusPicked: false, added: null });
let resultsOf = "";

const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- small pieces ---------- */

/** The folds the user has opened, kept through redraws. */
const openFolds = new Set<string>();

/**
 * Detail one press away. The face says what is inside as it stands now, so that nothing
 * the tool assumed is hidden: only the means of changing it is folded.
 * `holds`: the fields inside; a refusal about one of them opens the fold.
 */
function fold(id: string, glyph: string, title: string, face: string, body: string, holds: string[] = []): string {
  const wrong = blocked?.field ? holds.some((h) => h === blocked!.field || h.endsWith(`.${blocked!.field}`)) : false;
  return `<details class="more" data-fold="${id}"${openFolds.has(id) || wrong ? " open" : ""}><summary>${icon(glyph)}${escape(title)}<span class="quiet">${escape(face)}</span></summary>${body}</details>`;
}

/** The cooling as the user set it, in a few words. */
function coolingWords(): string {
  const k = state.conditions;
  const under = String(k.rth_case_sink ?? "").trim() !== "" ? `, ${k.rth_case_sink} K/W from each case to it` : k.interface === "pad" ? ", each package on a thermal pad" : "";
  // What the user typed is text until the engine has taken it: it is written out as text.
  if (k.cooling === "heatsink") return escape(`a ${k.rth_sink || "?"} K/W heatsink in ${sig(k.t_ambient)} °C air${under}`);
  if (k.cooling === "none") return `no heatsink, in ${sig(k.t_ambient)} °C air`;
  if (k.cooling === "board") return escape(`no heatsink, on a ${k.board_area || "?"} cm² board in ${sig(k.t_ambient)} °C air`);
  return escape(`a ${sig(k.t_sink)} °C heatsink${under}`);
}

/** A figure typed in a base unit, said the way it is spoken: 0.00833 H is "8.33 mH". Only
 *  where the two differ enough to help; it follows the figure as it is typed. */
const SPOKEN = new Set(["H", "Ω", "F", "Wb", "V·s/rad"]);
function saidAs(raw: string | number, unit: string): string {
  const v = Number(raw);
  if (!SPOKEN.has(unit) || String(raw).trim() === "" || !Number.isFinite(v) || v === 0) return "";
  return Math.abs(v) < 0.1 || Math.abs(v) >= 10000 ? `That is ${eng(v, unit)}. ` : "";
}

/** The engine's name for a figure, as the page's box for it is bound. */
const BOX: Record<string, string[]> = { f_sw: ["f_khz"], t_dead: ["t_dead_ns"], l_loop: ["l_loop_nh"], t_min_pulse: ["t_min_ns"], point: ["rpm", "torque"], speed: ["rpm"] };
/** Whether the box bound to this path holds the figure the engine refused. */
function wrongAt(path: string): boolean {
  if (!blocked?.field) return false;
  const last = path.split(".").pop()!;
  return (BOX[blocked.field] ?? [blocked.field]).includes(last) && /^(conditions|motors|load|sink|start)\./.test(path);
}

function field(path: string, label: string, value: string | number, unit: string, help = "", attrs = ""): string {
  const id = `f-${path.replace(/\W+/g, "-")}`;
  const marked = wrongAt(path) ? " is-wrong" : "";
  const spoken = SPOKEN.has(unit);
  const below = help || spoken ? `<p class="help" id="${id}-h">${spoken ? `<span data-said="${escape(unit)}">${escape(saidAs(value, unit))}</span>` : ""}${escape(help)}</p>` : "";
  return `<div class="field${marked}"><label for="${id}">${escape(label)}</label><div class="control"><input id="${id}" data-bind="${path}" inputmode="decimal" autocomplete="off" value="${escape(String(value ?? ""))}" ${attrs} ${below ? `aria-describedby="${id}-h"` : ""}/>${unit ? `<span class="unit">${escape(unit)}</span>` : ""}</div>${below}</div>`;
}

function select(path: string, label: string, value: string, options: [string, string][], help = ""): string {
  const id = `f-${path.replace(/\W+/g, "-")}`;
  return `<div class="field"><label for="${id}">${escape(label)}</label><div class="control"><select id="${id}" data-bind="${path}">${options.map(([v, t]) => `<option value="${escape(v)}"${v === value ? " selected" : ""}>${escape(t)}</option>`).join("")}</select></div>${help ? `<p class="help">${escape(help)}</p>` : ""}</div>`;
}

const verdict = (level: string) =>
  `<span class="verdict ${level}">${icon(level === "ok" ? "circle-check" : level === "fail" ? "circle-x" : level === "undecided" ? "help-circle" : "alert-triangle")}${level === "ok" ? "Passes" : level === "fail" ? "Ruled out" : level === "undecided" ? "Undecided on this data" : "Cautions"}</span>`;

const checkList = (checks: Check[]) =>
  `<ul class="checks">${checks.map((c) => `<li class="${c.level}">${icon(c.level === "ok" ? "check" : c.level === "fail" ? "x" : c.level === "undecided" ? "help-circle" : "alert-triangle")}<span><b>${escape(sentence(c.topic))}.</b> ${escape(sentence(c.message))}</span></li>`).join("")}</ul>`;

function refusal(r: Refused): string {
  return `<div class="refusal" role="alert">${icon("ban")}<div><p><b>This cannot work.</b> ${escape(sentence(r.reason))}.</p>${r.fix ? `<p class="fix">${escape(sentence(r.fix))}.</p>` : ""}</div></div>`;
}

const waiting = (text: string) => `<p class="waiting" role="status"><span class="spinner" aria-hidden="true"></span>${escape(text)}</p>`;

/* ---------- the stage ---------- */

function focused(): Candidate | null {
  const list = proposal?.candidates ?? [];
  return list.find((c) => c.id === state.focus) ?? list.find((c) => c.result) ?? null;
}

function readout(label: string, value: string, note = "", tone = ""): string {
  // A figure is set large; a name or a phrase is set smaller and may wrap.
  const words = /^[^\d–]/.test(value) ? " words" : "";
  return `<div class="readout ${tone}"><dt>${escape(label)}</dt><dd><span class="figure${words}" data-roll>${escape(value)}</span>${note ? `<span class="note">${escape(note)}</span>` : ""}</dd></div>`;
}

/** Results are shown once the device, the motor and the conditions have all been given. */
const conditionsGiven = () => state.reached >= LOAD && state.devices.length > 0;

function renderStage(): void {
  const c = conditionsGiven() ? focused() : null;
  const r = c?.result ?? null;
  const chosen = setup.devices.filter((d) => state.devices.includes(d.id));
  const shown = setup.devices.find((d) => d.id === (c?.id ?? chosen[0]?.id));
  // On a narrow screen the verdict is a long way below the drawing: its word is said first,
  // with the way down to the reasons. It repeats the panel, so it is kept from screen readers.
  $("#verdict-strip").innerHTML = state.step === RESULTS && c?.level && !blocked
    ? `${verdict(c.level)}<a class="link" href="#panel" tabindex="-1">Why${icon("chevron-down")}</a>`
    : "";
  $("#plate").innerHTML = schematic({
    kind: state.kind, stage: state.reached >= SUPPLY ? stage : null, result: r,
    tSink: state.conditions.cooling === "held" ? state.conditions.t_sink : state.conditions.t_ambient, vdc: state.reached >= SUPPLY ? state.conditions.v_dc : null,
    motorKnown: state.reached >= MOTOR,
    parallel: state.reached >= SUPPLY ? Math.max(1, Math.round(Number(state.conditions.parallel) || 1)) : 1,
    fet: shown ? !shown.technology.includes("IGBT") : false,
    blocked: !!blocked && state.reached >= SUPPLY, deviceName: shown?.name ?? null,
    battery: state.supply === "battery",
    pack: shown ? { positions: shown.positions, driver: shown.integrated_driver } : null,
    rotor: {
      kind: state.kind, magnets: String(state.motors[state.kind].magnets ?? "surface"),
      polePairs: Number(state.motors[state.kind].pole_pairs) || 1,
      steps: Number(state.motors[state.kind].steps_per_rev) || 200,
    },
    // The rotor turns only while the user is at or past the point where they set the
    // speed. Going back to the motor or the device stops it.
    rpm: state.step >= SUPPLY ? state.conditions.rpm : 0,
  });
  const many = conditionsGiven() && (proposal?.candidates.filter((x) => x.result).length ?? 0) > 1;
  $("#switcher").innerHTML = many
    ? `<span class="switcher-label">On the drawing</span>${proposal!.candidates.filter((x) => x.result).map((x) => `<button type="button" class="chip${x.id === c?.id ? " is-on" : ""}" data-focus="${escape(x.id)}" aria-pressed="${x.id === c?.id}">${escape(x.name)}</button>`).join("")}`
    : "";
  let cells: string;
  if (!chosen.length && starting && state.devices.length) {
    // A part kept from an earlier visit is not on the page until the engine has it again.
    cells = readout("Starting the engine", starting, "Your part and what you entered are kept in this browser, and come back when the engine has started.");
  } else if (!chosen.length) {
    cells = readout("Start here", "Choose the device to test", "Step 1. Nothing is worked out until you have brought a part.");
  } else if (blocked && state.reached >= SUPPLY) {
    cells = readout("Power stage", "No solution", state.step === RESULTS ? `go back to ${STEPS[blockedStep() < 0 ? SUPPLY : blockedStep()].name.toLowerCase()} and change it` : "change an input on the right");
  } else if (r) {
    const range = r.tj_range && Math.round(r.tj_range[0]) !== Math.round(r.tj_range[1]) ? `${Math.round(r.tj_range[0])} to ${Math.round(r.tj_range[1])} °C across the thermal assumptions` : `${Math.round(r.tj_max - r.tj_peak)} °C under the rating`;
    const settled = state.conditions.cooling === "heatsink" && r.t_sink != null ? `heatsink at ${Math.round(r.t_sink)} °C, ` : "";
    const hot = r.tj_peak > r.tj_max ? "fail" : r.tj_max - (r.tj_range?.[1] ?? r.tj_peak) < 25 ? "caution" : "";
    cells =
      readout("Power-stage loss", watts(r.loss), `${many ? "" : `${c!.name}, `}${sig(r.loss / (stage?.positions ?? 6))} W a switch on average`) +
      readout("Conduction", watts(r.conduction), percent(r.conduction / Math.max(r.loss, 1e-9), 0)) +
      readout("Switching", watts(r.switching), percent(r.switching / Math.max(r.loss, 1e-9), 0), "accent") +
      readout("Hottest junction", degrees(r.tj_peak), settled + range, hot) +
      (c?.efficiency != null ? readout("DC-to-shaft efficiency", percent(c.efficiency), "motor windings included") : "");
  } else if (starting) {
    cells = readout("Starting the engine", starting, "About 20 MB the first time, fetched from cdn.jsdelivr.net and then kept by your browser. Nothing you enter leaves this page. Carry on meanwhile.");
  } else if (conditionsGiven() && c?.problem) {
    cells = readout("Power stage", "Cannot be worked out", `${sentence(c.problem)}. ${sentence(c.fix)}`);
  } else {
    // The part is known; what it must do is not yet. Say what the part is, then what the
    // motor asks of it, and nothing about losses.
    const d = shown!;
    cells =
      readout("Device under test", d.name, `${d.technology}. ${packaging(d)}${chosen.length > 1 ? `, and ${chosen.length - 1} more to compare` : ""}`) +
      readout("Rated", `${sig(d.v_max)} V`, `${sig(d.i_nominal)} A, ${Math.round(d.tj_max)} °C junction`);
    if (state.reached >= SUPPLY && stage) {
      const over = stage.i_peak > d.i_nominal;
      cells +=
        readout("The motor asks for", `${sig(stage.i_peak)} A`, over ? `peak, above this part's ${sig(d.i_nominal)} A rating` : "peak in the windings", over ? "caution" : "") +
        readout("Shaft power", watts(stage.p_shaft), `from ${sig(state.conditions.v_dc)} V`);
    } else {
      cells += readout("Next", state.reached < MOTOR ? "The motor" : "Supply and point", "Losses appear once the conditions are set.");
    }
  }
  const before = [...document.querySelectorAll<HTMLElement>("#readouts [data-roll]")].map((e) => e.textContent ?? "");
  // The table belongs to the results: away from them the things compared are not being
  // worked out, so the plain figures of the device under test are shown.
  const table = r && state.step === RESULTS && conditionsGiven() && comparing() && !(blocked && state.reached >= SUPPLY) ? compareTable() : "";
  $("#compare-table").innerHTML = table;
  $("#readouts").innerHTML = table ? "" : cells;
  // Under the figures: where the two kinds of loss come from, period by period.
  $("#pwm").innerHTML = r && c?.pwm && !(blocked && state.reached >= SUPPLY)
    ? `<details class="pwm-fold"${pwmOpen ?? !matchMedia("(max-width: 860px)").matches ? " open" : ""}><summary>${icon("adjustments")}Where the loss comes from, period by period</summary><div class="pwm-head"><h3>${state.pwmPeriods === 1 ? "One switching period" : `${state.pwmPeriods} switching periods`}</h3><div class="zoom" role="group" aria-label="How many periods are shown"><button type="button" class="ghost" data-zoom="in" aria-label="Zoom in: fewer periods" ${state.pwmPeriods <= ZOOMS[0] ? "disabled" : ""}>${icon("zoom-in")}</button><button type="button" class="ghost" data-zoom="out" aria-label="Zoom out: more periods" ${state.pwmPeriods >= ZOOMS[ZOOMS.length - 1] ? "disabled" : ""}>${icon("zoom-out")}</button></div></div><p class="quiet">${escape(sentence(c.pwm.position))}, the hottest switch of ${escape(c.name)}.</p>${pwmChart(c.pwm, state.pwmPeriods)}</details>`
    : "";
  roll(before);
}

/** Figures count to their new value in place, like a counter, instead of jumping. */
function roll(before: string[]): void {
  if (reduced()) return;
  document.querySelectorAll<HTMLElement>("#readouts [data-roll]").forEach((el, k) => {
    const to = el.textContent ?? "";
    const a = parseFloat(before[k] ?? "");
    const b = parseFloat(to);
    if (!Number.isFinite(a) || !Number.isFinite(b) || a === b || to.replace(/[\d.]/g, "") !== (before[k] ?? "").replace(/[\d.]/g, "")) return;
    const decimals = (to.match(/\.(\d+)/)?.[1].length ?? 0);
    const tail = to.replace(/^[-\d.]+/, "");
    const t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - t0) / 380, 1);
      const eased = 1 - (1 - p) ** 4;
      el.textContent = (a + (b - a) * eased).toFixed(decimals) + tail;
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
}

/* ---------- the rail ---------- */

/** The step whose form holds the input that was refused. */
function blockedStep(): number {
  if (!blocked || state.reached < SUPPLY) return -1;
  const motorKeys = setup.motors[state.kind].fields.map((f) => f.key);
  return motorKeys.includes(blocked.field) ? MOTOR : SUPPLY;
}

function stepState(k: number): string {
  if (k === blockedStep()) return "blocked";
  if (k === DEVICE && state.reached > DEVICE && !state.devices.length) return "blocked";
  if (k === RESULTS && state.reached >= RESULTS && proposal && !proposal.candidates.some((c) => c.result)) return "blocked";
  return k < state.reached || (k === state.reached && k !== state.step) ? "done" : "todo";
}

function renderRail(): void {
  $("#rail").innerHTML = `<ol>${STEPS.map((s, k) => {
    const st = stepState(k);
    const said = st === "blocked" ? "needs a change" : k === state.step ? "current step" : st === "done" ? "done" : "not opened yet";
    return `<li class="${st}${k === state.step ? " is-current" : ""}"><button type="button" data-step="${k}" aria-describedby="step-${k}-state" title="${s.name}" ${k === state.step ? 'aria-current="step"' : ""}><span class="station">${st === "blocked" ? icon("x") : st === "done" && k !== state.step ? icon("check") : icon(s.icon)}<span class="station-number">${k + 1}</span></span><span class="step-text"><span class="step-name">${s.name}</span><span class="step-about">${st === "blocked" ? (k === DEVICE ? "Choose a part" : "Needs a change") : s.about}</span></span></button><span class="sr" id="step-${k}-state">${said}</span></li>`;
  }).join("")}</ol>`;
}

/* ---------- the panel, step by step ---------- */

function nextButton(k: number): string {
  const back = k > 0 ? `<button type="button" class="ghost" data-step="${k - 1}">${icon("arrow-left")}Back</button>` : "<span></span>";
  const stuck = k === DEVICE && !state.devices.length;
  const label = k === LOAD ? "See the results" : `Next: ${STEPS[k + 1].name.toLowerCase()}`;
  return `<div class="actions">${back}<button type="button" class="primary" data-step="${k + 1}" ${stuck ? 'disabled aria-describedby="need-device"' : ""}>${label}${icon("arrow-right")}</button></div>${stuck ? '<p class="quiet need" id="need-device">Tick a device, or add one, to go on.</p>' : ""}`;
}

function motorPanel(): string {
  const kinds = Object.entries(setup.motors);
  const m = setup.motors[state.kind];
  const v = state.motors[state.kind];
  const fits = suggestion && suggestion.id === underTest() ? suggestion.data.motors : null;
  const unusual = (k: string) => fits?.[k]?.fit === "unusual";
  const option = ([k, x]: (typeof kinds)[number]) => {
    const fit = fits?.[k];
    const tag = fit?.fit === "recommended" ? '<span class="tag recommended">Starting point for your device</span>' : "";
    const why = fit && fit.fit !== "suits" ? `<span class="kind-why">${escape(sentence(fit.why))}.</span>` : "";
    return `<label class="kind${k === state.kind ? " is-on" : ""}${fit?.fit === "recommended" ? " is-rec" : ""}"><input type="radio" name="kind" value="${k}" data-kind ${k === state.kind ? "checked" : ""}/><span class="kind-name">${escape(x.label)}${tag}</span><span class="kind-about">${escape(x.about)}</span>${why}</label>`;
  };
  const group = (subset: typeof kinds) => [...new Set(subset.map(([, x]) => x.family))]
    .map((family) => `<div class="family" role="group" aria-label="${escape(family)}"><p class="family-name">${escape(family)}</p>${subset.filter(([, x]) => x.family === family).map(option).join("")}</div>`).join("");
  // The kinds that make sense with the device come first; the rest stay one press away.
  const usual = kinds.filter(([k]) => !unusual(k));
  const rest = kinds.filter(([k]) => unusual(k));
  const list = group(usual) + (rest.length
    ? `<details class="more other-kinds"${unusual(state.kind) ? " open" : ""}><summary>${icon("adjustments")}Other kinds of motor<span class="quiet">unusual with your device, each with the reason</span></summary>${group(rest)}</details>`
    : "");
  const device = setup.devices.find((d) => d.id === underTest());
  const suits = fits && device
    ? ` The example is wound for your ${Math.round(device.v_max)} V device, on about ${Math.round(suggestion!.data.v_supply)} V.`
    : "";
  return `<h2 tabindex="-1">The motor it drives</h2><p class="lead">Pick the motor and put in its catalogue figures.${suits}</p>
<fieldset class="kinds"><legend>Kind of motor</legend>${list}</fieldset>
<div class="fields">${m.fields.map((f) => (f.options ? select(`motors.${state.kind}.${f.key}`, f.label, String(v[f.key] ?? f.options[0]), f.options.map((o) => [o, o]), f.help) : field(`motors.${state.kind}.${f.key}`, f.label, v[f.key] ?? "", f.unit, f.help))).join("")}</div>
<div id="motor-fit" aria-live="polite">${fitBlock()}</div>
${m.optional?.length ? `<details class="more"${m.optional.some((f) => v[f.key] !== undefined && v[f.key] !== "") ? " open" : ""}><summary>${icon("adjustments")}More about this motor<span class="quiet">optional: iron loss${m.optional.some((f) => f.key === "i_sat") ? " and saturation" : ""}. Left empty, they are left out and the result says so</span></summary><div class="fields">${m.optional.map((f) => field(`motors.${state.kind}.${f.key}`, f.label, v[f.key] ?? "", f.unit, f.help)).join("")}</div></details>` : ""}${nextButton(MOTOR)}`;
}

/** Every part under test has its gate drivers inside the package. */
const driversBuiltIn = () => {
  const chosen = setup.devices.filter((d) => state.devices.includes(d.id));
  return chosen.length > 0 && chosen.every((d) => d.integrated_driver);
};
/** How a part is packaged, in the words a builder would use. */
const packaging = (d: { positions: number; integrated_driver: boolean }) =>
  d.integrated_driver ? "IPM: power module with its gate drivers built in"
    : d.positions >= 6 ? "Module: six switches in one package, gates driven from outside"
    : d.positions >= 4 ? "Module: two legs in one package, gates driven from outside"
    : d.positions >= 2 ? "Module: one leg in a package, gates driven from outside"
    : "Discrete: one switch a package, gates driven from outside";
const ZOOMS = [1, 2, 5, 10, 20]; // switching periods the drawing can show

function openEquations(): void {
  const dialog = document.querySelector<HTMLDialogElement>("#equations")!;
  $("#equations-body").innerHTML = equationsPage();
  dialog.showModal();
}

/** The checks that need reading stay in the open; those that passed are counted and folded. */
function checksBlock(c: Candidate): string {
  if (!c.checks.length) return "";
  const raised = c.checks.filter((x) => x.level !== "ok");
  const passed = c.checks.filter((x) => x.level === "ok");
  const id = `passed-${c.id}`;
  const rest = passed.length
    ? `<details class="more" data-fold="${escape(id)}"${openFolds.has(id) ? " open" : ""}><summary>${icon("circle-check")}${passed.length} ${passed.length === 1 ? "check passes" : "checks pass"}<span class="quiet">${escape(passed.map((x) => x.topic).join(", "))}</span></summary>${checkList(passed)}</details>`
    : "";
  // Where the layer under the package is what leaves the answer open, the way to it is one press.
  const cond = state.conditions;
  const mount = c.result?.range_lead === "mounting" && raised.some((x) => x.level === "undecided" && x.message.includes("case-to-heatsink resistance"))
    && (cond.cooling === "held" || cond.cooling === "heatsink") && String(cond.rth_case_sink ?? "").trim() === ""
    ? `<p><button type="button" class="ghost" data-step="${SUPPLY}" data-open-fold="mounting">${icon("adjustments")}Give the case-to-heatsink resistance</button></p>`
    : "";
  return `${raised.length ? `<h4>To read</h4>${checkList(raised)}${mount}` : ""}${rest}`;
}

/** The gate drive a result was worked out with: the headline value, then the reasons. */
function gateBlock(c: Candidate): string {
  const g = c.gate;
  if (!g || !c.result) return "";
  const ohm = (v: number | null) => (v === null ? "" : `${sig(v, 2)} Ω`);
  const head =
    g.kind === "built in" ? "Inside the module"
    : g.kind === "datasheet" ? (g.rg_on ? `${g.rg_off && g.rg_off !== g.rg_on ? `${ohm(g.rg_on)} on, ${ohm(g.rg_off)} off` : ohm(g.rg_on)}, as the datasheet measured with` : "As the datasheet measured with")
    : `${ohm(g.rg_on)} on, ${ohm(g.rg_off)} off, at ${sig(g.v_drive ?? 0, 2)} V drive`;
  const tag = g.kind === "chosen" ? '<span class="tag">chosen for lowest loss</span>' : g.kind === "given" ? '<span class="tag">yours</span>' : "";
  const id = `gate-${c.id}`;
  return `<details class="more" data-fold="${escape(id)}"${openFolds.has(id) ? " open" : ""}><summary>${icon("adjustments")}Gate drive<span class="quiet">${head}${g.kind === "chosen" ? ", chosen for you" : g.kind === "given" ? ", yours" : ""}${g.t_dead ? `, ${eng(g.t_dead, "s", 2)} dead time` : ""}</span></summary><p class="gate-used"><b>${head}</b> ${tag}</p><ul class="plain small">${g.lines.map((l) => `<li>${escape(sentence(l))}</li>`).join("")}</ul>${g.kind === "chosen" ? '<p class="quiet small">To use your own, give them under Supply and point, Gate drive.</p>' : ""}</details>`;
}

/** Whether a chosen device has no tabulated switching energy, so needs its gate drive described. */
const needsGate = () => setup.devices.some((d) => state.devices.includes(d.id) && d.needs_gate_drive);

/** What the gate fold says on its face: the drive in use, chosen or the user's own. */
function gateFace(): string {
  const used = focused()?.gate;
  return used?.rg_on
    ? `${sig(used.rg_on, 2)} Ω on, ${sig(used.rg_off ?? 0, 2)} Ω off${used.v_drive ? `, ${sig(used.v_drive, 2)} V` : ""}${used.t_dead ? `, ${eng(used.t_dead, "s", 2)} dead time` : ""}: ${used.kind === "given" ? "yours" : used.kind === "datasheet" ? "as the datasheet measured with" : "chosen for you, change them here"}`
    : needsGate() ? "left empty, the gate resistors with the lowest loss within the limits are chosen for you" : "optional for your device";
}
/** What the supply fold says on its face. */
const supplyFace = (): string => `${state.supply === "battery" ? "a battery, which takes braking energy back" : "a power supply, which does not take braking energy back"}; motor ${state.conditions.t_motor ? `at ${state.conditions.t_motor} °C` : "at 25 °C, as its figures are given"}`;

function supplyPanel(): string {
  const c = state.conditions;
  const m = setup.motors[state.kind];
  const scheme = m.fixed_scheme
    ? `<p class="fact">${icon("wave-sine")}<span>Modulation: ${escape(m.fixed_scheme)}. This motor type decides it.</span></p>`
    : select("conditions.pwm", "Modulation", c.pwm, [["", `Usual for this motor (${m.default_pwm})`], ...setup.pwm.map((p) => [p, p] as [string, string])], "Leave this on the usual scheme unless you know your controller uses another.");
  // What a drive designer sets first is in view: the bus, the point, how the stage switches,
  // how many devices share a switch, and the cooling. Second-order settings (what the supply
  // does with braking energy, the winding's temperature) are one press away, and so is the
  // gate drive, which the tool chooses and states when it is left open.
  return `<h2 tabindex="-1">Supply and design point</h2><p class="lead">The supply, and the hardest point the motor has to hold.</p>
<div class="fields">${field("conditions.v_dc", "Supply voltage", c.v_dc, "V")}<div></div>
${field("conditions.rpm", "Speed", c.rpm, "rpm")}${field("conditions.torque", "Torque", c.torque, "N·m")}</div>
<h3>Switching</h3><div class="fields">${field("conditions.f_khz", "Switching frequency", c.f_khz, "kHz", "Above 20 kHz is inaudible. Lower loses less.")}${field("conditions.parallel", "Devices in parallel", c.parallel, "a switch", "1 unless you put several side by side to share the current.")}<div class="wide">${scheme}</div></div>
<h3>Cooling</h3><div class="fields">${select("conditions.cooling", "What the devices sit on", c.cooling, [["held", "A heatsink, at a temperature I know"], ["heatsink", "A heatsink, in air"], ["none", "No heatsink: each part standing in the air"], ["board", "No heatsink: parts soldered to one board"]], c.cooling === "held" ? "Not sure of its temperature? Pick a heatsink in air, or no heatsink: those start from the air's temperature." : "")}
${c.cooling === "held" ? field("conditions.t_sink", "Heatsink temperature", c.t_sink, "°C", "What the heatsink sits at when warm. 60 is a fair start.")
    : c.cooling === "heatsink" ? field("conditions.rth_sink", "Heatsink to air", c.rth_sink, "K/W", "From the heatsink's data, with every device on it. A smaller figure is a bigger heatsink.") + field("conditions.t_ambient", "Air temperature", c.t_ambient, "°C", "Around the heatsink, inside the enclosure if there is one.")
    : c.cooling === "none" ? field("conditions.rth_ja", "Junction to air, one package", c.rth_ja, "K/W", "RthJA on the datasheet. Empty: the usual figure for a TO-220, TO-247 or TO-263, where the part is one of those.") + field("conditions.t_ambient", "Air temperature", c.t_ambient, "°C", "Around the devices, inside the enclosure if there is one.")
    : field("conditions.rth_ja", "Junction to air, one package", c.rth_ja, "K/W", "RthJA on the datasheet, with the copper area its footnote gives.") + field("conditions.t_ambient", "Air temperature", c.t_ambient, "°C", "Around the board, inside the enclosure if there is one.")
      + field("conditions.board_area", "Board area", c.board_area, "cm²", "Of the board the power stage is on. Everything the stage loses warms it, and it warms every part.")
      + field("conditions.copper", "Copper for each part", c.copper, "cm²", "The pad each part is soldered to. Empty: what the datasheet's figure was taken on.")
      + field("conditions.copper_ref", "Copper in the datasheet's figure", c.copper_ref, "cm²", "Empty: 6.45, one square inch, the usual footnote.")}
</div>
${c.cooling === "held" || c.cooling === "heatsink"
    ? fold("mounting", "adjustments", "How the packages sit on the heatsink",
        String(c.rth_case_sink ?? "").trim() !== "" ? `${c.rth_case_sink} K/W from each case to it` : c.interface === "pad" ? "on a thermal pad" : "on thermal grease",
        `<div class="fields">${select("conditions.interface", "Under each package", c.interface, [["", "Thermal grease"], ["pad", "A thermal pad"]], "What lies between a package and the heatsink. A pad is thicker than grease, so the package runs warmer on it.") + field("conditions.rth_case_sink", "Case to heatsink", c.rth_case_sink, "K/W", "Of one package. Empty: the device's own figure where its datasheet gives one for this layer, else worked out. A figure given here stands, whatever the layer.")}</div>`,
        ["interface", "rth_case_sink"])
    : ""}
${fold("more-settings", "adjustments", "Supply kind and motor temperature", supplyFace(),
    `<div class="fields">${select("supply", "Supply", state.supply, [["one-way", "Power supply"], ["battery", "Battery"]], "A battery takes braking energy back. A power supply does not.")}${field("conditions.t_motor", "Motor temperature", c.t_motor, "°C", "Empty: the motor's figures as given, at 25 °C. A warm motor (80 to 120) needs more current for the same torque.")}</div>`,
    ["t_motor"])}
${driversBuiltIn()
    ? `<details class="more"><summary>${icon("adjustments")}Dead time<span class="quiet">the gate drive is inside this module, so there is no gate voltage or resistor to set</span></summary><div class="fields">${field("conditions.t_dead_ns", "Dead time", c.t_dead_ns, "ns")}</div></details>`
    : `<details class="more" data-fold="gate"${c.v_drive || c.rg_on || openFolds.has("gate") || ["v_drive", "rg_on", "rg_off", "t_dead", "l_loop"].includes(blocked?.field ?? "") ? " open" : ""}><summary>${icon("adjustments")}Gate drive and layout<span class="quiet">${escape(gateFace())}</span></summary><div class="fields">
${field("conditions.v_drive", "Gate drive voltage", c.v_drive, "V", "Often 10 to 12 for silicon, 15 to 20 for SiC, 5 for GaN.")}${field("conditions.t_dead_ns", "Dead time", c.t_dead_ns, "ns")}${field("conditions.t_min_ns", "Shortest pulse", c.t_min_ns, "ns", "The shortest pulse your gate drive passes. It keeps the duty cycle off the rails.")}
${field("conditions.rg_on", "Turn-on gate resistance", c.rg_on, "Ω")}${field("conditions.rg_off", "Turn-off gate resistance", c.rg_off, "Ω")}
${field("conditions.l_loop_nh", "Loop inductance", c.l_loop_nh, "nH", "Of the switching loop on your board. 10 to 30 is typical for a careful layout.")}</div></details>`}
${nextButton(SUPPLY)}`;
}

function adviceBlock(): string {
  if (!advice) return "";
  return `<details class="more"><summary>${icon("list-details")}If you were choosing from scratch<span class="quiet">what to look for</span></summary><p class="quiet">Rules of thumb for the kind of part this motor and supply call for. Use them to find other datasheets to test.</p><ul class="plain small">${advice.lines.map((l) => `<li>${escape(l)}</li>`).join("")}</ul></details>`;
}

const LOAD_FIELDS: Record<string, [string, string, string]> = {
  gear_ratio: ["Gear ratio", ": 1", "Motor turns per load turn. 1 for direct drive."],
  gear_efficiency: ["Gear efficiency", "", "Between 0 and 1."],
  inertia: ["Load inertia", "kg·m²", "At the load's own shaft. Mass times radius squared for a weight on an arm."],
  motor_inertia: ["Rotor inertia", "kg·m²", ""],
  friction_coulomb: ["Friction", "N·m", "Constant, opposing motion."],
  friction_viscous: ["Friction growing with speed", "N·m·s", ""],
  constant_torque: ["Steady torque", "N·m", "What the load asks for at any speed."],
  fan_coefficient: ["Fan constant", "N·m·s²", "Torque over speed squared, speed in rad/s."],
  mass: ["Weight on an arm", "kg", "0 if there is none."],
  arm: ["Arm length", "m", ""],
  start_angle_deg: ["Starting angle", "°", "0 hangs straight down, 90 is level."],
  v_mass: ["Mass carried", "kg", "By this motor's wheel or axle."],
  wheel_radius: ["Wheel radius", "m", ""],
  rolling_resistance: ["Rolling resistance", "", "About 0.015 for tyres on a road."],
  drag_area: ["Drag area", "m²", "Drag coefficient times frontal area. 0 to leave air out."],
  slope_percent: ["Slope", "%", "Uphill is positive."],
};

let savingMd = false;

/** The whole design as a Markdown file: the same report the command line writes. The device
 *  on the drawing comes first, so it is the one followed through the motion. */
async function saveMarkdown(): Promise<void> {
  const first = focused()?.id;
  const devices = [...new Set([...(first ? [first] : []), ...state.devices])];
  savingMd = true; reportFault = null; renderPanel(true);
  try {
    const { markdown } = await api.report({ ...request(state), ...motionRequest(state), devices, follow: first });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
    link.download = `${(focused()?.name ?? "motionsim").replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "motionsim"}-report.md`;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 4000);
  } catch (e) {
    reportFault = `The report could not be written: ${(e as Error).message}`;
  }
  savingMd = false; renderPanel(true);
  document.querySelector<HTMLElement>("[data-report-md]")?.focus();
}

/** The whole result as a document to print or save as a PDF: what went in, what came out,
 *  what it rests on and the equations behind it. Built when asked for, from what is on screen. */
async function printReport(): Promise<void> {
  const c = focused();
  const r = c?.result;
  if (!c || !r) return;
  // The motion belongs in the report; work it out if the user has not opened that tab.
  if (cycle === null) {
    try { cycle = await api.cycle({ ...request(state), device: c.id, ...motionRequest(state) }); } catch (e) { cycle = e instanceof Refused ? e : null; }
  }
  const k = state.conditions;
  const m = setup.motors[state.kind];
  const rows = (pairs: [string, string][]) => `<table>${pairs.map(([a, b]) => `<tr><th>${escape(a)}</th><td>${b}</td></tr>`).join("")}</table>`;
  const list = (items: string[]) => (items.length ? `<ul>${items.map((x) => `<li>${escape(sentence(x))}.</li>`).join("")}</ul>` : "<p>None.</p>");
  const device = setup.devices.find((d) => d.id === c.id);
  const load = state.mission ? `Mission profile ${escape(state.mission.name)}, ${state.mission.time.length} instants` : escape(presets?.list.find((p) => p.id === state.loadKind)?.label ?? "Your own load");
  const compared = comparing() ? `<h2>Compared</h2>${compareTable()}` : "";
  const motion = cycle && !(cycle instanceof Refused)
    ? `<h2>Through the motion</h2>${rows([["Load", load], ["Lasts", `${sig(cycle.summary.duration!)} s`], ["Mean loss", watts(cycle.summary.mean_loss!)], ["Hottest junction reached", degrees(cycle.summary.peak!)], ["Energy lost", `${sig(cycle.summary.loss_energy!)} J`], ["Peak motor current", `${sig(Math.max(...cycle.i_peak.map((v) => v ?? 0)))} A`]])}<h3>Starting</h3>${list(cycle.start.lines)}${lifeBlock(cycle)}<h3>Checks over the motion</h3>${list(cycle.checks.map((x) => `${x.topic}: ${x.message}`))}`
    : "";
  const page = `<article class="report"><header><h1>${escape(c.name)}: power-stage estimate</h1><p>${new Date().toISOString().slice(0, 10)} · MotionSim, an exploratory tool. Results are estimates from datasheet values, stated assumptions and simplified models. Verify by measurement before building anything.</p></header>
<h2>What was tested</h2>${rows([["Device", `${escape(c.name)}, ${escape(c.technology)}${device ? `, ${sig(device.v_max)} V, ${sig(device.i_nominal)} A. ${packaging(device)}` : ""}`], ["Devices in parallel", escape(String(k.parallel || 1))], ["Motor", `${escape(m.label)}: ${m.fields.map((f) => `${escape(f.label)} ${escape(String(state.motors[state.kind][f.key] ?? ""))} ${escape(f.unit)}`.trim()).join("; ")}`], ["Supply", `${sig(k.v_dc)} V, ${state.supply === "battery" ? "battery" : "power supply"}`], ["Design point", `${sig(k.rpm)} rpm, ${sig(k.torque)} N·m`], ["Switching", `${sig(k.f_khz)} kHz, ${escape(stage?.scheme ?? "")}`], ["Cooling", sentence(coolingWords())], ["Gate drive", escape(c.gate.lines.map(sentence).join(". "))]])}
<h2>Result at the design point</h2>${rows([["Verdict", { ok: "Passes every check", caution: "Passes, with cautions", undecided: "Undecided on this data", fail: "Does not pass" }[c.level] ?? c.level], ["Power-stage loss", watts(r.loss)], ["Conduction", `${watts(r.conduction)} (${percent(r.conduction / Math.max(r.loss, 1e-9), 0)})`], ["Switching", `${watts(r.switching)} (${percent(r.switching / Math.max(r.loss, 1e-9), 0)})`], ["Hottest junction", `${degrees(r.tj_peak)}${r.tj_range && Math.round(r.tj_range[0]) !== Math.round(r.tj_range[1]) ? `, ${Math.round(r.tj_range[0])} to ${Math.round(r.tj_range[1])} °C across the thermal assumptions` : ""}; rating ${degrees(r.tj_max)}`], ["DC-to-shaft efficiency", c.efficiency != null ? percent(c.efficiency) : "n/a"]])}
<h3>Checks</h3>${list(c.checks.map((x) => `${x.topic}: ${x.message}`))}
<h3>What it needs around it</h3>${list(c.needs)}
${compared}${motion}
<h2>What this rests on</h2><h3>Notes</h3>${list(r.notes)}<h3>Assumed</h3>${list(r.assumptions)}<h3>Not modelled</h3>${list(r.limits)}${r.warnings.length ? `<h3>Rating warnings</h3>${list(r.warnings)}` : ""}
<h2>The equations</h2>${equationsPage()}</article>`;
  let host = document.querySelector<HTMLElement>("#report");
  if (!host) { host = document.createElement("div"); host.id = "report"; document.body.append(host); }
  host.innerHTML = page;
  window.print();
}

/** Beside the totals: every loss and every temperature of the switch position that runs
 *  hottest, one device of it, and what the switching does to the link and the motor current.
 *  A row is left out when it is nothing in every column (a diode the part does not have). */
function chipRows(list: Series[], got: (Result | "refused" | null)[], line: (label: string, cells: string[], best?: number[], name?: string) => string): string {
  const at = got.map((g) => (g && g !== "refused" && g.positions.length ? g.positions.reduce((a, b) => (b.tj > a.tj ? b : a)) : null));
  const cells = (pick: (p: Position, r: Result, k: number) => string) => got.map((g, k) => (g === "refused" ? "cannot run" : g === null || !at[k] ? "…" : pick(at[k]!, g, k)));
  const some = (pick: (p: Position) => number) => at.some((p) => p !== null && pick(p) > 0);
  const share = (w: number, p: Position) => `${watts(w)} <span class="quiet">${percent(w / Math.max(p.total, 1e-9), 0)}</span>`;
  const both = (peak: number, mean: number) => `${degrees(peak)} <span class="sub">average ${degrees(mean)}, swing ${sig(Math.max(peak - mean, 0), 2)} °C a turn</span>`;
  const diode = some((p) => p.diode_conduction + p.diode_recovery);
  const link = list.map((x) => resultOf(x)?.link ?? null);
  const rows = [
    `<tr class="group"><th scope="rowgroup" colspan="${list.length + 1}">One device at the hottest switch position</th></tr>`,
    line("Loss in that device", cells((p) => watts(p.total))),
    line("Switch, conducting", cells((p) => share(p.conduction, p))),
    line("Switch, turning on", cells((p) => share(p.turn_on, p))),
    line("Switch, turning off", cells((p) => share(p.turn_off, p))),
    some((p) => p.dead_time) ? line("Dead time, through the body diode", cells((p) => share(p.dead_time, p))) : "",
    some((p) => p.recovery) ? line("Body-diode recovery", cells((p) => share(p.recovery, p))) : "",
    diode ? line("Diode, conducting", cells((p) => share(p.diode_conduction, p))) : "",
    diode ? line("Diode, recovery", cells((p) => share(p.diode_recovery, p))) : "",
    line("Switch junction, peak", cells((p) => both(p.tj_switch, p.tj_switch_mean))),
    diode ? line("Diode junction, peak", cells((p) => both(p.tj_diode, p.tj_diode_mean))) : "",
    line("Case", cells((_, r) => degrees(r.t_case))),
    (state.conditions.cooling === "held" || state.conditions.cooling === "heatsink") && got.some((g) => g && g !== "refused" && g.t_sink != null) ? line("Heatsink", cells((_, r) => (r.t_sink != null ? degrees(r.t_sink) : "n/a"))) : "",
    `<tr class="group"><th scope="rowgroup" colspan="${list.length + 1}">What the switching does around the stage</th></tr>`,
    line("DC-link capacitor current", got.map((g, k) => (g === "refused" ? "cannot run" : link[k]?.capacitor_rms != null ? `${sig(link[k]!.capacitor_rms!)} A rms` : resultOf(list[k]) ? "n/a" : "…"))),
    line("Motor current ripple", got.map((g, k) => (g === "refused" ? "cannot run" : link[k]?.ripple_pp != null ? `${sig(link[k]!.ripple_pp!)} A peak to peak` : resultOf(list[k]) ? "n/a" : "…"))),
  ];
  return rows.filter(Boolean).join("\n");
}

/** Thermal-cycling life, from the swings of the temperature trace. */
function lifeBlock(c: Cycle): string {
  const l = c.life;
  if (!l) return "";
  const big = (v: number) => (v >= 1e12 ? `${sig(v / 1e12, 2)} trillion` : v >= 1e9 ? `${sig(v / 1e9, 2)} billion` : v >= 1e6 ? `${sig(v / 1e6, 2)} million` : v >= 1e3 ? `${sig(v / 1e3, 2)} thousand` : sig(v, 2));
  const body = l.repeats === null
    ? `<li>The junction temperature swings by less than 1 °C through this motion: this thermal-cycling model counts the wear from a swing that small as negligible.</li>`
    : `<li>About <b>${big(l.repeats)}</b> repeats of this motion${l.hours !== null ? `, which back to back is about ${big(l.hours)} hours` : ""}.</li><li>${l.chip ? `The chip that wears out first is the ${escape(l.chip)}. ` : ""}${percent(l.swing_share, 0)} of its wear comes from ${l.within_turn ? `the swing of ${sig(l.swing, 2)} °C it goes through on every turn of the motor` : `one swing of ${sig(l.swing, 2)} °C`}, about ${Math.round(l.swing_mean)} °C. A smaller swing lasts far longer: halving it gives about thirty times the life.${l.within_turn ? " Turning faster, or a larger chip, makes that swing smaller." : ""}</li>`;
  // Shown, since it is what the swings on the chart above cost; named for what it is, a generic model.
  return `<h4>Life under thermal cycling <span class="quiet">a rough indicator</span></h4><ul class="plain small">${body}<li>A generic model for modules with aluminium bond wires (LESIT), applied to discrete parts too. A real part may last several times longer or shorter; use the maker's power-cycling curve where there is one.</li></ul>`;
}

/** How the drive gets this motor going. What can be chosen depends on the kind of motor. */
function startBlock(): string {
  const st = state.start;
  const kind = state.kind;
  if (kind === "induction") {
    return `<details class="more"><summary>${icon("bolt")}Starting<span class="quiet">the flux is built before torque</span></summary><div class="fields">${field("start.flux_time", "Flux build-up time", st.flux_time, "s", "Leave empty for three rotor time constants.")}</div></details>`;
  }
  if (!["pmsm", "bldc", "synrm"].includes(kind)) return "";
  const open = st.method === "open_loop";
  return `<details class="more"${st.method !== "sensor" ? " open" : ""}><summary>${icon("bolt")}Starting<span class="quiet">how the drive finds the rotor</span></summary><div class="fields"><div class="wide">${select("start.method", "The drive starts", st.method, [["sensor", "With a position sensor (encoder or Hall)"], ["open_loop", "Sensorless: aligns, then ramps up open loop"], ["injection", "Sensorless: finds the rotor by signal injection"]], "A sensorless drive that reads the back-EMF sees nothing at standstill, so it holds a set current until the motor turns fast enough.")}</div>
${open ? field("start.current", "Start current", st.current, "A rms", "Held through alignment and the ramp. Empty: the current at your design point.") + field("start.align_time", "Alignment time", st.align_time, "s", "Empty: 0.5 s.") + field("start.handover_rpm", "Handover speed", st.handover_rpm, "rpm", "Where normal control takes over. Empty: a tenth of the design speed.") : ""}</div></details>`;
}

/** A mission profile brought as a file takes the place of the load and the motion. */
function missionBlock(): string {
  const m = state.mission;
  if (m) {
    // A long log has more instants than a call takes arguments: the largest is found one by one.
    const most = (values: number[]) => values.reduce((a, b) => Math.max(a, Math.abs(b)), 0);
    const top = most(m.rpm);
    const peak = most(m.torque);
    return `<div class="read-result" role="status"><p>${icon("circle-check")}<b>${escape(m.name)}</b> is the motion: ${m.time.length} instants over ${sig(m.time[m.time.length - 1] - m.time[0])} s, up to ${sig(top)} rpm and ${sig(peak)} N·m at the motor.</p><p class="quiet">The load figures below are not used while a mission profile is set.</p><p><button type="button" class="ghost" data-drop-mission>${icon("x")}Take the profile out</button></p></div>${missionFault ? refusal(missionFault) : ""}`;
  }
  return `<details class="more"${missionFault ? " open" : ""}><summary>${icon("upload")}Bring a mission profile<span class="quiet">measured or planned speed and torque, as a CSV file</span></summary><p class="quiet">Three columns, one row an instant: time in seconds, motor speed in rpm, motor torque in N·m. A first row of headings is fine. It takes the place of the load and the motion below.</p><label class="ghost add-part"><input type="file" data-mission-file accept=".csv,text/csv,.txt" class="sr"/>${icon("upload")}Choose a CSV file</label>${missionFault ? refusal(missionFault) : ""}</details>`;
}

/** Read a mission profile: comma, semicolon or tab between columns; a heading row is skipped. */
async function addMission(file: File): Promise<void> {
  missionFault = null;
  const lines = (await file.text()).split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  // Where semicolons or tabs part the columns, a comma is a decimal point.
  const comma = !lines.some((line) => /[;\t]/.test(line));
  const rows = lines.map((line) => line.split(comma ? "," : /[;\t]/).map((cell) => Number(comma ? cell.trim() : cell.trim().replace(",", "."))));
  const data = rows.filter((r) => r.length >= 3 && r.slice(0, 3).every(Number.isFinite));
  const forward = data.every((r, k) => k === 0 || r[0] > data[k - 1][0]);
  if (data.length < 2 || !forward) {
    missionFault = new Refused(data.length < 2 ? "that file does not hold rows of time, speed and torque" : "the time column does not run forward",
      "give three columns of numbers, one row an instant, sorted by time", "mission");
  } else {
    if (!state.mission) state.loadTouchedBefore = state.loadTouched;
    state.mission = { name: file.name, time: data.map((r) => r[0]), rpm: data.map((r) => r[1]), torque: data.map((r) => r[2]) };
    state.loadTouched = true;
    cycle = null; cycles.clear();
  }
  save(state);
  renderPanel(true);
  schedule();
}

function loadPanel(): string {
  const l = state.load as Record<string, number>;
  const list = presets?.list ?? [];
  const chosen = list.find((p) => p.id === state.loadKind);
  const shown = chosen?.fields ?? ["gear_ratio", "gear_efficiency", "inertia", "motor_inertia", "friction_coulomb", "friction_viscous", "mass", "arm", "start_angle_deg"];
  const rest = Object.keys(LOAD_FIELDS).filter((k) => !shown.includes(k));
  const one = (k: string) => field(`load.${k}`, LOAD_FIELDS[k][0], l[k], LOAD_FIELDS[k][1], LOAD_FIELDS[k][2]);
  const kinds = list.length
    ? `<fieldset class="kinds loads"><legend>Kind of load</legend><div class="family">${list.map((p, k) => `<label class="kind${p.id === state.loadKind ? " is-on" : ""}"><input type="radio" name="load-kind" value="${p.id}" data-load ${p.id === state.loadKind ? "checked" : ""}/><span class="kind-name">${escape(p.label)}${k === 0 ? '<span class="tag">usual for this motor</span>' : ""}</span><span class="kind-about">${escape(p.about)}</span></label>`).join("")}</div></fieldset>`
    : "";
  return `<h2 tabindex="-1">What the motor moves</h2><p class="lead">Pick what the motor drives. It starts sized to your motor, so it runs as it is. These are the loads this kind of motor commonly drives; any other can be entered by its figures.</p>
${missionBlock()}${state.mission ? "" : kinds}
<div id="load-note">${!state.mission && (chosen || state.loadTouched) ? loadNote(chosen?.link ?? "") : ""}</div>
${fold("load-figures", "adjustments", "Change the load's figures", state.loadTouched ? "yours" : "sized to your motor: put in your own",
    `<div class="fields">${shown.map(one).join("")}</div><details class="more"><summary>${icon("adjustments")}Every load figure<span class="quiet">the ones this kind of load does not use</span></summary><div class="fields">${rest.map(one).join("")}</div></details>`,
    Object.keys(LOAD_FIELDS))}
<h3>The motion</h3>
<div id="motion-preview"></div>
<details class="more" data-fold="motion"${openFolds.has("motion") || blocked?.field === "motion" ? " open" : ""}><summary>${icon("adjustments")}Change the motion<span class="quiet">${state.segments.length} stretches, ${sig(state.segments.reduce((n, x) => n + Number(x.duration || 0), 0))} s: load speed in straight lines between the values you give</span></summary>
<table class="segments"><thead><tr><th scope="col">Lasts</th><th scope="col">From</th><th scope="col">To</th><th scope="col"><span class="sr">Remove</span></th></tr></thead><tbody>${state.segments.map((s, k) => `<tr><td><div class="control"><input aria-label="Stretch ${k + 1} duration in seconds" data-bind="segments.${k}.duration" inputmode="decimal" value="${escape(String(s.duration))}"/><span class="unit">s</span></div></td><td><div class="control"><input aria-label="Stretch ${k + 1} starting speed" data-bind="segments.${k}.speed_start" inputmode="decimal" value="${s.speed_start}"/><span class="unit">rpm</span></div></td><td><div class="control"><input aria-label="Stretch ${k + 1} ending speed" data-bind="segments.${k}.speed_end" inputmode="decimal" value="${s.speed_end}"/><span class="unit">rpm</span></div></td><td><button type="button" class="icon-button" data-remove="${k}" aria-label="Remove stretch ${k + 1}" ${state.segments.length < 2 ? "disabled" : ""}>${icon("trash")}</button></td></tr>`).join("")}</tbody></table>
<button type="button" class="ghost" data-add>${icon("plus")}Add a stretch</button></details>
${startBlock()}
<details class="more"${state.sink.rth || state.sink.c_link_uf ? " open" : ""}><summary>${icon("temperature")}Heatsink and DC link<span class="quiet">optional</span></summary><div class="fields">
${state.conditions.cooling === "held" ? field("sink.rth", "Heatsink to air", state.sink.rth, "K/W", "With its heat capacity, the heatsink warms up during the motion.") : ""}${state.conditions.cooling === "none" || state.conditions.cooling === "board" ? "" : field("sink.capacity", "Heatsink heat capacity", state.sink.capacity, "J/K", state.conditions.cooling === "heatsink" ? "About 900 for each kilogram of aluminium. Given, the heatsink is followed as it warms from the air's temperature. Empty, it is taken as already warm." : "About 900 for each kilogram of aluminium.")}
${field("sink.precharge", "Precharge resistance", state.sink.precharge, "Ω", "What limits the current when the link is first charged.")}${state.conditions.cooling === "held" ? field("sink.t_ambient", "Air temperature", state.sink.t_ambient, "°C") : ""}${field("sink.c_link_uf", "DC-link capacitance", state.sink.c_link_uf, "µF", "Braking energy charges it when the supply cannot take it back.")}
${field("sink.repeats", "Repeat the motion", state.sink.repeats, "times")}</div></details>${nextButton(LOAD)}`;
}

const READ_NAMES: Record<string, string> = {
  vce_sat: "On-state voltage", vf: "Diode forward voltage", e_on: "Turn-on energy", e_off: "Turn-off energy",
  e_rr: "Diode recovery energy", rth_jc_switch: "Thermal resistance, switch", rth_jc_diode: "Thermal resistance, diode",
  v_rated: "Voltage rating", i_rated: "Current rating", tj_max: "Highest junction temperature",
  rds_on: "On-resistance", v_sd: "Reverse (body-diode) voltage", v_th: "Gate threshold", q_gs: "Gate-source charge",
  q_gd: "Gate-drain charge", q_g_th: "Gate charge at threshold", q_oss: "Output charge", q_rr: "Recovery charge",
  c_oss: "Output capacitance", g_fs: "Transconductance", v_plateau: "Gate plateau voltage",
  t_d_off: "Turn-off delay", t_f: "Fall time", vce_curve: "On-state voltage curve", vf_curve: "Diode forward curve",
  e_on_rg_curve: "Turn-on energy against gate resistance", e_off_rg_curve: "Turn-off energy against gate resistance",
  rg_on_test: "Gate resistor of the switching test, turn-on", rg_off_test: "Gate resistor of the switching test, turn-off",
  e_on_curve: "Turn-on energy curve", e_off_curve: "Turn-off energy curve", e_rr_curve: "Recovery energy curve",
  zth_jc_switch: "Thermal impedance, switch", zth_jc_diode: "Thermal impedance, diode",
  gate_charge_curve: "Gate-charge curve", c_oss_curve: "Output-capacitance curve", rds_norm_curve: "On-resistance against temperature",
};
const readName = (what: string) => READ_NAMES[what] ?? what.replace(/_/g, " ");

/** A device model laid open: its tables as charts, and each thing read from the datasheet
 *  with its page, so the user can hold it against the datasheet. */
function reviewBlock(): string {
  if (!review) return "";
  const name = setup.devices.find((d) => d.id === review!.id)?.name ?? "";
  const head = `<div class="review-head"><h3>What the model of ${escape(name)} rests on</h3><button type="button" class="ghost" data-review="${escape(review.id)}">${icon("x")}Close</button></div>`;
  if (review.failed) return `<section class="review" id="review">${head}<p class="quiet">${escape(review.failed)}</p></section>`;
  const data = review.data;
  if (!data) return `<section class="review" id="review">${head}<p class="waiting">Opening the model</p></section>`;
  const chart = (title: string, t: ModelTable | null) => {
    if (!t || !t.curves?.length) return "";
    const basis = t.basis === "point" ? "From table values; the line between them is assumed." : "From the datasheet's curve.";
    return `<div class="read-item">${tableChart(title, t)}<p class="small quiet">${basis}${t.page ? ` Page ${t.page}.` : ""}${t.assumption ? ` ${escape(sentence(t.assumption))}.` : ""}</p></div>`;
  };
  const charts = chart("on-state voltage", data.conduction) + chart("diode voltage", data.diode) + chart("reverse voltage", data.reverse)
    + chart("turn-on energy", data.e_on) + chart("turn-off energy", data.e_off) + chart("recovery energy", data.e_rr);
  const r = data.reading;
  if (!r) return `<section class="review" id="review">${head}<p class="quiet">This part came as a device file, so there is no datasheet reading to show. These are the tables in the file.</p><div class="read-grid">${charts}</div></section>`;
  const aside = [...r.values.filter((v) => v.flags.length).map((v) => ({ what: readName(v.what), page: v.page, why: v.flags.join("; ") })),
    ...r.figures.filter((f) => f.flags.length).map((f) => ({ what: `${readName(f.what)}${f.tj !== null ? ` at ${sig(f.tj)} °C` : ""} (${f.label})`, page: f.page, why: f.flags.join("; ") }))];
  const used = r.figures.filter((f) => !f.flags.length);
  const rows = r.values.map((v) => `<tr${v.flags.length ? ' class="aside-row"' : ""}><td>${escape(readName(v.what))}</td><td>${escape(v.printed)}</td><td>${escape(v.at)}</td><td class="num">${v.page}</td></tr>`).join("");
  return `<section class="review" id="review">${head}
<p class="quiet">Read from ${escape(r.document)}, ${r.pages} pages. Hold these against the datasheet: the page of each is given.${r.from_images ? ` ${r.from_images} pages are pictures with no text; their values were read from the picture.` : ""}</p>
<div class="read-grid">${charts}</div>
${aside.length ? `<h4>Set aside</h4><p class="quiet small">A check did not pass, so the model does not use these.</p><ul class="plain small">${aside.map((a) => `<li>${escape(a.what)}, page ${a.page}: ${escape(a.why)}</li>`).join("")}</ul>` : ""}
${used.length ? `<h4>Curves used</h4><ul class="plain small">${used.map((f) => `<li>${escape(readName(f.what))}${f.tj !== null ? ` at ${sig(f.tj)} °C` : ""}, page ${f.page}${f.within !== null ? `: within ${percent(f.within, 0)} of the table value` : ""}${f.notes.length ? `. ${escape(sentence(f.notes[0]))}` : ""}${f.method === "picture" ? ". Traced from a picture" : ""}</li>`).join("")}</ul>` : ""}
<h4>Table values read</h4>
<div class="scroll-x"><table class="data"><thead><tr><th scope="col">Value</th><th scope="col">As printed</th><th scope="col">At</th><th scope="col" class="num">Page</th></tr></thead><tbody>${rows}</tbody></table></div>
</section>`;
}

async function openReview(id: string): Promise<void> {
  if (review?.id === id) { review = null; renderPanel(true); return; }
  review = { id };
  renderPanel(true);
  try {
    review = { id, data: await api.reading(id) };
  } catch (e) {
    review = { id, failed: `The model could not be opened: ${(e as Error).message}` };
  }
  renderPanel(true);
  document.querySelector("#review")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

/** A transistor typed in from its datasheet: the figures of its tables, in their own units. */
function typedForm(): string {
  const form = setup.typed;
  const t = state.typed;
  const wrong = typedRefused?.field ?? "";
  const one = (key: string, label: string, unit: string, required: boolean, help: string, wide = false) => {
    const id = `t-${key}`;
    const bad = wrong === key && typedRefused ? `<p class="help said-wrong" id="${id}-w" role="alert">${escape(sentence(typedRefused.reason))}. ${escape(sentence(typedRefused.fix))}.</p>` : "";
    const described = [bad ? `${id}-w` : "", help ? `${id}-h` : ""].filter(Boolean).join(" ");
    return `<div class="field${wrong === key ? " is-wrong" : ""}${wide ? " wide" : ""}"><label for="${id}">${escape(label)}${required ? "" : ' <span class="quiet">optional</span>'}</label><div class="control"><input id="${id}" data-typed="${key}" ${unit ? 'inputmode="decimal"' : ""} autocomplete="off" value="${escape(t[key] ?? "")}" ${bad ? 'aria-invalid="true"' : ""} ${described ? `aria-describedby="${described}"` : ""}/>${unit ? `<span class="unit">${escape(unit)}</span>` : ""}</div>${bad}${help ? `<p class="help" id="${id}-h">${escape(help)}</p>` : ""}</div>`;
  };
  const pick = (key: string, label: string, options: string[], last: string, help: string) =>
    `<div class="field"><label for="t-${key}">${escape(label)}</label><div class="control"><select id="t-${key}" data-typed="${key}">${[...options, ...(last ? [""] : [])].map((o) => `<option value="${escape(o)}"${(t[key] ?? (last ? "" : options[0])) === o ? " selected" : ""}>${escape(o || last)}</option>`).join("")}</select></div><p class="help">${escape(help)}</p></div>`;
  return `<details class="more typed"${typedOpen || Object.values(t).some((v) => String(v ?? "").trim() !== "") ? " open" : ""}><summary>${icon("adjustments")}Type in the figures from its datasheet<span class="quiet">MOSFET, SiC or GaN: nine figures, no file, no key</span></summary>
<p class="quiet">Copy each figure as the datasheet prints it, typical values where it gives them.</p>
<div class="fields">${one("part_number", "Part number", "", true, "")}${one("vendor", "Maker", "", false, "")}
${pick("technology", "Kind of transistor", form.technologies, "", "Silicon unless the datasheet says otherwise.")}${pick("outline", "Package", form.outlines, "another package", "Sets what lies between the case and a heatsink.")}
${form.fields.filter((f) => f.required).map((f) => one(f.key, f.label, f.unit, f.required, f.help)).join("")}</div>
<details class="more" data-fold="typed-more"${openFolds.has("typed-more") || form.fields.some((f) => !f.required && (f.key === wrong || String(t[f.key] ?? "").trim() !== "")) ? " open" : ""}><summary>${icon("adjustments")}More figures<span class="quiet">optional: hot on-resistance, output and recovery charge, body diode. Each one sharpens the result</span></summary><div class="fields">${form.fields.filter((f) => !f.required).map((f) => one(f.key, f.label, f.unit, f.required, f.help)).join("")}</div></details>
${typedRefused && !form.fields.some((f) => f.key === wrong) && wrong !== "part_number" ? refusal(typedRefused) : ""}
<p><button type="button" class="ghost" data-add-typed ${typedBusy ? "disabled" : ""}>${icon("plus")}${typedBusy ? "Adding" : "Add this part"}</button></p></details>`;
}

async function addTyped(): Promise<void> {
  typedBusy = true; typedRefused = null; typedOpen = true;
  renderPanel(true);
  try {
    const form = setup.typed;
    const figures = { technology: form.technologies[0], ...state.typed };
    const answer = await api.addTyped(figures);
    reading = { name: answer.name, outcome: { device: answer.device, read: { values: 0, curves: 0, flagged: [] } }, file: answer.text };
    setup = await api.setup();
    const made = new Set(setup.devices.filter((d) => d.example).map((d) => d.id));
    state.devices = [...new Set([...state.devices.filter((id) => !made.has(id)), answer.device.id])].slice(-MOST);
    state.added = [...new Set([...state.added.filter((id) => !made.has(id)), answer.device.id])];
    state.typed = {};
    typedOpen = false;
    void suggestFor();
    schedule();
  } catch (e) {
    typedRefused = e instanceof Refused ? e : new Refused((e as Error).message, "check the figures and try again", "");
  }
  typedBusy = false;
  renderPanel(true);
  renderRail(); renderStage();
  const to = typedRefused
    ? document.querySelector<HTMLElement>(typedRefused.field ? `[data-typed="${typedRefused.field}"]` : "details.typed .refusal")
    : document.querySelector<HTMLElement>(".read-result");
  to?.scrollIntoView({ block: "center" });
  to?.focus();
}

/** The parts the user has brought. The made-up one appears only if they asked for it. */
function ownDevices() {
  // Whatever else sits in the folder the page is served from, only what this user added
  // here is shown: the tool does not put parts in front of anyone.
  return setup.devices.filter((d) => state.added.includes(d.id));
}

function devicesPanel(): string {
  const local = api.mode() === "browser";
  const canRead = !local && setup.can_read;
  const parts = ownDevices();
  const rows = parts
    .map((d) => {
      const on = state.devices.includes(d.id);
      return `<li class="device${on ? " is-on" : ""}"><label><input type="checkbox" data-device="${escape(d.id)}" ${on ? "checked" : ""}/><span class="device-name">${escape(d.name)}${d.example ? ' <span class="tag">made-up part</span>' : ""}</span><span class="device-facts">${escape(d.technology)} · ${sig(d.v_max)} V · ${sig(d.i_nominal)} A</span><span class="device-facts kind-of-part">${packaging(d)}</span><span class="device-facts">Switching loss: ${escape(d.switching)}. Model built from ${escape(d.support)}.</span></label><button type="button" class="link review-link" data-forget-device="${escape(d.id)}" aria-label="Take ${escape(d.name)} off this page">Take off this page</button><button type="button" class="link review-link" data-review="${escape(d.id)}" aria-label="${review?.id === d.id ? "Hide" : "Check"} what was read for ${escape(d.name)}" aria-expanded="${review?.id === d.id}">${review?.id === d.id ? "Hide what was read" : "Check what was read"}</button></li>`;
    })
    .join("");
  const accepts = canRead ? "its datasheet (PDF), a device file (.yaml)" : "a device file (.device.yaml)";
  const drop = reading && !reading.outcome && !reading.refused
    ? waiting(/\.pdf$/i.test(reading.name) ? `Reading ${reading.name}. This takes a minute or two.` : `Adding ${reading.name}.`)
    : `<label class="drop big" id="drop"><input type="file" id="part-file" accept="${canRead ? "application/pdf," : ""}.yaml,.yml,.json" class="sr"/>${icon("upload")}<span><b>Add your device</b> Drop ${accepts}, or your own double-pulse measurements (.json). Or press to choose a file.</span>${canRead ? "" : `<span class="quiet">${local ? "A datasheet PDF is read on your own machine, not on this page: how is below." : "A datasheet PDF is read here too, once your own API key is set: how is below."}</span>`}${canRead ? '<span class="quiet">Reading a datasheet is a paid language-model call from this machine, with your key. It takes a minute or two.</span>' : ""}</label>`;
  let how: string;
  if (canRead) {
    how = "";
  } else if (local) {
    how = `<details class="more"><summary>${icon("info-circle")}How to get a device file from a datasheet</summary><p class="quiet">Reading a datasheet needs a language-model key, so it is done on your own machine, not on this page. With the tool installed:</p><p><code>motionsim extract part.pdf -o part.observations.yaml</code><br/><code>motionsim build part.observations.yaml -o part.device.yaml</code></p><p class="quiet">Then drop <code>part.device.yaml</code> above. It stays in this browser and is sent nowhere. Or run <code>motionsim serve</code> to drop the PDF straight onto the page.</p></details><p class="quiet small local-note">The engine runs in this browser. Its Python runtime is fetched once from cdn.jsdelivr.net, and nothing you enter is sent anywhere. To work offline, install it as the README says.</p>`;
  } else {
    how = `<details class="more"><summary>${icon("info-circle")}To read a datasheet PDF here<span class="quiet">it needs your own key, on your own machine</span></summary><p class="quiet">Reading a datasheet is done by a language model, and that is a paid call. It is made from this machine with your own key, straight to its maker, or to a model you run yourself: this tool has no server of its own, keeps no key and sees none of your files. That is why it runs on your machine.</p><p class="quiet">Set the key in the terminal, then start the page again:</p><p><code>export ANTHROPIC_API_KEY=your-key</code><br/><code>motionsim serve</code></p><p class="quiet">OpenAI, Gemini, Grok or a model of your own work too: the README says what to set.</p><p class="quiet">Without a key everything else works: device files, your own measurements, and the made-up part.</p></details>`;
  }
  const outcome = reading?.refused
    ? refusal(reading.refused)
    : reading?.outcome
      ? `<div class="read-result" role="status" tabindex="-1"><p>${icon("circle-check")}<b>${escape(reading.outcome.device.name)}</b> ${reading.outcome.read.values ? `read: ${reading.outcome.read.values} table values and ${reading.outcome.read.curves} curves.` : "added."}${reading.file ? ` <a class="link" download="${escape(reading.name)}" href="data:text/yaml;charset=utf-8,${encodeURIComponent(reading.file)}">Save it as a device file</a>, to bring it back another day.` : ""}</p>${reading.outcome.read.from_images ? `<p class="quiet">${reading.outcome.read.from_images} pages of this datasheet are pictures with no text. Their values were read from the picture, which is less sure than reading printed text: check the ratings against the datasheet.</p>` : ""}${reading.outcome.read.flagged.length ? `<p class="quiet">Set aside, because a check did not pass:</p><ul class="plain small">${reading.outcome.read.flagged.map((f) => `<li>${escape(f.what)}, page ${f.page}: ${escape(f.why)}</li>`).join("")}</ul>` : ""}</div>`
      : "";
  const list = parts.length
    ? `<h3>Your ${parts.length > 1 ? "parts" : "part"}</h3><p class="quiet">${parts.length > 1 ? "Tick the ones to test. More than one are compared under the same conditions." : "Ticked: this is the part under test."}</p><ul class="devices">${rows}</ul>`
    : "";
  const again = state.reached > DEVICE || state.added.length
    ? `<p class="aside"><button type="button" class="link" data-start-over>Start over: clear everything entered on this page</button></p>`
    : "";
  const files = `<p class="aside setup-files"><button type="button" class="link" data-save-setup ${state.reached > DEVICE ? "" : "disabled"}>Save this setup to a file</button><label class="link-label"><input type="file" data-setup-file accept=".json,application/json" class="sr"/>Open a setup file</label></p>`;
  const spare = setup.devices.filter((d) => d.example && !state.added.includes(d.id));
  const example = spare.length
    ? `<p class="aside examples">No part to hand? Try the tool with a made-up one: ${spare.map((d) => `<button type="button" class="link" data-example="${escape(d.id)}">a ${sig(d.v_max)} V ${escape(d.technology.replace(/^Si /, ""))}</button>`).join(" or ")}.</p>`
    : "";
  // Where a datasheet cannot be read on this page, a newcomer has no file to drop: what they
  // can do at once comes first, and the file last.
  if (!canRead && !parts.length && !reading && !(starting && state.added.length)) {
    const tryIt = spare.length
      ? `<section class="path"><h3>See what it does</h3><p class="quiet">A made-up part, to walk through every step. Not a real device.</p><p class="path-go">${spare.map((d) => `<button type="button" class="ghost" data-example="${escape(d.id)}">${icon("player-play")}A ${sig(d.v_max)} V ${escape(d.technology.replace(/^Si /, ""))}</button>`).join("")}</p></section>`
      : "";
    return `<h2 tabindex="-1">The device you want to test</h2><p class="lead">The power transistor or module you have in mind. Three ways to bring one.</p>
${tryIt}<section class="path"><h3>Your own part, typed in</h3>${typedForm()}</section><section class="path"><h3>Your own part, from a file</h3>${drop}${how}</section>${files}${again}${nextButton(DEVICE)}`;
  }
  return `<h2 tabindex="-1">The device you want to test</h2><p class="lead">The power transistor or module you have in mind: ${canRead ? "drop its datasheet, " : ""}type in its figures, or drop a device file.</p>
${drop}${outcome}${typedForm()}${how}${list}${reviewBlock()}${example}${files}${again}${nextButton(DEVICE)}`;
}

/* ---------- results ---------- */

/** Why there is nothing to show yet on a results tab: no device, a design that cannot run
 *  (with the reason and the way back to the step at fault), or an answer on its way. */
function notReady(): string {
  if (!state.devices.length) return `<p class="empty">${icon("cpu")}No device is chosen. Go back to step 1 and tick the part you want to test.</p>`;
  if (blocked) {
    const at = blockedStep() < 0 ? SUPPLY : blockedStep();
    return `${refusal(blocked)}<p><button type="button" class="ghost" data-step="${at}">${icon("arrow-left")}Go to ${escape(STEPS[at].name.toLowerCase())} to change it</button></p>`;
  }
  if (fault) return `<div class="refusal" role="alert">${icon("alert-triangle")}<div><p><b>Something went wrong on our side.</b> ${escape(fault)}</p></div></div>`;
  const c = focused();
  if (proposal && c && !c.result) return `<div class="refusal" role="alert">${icon("ban")}<div><p><b>${escape(c.name)} cannot be worked out here.</b> ${escape(sentence(c.problem ?? "it could not be run at this design point"))}.</p>${c.fix ? `<p class="fix">${escape(sentence(c.fix))}.</p>` : ""}</div></div>`;
  return waiting("Working out the losses.");
}

function proposalTab(): string {
  if (!state.devices.length) return `<p class="empty">${icon("cpu")}No device is chosen. Go back to step 1 and tick the part you want to test.</p>`;
  if (!proposal) return notReady();
  const rows = proposal.candidates
    .map((c, k) => {
      const r = c.result;
      return `<details class="candidate ${c.level}"${c.id === focused()?.id ? " open" : ""}><summary data-focus="${escape(c.id)}"><span class="rank">${k + 1}</span><span class="cand-name">${escape(c.name)}<span class="quiet">${escape(c.technology)}</span></span><span class="num loss"><span class="cell-label">Loss </span>${r ? watts(r.loss) : "–"}</span><span class="num junction"><span class="cell-label">Junction </span>${r ? degrees(r.tj_peak) : "–"}</span><span class="num still"><span class="cell-label">Standstill </span>${c.stall_tj != null ? degrees(c.stall_tj) : "–"}</span>${verdict(c.level)}</summary>
<div class="cand-body">${c.problem ? `<p class="fix"><b>${escape(sentence(c.problem))}.</b> ${escape(sentence(c.fix))}${c.fix ? "." : ""}</p>` : ""}${checksBlock(c)}${gateBlock(c)}${c.needs.length ? `<details class="more" data-fold="needs-${escape(c.id)}"${openFolds.has(`needs-${c.id}`) ? " open" : ""}><summary>${icon("adjustments")}What it needs around it<span class="quiet">${escape(c.needs[0] ?? "")}</span></summary><ul class="plain">${c.needs.map((n) => `<li>${escape(sentence(n))}</li>`).join("")}</ul></details>` : ""}</div></details>`;
    })
    .join("");
  const single = proposal.candidates.length === 1;
  const only = proposal.candidates[0];
  const headline = single
    ? only.level === "ok" ? `${only.name} passes every check at this design point.`
      : only.level === "caution" ? `${only.name} can do this, with cautions to read below.`
      : only.level === "undecided" ? `${only.name} is not decided by this data: what the datasheet leaves out could change the answer. The check below says what would settle it.`
      : `${only.name} does not pass at this design point: see the checks below.`
    : null;
  // The order is by loss among the parts that pass, and a caution does not move a part down it.
  const order = single ? "" : '<p class="quiet small">In order of modelled loss among the parts that pass. A caution does not change the order: read it before choosing.</p>';
  const lead = headline ? `<p>${escape(headline)}</p>` : proposal.explain.map((l) => `<p>${escape(l)}</p>`).join("") + order;
  return `<div class="explain">${lead}</div>
<div class="cand-head" aria-hidden="true"><span></span><span>Device</span><span class="num">Loss</span><span class="num">Junction</span><span class="num" title="The hottest junction holding the same torque at standstill">Standstill</span><span>Verdict</span></div>${rows}${adviceBlock()}`;
}

function lossesTab(): string {
  const c = focused();
  const r = c?.result;
  if (!r && (blocked || fault || !proposal)) return notReady();
  if (!r) return `<p class="empty">${icon("flame")}${c?.problem ? escape(sentence(c.problem)) + ". " + escape(sentence(c.fix)) + "." : "Choose a device to see where its loss goes."}</p>`;
  const hasDiode = r.hottest.diode_conduction + r.hottest.diode_recovery > 0;
  const positions = r.positions.length > 1
    ? `<h4>By position</h4><table class="data"><thead><tr><th scope="col">Position</th><th scope="col" class="num">Loss</th><th scope="col" class="num">Junction</th></tr></thead><tbody>${r.positions.map((p) => `<tr><td>${p.count} × ${escape(p.name)}</td><td class="num">${sig(p.total)} W</td><td class="num">${degrees(p.tj)}</td></tr>`).join("")}</tbody></table>`
    : "";
  const support = { interpolated: "Inside the datasheet's own curves.", extrapolated: "Partly outside the datasheet's data.", assumed: "Partly on table points with an assumed shape between them." }[r.validity] ?? r.validity;
  const list = (title: string, items: string[]) => (items.length ? `<details class="more counted"><summary>${title}<span class="count">${items.length}</span></summary><ul class="plain small">${items.map((n) => `<li>${escape(sentence(n))}</li>`).join("")}</ul></details>` : "");
  const compared = series();
  const side = compared.length < 2 ? ""
    : state.compare !== "loads"
      ? `<h3>${{ devices: "Loss of each device", motors: "Loss with each motor", sweep: "Loss at each value" }[state.compare as "devices"]}</h3>${compareBars(compared.map((x) => ({ name: x.name, parts: [{ value: resultOf(x)?.result?.conduction ?? 0, tone: "cond" }, { value: resultOf(x)?.result?.switching ?? 0, tone: "sw" }] })), "W")}<ul class="legend inline"><li><span class="key cond"></span>conduction</li><li><span class="key sw"></span>switching</li></ul>`
      : `<h3>Mean loss under each load</h3>${compareBars(compared.map((x) => { const g = cycles.get(x.key); return { name: x.name, parts: [{ value: g && !(g instanceof Refused) ? g.summary.mean_loss ?? 0 : 0, tone: "cond" }] }; }), "W")}`;
  return `${side}<h3>${escape(c!.name)}: one switch position</h3><p class="quiet">The hottest position. Conduction is the price of carrying current; switching is paid ${Math.round(state.conditions.f_khz * 1000).toLocaleString("en-US")} times a second.</p>
${lossBar(r.hottest, hasDiode)}${positions}
<h4>What this rests on</h4><p class="fact ${r.validity === "interpolated" ? "" : "warn"}">${icon(r.validity === "interpolated" ? "circle-check" : "alert-triangle")}<span>${support}</span></p>
${list("Where the data runs out", r.notes)}${list("Thermal values the tool had to compute", r.assumptions)}${list("Left out of the model", r.limits)}${list("Rating warnings", r.warnings)}`;
}

function motionTab(): string {
  if (!focused()?.result) return notReady();
  if (loading.has("cycle") || cycle === null) return waiting("Following the motion through time.");
  if (cycle instanceof Refused) return `${refusal(cycle)}<p><button type="button" class="ghost" data-step="${LOAD}">${icon("arrow-left")}Go to ${escape(STEPS[LOAD].name.toLowerCase())} to change it</button></p>`;
  const s = cycle.summary;
  const saved = (s.forever ?? 0) - (s.peak ?? 0);
  const list = series();
  const drawn = list.map((x) => ({ x, g: cycles.get(x.key) })).filter((p): p is { x: Series; g: Cycle } => !!p.g && !(p.g instanceof Refused));
  const side = list.length < 2 ? ""
    : `<h3>${{ devices: "Each device through the motion", loads: "Each load's motion", motors: "Each motor through the motion", sweep: "The motion at each value" }[state.compare]}</h3>${drawn.length ? overlayChart(drawn.map((p) => ({ name: p.x.name, time: p.g.time, tj: p.g.tj })), Math.max(...drawn.map((p) => p.g.summary.tj_max ?? 150))) + legendOf(drawn.map((p) => p.x.name)) + (list.some((x) => !cycles.has(x.key)) ? waiting("Following the others through the motion.") : "") : waiting("Following each one through its motion.")}${list.filter((x) => cycles.get(x.key) instanceof Refused).map((x) => `<p class="fact warn">${icon("alert-triangle")}<span>${escape(x.name)}: ${escape(sentence((cycles.get(x.key) as Refused).reason))}.</span></p>`).join("")}`;
  return `${side}<h3>${escape(focused()!.name)} through the motion</h3>
<p class="quiet">The hottest junction reaches <b>${degrees(s.peak!)}</b>.${saved > 0.5 ? ` Solving each instant as if it lasted forever would say ${degrees(s.forever!)}: short peaks do not have time to heat the chip fully.` : ""}</p>
${timeChart(cycle)}
<dl class="facts"><div><dt>Lasts</dt><dd>${sig(s.duration!)} s</dd></div><div><dt>Mean loss</dt><dd>${watts(s.mean_loss!)}</dd></div><div><dt>Torque, rms</dt><dd>${sig(s.rms_torque!)} N·m</dd></div><div><dt>Energy to the shaft</dt><dd>${fig(s.shaft_energy!)} J</dd></div><div><dt>Energy lost</dt><dd>${fig(s.loss_energy!)} J</dd></div><div><dt>Returned by braking</dt><dd>${fig(s.returned ?? 0)} J</dd></div></dl>
${cycle.start.applies !== "none" || state.kind === "stepper" ? `<h4>Starting</h4><ul class="plain small">${cycle.start.lines.map((l) => `<li>${escape(sentence(l))}</li>`).join("")}</ul>` : ""}
${cycle.inrush ? `<h4>Charging the DC link at power-up</h4><ul class="plain small"><li>The link stores ${fig(cycle.inrush.energy)} J, and whatever limits the charging current absorbs as much again.</li><li>${cycle.inrush.peak !== null ? `Through your precharge resistance the current peaks at ${sig(cycle.inrush.peak)} A and the link is charged in about ${eng(cycle.inrush.time!, "s")}.` : "With no precharge resistance given, only the supply and the wiring limit the current. Give one in step 4 to see the peak."}</li></ul>` : ""}
${lifeBlock(cycle)}
<h4>Checks over the whole motion</h4>${checkList(cycle.checks)}
<p class="quiet after-facts">Change the load or the motion in step 4 and this redraws.</p>`;
}

/** The map's axes in the load's own terms: through the gearbox, and for a vehicle as road
 *  speed and the force at the wheel. A change of units only; the map itself is the motor's. */
function loadAxes(): MapAxes | null {
  const l = state.load;
  const n = l.gear_ratio || 1;
  const eta = l.gear_efficiency || 1;
  if (l.v_mass > 0 && l.wheel_radius > 0) {
    return { speed: ((2 * Math.PI) / 60 / n) * l.wheel_radius * 3.6, torque: (n * eta) / l.wheel_radius,
      speedLabel: "road speed, km/h", torqueLabel: "force at the wheel, N", speedUnit: "km/h", torqueUnit: "N" };
  }
  if (n === 1 && eta === 1) return null; // direct drive: the load's units are the motor's
  return { speed: 1 / n, torque: n * eta, speedLabel: "load speed, rpm", torqueLabel: "torque at the load, N·m", speedUnit: "rpm", torqueUnit: "N·m" };
}

function mapTab(): string {
  if (!focused()?.result) return notReady();
  const c = state.conditions;
  const controls = `<div class="fields">${field("map.rpm_max", "Top motor speed", state.map.rpm_max || String(Math.round(c.rpm * 2)), "rpm")}${field("map.torque_max", "Top motor torque", state.map.torque_max || sig(c.torque * 2), "N·m")}</div>
<div class="segmented" role="group" aria-label="What the map shows">${(["loss", "tj", "efficiency"] as const).map((m) => `<button type="button" data-metric="${m}" aria-pressed="${state.metric === m}" class="${state.metric === m ? "is-on" : ""}">${{ loss: "Loss", tj: "Junction temperature", efficiency: "Efficiency" }[m]}</button>`).join("")}</div>`;
  const load = loadAxes();
  const atLoad = !!load && state.mapAt !== "motor";
  const side = load
    ? `<div class="segmented" role="group" aria-label="Where the map's axes are measured">${([["load", load.speedUnit === "km/h" ? "On the road" : "At the load"], ["motor", "At the motor"]] as const).map(([v, name]) => `<button type="button" data-map-at="${v}" aria-pressed="${atLoad === (v === "load")}" class="${atLoad === (v === "load") ? "is-on" : ""}">${name}</button>`).join("")}</div>`
    : "";
  let body: string;
  if (loading.has("map") || grid === null) body = waiting("Solving every point of the map. A few seconds.");
  else if (grid instanceof Refused) body = refusal(grid);
  else body = heatMap(grid, state.metric, atLoad ? load! : AT_MOTOR);
  const list = series();
  if (state.compare === "devices" && list.length > 1) {
    // Set side by side, the maps share one scale: the eye compares colours, and the same
    // colour has to mean the same loss in each. Until every map is solved the scale would
    // move as each arrives, so each is drawn on its own with its own key until then.
    const solved = list.map((x) => grids.get(x.key)).filter((g): g is MapGrid => g !== undefined && !(g instanceof Refused));
    const all = solved.length === list.filter((x) => !(grids.get(x.key) instanceof Refused)).length;
    const range = all && solved.length > 1 ? sharedRange(solved, state.metric) ?? undefined : undefined;
    body = `<div class="maps">${list.map((x) => { const g = grids.get(x.key); return `<figure class="map-one"><figcaption>${escape(x.name)}</figcaption>${g === undefined ? waiting("Solving this map.") : g instanceof Refused ? refusal(g) : heatMap(g, state.metric, atLoad ? load! : AT_MOTOR, true, range)}</figure>`; }).join("")}</div>${range ? `<div class="shared-scale">${mapScale(range.lo, range.hi, state.metric)}<p class="quiet small">One scale for every map: the same colour is the same ${state.metric === "loss" ? "loss" : state.metric === "tj" ? "temperature" : "efficiency"} in each.</p></div>` : ""}<p class="quiet small">Across each map: ${(atLoad ? load! : AT_MOTOR).speedLabel}. Up: ${(atLoad ? load! : AT_MOTOR).torqueLabel}.</p>`;
    return `<h3>Each device over the motor's range</h3>${controls}${side}<div id="map-body">${body}</div>`;
  }
  return `<h3>${escape(focused()!.name)} over the motor's range</h3>${controls}${side}<div id="map-body">${body}</div>`;
}

/** The inverter this load asks for, on one sheet: the device, what cools it, the capacitor
 *  on the link, the gate drive and the protection. Every line is taken from a result worked
 *  out elsewhere on the page; nothing is worked out here. */
function buildSpec(): string {
  const c = focused();
  const r = c?.result;
  if (!c || !r || !(advised instanceof Array)) return "";
  const k = state.conditions;
  const sinkRec = advised.find((x) => x.topic === "heatsink");
  const dead = advised.find((x) => x.topic === "dead time");
  const motion = cycle && !(cycle instanceof Refused) ? cycle : null;
  const trip = [...c.checks, ...(motion?.checks ?? [])].filter((x) => x.topic === "trip").sort((a, b) => ["ok", "caution", "undecided", "fail"].indexOf(b.level) - ["ok", "caution", "undecided", "fail"].indexOf(a.level))[0];
  const cap: string[] = [];
  const rms = Math.max(c.link?.capacitor_rms ?? 0, motion?.summary.capacitor_rms_worst ?? 0);
  if (rms > 0) cap.push(`Ripple-current rating of at least ${sig(rms, 2)} A rms at ${sig(k.f_khz)} kHz${motion?.summary.capacitor_rms ? ` (${sig(motion.summary.capacitor_rms, 2)} A rms averaged over the motion, which is what heats it)` : ""}. The supply's own ripple comes on top.`);
  cap.push(`Voltage rating above the ${sig(k.v_dc)} V supply${motion?.summary.v_link_peak ? `, and above the ${sig(motion.summary.v_link_peak)} V the link reaches when the motor brakes` : ""}.`);
  if (motion?.summary.c_needed) cap.push(`At least ${eng(motion.summary.c_needed, "F", 2)} to take the braking energy of this motion on a supply that cannot take it back.`);
  if (motion?.inrush) cap.push(`Charging it stores ${fig(motion.inrush.energy)} J${motion.inrush.peak !== null ? `, with ${sig(motion.inrush.peak)} A peak through your precharge resistance` : "; limit the charging current with a precharge resistance"}.`);
  const gate = [c.gate.kind === "built in" ? "Inside the module." : c.gate.rg_on ? `${sig(c.gate.rg_on, 2)} Ω on, ${sig(c.gate.rg_off ?? c.gate.rg_on, 2)} Ω off${c.gate.v_drive ? `, ${sig(c.gate.v_drive, 2)} V drive` : ""}${c.gate.kind === "chosen" ? ", chosen for the lowest loss within the limits" : c.gate.kind === "datasheet" ? ", as the datasheet measured with" : ", yours"}.` : "Start from the gate resistor of the datasheet's switching test.",
    ...c.needs.slice(1).map((n) => `${sentence(n)}.`),
    ...(dead?.value.t_dead ? [`Dead time of at least ${eng(dead.value.t_dead, "s", 2)}.`] : [])];
  const protect = [
    ...(trip ? [`${sentence(trip.message)}.`] : []),
    ...(c.link?.ripple_pp ? [`A switch turns off up to ${sig(stage ? stage.i_peak + c.link.ripple_pp / 2 : c.link.ripple_pp / 2, 3)} A: the current peak with half the ${sig(c.link.ripple_pp, 2)} A ripple on top. Set the overcurrent trip above that and below the device's limit.`] : []),
    ...(c.stall_tj !== null ? [`Holding this torque at standstill, the hottest junction reaches ${degrees(c.stall_tj)}: a stalled motor needs a current limit that holds it there, or a time limit.`] : []),
  ];
  const section = (title: string, glyph: string, head: string, lines: string[]) => `<section class="rec"><h4>${icon(glyph)}${title}<span class="rec-value">${escape(head)}</span></h4><ul class="plain small">${lines.map((l) => `<li>${escape(l)}</li>`).join("")}</ul></section>`;
  return `<h3>What to build</h3><p class="quiet">What this motor and load require of the power stage, with ${escape(c.name)} as the switch: requirements to start a design from, not a finished design.</p>
${section("Power device", "cpu", c.needs[0] ? sentence(c.needs[0]) : c.name, [`${c.name}, ${c.technology}. ${{ ok: "It passes every check at this design point.", caution: "It can do this, with the cautions on the Verdict tab.", undecided: "Whether it can do this is not decided by the data: see the Verdict tab.", fail: "It does not pass: see the Verdict tab." }[c.level]}`, ...(advice ? [`Starting from scratch you would look for at least a ${sig(advice.v_minimum)} V part, ${sig(advice.v_comfortable)} V for margin, for a peak current of ${sig(advice.i_peak)} A.`] : [])])}
${section("Heatsink", "temperature", sinkRec?.value.rth_sink ? `${sig(sinkRec.value.rth_sink, 2)} K/W or lower` : "See below", [`${watts(r.loss)} to remove at the design point${motion ? `, ${watts(motion.summary.mean_loss!)} averaged over the motion` : ""}.`, ...(sinkRec ? [...sinkRec.lines.slice(0, 2), ...sinkRec.lines.filter((l) => l.startsWith("With no heatsink"))].map((l) => `${sentence(l)}.`) : [])])}
${section("DC-link capacitor", "bolt", rms > 0 ? `${sig(rms, 2)} A rms ripple` : "See below", cap)}
${section("Gate drive", "adjustments", c.gate.kind === "built in" ? "Built in" : `${state.conditions.parallel > 1 ? `${state.conditions.parallel} gates a channel` : "One gate a channel"}`, gate)}
${section("Protection", "alert-triangle", trip ? { ok: "A trip is harmless", caution: "A trip charges the link", undecided: "A trip may exceed the rating", fail: "A trip exceeds the rating" }[trip.level] : "Overcurrent and stall", protect.length ? protect : ["Set an overcurrent trip above the peak current and below the device's limit."])}`;
}

/** The question turned round: with this device, this motor and this cooling, what can be
 *  driven? The torque it holds at each speed, how that moves, and how much heavier the load
 *  of step 4 could be. */
function capabilityTab(): string {
  const c = focused();
  if (!c?.result) return notReady();
  if (loading.has("capability") || capable === null) return waiting("Finding what this device can hold. About ten seconds.");
  if (capable instanceof Refused) return refusal(capable);
  const d = capable.design;
  const k = state.conditions;
  const room = d.share === null ? "" : d.share <= 1
    ? `Your design torque of ${sig(d.torque === 0 ? 0 : k.torque)} N·m is ${percent(d.share, 0)} of that.`
    : `Your design torque of ${sig(k.torque)} N·m is above it.`;
  const load = (() => {
    if (biggest === "working") return waiting("Making the load heavier until something gives.");
    if (biggest instanceof Refused) return refusal(biggest);
    if (!biggest) return `<p><button type="button" class="ghost" data-largest>${icon("plus")}Find the largest load</button></p>`;
    if (biggest.scale < 1) return `<p class="fact warn">${icon("alert-triangle")}<span>The load of step 4 is already too much: it would have to be ${sig(biggest.scale, 2)} times what it is. ${escape(sentence(biggest.why))}.</span></p>`;
    if (biggest.open) return `<p class="fact">${icon("circle-check")}<span>The load could be more than ${sig(biggest.scale, 2)} times heavier and still pass every check: something other than this device will limit it first.</span></p>`;
    return `<p class="fact">${icon("circle-check")}<span>The load of step 4 could be <b>${sig(biggest.scale, 2)} times</b> as heavy (its inertia, friction, steady torque and mass together) before a check fails. What gives first: ${escape(sentence(biggest.why))}.</span></p>`;
  })();
  return `<h3>What ${escape(c.name)} can drive</h3>
<p class="quiet">On this motor, at ${sig(k.v_dc)} V, ${sig(k.f_khz)} kHz and ${coolingWords()}, held without end.</p>
<dl class="facts"><div><dt>Torque at ${sig(d.rpm)} rpm</dt><dd>${sig(d.torque)} N·m</dd></div><div><dt>Shaft power there</dt><dd>${watts(d.power)}</dd></div><div><dt>Motor current there</dt><dd>${d.current === null ? "n/a" : `${sig(d.current)} A peak`}</dd></div><div class="wide"><dt>What stops it</dt><dd class="words">${escape(sentence(d.why))}</dd></div></dl>
<p class="quiet after-facts">${room}${d.current !== null && d.current > d.rated ? ` At that limit the current is above the device's ${sig(d.rated)} A rating: check what case temperature that rating assumes.` : ""}</p>
<h4>Across the speed range</h4>
<div class="when-wide">${limitChart(capable.rpm, capable.edge.map((x) => x.torque), "speed, rpm", "torque it can hold, N·m", { x: d.rpm, y: k.torque, label: "your design point" }, true)}</div><div class="when-narrow">${limitChart(capable.rpm, capable.edge.map((x) => x.torque), "speed, rpm", "torque it can hold, N·m", { x: d.rpm, y: k.torque, label: "your design point" })}</div>
<p class="quiet small caption">Below the line every junction stays within its rating.${capable.edge[0].torque < 0.98 * Math.max(...capable.edge.map((x) => x.torque)) ? " At standstill one switch carries the current without rest, so the limit is lower there." : ""}</p>
<div class="read-grid"><div class="read-item"><h4>Against switching frequency</h4>${limitChart(capable.f_sw.map((v) => v / 1000), capable.by_f_sw.map((x) => x.torque), "switching frequency, kHz", "torque, N·m")}</div>
<div class="read-item"><h4>Against ${k.cooling === "held" ? "heatsink" : "air"} temperature</h4>${limitChart(capable.t_sink, capable.by_t_sink.map((x) => x.torque), `${k.cooling === "held" ? "heatsink" : "air"}, °C`, "torque, N·m")}</div></div>
<h4>How much heavier could the load be?</h4><div data-asked>${load}</div>`;
}

function settingsTab(): string {
  if (!focused()?.result) return notReady();
  if (loading.has("recommend") || advised === null) return waiting("Working out starting values.");
  if (advised instanceof Refused) return refusal(advised);
  const names: Record<string, string> = { "gate resistors": "Gate resistors", "dead time": "Dead time", modulation: "Modulation", heatsink: "Heatsink", "d-axis current": "Field current" };
  const icons: Record<string, string> = { "gate resistors": "adjustments", "dead time": "ruler-measure", modulation: "wave-sine", heatsink: "temperature", "d-axis current": "engine" };
  const value = (r: Recommendation): string => {
    const v = r.value;
    if (r.topic === "gate resistors" && v.rg_on) return `${sig(v.rg_on, 2)} Ω on, ${sig(v.rg_off, 2)} Ω off`;
    if (r.topic === "dead time" && v.t_dead) return eng(v.t_dead, "s", 2);
    if (r.topic === "heatsink" && v.rth_sink) return `${sig(v.rth_sink, 2)} K/W or lower`;
    if (r.topic === "modulation") return v.saving ? `${sig(v.saving)} W to save` : "Keep the usual scheme";
    if (r.topic === "d-axis current") return v.saving ? `${sig(v.saving)} W to save` : "Keep the least current";
    return "Needs more from you";
  };
  return `${buildSpec()}<h3>Starting values for ${escape(focused()!.name)}</h3><p class="quiet">For a first prototype. Settle them on the bench, with a probe on the switch.</p>
${advised.map((r) => `<section class="rec${Object.keys(r.value).length ? "" : " open-question"}"><h4>${icon(icons[r.topic] ?? "settings")}${names[r.topic] ?? sentence(r.topic)}<span class="rec-value">${escape(value(r))}</span></h4><ul class="plain small">${r.lines.map((l) => `<li>${escape(sentence(l))}</li>`).join("")}</ul></section>`).join("")}`;
}

/** What is being compared: up to five devices, loads or motors, or one setting at up to
 *  five values. One kind at a time; more at once is too much to read. */
interface Series {
  key: string; name: string; candidate: Candidate | null; item: LoadItem | null;
  // For a motor or a setting compared: what differs from the request of the page.
  over?: { motor?: Record<string, string | number>; conditions?: Record<string, number | string | null> };
}

/** The settings that can be tried at several values, and how each reaches the engine. */
const SWEEPS: Record<string, { label: string; unit: string; field: string; scale: number }> = {
  f_khz: { label: "Switching frequency", unit: "kHz", field: "f_sw", scale: 1000 },
  v_dc: { label: "Supply voltage", unit: "V", field: "v_dc", scale: 1 },
  t_sink: { label: "Heatsink temperature", unit: "°C", field: "t_sink", scale: 1 },
  parallel: { label: "Devices in parallel", unit: "a switch", field: "parallel", scale: 1 },
};

/** A setting as it is tried. With cooling to air there is no heatsink temperature to set:
 *  the temperature tried is the air's. */
function sweepOf(key: string): { label: string; unit: string; field: string; scale: number } {
  if (key === "t_sink" && state.conditions.cooling !== "held") return { label: "Air temperature", unit: "°C", field: "t_ambient", scale: 1 };
  return SWEEPS[key] ?? SWEEPS.f_khz;
}

/** The values a setting is tried at: the user's, or the present one with half and double. */
function sweepValues(): number[] {
  const degrees = state.sweep.key === "t_sink"; // a temperature may be zero or below
  const typed = state.sweep.values.split(/[\s,;]+/).filter((v) => v !== "").map(Number).filter((v) => Number.isFinite(v) && (degrees || v > 0));
  const held = (state.conditions as Record<string, any>)[degrees && state.conditions.cooling !== "held" ? "t_ambient" : state.sweep.key];
  const now = degrees ? Number(held) || 0 : Number(held) || 1;
  const count = Math.min(12, Math.max(1, Math.round(now)));
  const usual = state.sweep.key === "parallel" ? (count === 1 ? [1, 2, 3] : count === 12 ? [10, 11, 12] : [count - 1, count, count + 1]) : state.sweep.key === "t_sink" ? [now - 20, now, now + 20] : [now / 2, now, now * 2];
  // The value as it is set is one of them as it is; those beside it are round figures.
  return [...new Set(typed.length ? typed : usual.map((v) => (v === now ? v : Number(v.toPrecision(3)))))].slice(0, MOST);
}

/** One more value to try, typed into the box: added to those in the table, in order. */
function addSweepValue(): void {
  const box = document.querySelector<HTMLInputElement>("[data-sweep-add]");
  if (!box || box.value.trim() === "") return;
  const degrees = state.sweep.key === "t_sink";
  const typed = box.value.split(/[\s;]+|,(?=\s)|,$/).flatMap((v) => (v.trim() === "" ? [] : [Number(v.trim().replace(/^(-?\d+),(\d+)$/, "$1.$2"))]));
  const good = typed.filter((v) => Number.isFinite(v) && (degrees || v > 0));
  const field = box.closest<HTMLElement>(".field")!;
  field.querySelector(".unread")?.remove();
  const say = (text: string) => { const note = document.createElement("p"); note.className = "help unread"; note.setAttribute("role", "alert"); note.textContent = text; field.append(note); box.setAttribute("aria-invalid", "true"); };
  if (!good.length || good.length < typed.length) { say(degrees ? "Not a number: nothing was added." : "Not a number above zero: nothing was added."); return; }
  const now = sweepValues();
  const merged = [...new Set([...now, ...good])];
  if (merged.length === now.length) { say("That value is already in the table."); return; }
  if (merged.length > MOST) { say(`Five values is the most: ${now.length} are in the table, so ${MOST - now.length} more can be added.`); return; }
  state.sweep.values = merged.sort((a, b) => a - b).join(", ");
  cycles.clear();
  save(state); renderPanel(true); renderStage(); void deep();
  document.querySelector<HTMLInputElement>("[data-sweep-add]")?.focus();
}

/** The request for one thing compared: the page's own, with what differs laid over it. */
function requestOf(x: Series) {
  const base = request(state);
  if (!x.over) return base;
  return { ...base, motor: x.over.motor ?? base.motor, conditions: { ...base.conditions, ...x.over.conditions } };
}

/** Results for the motors and settings compared, each worked out with its own request. */
const variants = new Map<string, Candidate | Refused>();
const resultOf = (x: Series): Candidate | null => (x.over ? ((v) => (v instanceof Refused || !v ? null : v))(variants.get(x.key)) : x.candidate);

function series(): Series[] {
  if (state.compare === "loads") {
    const now = state.mission ? state.mission.name : state.loadTouched ? "Your load" : presets?.list.find((p) => p.id === state.loadKind)?.label ?? "Your load";
    return [{ key: "now", name: `${now} (step 4)`, candidate: focused(), item: null },
      ...state.loadSet.slice(0, MOST - 1).map((item) => ({ key: item.id, name: item.label, candidate: focused(), item }))];
  }
  if (state.compare === "motors") {
    return [{ key: "now", name: `${setup.motors[state.kind].label} (step 2)`, candidate: focused(), item: null },
      ...state.motorSet.slice(0, MOST - 1).map((m) => ({ key: m.id, name: m.label, candidate: focused(), item: null, over: { motor: m.motor, conditions: m.conditions } }))];
  }
  if (state.compare === "sweep") {
    const sweep = sweepOf(state.sweep.key);
    return sweepValues().map((v) => ({ key: `${state.sweep.key}=${v}`, name: `${sig(v)} ${sweep.unit}`, candidate: focused(), item: null, over: { conditions: { [sweep.field]: v * sweep.scale } } }));
  }
  return (proposal?.candidates ?? []).filter((c) => c.result).slice(0, MOST).map((c) => ({ key: c.id, name: c.name, candidate: c, item: null }));
}

const comparing = () => series().length > 1;

/** The main figures, one column for each thing compared. Devices are compared at the design
 *  point; loads are compared over their motion, since the design point is the same for all. */
function compareTable(): string {
  const list = series();
  const head = `<thead><tr><th scope="col"><span class="sr">Figure</span></th>${list.map((x, k) => `<th scope="col"><span class="key line s${k}"></span>${escape(x.name)}</th>`).join("")}</tr></thead>`;
  const line = (label: string, cells: string[], best: number[] = [], name = "") => `<tr${name ? ` class="${name}"` : ""}><th scope="row">${label}</th>${cells.map((v, k) => `<td class="${best.includes(k) ? "best" : ""}">${v}</td>`).join("")}</tr>`;
  if (state.compare !== "loads") {
    const got = list.map((x) => (x.over && variants.get(x.key) instanceof Refused ? "refused" : resultOf(x)?.result ?? null));
    const cell = (pick: (r: NonNullable<Candidate["result"]>, k: number) => string) => got.map((g, k) => (g === null ? "…" : g === "refused" ? "cannot run" : pick(g, k)));
    // What a candidate carries beside its result: its verdict, its margins, its data.
    const whole = (pick: (c: Candidate) => string) => got.map((g, k) => { const c = resultOf(list[k]); return g === "refused" ? "cannot run" : g === null || !c ? "…" : pick(c); });
    // A part that does not pass is not the one with the lowest loss, whatever it would lose.
    const losses = got.map((g, k) => (g && g !== "refused" && !["fail", "undecided"].includes(resultOf(list[k])?.level ?? "") ? g.loss : Infinity));
    // Losses closer than the engine can tell apart are marked together, not one as the winner.
    const least = Math.min(...losses);
    const level = Number.isFinite(least) ? losses.flatMap((v, k) => (v <= least * (1 + (proposal?.level ?? 0.05)) ? [k] : [])) : [];
    const room = (m: number | null) => (m == null ? "" : ` <span class="room ${m < 0 ? "fail" : ""}">${m < 0 ? `${sig(-m, 2)} °C over the limit` : `${sig(m, 2)} °C to the limit`}</span>`);
    const said = { ok: "Passes", caution: "Passes, with cautions", undecided: "Undecided on this data", fail: "Does not pass" };
    const foot = state.compare === "devices" ? "At your design point." : state.compare === "motors" ? `Each motor at its own design point, on ${escape(focused()?.name ?? "the device under test")}.` : `At your design point, on ${escape(focused()?.name ?? "the device under test")}, with one setting changed.`;
    const marked = level.length > 1 ? `These losses are within ${percent(proposal?.level ?? 0.05, 0)} of each other, closer than the model tells apart: they are marked together.` : "The lowest loss is marked.";
    return `<table class="data wide" style="--cols:${list.length}">${head}<tbody>
${line("Verdict", whole((c) => `<span class="${c.level === "fail" ? "fail" : ""}">${said[c.level]}</span>`))}
${line("Power-stage loss", cell((r) => watts(r.loss)), level, "loss")}
${line("Conduction", cell((r) => `${watts(r.conduction)} <span class="quiet">${percent(r.conduction / Math.max(r.loss, 1e-9), 0)}</span>`))}
${line("Switching", cell((r) => `${watts(r.switching)} <span class="quiet">${percent(r.switching / Math.max(r.loss, 1e-9), 0)}</span>`))}
${line("Hottest junction", whole((c) => `<span class="${c.result!.tj_peak > c.result!.tj_max ? "fail" : ""}">${degrees(c.result!.tj_peak)}</span>${room(c.margin)}`))}
${line("Held at standstill", whole((c) => (c.stall_tj == null ? "n/a" : `<span class="${c.stall_tj > c.result!.tj_max ? "fail" : ""}">${degrees(c.stall_tj)}</span>${room(c.stall_margin)}`)))}
${line("DC-to-shaft efficiency", list.map((x, k) => { const e = resultOf(x)?.efficiency; return got[k] === "refused" ? "cannot run" : e != null ? percent(e) : resultOf(x) ? "n/a" : "…"; }))}
${state.compare === "devices" ? line("Switching data", whole((c) => `<span class="basis">${escape(sentence(c.switching?.text ?? "not given"))}</span>`)) : ""}
${chipRows(list, got, line)}
</tbody></table>${list.flatMap((x) => { const r = x.over ? variants.get(x.key) : null; return r instanceof Refused ? [`<p class="fact warn">${icon("alert-triangle")}<span>${escape(x.name)} cannot run: ${escape(r.reason)}.</span></p>`] : []; }).join("")}<p class="quiet small">${foot} ${marked} The margin is counted from the top of the temperature range where values are assumed.${list.length > 1 ? " Slide the table sideways if a column is cut." : ""}</p>`;
  }
  const got = list.map((x) => cycles.get(x.key));
  const cell = (pick: (c: Cycle) => string) => got.map((g) => (g === undefined ? "…" : g instanceof Refused ? "cannot run" : pick(g)));
  const means = got.map((g) => (g && !(g instanceof Refused) ? g.summary.mean_loss ?? Infinity : Infinity));
  const least = means.some(Number.isFinite) ? means.indexOf(Math.min(...means)) : -1;
  return `<table class="data wide">${head}<tbody>
${line("Mean loss", cell((c) => watts(c.summary.mean_loss!)), [least], "loss")}
${line("Hottest junction reached", cell((c) => `<span class="${c.summary.peak! > c.summary.tj_max! ? "fail" : ""}">${degrees(c.summary.peak!)}</span>`))}
${line("Peak motor current", cell((c) => `${sig(Math.max(...c.i_peak.map((v) => v ?? 0)))} A`))}
${line("Energy lost", cell((c) => `${fig(c.summary.loss_energy!)} J`))}
${line("Returned by braking", cell((c) => `${fig(c.summary.returned ?? 0)} J`))}
</tbody></table><p class="quiet small">Over each load's own motion, on ${escape(focused()?.name ?? "the device under test")}. The lowest mean loss is marked.</p>`;
}

/** The bar that says what is compared, and lets more be added without leaving the results. */
function compareBar(): string {
  const mode = state.compare;
  const all = series();
  const full = all.length >= MOST;
  let items: string;
  let add: string;
  if (mode === "devices") {
    const chosen = setup.devices.filter((d) => state.devices.includes(d.id));
    items = chosen.map((d) => `<li class="chip-item">${escape(d.name)}${chosen.length > 1 ? `<button type="button" class="chip-x" data-drop-device="${escape(d.id)}" aria-label="Take ${escape(d.name)} out of the comparison">${icon("x")}</button>` : ""}</li>`).join("");
    const canRead = api.mode() !== "browser" && setup.can_read;
    add = chosen.length >= MOST ? `<span class="quiet small">Five devices is the most.</span>`
      : reading && !reading.outcome && !reading.refused ? `<span class="quiet small">Adding ${escape(reading.name)}…</span>`
      : `<label class="ghost add-part"><input type="file" data-part-file accept="${canRead ? "application/pdf," : ""}.yaml,.yml,.json" class="sr"/>${icon("plus")}Add a device</label>`;
  } else if (mode === "motors") {
    items = all.map((x) => `<li class="chip-item">${escape(x.name)}${x.over ? `<button type="button" class="chip-x" data-drop-motor="${escape(x.key)}" aria-label="Take ${escape(x.name)} out of the comparison">${icon("x")}</button>` : ""}</li>`).join("");
    add = full ? `<span class="quiet small">Five motors is the most.</span>`
      : `<button type="button" class="ghost add-part" data-add-motor>${icon("plus")}Keep the motor of step 2 to compare</button><span class="quiet small">Then change the motor in step 2: the one kept stays here beside it.</span>`;
  } else if (mode === "sweep") {
    const sweep = sweepOf(state.sweep.key);
    // Each value is a column of the table: one more is added to those there, up to five,
    // and any can be taken out. With none of the user's own, the present value is tried
    // with half of it and double.
    items = all.map((x) => `<li class="chip-item">${escape(x.name)}${all.length > 2 ? `<button type="button" class="chip-x" data-drop-value="${escape(x.key.split("=")[1])}" aria-label="Take ${escape(x.name)} out of the table">${icon("x")}</button>` : ""}</li>`).join("");
    const adding = full ? `<p class="quiet small">Five values is the most: take one out to try another.</p>`
      : `<div class="field"><label for="f-sweep-add">Add a value</label><div class="control"><input id="f-sweep-add" data-sweep-add inputmode="decimal" autocomplete="off" aria-describedby="f-sweep-add-h"/><span class="unit">${escape(sweep.unit)}</span><button type="button" class="in-control" data-sweep-go aria-label="Add this value to the table">${icon("plus")}</button></div><p class="help" id="f-sweep-add-h">Enter adds it as a column, beside those there. Two to five.</p></div>`;
    add = `<div class="fields sweep">${select("sweep.key", "Setting", state.sweep.key, Object.keys(SWEEPS).map((k) => [k, sweepOf(k).label] as [string, string]))}${adding}</div>`;
  } else {
    items = all.map((x) => `<li class="chip-item">${escape(x.name)}${x.item ? `<button type="button" class="chip-x" data-drop-load="${escape(x.key)}" aria-label="Take ${escape(x.name)} out of the comparison">${icon("x")}</button>` : ""}</li>`).join("");
    const offered = (presets?.list ?? []).filter((p) => p.id !== state.loadKind && !state.loadSet.some((x) => x.id === p.id));
    add = full ? `<span class="quiet small">Five loads is the most.</span>`
      : `<label class="add-load"><span class="sr">Add a load to compare</span><select data-add-load id="add-load"><option value="">Add a load…</option><option value="own">Your own: the load of step 4 as it is now</option>${offered.map((p) => `<option value="${p.id}">${escape(p.label)}</option>`).join("")}</select></label>`;
  }
  return `<div class="compare-bar"><div class="segmented" role="group" aria-label="What is compared"><button type="button" data-compare="devices" aria-pressed="${mode === "devices"}" class="${mode === "devices" ? "is-on" : ""}">Compare devices</button><button type="button" data-compare="loads" aria-pressed="${mode === "loads"}" class="${mode === "loads" ? "is-on" : ""}">Compare loads</button><button type="button" data-compare="motors" aria-pressed="${mode === "motors"}" class="${mode === "motors" ? "is-on" : ""}">Compare motors</button><button type="button" data-compare="sweep" aria-pressed="${mode === "sweep"}" class="${mode === "sweep" ? "is-on" : ""}">Try a setting</button></div>
<p class="quiet small">${{ devices: "Up to five devices, each on the motor and load you set.", loads: `Up to five loads, each on ${escape(focused()?.name ?? "the device under test")}.`, motors: `Up to five motors, each at its own design point, on ${escape(focused()?.name ?? "the device under test")}.`, sweep: `One setting at up to five values, everything else as you set it, on ${escape(focused()?.name ?? "the device under test")}.` }[mode]}</p>
<ul class="chip-list">${items}</ul>${add}${reading?.refused && mode === "devices" ? refusal(reading.refused) : ""}</div>`;
}

/** Up to five lines on one chart, told apart by weight and dash as well as by tone. */
const legendOf = (names: string[]) => `<ul class="legend inline series-legend">${names.map((n, k) => `<li><span class="key line s${k}"></span>${escape(n)}</li>`).join("")}</ul>`;

function resultsPanel(): string {
  const body = { proposal: proposalTab, losses: lossesTab, motion: motionTab, map: mapTab, settings: settingsTab, capability: capabilityTab }[state.tab]();
  return `<h2 tabindex="-1">Results</h2>${compareBar()}<div class="tabs" role="tablist" aria-label="Results">${TABS.map(([t, name]) => `<button type="button" role="tab" id="tab-${t}" aria-selected="${state.tab === t}" aria-controls="tab-body" tabindex="${state.tab === t ? 0 : -1}" data-tab="${t}">${name}</button>`).join("")}</div>
<div id="tab-body" role="tabpanel" aria-labelledby="tab-${state.tab}" tabindex="0">${body}</div>
<div class="actions"><button type="button" class="ghost" data-step="${LOAD}">${icon("arrow-left")}Back to the load</button><span class="save-as"><button type="button" class="ghost" data-report-md ${focused()?.result ? "" : "disabled"} title="The whole design as a Markdown file: for your notes, or to hand to a coding agent">${icon("file-text")}${savingMd ? "Writing" : "Report as .md"}</button><button type="button" class="ghost" data-report ${focused()?.result ? "" : "disabled"} title="Opens the print dialog: choose Save as PDF">${icon("file-text")}Report as PDF</button></span></div>${reportFault ? `<p class="help said-wrong" role="alert">${escape(reportFault)}</p>` : ""}`;
}

function renderPanel(keepFocus = false): void {
  const panel = $("#panel");
  const body = [devicesPanel, motorPanel, supplyPanel, loadPanel, resultsPanel][state.step]();
  const banner = blocked && state.step !== RESULTS && state.step >= MOTOR && state.reached >= SUPPLY ? refusal(blocked) : fault ? `<div class="refusal" role="alert">${icon("alert-triangle")}<div><p><b>The engine stopped.</b> ${escape(fault)}</p><p class="fix">${api.mode() === "server" ? "Check that <code>motionsim serve</code> is still running." : "Reload the page to start it again."}</p></div></div>` : "";
  const held = document.activeElement instanceof HTMLElement && panel.contains(document.activeElement) ? document.activeElement.id : "";
  panel.innerHTML = `<div id="banner" aria-live="assertive">${banner}</div>${body}`;
  document.body.dataset.at = String(state.step);
  // What had the keyboard keeps it through a redraw, and the tab in use stays in view.
  if (keepFocus && held && document.activeElement === document.body) document.getElementById(held)?.focus({ preventScroll: true });
  panel.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  renderPreview();
  if (!keepFocus) panel.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
}

/** What the motion asks of the motor, set against the design point of step 3: the two are
 *  entered on different steps and have to agree. */
function motionAgainstDesign(): string {
  if (state.mission) return "";
  const gear = Number(state.load.gear_ratio) || 1;
  const top = Math.max(...state.segments.flatMap((g) => [Math.abs(g.speed_start), Math.abs(g.speed_end)]), 0) * gear;
  const design = Math.abs(state.conditions.rpm);
  const round = (v: number) => Math.round(v).toLocaleString("en-US");
  const over = top > design * 1.01;
  return `<p class="fact${over ? " warn" : ""}">${icon(over ? "alert-triangle" : "info-circle")}<span>At the motor this motion reaches ${round(top)} rpm${gear !== 1 ? `, the load's speed times the ${sig(gear)}:1 gear` : ""}. ${over ? `That is above the ${round(design)} rpm you gave as the design speed in step 3: the device was tested at the lower speed. Raise the design speed, or slow the motion.` : `Your design speed in step 3 is ${round(design)} rpm.`}</span></p>`;
}

/** Under the kinds of load: how this one was sized, or that its figures are now the user's own. */
function loadNote(link: string): string {
  return state.loadTouched
    ? `<p class="fact">${icon("info-circle")}<span>These are your own figures now: they stay as they are when the motor or the design point changes. <button type="button" class="link" data-resize-load>Size this load to the motor again</button></span></p>`
    : `<p class="fact">${icon("info-circle")}<span>${escape(link)}</span></p>`;
}

function renderPreview(): void {
  const box = document.querySelector<HTMLElement>("#motion-preview");
  if (box) box.innerHTML = state.mission ? `<p class="quiet">The mission profile above is the motion. The stretches below are not used while it is there.</p>` : motionPreview(state.segments) + motionAgainstDesign();
}

/** Results change under the user's hands, so only the part that changed is redrawn. */
function refreshOutputs(): void {
  renderStage();
  renderRail();
  const banner = document.querySelector<HTMLElement>("#banner");
  if (banner) banner.innerHTML = blocked && state.step !== RESULTS && state.step >= MOTOR && state.reached >= SUPPLY ? refusal(blocked) : "";
  document.querySelectorAll<HTMLElement>(".field.is-wrong").forEach((e) => { e.classList.remove("is-wrong"); e.querySelector("input")?.removeAttribute("aria-invalid"); });
  if (blocked?.field) {
    document.querySelectorAll<HTMLInputElement>("#panel [data-bind]").forEach((input) => {
      if (wrongAt(input.dataset.bind!)) {
        input.closest(".field")?.classList.add("is-wrong");
        input.setAttribute("aria-invalid", "true");
      }
    });
  }
  if (state.step === SUPPLY) {
    const face = (id: string, text: string) => { const el = document.querySelector<HTMLElement>(`#panel [data-fold="${id}"] > summary .quiet`); if (el) el.textContent = text; };
    face("gate", gateFace());
    face("more-settings", supplyFace());
  }
  if (state.step === RESULTS) {
    if (document.querySelector("#tab-body")) renderPanel(true);
  }
}

/* ---------- talking to the engine ---------- */

function schedule(): void {
  save(state);
  clearTimeout(timer);
  timer = window.setTimeout(compute, 240);
}

async function compute(): Promise<void> {
  pending?.abort();
  const mine = (pending = new AbortController());
  fault = null;
  const req = request(state);
  try {
    const answer = await api.stage(req, mine.signal);
    stage = answer.stage;
    advice = answer.advice;
    blocked = null;
    if (conditionsGiven()) {
      proposal = await api.proposal({ ...req, devices: state.devices }, mine.signal);
      const stillThere = proposal.candidates.some((c) => c.id === state.focus && c.result);
      if (!state.focusPicked || !stillThere) state.focus = proposal.candidates.find((c) => c.result)?.id ?? null;
    } else {
      proposal = null;
    }
  } catch (error) {
    if (mine.signal.aborted) return;
    if (error instanceof Refused) {
      blocked = error;
      stage = null;
      advice = null;
      proposal = null;
    } else {
      fault = (error as Error).message;
    }
  }
  cycle = grid = advised = null;
  capable = null; biggest = null;
  cycles.clear(); grids.clear(); variants.clear();
  refreshOutputs();
  if (fault) renderPanel(true);
  void deep();
}

/** The slower results, worked out only for the tab that is open. */
async function deep(): Promise<void> {
  const c = focused();
  if (state.step !== RESULTS || !c?.result || blocked) return;
  const req = { ...request(state), device: c.id };
  // Whatever was worked out for other inputs is not an answer for these.
  if (inputsNow() !== resultsOf) {
    cycle = grid = advised = null; capable = null; biggest = null;
    cycles.clear(); grids.clear(); variants.clear();
    resultsOf = inputsNow();
  }
  // This pass is for these inputs and this device. Once either has moved on it asks for
  // nothing more: what it would ask with (the device, the request) is no longer what is wanted.
  const begun = { inputs: inputsNow(), focus: state.focus };
  const still = (key: string) => inputsNow() === begun.inputs && ((state.compare === "devices" && key.includes(":")) || state.focus === begun.focus);
  const run = async <T>(key: string, call: () => Promise<T>, store: (v: T | Refused) => void) => {
    // Only the results are redrawn by a slow answer: if the user has moved to another
    // step meanwhile, that step is theirs and is left as it is.
    if (state.step !== RESULTS || !still(key)) return;
    if (loading.has(key)) { askedAgain.add(key); return; }
    loading.add(key);
    document.body.dataset.busy = "1"; // something is being worked out, whether or not this tab shows it
    renderPanel(true);
    // In a comparison of devices each answer is one device's own; anywhere else it is
    // the answer for the device on the drawing.
    let got: T | Refused;
    try { got = await call(); } catch (e) { got = e instanceof Refused ? e : new Refused((e as Error).message, "", ""); }
    if (still(key)) store(got);
    loading.delete(key);
    if (!loading.size) delete document.body.dataset.busy;
    if (state.step === RESULTS) renderPanel(true);
    // An answer that came back for inputs since changed is not shown, and one asked for
    // again while this was out is owed. The pass is made once more after every answer: it
    // works out only what is still missing, and so cannot leave something out for good.
    askedAgain.delete(key);
    void deep();
  };
  // What is compared: each one's motion, and for devices each one's map.
  const list = series();
  const wide = list.length > 1;
  for (const x of wide ? list : []) {
    if (!x.over || variants.has(x.key)) continue;
    if (state.step !== RESULTS) return;
    await run(`variant:${x.key}`, () => api.proposal({ ...requestOf(x), devices: [c.id] }).then((p) => p.candidates[0]), (v) => { variants.set(x.key, v); });
    renderStage();
  }
  if (wide && (state.compare === "loads" || state.tab === "motion")) {
    for (const x of list) {
      if (state.step !== RESULTS) return;
      if (cycles.has(x.key) || !x.candidate) continue;
      // A heatsink temperature being tried is also where that column's heatsink starts from.
      const tried = x.over?.conditions?.t_sink;
      const as = tried != null ? { ...state, conditions: { ...state.conditions, t_sink: Number(tried) } } : state;
      const motion = x.item ? motionRequest({ ...state, load: x.item.load, segments: x.item.segments, mission: x.item.mission ?? null }) : motionRequest(as);
      await run(`cycle:${x.key}`, () => api.cycle({ ...requestOf(x), device: x.candidate!.id, ...motion }), (v) => { cycles.set(x.key, v); });
      if (state.compare === "loads") renderStage();
    }
    const mine = cycles.get(state.compare === "devices" ? c.id : state.compare === "sweep" ? "" : "now");
    if (mine && cycle !== mine) { cycle = mine; if (state.step === RESULTS) renderPanel(true); }
  }
  if (wide && state.compare === "devices" && state.tab === "map") {
    const cc = state.conditions;
    for (const x of list) {
      if (state.step !== RESULTS) return;
      if (grids.has(x.key)) continue;
      await run(`map:${x.key}`, () => api.map({ ...request(state), device: x.key, rpm_max: Number(state.map.rpm_max) || cc.rpm * 2, torque_max: Number(state.map.torque_max) || cc.torque * 2, n: 6 }), (v) => { grids.set(x.key, v); });
    }
    return;
  }
  if (state.tab === "motion" && cycle === null) await run("cycle", () => api.cycle({ ...req, ...motionRequest(state) }), (v) => (cycle = v));
  if (state.tab === "map" && grid === null) {
    const cc = state.conditions;
    await run("map", () => api.map({ ...req, rpm_max: Number(state.map.rpm_max) || cc.rpm * 2, torque_max: Number(state.map.torque_max) || cc.torque * 2, n: 8 }), (v) => (grid = v));
  }
  if (state.tab === "capability" && capable === null) await run("capability", () => api.capability(req), (v) => (capable = v));
  // The sheet of what to build draws on the motion too: the capacitor is sized by braking.
  if (state.tab === "settings" && cycle === null) await run("cycle", () => api.cycle({ ...req, ...motionRequest(state) }), (v) => (cycle = v));
  if (state.tab === "settings" && advised === null) await run("recommend", () => api.recommend({ ...req, t_ambient: state.sink.t_ambient === "" || Number.isNaN(Number(state.sink.t_ambient)) ? 40 : Number(state.sink.t_ambient) }).then((x) => x.items), (v) => (advised = v));
}

/** Open a setup saved from this page: everything entered comes back as it was. */
async function openSetup(file: File): Promise<void> {
  try {
    const data = JSON.parse(await file.text());
    if (data?.app !== "MotionSim" || !data.state || !setup.motors[data.state.kind]) throw new Error("not a setup file");
    const missing = (data.state.devices as string[]).filter((id) => !setup.devices.some((d) => d.id === id));
    save(data.state as State);
    if (missing.length) window.alert(`This setup names ${missing.length === 1 ? "a part" : "parts"} that this page does not hold. Add ${missing.length === 1 ? "it" : "them"} again in step 1: the rest of the setup is in place.`);
    location.reload();
  } catch {
    reading = { name: file.name, refused: new Refused("that file is not a setup saved from this page", "choose a file made by \"Save this setup to a file\"", "") };
    renderPanel(true);
  }
}

/** Take in whatever the user dropped: a datasheet, a device file, or their own measurements. */
async function addPart(file: File): Promise<void> {
  reading = { name: file.name };
  renderPanel(true);
  const none = { values: 0, curves: 0, flagged: [] };
  try {
    let outcome: ReadOutcome;
    if (/\.json$/i.test(file.name)) {
      // Measurements belong to the device on the drawing where the user chose one, else to the first ticked.
      const target = [state.focusPicked ? state.focus : null, ...state.devices].find((id) => id && !id.endsWith("-measured")) ?? ownDevices()[0]?.id;
      if (!target) throw new Refused("measurements need the device they were taken on", "add the device's datasheet or device file first, then drop the measurements", "");
      outcome = { ...(await api.addMeasurement(target, file)), read: none };
    } else if (/\.ya?ml$/i.test(file.name)) {
      outcome = { ...(await api.addDevice(file)), read: none };
    } else if (api.mode() === "browser" || !setup.can_read) {
      throw new Refused("a datasheet PDF cannot be read on this page", "see below for how to turn it into a device file on your own machine", "");
    } else {
      outcome = await api.read(file);
    }
    reading = { name: file.name, outcome };
    setup = await api.setup();
    if (suggestion?.id === outcome.device.id) suggestion = null;
    if (review?.id === outcome.device.id) { review = null; void openReview(outcome.device.id); }
    // On the first step the part just brought is the part under test, in place of a made-up
    // one. Added on the results, it stands beside whatever is there, to be compared with it.
    const made = state.step === RESULTS || state.reached > DEVICE ? new Set<string>() : new Set(setup.devices.filter((d) => d.example).map((d) => d.id));
    state.devices = [...new Set([...state.devices.filter((id) => !made.has(id)), outcome.device.id])].slice(-MOST);
    state.added = [...new Set([...state.added.filter((id) => !made.has(id)), outcome.device.id])];
    void suggestFor();
    schedule();
  } catch (e) {
    reading = { name: file.name, refused: e instanceof Refused ? e : new Refused((e as Error).message, api.mode() === "server" ? "check the terminal that runs motionsim serve" : "check the file and try again", "") };
  }
  renderPanel(true);
  renderRail();
  renderStage();
}

/* ---------- events ---------- */

/** Takes what was typed into the state. Returns the figure still in use when what was typed
 *  cannot be read as a number, so that the page can say so at the box; null when all is well. */
function setPath(path: string, raw: string): string | null {
  const keys = path.split(".");
  let target: any = state;
  for (const k of keys.slice(0, -1)) target = target[k];
  const last = keys[keys.length - 1];
  // A comma for the decimal point is how half the world writes a number.
  if (/^\s*-?\d+,\d+\s*$/.test(raw)) raw = raw.replace(",", ".");
  const numeric = typeof target[last] === "number";
  const unread = raw.trim() === "" || Number.isNaN(Number(raw));
  let kept: string | null = null;
  if (numeric && unread) kept = String(target[last]);
  target[last] = numeric ? (unread ? target[last] : Number(raw)) : raw;
  if (keys[0] === "motors" && raw.trim() !== "" && !Number.isNaN(Number(raw))) target[last] = Number(raw);
  // A figure the motor can do without is taken away when its box is emptied, not kept unseen.
  const m = keys[0] === "motors" ? setup.motors[keys[1]] : null;
  if (m && raw.trim() === "" && (m.fields.some((f) => f.key === last && f.required === false) || m.optional?.some((f) => f.key === last))) { target[last] = ""; kept = null; }
  const spec = m ? [...m.fields, ...(m.optional ?? [])].find((f) => f.key === last) : null;
  if (spec && !(spec as { options?: unknown }).options && typeof target[last] === "string" && target[last].trim() !== "") target[last] = "";
  if (keys[0] === "motors" && !state.motorEdited.includes(keys[1])) state.motorEdited = [...state.motorEdited, keys[1]];
  if (keys[0] === "motors" || keys[0] === "conditions") state.motorTouched = true;
  if (keys[0] === "load" || keys[0] === "segments") state.loadTouched = true;
  return kept;
}

/** Says at a box that what is in it is not a number and which figure the results still use,
 *  or takes that note away. */
function markUnread(el: HTMLInputElement, kept: string | null): void {
  const box = el.closest<HTMLElement>(".field") ?? el.closest<HTMLElement>("td");
  if (!box) return;
  box.querySelector(".unread")?.remove();
  box.classList.toggle("is-unread", kept !== null);
  if (kept === null) { el.removeAttribute("aria-invalid"); return; }
  el.setAttribute("aria-invalid", "true");
  const note = document.createElement("p");
  note.className = "help unread"; note.setAttribute("role", "alert");
  note.textContent = el.value.trim() === "" ? `Empty: ${kept} is still in use.` : `Not a number: ${kept} is still in use.`;
  box.append(note);
}

function goTo(step: number, fromHistory = false): void {
  missionFault = null; // a file refused is said where it was refused, not for ever after
  if (!fromHistory && step !== state.step) history.pushState({ step }, "");
  void suggestFor();
  if (step >= LOAD) void presetsFor();
  state.step = Math.max(0, Math.min(STEPS.length - 1, step));
  state.reached = Math.max(state.reached, state.step);
  save(state);
  const draw = () => { renderPanel(); renderRail(); renderStage(); $("#panel").querySelector("h2")?.scrollIntoView({ block: "start" }); };
  const doc = document as Document & { startViewTransition?: (f: () => void) => void };
  if (doc.startViewTransition && !reduced()) doc.startViewTransition(draw); else draw();
  if (conditionsGiven() && !proposal && !blocked) void compute(); else void deep();
  if (state.step === MOTOR) fitFor(true);
}

/** The page open in two tabs keeps one saved state. A tab that sees the other change it
 *  takes that up when it is next looked at, and does not write its own older figures over it. */
function followOtherTabs(): void {
  let stale = false;
  const take = () => { if (stale) location.reload(); };
  window.addEventListener("storage", (e) => {
    if (e.key !== null && e.key !== KEY) return;
    if (e.newValue === JSON.stringify(state)) return;
    stale = true;
    if (document.hidden) take();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) take(); });
  window.addEventListener("focus", take);
}

function wire(): void {
  followOtherTabs();
  const app = $("#app");
  app.addEventListener("input", (e) => {
    const el = e.target as HTMLInputElement;
    if (el.dataset.typed) {
      state.typed[el.dataset.typed] = el.value; save(state);
      if (typedRefused?.field === el.dataset.typed) {
        typedRefused = null;
        const box = el.closest(".field");
        box?.classList.remove("is-wrong"); box?.querySelector(".said-wrong")?.remove(); el.removeAttribute("aria-invalid");
      }
      return;
    }
    if (!el.dataset.bind || el.tagName === "SELECT") return;
    if (el.dataset.bind.startsWith("sweep.")) return; // taken when the field is left: see the change handler
    markUnread(el, setPath(el.dataset.bind, el.value));
    const typed = el.value.trim().replace(/^(-?\d+),(\d+)$/, "$1.$2");
    if (el.inputMode === "decimal" && typed !== "" && Number.isNaN(Number(typed)) && !el.closest(".is-unread")) {
      // A figure that may be left empty: what is typed is not a number, and nothing is used for it.
      const box = el.closest<HTMLElement>(".field") ?? el.closest<HTMLElement>("td");
      if (box) {
        box.classList.add("is-unread"); el.setAttribute("aria-invalid", "true");
        const note = document.createElement("p");
        note.className = "help unread"; note.setAttribute("role", "alert"); note.textContent = "Not a number: this box is left out.";
        box.append(note);
      }
    }
    const said = el.closest(".field")?.querySelector<HTMLElement>("[data-said]");
    if (said) said.textContent = saidAs(el.value, said.dataset.said!); // the spoken figure follows what is typed
    if (el.dataset.bind.startsWith("motors.")) { renderStage(); fitFor(); } // the drawing and the fit follow the motor's figures as they are typed
    if (el.dataset.bind.startsWith("segments") || el.dataset.bind.startsWith("load.")) {
      renderPreview();
      // What the step says of the load follows the figures as they are typed.
      const said = document.querySelector<HTMLElement>("#load-note");
      if (said && said.innerHTML && !said.querySelector("[data-resize-load]")) said.innerHTML = loadNote("");
      const face = document.querySelector<HTMLElement>('[data-fold="load-figures"] > summary .quiet');
      if (face) face.textContent = "yours";
    }
    if (el.dataset.bind.startsWith("map.")) { grid = null; clearTimeout(timer); timer = window.setTimeout(() => void deep(), 500); save(state); return; }
    schedule();
  });
  app.addEventListener("change", (e) => {
    const el = e.target as HTMLInputElement;
    if (el.matches("[data-load]")) {
      const picked = presets?.list.find((p) => p.id === el.value);
      if (picked) { state.loadTouched = false; state.mission = null; missionFault = null; applyPreset(picked); state.loadSet = state.loadSet.filter((x) => x.id !== picked.id); cycles.clear(); renderPanel(true); renderPreview(); schedule(); document.querySelector<HTMLInputElement>(`[data-load][value="${picked.id}"]`)?.focus(); }
      return;
    }
    if (el.matches("[data-kind]")) {
      const was = state.conditions;
      state.pointOf = { ...state.pointOf, [state.kind]: { v_dc: was.v_dc, rpm: was.rpm, torque: was.torque, f_khz: was.f_khz, pwm: was.pwm } };
      state.kind = el.value;
      state.motorTouched = true;
      const start = (suggestion && suggestion.id === underTest() ? suggestion.data.motors[state.kind]?.start : null) ?? setup.motors[state.kind].start;
      // The point this kind was left at, where it has been here before; else where its example starts.
      Object.assign(state.conditions, state.pointOf[state.kind] ?? { v_dc: start.v_dc, rpm: start.rpm, torque: start.torque, f_khz: start.f_sw / 1000, pwm: "" });
      state.map = { rpm_max: "", torque_max: "" };
      renderStage(); // the drawing shows the kind of motor at once
      fit = null;
      renderPanel(true);
      document.querySelector<HTMLInputElement>(`[data-kind][value="${state.kind}"]`)?.focus();
      fitFor(true);
      schedule();
    } else if (el.matches("[data-device]")) {
      const id = el.dataset.device!;
      if (el.checked && !state.devices.includes(id) && state.devices.length >= MOST) {
        // Five are compared at most: a sixth is not ticked, and the step says why.
        el.checked = false;
        document.querySelector("#most-devices")?.remove();
        el.closest(".device")?.insertAdjacentHTML("afterend", `<li class="quiet small" id="most-devices" role="alert">Five devices is the most at once: untick one to tick another.</li>`);
        return;
      }
      document.querySelector("#most-devices")?.remove();
      state.devices = el.checked ? [...new Set([...state.devices, id])] : state.devices.filter((d) => d !== id);
      void suggestFor();
      if (state.focus === id && !el.checked) state.focusPicked = false;
      el.closest(".device")?.classList.toggle("is-on", el.checked);
      const foot = document.querySelector<HTMLElement>("#panel .actions");
      if (foot) { document.querySelector("#need-device")?.remove(); foot.outerHTML = nextButton(DEVICE); }
      renderRail();
      renderStage();
      schedule();
    } else if ((el.id === "part-file" || el.dataset.partFile !== undefined) && el.files?.[0]) {
      void addPart(el.files[0]);
    } else if (el.dataset.missionFile !== undefined && el.files?.[0]) {
      void addMission(el.files[0]);
    } else if (el.dataset.addLoad !== undefined && el.dataset.keys === "1") {
      // Arrow keys on the closed list change it at every press: that is looking, not choosing.
    } else if (el.dataset.addLoad !== undefined && el.value === "own" && series().length < MOST) {
      // The user's own load: what step 4 holds now, kept as it is. They can then change
      // step 4 and see the two side by side.
      const n = Math.max(0, ...state.loadSet.filter((x) => x.id.startsWith("own-")).map((x) => Number(/^Your load (\d+)/.exec(x.label)?.[1] ?? 0))) + 1;
      const from = state.mission ? state.mission.name : presets?.list.find((p) => p.id === state.loadKind)?.label ?? "load";
      state.loadSet.push({ id: `own-${Date.now()}`, label: `Your load ${n} (${from}, as set)`, loadKind: state.loadKind,
        load: { ...state.load }, segments: state.segments.map((x) => ({ ...x })), mission: state.mission });
      save(state); renderPanel(true); renderStage(); void deep();
    } else if (el.dataset.addLoad !== undefined) {
      const picked = presets?.list.find((p) => p.id === el.value);
      if (picked && series().length < MOST) {
        state.loadSet.push(itemOf(picked));
        save(state); renderPanel(true); renderStage(); void deep();
      }
    } else if (el.dataset.sweepAdd !== undefined) {
      addSweepValue();
    } else if (el.dataset.bind?.startsWith("sweep.")) {
      if (el.dataset.bind === "sweep.key") state.sweep = { key: el.value, values: "" };
      variants.clear(); cycles.clear();
      save(state); renderPanel(true); renderStage(); void deep();
    } else if (el.dataset.setupFile !== undefined && el.files?.[0]) {
      void openSetup(el.files[0]);
    } else if (el.tagName === "SELECT" && el.dataset.bind) {
      setPath(el.dataset.bind, el.value);
      if (el.dataset.bind.startsWith("motors.")) { renderStage(); fitFor(); }
      if (el.dataset.bind === "conditions.cooling") { if (state.sweep.key === "t_sink") state.sweep.values = ""; renderPanel(true); document.querySelector<HTMLElement>('[data-bind="conditions.cooling"]')?.focus(); }
      if (el.dataset.bind === "start.method") { cycle = null; renderPanel(true); document.querySelector<HTMLElement>('[data-bind="start.method"]')?.focus(); }
      schedule();
    }
  });
  window.addEventListener("popstate", (e) => {
    const step = (e.state as { step?: number } | null)?.step;
    if (typeof step === "number" && step <= state.reached) goTo(step, true);
  });
  document.addEventListener("click", (e) => {
    const dialog = document.querySelector<HTMLDialogElement>("#equations");
    const target = e.target as HTMLElement;
    // Closed by its button, or by a press on the dimmed page behind it.
    if (dialog?.open && (target.closest("[data-close-equations]") || target === dialog)) dialog.close();
  });
  // The period drawing stays as the user left it, open or folded, through redraws.
  app.addEventListener("toggle", (e) => {
    const el = e.target as HTMLDetailsElement;
    if (el.classList?.contains("pwm-fold")) pwmOpen = el.open;
    if (el.classList?.contains("typed")) typedOpen = el.open;
    if (el.dataset?.fold) { if (el.open) openFolds.add(el.dataset.fold); else openFolds.delete(el.dataset.fold); }
  }, true);
  app.addEventListener("click", (e) => {
    const el = (e.target as HTMLElement).closest<HTMLElement>("[data-sweep-go],[data-drop-value],[data-step],[data-tab],[data-focus],[data-metric],[data-add],[data-remove],[data-example],[data-add-typed],[data-report-md],[data-review],[data-add-motor],[data-drop-motor],[data-save-setup],[data-largest],[data-forget-device],[data-start-over],[data-compare],[data-drop-device],[data-drop-load],[data-drop-mission],[data-resize-load],[data-report],[data-zoom],[data-equations],[data-map-at]");
    if (!el) return;
    if (el.dataset.zoom) {
      const at = ZOOMS.indexOf(state.pwmPeriods);
      state.pwmPeriods = ZOOMS[Math.min(Math.max((at < 0 ? 2 : at) + (el.dataset.zoom === "in" ? -1 : 1), 0), ZOOMS.length - 1)];
      save(state); renderStage();
      document.querySelector<HTMLElement>(`[data-zoom="${el.dataset.zoom}"]:not(:disabled), [data-zoom]:not(:disabled)`)?.focus();
      return;
    }
    if (el.dataset.equations !== undefined) { openEquations(); return; }
    if (el.dataset.saveSetup !== undefined) {
      // Everything entered on the page, as one file to keep, share or open again. Device
      // models are named, not carried: they are added on the page that opens it.
      const blob = new Blob([JSON.stringify({ app: "MotionSim", setup: 1, state }, null, 1)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "motionsim-setup.json";
      link.click();
      URL.revokeObjectURL(link.href);
      return;
    }
    if (el.dataset.largest !== undefined) {
      const c = focused();
      if (!c) return;
      biggest = "working";
      renderPanel(true);
      const at = `${inputsNow()}|${state.focus}`;
      const keep = (v: Largest | Refused) => { if (`${inputsNow()}|${state.focus}` === at) biggest = v; else if (biggest === "working") biggest = null; };
      api.largest({ ...request(state), device: c.id, ...motionRequest(state) })
        .then((v) => keep(v), (e) => keep(e instanceof Refused ? e : new Refused((e as Error).message, "", "")))
        .then(() => { if (state.step === RESULTS && state.tab === "capability") renderPanel(true); });
      return;
    }
    if (el.dataset.forgetDevice !== undefined) {
      const id = el.dataset.forgetDevice;
      state.added = state.added.filter((d) => d !== id);
      state.devices = state.devices.filter((d) => d !== id);
      api.forget(id!);
      if (review?.id === id) review = null;
      if (reading?.outcome?.device.id === id) reading = null;
      state.focusPicked = false;
      void suggestFor();
      renderPanel(true); renderRail(); renderStage(); schedule();
      return;
    }
    if (el.dataset.startOver !== undefined) {
      if (!window.confirm("Reset the simulation? This clears the parts, the motor, the load and everything else entered on this page.")) return;
      try { localStorage.clear(); } catch { /* a private window: nothing was kept */ }
      location.reload();
      return;
    }
    if (el.dataset.dropMission !== undefined) { state.mission = null; state.loadTouched = state.loadTouchedBefore; missionFault = null; cycle = null; cycles.clear(); save(state); renderPanel(true); schedule(); return; }
    if (el.dataset.report !== undefined) { void printReport(); return; }
    if (el.dataset.reportMd !== undefined) { void saveMarkdown(); return; }
    if (el.dataset.resizeLoad !== undefined) {
      // A load of a kind this motor is not offered gives way to the usual one for it.
      const again = presets?.list.find((p) => p.id === state.loadKind) ?? presets?.list[0];
      if (again) { state.loadTouched = false; applyPreset(again); cycles.clear(); renderPanel(true); renderPreview(); schedule(); }
      return;
    }
    if (el.dataset.mapAt) { state.mapAt = el.dataset.mapAt as "motor" | "load"; save(state); renderPanel(true); document.querySelector<HTMLElement>(`[data-map-at="${state.mapAt}"]`)?.focus(); return; }
    if (el.dataset.addMotor !== undefined && series().length < MOST) {
      const k = state.conditions;
      const n = Math.max(0, ...state.motorSet.map((m) => Number(/ (\d+) \(/.exec(m.label)?.[1] ?? 0))) + 1;
      const asked = request(state);
      state.motorSet.push({ id: `motor-${Date.now()}`, label: `${setup.motors[state.kind].label} ${n} (${sig(k.rpm)} rpm, ${sig(k.torque)} N·m, as set)`,
        motor: asked.motor as Record<string, string | number>, conditions: { v_dc: k.v_dc, rpm: k.rpm, torque: k.torque, f_sw: asked.conditions.f_sw, pwm: asked.conditions.pwm } });
      save(state); renderPanel(true); renderStage(); void deep();
      return;
    }
    if (el.dataset.dropMotor !== undefined) { state.motorSet = state.motorSet.filter((m) => m.id !== el.dataset.dropMotor); variants.delete(el.dataset.dropMotor!); cycles.delete(el.dataset.dropMotor!); save(state); renderPanel(true); renderStage(); return; }
    if (el.dataset.compare) { state.compare = el.dataset.compare as State["compare"]; cycles.clear(); variants.clear(); save(state); renderPanel(true); renderStage(); void deep(); document.querySelector<HTMLElement>(`[data-compare="${state.compare}"]`)?.focus(); return; }
    if (el.dataset.dropDevice !== undefined) { state.devices = state.devices.filter((d) => d !== el.dataset.dropDevice); if (state.focus === el.dataset.dropDevice) state.focusPicked = false; void suggestFor(); renderPanel(true); schedule(); return; }
    if (el.dataset.dropLoad !== undefined) { state.loadSet = state.loadSet.filter((x) => x.id !== el.dataset.dropLoad); cycles.delete(el.dataset.dropLoad!); save(state); renderPanel(true); renderStage(); return; }
    if (el.dataset.sweepGo !== undefined) { addSweepValue(); return; }
    if (el.dataset.dropValue !== undefined) {
      const left = sweepValues().filter((v) => String(v) !== el.dataset.dropValue);
      state.sweep.values = left.join(", ");
      cycles.clear(); save(state); renderPanel(true); renderStage(); void deep();
      document.querySelector<HTMLInputElement>("[data-sweep-add]")?.focus();
      return;
    }
    if (el.dataset.review !== undefined) { void openReview(el.dataset.review); return; }
    if (el.dataset.addTyped !== undefined) { void addTyped(); return; }
    if (el.dataset.example !== undefined) { const made = el.dataset.example || "example"; state.devices = [...new Set([...state.devices, made])].slice(-MOST); state.added = [...new Set([...state.added, made])]; save(state); void suggestFor(); renderPanel(true); renderRail(); renderStage(); schedule(); (document.querySelector<HTMLElement>(`[data-drop-device="${made}"]`) ?? document.querySelector<HTMLElement>("#panel h2"))?.focus({ preventScroll: true }); return; }
    if (el.dataset.openFold) openFolds.add(el.dataset.openFold);
    if (el.dataset.step !== undefined) goTo(Number(el.dataset.step));
    else if (el.dataset.tab) { state.tab = el.dataset.tab as Tab; save(state); renderPanel(true); document.querySelector<HTMLElement>(`#tab-${state.tab}`)?.focus(); void deep(); }
    else if (el.dataset.focus) { state.focusPicked = true; if (state.focus !== el.dataset.focus) { state.focus = el.dataset.focus; cycle = grid = advised = null; capable = null; biggest = null; if (state.compare !== "devices") { variants.clear(); cycles.clear(); } save(state); renderStage(); if (!el.matches("summary")) renderPanel(true); void deep(); } }
    else if (el.dataset.metric) { state.metric = el.dataset.metric as State["metric"]; save(state); renderPanel(true); }
    else if (el.dataset.add !== undefined) { const last = state.segments[state.segments.length - 1]; state.segments.push({ duration: 1, speed_start: last?.speed_end ?? 0, speed_end: last?.speed_end ?? 0 }); state.loadTouched = true; save(state); renderPanel(true); renderPreview(); schedule(); }
    else if (el.dataset.remove !== undefined) { state.segments.splice(Number(el.dataset.remove), 1); state.loadTouched = true; save(state); renderPanel(true); renderPreview(); schedule(); }
  });
  app.addEventListener("pointerdown", (e) => { const t = e.target as HTMLElement; if (t.dataset?.addLoad !== undefined) delete t.dataset.keys; });
  app.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.target as HTMLElement).dataset?.sweepAdd !== undefined) { e.preventDefault(); addSweepValue(); return; }
    const list = e.target as HTMLSelectElement;
    if (list.dataset?.addLoad !== undefined) {
      // With the keyboard, the arrows move through the loads and Enter adds the one shown.
      if (e.key === "Enter" || e.key === " ") { if (list.dataset.keys === "1") { e.preventDefault(); delete list.dataset.keys; list.dispatchEvent(new Event("change", { bubbles: true })); document.querySelector<HTMLElement>("#add-load")?.focus(); } return; }
      if (e.key.startsWith("Arrow") || e.key.length === 1 || e.key === "Home" || e.key === "End") list.dataset.keys = "1";
      return;
    }
    if (e.key === "Enter" && (e.target as HTMLElement).matches?.("input[data-typed]") && !typedBusy) { e.preventDefault(); void addTyped(); return; }
    const tab = (e.target as HTMLElement).closest<HTMLElement>("[role=tab]");
    if (!tab || !["ArrowLeft", "ArrowRight"].includes(e.key)) return;
    const k = TABS.findIndex(([t]) => t === state.tab);
    const next = TABS[(k + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length][0];
    document.querySelector<HTMLElement>(`#tab-${next}`)?.click();
  });
  for (const type of ["dragover", "drop"] as const) {
    app.addEventListener(type, (e) => {
      const zone = (e.target as HTMLElement).closest("#drop");
      if (!zone) return;
      e.preventDefault();
      zone.classList.toggle("is-over", type === "dragover");
      const file = type === "drop" ? (e as DragEvent).dataTransfer?.files[0] : null;
      if (file) void addPart(file);
    });
  }
}

async function start(): Promise<void> {
  const app = $("#app");
  app.innerHTML = `<header class="top"><span class="brand">MotionSim</span><span class="top-note">Datasheets as models for motor drives</span><button type="button" class="top-button" data-equations aria-label="The equations">${icon("math-function")}<span>The equations</span></button><details class="about"><summary aria-label="Exploratory tool">${icon("info-circle")}<span>Exploratory tool</span></summary><p>Results are estimates from what you bring (a datasheet, a device file or your own measurements), stated assumptions and simplified models. They can be wrong. Check them against the manufacturer's data and measure on real hardware before you rely on them.</p></details><button type="button" class="top-button reset" data-start-over aria-label="Reset the simulation" title="Clear everything entered and start again">${icon("rotate-clockwise")}<span>Reset</span></button></header>
<dialog id="equations" aria-labelledby="equations-title"><div class="dialog-head"><h2 id="equations-title">How the results are worked out</h2><button type="button" class="ghost" data-close-equations>${icon("x")}Close</button></div><p class="lead">Every figure on this page comes from these equations and from the values read from your device. Nothing else is fitted or tuned.</p><div id="equations-body"></div></dialog>
`;
  // The steps, the drawing and the form are put on the page only once they can be drawn in
  // full: an empty frame filled a moment later pushes everything below it down.
  const frame = `<nav id="rail" aria-label="Steps"></nav>
<main id="stage"><p id="verdict-strip" class="verdict-strip" aria-hidden="true"></p><div id="plate" class="plate" tabindex="0" role="group" aria-label="Power stage drawing"></div><p class="swipe-hint">${icon("arrow-right")}Slide the drawing sideways to see the motor.</p><div id="switcher" class="switcher"></div><dl id="readouts" class="readouts" aria-live="polite"></dl><div id="compare-table" class="compare-table" aria-live="polite"></div><section id="pwm" class="pwm-view" aria-label="Switching periods"></section></main>
<section id="panel" aria-label="Current step"></section>`;
  let engine: Awaited<ReturnType<typeof boot>>;
  try {
    engine = await boot((text) => { starting = text; if (document.querySelector("#stage")) renderStage(); });
  } catch (e) {
    app.innerHTML = `<div class="dead"><h1>motionsim could not start</h1><p>${escape((e as Error).message)}</p><p>Reload the page. If you run it yourself, start it with <code>motionsim serve</code>.</p></div>`;
    return;
  }
  setup = engine.setup;
  // In the browser the forms are drawn at once from a packed copy of the first screen,
  // while the engine loads behind them.
  const inBrowser = engine.mode === "browser";
  if (inBrowser) starting = "Fetching the Python runtime";
  state = restore(setup, inBrowser);
  state.reached = Math.max(state.reached ?? 0, state.step);
  app.insertAdjacentHTML("beforeend", frame);
  wire();
  renderRail();
  renderPanel(true);
  renderStage();
  void suggestFor();
  if (state.step >= LOAD) void presetsFor();
  history.replaceState({ step: state.step }, "");
  if (inBrowser) {
    try {
      await engine.ready;
      setup = await api.setup();
    } catch (e) {
      starting = null;
      fault = `The engine could not start in this browser: ${(e as Error).message}`;
      renderStage();
      renderPanel(true);
      return;
    }
    starting = null;
    const known = new Set(setup.devices.map((d) => d.id));
    state.devices = state.devices.filter((d) => known.has(d));
    state.added = state.added.filter((d) => known.has(d));
    if (state.focus && !known.has(state.focus)) state.focus = null;
    renderPanel(true);
  }
  if (state.step === MOTOR) fitFor(true);
  await compute();
}

void start();
