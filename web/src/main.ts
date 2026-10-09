import "./style.css";
import { api, boot, Refused } from "./api";
import type { Candidate, Check, Cycle, LoadPreset, MapGrid, ModelTable, Proposal, Reading, ReadOutcome, Recommendation, Setup, Stage, Suggest, Advice } from "./api";
import { AT_MOTOR, compareBars, heatMap, lossBar, motionPreview, overlayChart, pwmChart, tableChart, timeChart } from "./charts";
import type { MapAxes } from "./charts";
import { degrees, eng, escape, percent, sentence, sig, watts } from "./format";
import { equationsPage } from "./equations";
import { icon } from "./icons";
import { schematic } from "./schematic";
import { motionRequest, request, restore, save } from "./state";
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
const TABS: [Tab, string][] = [["proposal", "Verdict"], ["losses", "Losses"], ["motion", "Motion"], ["map", "Map"], ["settings", "Settings"]];

let setup: Setup;
let state: State;
let stage: Stage | null = null;
let advice: Advice | null = null;
let proposal: Proposal | null = null;
let blocked: Refused | null = null;
let fault: string | null = null;
let cycle: Cycle | Refused | null = null;
let grid: MapGrid | Refused | null = null;
let advised: Recommendation[] | Refused | null = null;
let reading: { name: string; outcome?: ReadOutcome; refused?: Refused } | null = null;
/** What suits the device under test: the supply, and how each kind of motor fits it. */
let suggestion: { id: string; data: Suggest } | null = null;

/** Ask what suits the device under test. Until the user has touched the motor or the
 *  conditions, start them where their device belongs: the recommended kind of motor, its
 *  example wound for the supply the device suits, and that supply. */
async function suggestFor(): Promise<void> {
  const id = state.devices[0];
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
  if (state.devices[0] !== id) return; // the choice moved on while this was asked
  const motors = suggestion.data.motors;
  if (!state.motorTouched && changed) {
    state.kind = Object.keys(motors).find((k) => motors[k].fit === "recommended") ?? state.kind;
    for (const [k, m] of Object.entries(motors)) state.motors[k] = { ...state.motors[k], ...m.values };
    const start = motors[state.kind].start;
    Object.assign(state.conditions, { v_dc: start.v_dc, rpm: start.rpm, torque: start.torque, f_khz: start.f_sw / 1000, pwm: "" });
    save(state);
  }
  if (!changed) return;
  if (state.step === MOTOR || state.step === SUPPLY) renderPanel(true);
  renderStage();
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

/** Fetch the loads usual for this motor at this design point. Until the user has picked or
 *  edited a load, the most usual one is theirs to start from. */
async function presetsFor(): Promise<void> {
  const c = state.conditions;
  const key = `${state.kind}|${c.rpm}|${c.torque}|${c.v_dc}`;
  if (presets?.key === key) return;
  try {
    presets = { key, list: (await api.loads(state.kind, c.rpm, c.torque, c.v_dc)).loads };
  } catch {
    return; // a design point that is not a number yet: the step says so itself
  }
  if (presets.key !== `${state.kind}|${state.conditions.rpm}|${state.conditions.torque}|${state.conditions.v_dc}`) return;
  // The loads are sized from the design point, so when that moves they are sized again:
  // the load the user picked, unless they have put in figures of their own, and the ones
  // set beside it to compare. A load not offered for this motor gives way to the usual one.
  if (!state.loadTouched) applyPreset(presets.list.find((p) => p.id === state.loadKind) ?? presets.list[0]);
  const fresh = presets.list;
  state.loadSet = state.loadSet.flatMap((item) => {
    if (item.id.startsWith("own-")) return [item];
    const now = fresh.find((p) => p.id === item.id);
    return now ? [itemOf(now)] : [];
  });
  cycles.clear();
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
let missionFault: Refused | null = null;
let pwmOpen: boolean | null = null; // whether the user has the period drawing open; null: not chosen, so by screen width
let pending: AbortController | null = null;
let starting: string | null = null; // what the engine is doing while it loads in the browser
let focusPicked = false; // the user chose which device the drawing shows
let timer = 0;
const loading = new Set<string>();

const $ = <T extends HTMLElement = HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- small pieces ---------- */

function field(path: string, label: string, value: string | number, unit: string, help = "", attrs = ""): string {
  const id = `f-${path.replace(/\W+/g, "-")}`;
  const marked = blocked && blocked.field && path.endsWith(blocked.field) ? " is-wrong" : "";
  return `<div class="field${marked}"><label for="${id}">${escape(label)}</label><div class="control"><input id="${id}" data-bind="${path}" inputmode="decimal" autocomplete="off" value="${escape(String(value ?? ""))}" ${attrs} ${help ? `aria-describedby="${id}-h"` : ""}/>${unit ? `<span class="unit">${escape(unit)}</span>` : ""}</div>${help ? `<p class="help" id="${id}-h">${escape(help)}</p>` : ""}</div>`;
}

function select(path: string, label: string, value: string, options: [string, string][], help = ""): string {
  const id = `f-${path.replace(/\W+/g, "-")}`;
  return `<div class="field"><label for="${id}">${escape(label)}</label><div class="control"><select id="${id}" data-bind="${path}">${options.map(([v, t]) => `<option value="${escape(v)}"${v === value ? " selected" : ""}>${escape(t)}</option>`).join("")}</select></div>${help ? `<p class="help">${escape(help)}</p>` : ""}</div>`;
}

const verdict = (level: string) =>
  `<span class="verdict ${level}">${icon(level === "ok" ? "circle-check" : level === "fail" ? "circle-x" : "alert-triangle")}${level === "ok" ? "Passes" : level === "fail" ? "Ruled out" : "Cautions"}</span>`;

const checkList = (checks: Check[]) =>
  `<ul class="checks">${checks.map((c) => `<li class="${c.level}">${icon(c.level === "ok" ? "check" : c.level === "fail" ? "x" : "alert-triangle")}<span><b>${escape(sentence(c.topic))}.</b> ${escape(sentence(c.message))}</span></li>`).join("")}</ul>`;

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
  $("#plate").innerHTML = schematic({
    kind: state.kind, stage: state.reached >= SUPPLY ? stage : null, result: r,
    tSink: state.conditions.t_sink, vdc: state.reached >= SUPPLY ? state.conditions.v_dc : null,
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
  if (!chosen.length) {
    cells = readout("Start here", "Choose the device to test", "Step 1. Nothing is worked out until you have brought a part.");
  } else if (blocked && state.reached >= SUPPLY) {
    cells = readout("Power stage", "No solution", "change an input on the right");
  } else if (r) {
    const range = r.tj_range ? `${Math.round(r.tj_range[0])} to ${Math.round(r.tj_range[1])} °C across the thermal assumptions` : `${Math.round(r.tj_max - r.tj_peak)} °C under the rating`;
    const hot = r.tj_peak > r.tj_max ? "fail" : r.tj_max - (r.tj_range?.[1] ?? r.tj_peak) < 25 ? "caution" : "";
    cells =
      readout("Power-stage loss", watts(r.loss), `${many ? "" : `${c!.name}, `}${sig(r.loss / (stage?.positions ?? 6))} W a switch on average`) +
      readout("Conduction", watts(r.conduction), percent(r.conduction / Math.max(r.loss, 1e-9), 0)) +
      readout("Switching", watts(r.switching), percent(r.switching / Math.max(r.loss, 1e-9), 0), "accent") +
      readout("Hottest junction", degrees(r.tj_peak), range, hot) +
      (c?.efficiency != null ? readout("Shaft over DC power", percent(c.efficiency), "motor windings included") : "");
  } else if (starting) {
    cells = readout("Starting the engine", starting, "About 20 MB the first time, then kept by your browser. Carry on meanwhile.");
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
  const table = r && conditionsGiven() && comparing() && !(blocked && state.reached >= SUPPLY) ? compareTable() : "";
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
    return `<li class="${st}${k === state.step ? " is-current" : ""}"><button type="button" data-step="${k}" aria-label="Step ${k + 1}, ${s.name}: ${said}" title="${s.name}" ${k === state.step ? 'aria-current="step"' : ""}><span class="station">${st === "blocked" ? icon("x") : st === "done" && k !== state.step ? icon("check") : icon(s.icon)}<span class="station-number">${k + 1}</span></span><span class="step-text"><span class="step-name">${s.name}</span><span class="step-about">${st === "blocked" ? (k === DEVICE ? "Choose a part" : "Needs a change") : s.about}</span></span></button></li>`;
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
  const hint = (key: string, unit: string) => (unit === "H" && Number(v[key]) ? `That is ${eng(Number(v[key]), "H")}. ` : "");
  const fits = suggestion && suggestion.id === state.devices[0] ? suggestion.data.motors : null;
  const unusual = (k: string) => fits?.[k]?.fit === "unusual";
  const option = ([k, x]: (typeof kinds)[number]) => {
    const fit = fits?.[k];
    const tag = fit?.fit === "recommended" ? '<span class="tag recommended">Recommended for your device</span>' : "";
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
  const device = setup.devices.find((d) => d.id === state.devices[0]);
  const suits = fits && device
    ? ` Your device is rated ${Math.round(device.v_max)} V, which suits a supply of about ${Math.round(suggestion!.data.v_supply)} V; the kinds of motor usual at that voltage are listed first, and the example is wound for it.`
    : "";
  return `<h2 tabindex="-1">The motor it drives</h2><p class="lead">Pick the kind of motor, then put in its figures from the maker's data. The values shown are a made-up example to replace.${suits}</p>
<fieldset class="kinds"><legend>Kind of motor</legend>${list}</fieldset>
<div class="fields">${m.fields.map((f) => (f.options ? select(`motors.${state.kind}.${f.key}`, f.label, String(v[f.key] ?? f.options[0]), f.options.map((o) => [o, o]), f.help) : field(`motors.${state.kind}.${f.key}`, f.label, v[f.key] ?? "", f.unit, hint(f.key, f.unit) + f.help))).join("")}</div>${nextButton(MOTOR)}`;
}

/** Whether a chosen device has no tabulated switching energy, so needs its gate drive described. */
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
  return `<h4>Gate resistors</h4><p class="gate-used"><b>${head}</b> ${tag}</p><ul class="plain small">${g.lines.map((l) => `<li>${escape(sentence(l))}</li>`).join("")}</ul>${g.kind === "chosen" ? '<p class="quiet small">To use your own, give them under Supply and point, Gate drive.</p>' : ""}`;
}

const needsGate = () => setup.devices.some((d) => state.devices.includes(d.id) && d.needs_gate_drive);

function supplyPanel(): string {
  const c = state.conditions;
  const m = setup.motors[state.kind];
  const scheme = m.fixed_scheme
    ? `<p class="fact">${icon("wave-sine")}<span>Modulation: ${escape(m.fixed_scheme)}. This motor type decides it.</span></p>`
    : select("conditions.pwm", "Modulation", c.pwm, [["", `Usual for this motor (${m.default_pwm})`], ...setup.pwm.map((p) => [p, p] as [string, string])], "Leave this on the usual scheme unless you know your controller uses another.");
  return `<h2 tabindex="-1">Supply and design point</h2><p class="lead">The voltage you feed the power stage from, and the hardest point the motor has to hold. The device is tested here.</p>
<div class="fields">${field("conditions.v_dc", "Supply voltage", c.v_dc, "V")}${select("supply", "Supply", state.supply, [["one-way", "Power supply"], ["battery", "Battery"]], "A battery takes braking energy back. A power supply does not.")}
${field("conditions.rpm", "Speed", c.rpm, "rpm")}${field("conditions.torque", "Torque", c.torque, "N·m")}
${field("conditions.f_khz", "Switching frequency", c.f_khz, "kHz", "Above 20 kHz is inaudible. Lower loses less.")}${field("conditions.parallel", "Devices in parallel", c.parallel, "a switch", "1 unless you put several side by side to share the current.")}${field("conditions.t_sink", "Heatsink temperature", c.t_sink, "°C", "What the heatsink sits at when warm. 60 is a fair start.")}<div class="wide">${scheme}</div></div>
${driversBuiltIn()
    ? `<details class="more"><summary>${icon("adjustments")}Dead time<span class="quiet">the gate drive is inside this module, so there is no gate voltage or resistor to set</span></summary><div class="fields">${field("conditions.t_dead_ns", "Dead time", c.t_dead_ns, "ns")}</div></details>`
    : `<details class="more"${c.v_drive || c.rg_on ? " open" : ""}><summary>${icon("adjustments")}Gate drive and layout<span class="quiet">${needsGate() ? "left empty, the gate resistors with the lowest loss within the limits are chosen for you" : "optional for your device"}</span></summary><div class="fields">
${field("conditions.v_drive", "Gate drive voltage", c.v_drive, "V", "Often 10 to 12 for silicon, 15 to 20 for SiC, 5 for GaN.")}${field("conditions.t_dead_ns", "Dead time", c.t_dead_ns, "ns")}
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
<h2>What was tested</h2>${rows([["Device", `${escape(c.name)}, ${escape(c.technology)}${device ? `, ${sig(device.v_max)} V, ${sig(device.i_nominal)} A. ${packaging(device)}` : ""}`], ["Devices in parallel", String(k.parallel || 1)], ["Motor", `${escape(m.label)}: ${m.fields.map((f) => `${escape(f.label)} ${escape(String(state.motors[state.kind][f.key] ?? ""))} ${escape(f.unit)}`).join("; ")}`], ["Supply", `${sig(k.v_dc)} V, ${state.supply === "battery" ? "battery" : "power supply"}`], ["Design point", `${sig(k.rpm)} rpm, ${sig(k.torque)} N·m`], ["Switching", `${sig(k.f_khz)} kHz, ${escape(stage?.scheme ?? "")}`], ["Heatsink", `${sig(k.t_sink)} °C`], ["Gate drive", escape(c.gate.lines.map(sentence).join(". "))]])}
<h2>Result at the design point</h2>${rows([["Verdict", { ok: "Suits", caution: "Can do this, with cautions", fail: "Does not pass" }[c.level] ?? c.level], ["Power-stage loss", watts(r.loss)], ["Conduction", `${watts(r.conduction)} (${percent(r.conduction / Math.max(r.loss, 1e-9), 0)})`], ["Switching", `${watts(r.switching)} (${percent(r.switching / Math.max(r.loss, 1e-9), 0)})`], ["Hottest junction", `${degrees(r.tj_peak)}${r.tj_range ? `, ${Math.round(r.tj_range[0])} to ${Math.round(r.tj_range[1])} °C across the thermal assumptions` : ""}; rating ${degrees(r.tj_max)}`], ["Shaft over DC power", c.efficiency != null ? percent(c.efficiency) : "n/a"]])}
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

/** Thermal-cycling life, from the swings of the temperature trace. */
function lifeBlock(c: Cycle): string {
  const l = c.life;
  if (!l) return "";
  const big = (v: number) => (v >= 1e9 ? `${sig(v / 1e9, 2)} billion` : v >= 1e6 ? `${sig(v / 1e6, 2)} million` : v >= 1e3 ? `${sig(v / 1e3, 2)} thousand` : sig(v, 2));
  const body = l.repeats === null
    ? `<li>The junction temperature swings by less than 1 °C through this motion: thermal cycling wears nothing out here.</li>`
    : `<li>About <b>${big(l.repeats)}</b> repeats of this motion${l.hours !== null ? `, which back to back is about ${big(l.hours)} hours` : ""}.</li><li>${percent(l.swing_share, 0)} of the wear comes from one swing of ${sig(l.swing, 2)} °C about ${Math.round(l.swing_mean)} °C. A smaller swing lasts far longer: halving it gives about thirty times the life.</li>`;
  return `<h4>Life under thermal cycling</h4><ul class="plain small">${body}<li>A generic model for modules with aluminium bond wires (LESIT). A real part may last several times longer or shorter; use the maker's power-cycling curve where there is one.</li></ul>`;
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
    const top = Math.max(...m.rpm.map(Math.abs));
    const peak = Math.max(...m.torque.map(Math.abs));
    return `<div class="read-result" role="status"><p>${icon("circle-check")}<b>${escape(m.name)}</b> is the motion: ${m.time.length} instants over ${sig(m.time[m.time.length - 1] - m.time[0])} s, up to ${sig(top)} rpm and ${sig(peak)} N·m at the motor.</p><p class="quiet">The load figures below are not used while a mission profile is set.</p><p><button type="button" class="ghost" data-drop-mission>${icon("x")}Take the profile out</button></p></div>${missionFault ? refusal(missionFault) : ""}`;
  }
  return `<details class="more"${missionFault ? " open" : ""}><summary>${icon("upload")}Bring a mission profile<span class="quiet">measured or planned speed and torque, as a CSV file</span></summary><p class="quiet">Three columns, one row an instant: time in seconds, motor speed in rpm, motor torque in N·m. A first row of headings is fine. It takes the place of the load and the motion below.</p><label class="ghost add-part"><input type="file" data-mission-file accept=".csv,text/csv,.txt" class="sr"/>${icon("upload")}Choose a CSV file</label>${missionFault ? refusal(missionFault) : ""}</details>`;
}

/** Read a mission profile: comma, semicolon or tab between columns; a heading row is skipped. */
async function addMission(file: File): Promise<void> {
  missionFault = null;
  const rows = (await file.text()).split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    .map((line) => line.split(/[;,\t]/).map((cell) => Number(cell.trim())));
  const data = rows.filter((r) => r.length >= 3 && r.slice(0, 3).every(Number.isFinite));
  const forward = data.every((r, k) => k === 0 || r[0] > data[k - 1][0]);
  if (data.length < 2 || !forward) {
    missionFault = new Refused(data.length < 2 ? "that file does not hold rows of time, speed and torque" : "the time column does not run forward",
      "give three columns of numbers, one row an instant, sorted by time", "mission");
  } else {
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
  return `<h2 tabindex="-1">What the motor moves</h2><p class="lead">Pick the kind of load, then change its figures to yours. Each starts sized to your motor's speed and torque, so it runs as it is, and the tool follows temperature through the whole motion.</p>
${missionBlock()}${state.mission ? "" : kinds}
${chosen && !state.mission && !state.loadTouched ? `<p class="fact">${icon("info-circle")}<span>${escape(chosen.link)}</span></p>` : ""}
${chosen && !state.mission && state.loadTouched ? `<p class="fact">${icon("info-circle")}<span>These are your own figures now: they stay as they are when the motor or the design point changes. <button type="button" class="link" data-resize-load>Size this load to the motor again</button></span></p>` : ""}
<div class="fields">${shown.map(one).join("")}</div>
<details class="more"><summary>${icon("adjustments")}Every load figure<span class="quiet">the ones this kind of load does not use</span></summary><div class="fields">${rest.map(one).join("")}</div></details>
<h3>The motion</h3><p class="quiet">Load speed, in straight lines between the values you give.</p>
<div id="motion-preview"></div>
<table class="segments"><thead><tr><th scope="col">Lasts</th><th scope="col">From</th><th scope="col">To</th><th scope="col"><span class="sr">Remove</span></th></tr></thead><tbody>${state.segments.map((s, k) => `<tr><td><div class="control"><input aria-label="Stretch ${k + 1} duration in seconds" data-bind="segments.${k}.duration" inputmode="decimal" value="${s.duration}"/><span class="unit">s</span></div></td><td><div class="control"><input aria-label="Stretch ${k + 1} starting speed" data-bind="segments.${k}.speed_start" inputmode="decimal" value="${s.speed_start}"/><span class="unit">rpm</span></div></td><td><div class="control"><input aria-label="Stretch ${k + 1} ending speed" data-bind="segments.${k}.speed_end" inputmode="decimal" value="${s.speed_end}"/><span class="unit">rpm</span></div></td><td><button type="button" class="icon-button" data-remove="${k}" aria-label="Remove stretch ${k + 1}" ${state.segments.length < 2 ? "disabled" : ""}>${icon("trash")}</button></td></tr>`).join("")}</tbody></table>
<button type="button" class="ghost" data-add>${icon("plus")}Add a stretch</button>
${startBlock()}
<details class="more"${state.sink.rth || state.sink.c_link_uf ? " open" : ""}><summary>${icon("temperature")}Heatsink and DC link<span class="quiet">optional</span></summary><div class="fields">
${field("sink.rth", "Heatsink to air", state.sink.rth, "K/W", "With its heat capacity, the heatsink warms up during the motion.")}${field("sink.capacity", "Heatsink heat capacity", state.sink.capacity, "J/K", "About 900 for each kilogram of aluminium.")}
${field("sink.precharge", "Precharge resistance", state.sink.precharge, "Ω", "What limits the current when the link is first charged.")}${field("sink.t_ambient", "Air temperature", state.sink.t_ambient, "°C")}${field("sink.c_link_uf", "DC-link capacitance", state.sink.c_link_uf, "µF", "Braking energy charges it when the supply cannot take it back.")}
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
      return `<li class="device${on ? " is-on" : ""}"><label><input type="checkbox" data-device="${escape(d.id)}" ${on ? "checked" : ""}/><span class="device-name">${escape(d.name)}${d.example ? ' <span class="tag">made-up part</span>' : ""}</span><span class="device-facts">${escape(d.technology)} · ${sig(d.v_max)} V · ${sig(d.i_nominal)} A</span><span class="device-facts kind-of-part">${packaging(d)}</span><span class="device-facts">Switching loss: ${escape(d.switching)}. Model built from ${escape(d.support)}.</span></label><button type="button" class="link review-link" data-forget-device="${escape(d.id)}">Take off this page</button><button type="button" class="link review-link" data-review="${escape(d.id)}" aria-expanded="${review?.id === d.id}">${review?.id === d.id ? "Hide what was read" : "Check what was read"}</button></li>`;
    })
    .join("");
  const accepts = canRead ? "its datasheet (PDF), a device file (.yaml)" : "a device file (.device.yaml)";
  const drop = reading && !reading.outcome && !reading.refused
    ? waiting(/\.pdf$/i.test(reading.name) ? `Reading ${reading.name}. This takes a minute or two.` : `Adding ${reading.name}.`)
    : `<label class="drop big" id="drop"><input type="file" id="part-file" accept="${canRead ? "application/pdf," : ""}.yaml,.yml,.json" class="sr"/>${icon("upload")}<span><b>Add your device</b> Drop ${accepts}, or your own double-pulse measurements (.json). Or press to choose a file.</span>${canRead ? '<span class="quiet">Reading a datasheet is a paid language-model call from this machine, with your key. It takes a minute or two.</span>' : ""}</label>`;
  let how: string;
  if (canRead) {
    how = "";
  } else if (local) {
    how = `<details class="more"><summary>${icon("info-circle")}How to get a device file from a datasheet</summary><p class="quiet">Reading a datasheet needs a language-model key, so it is done on your own machine, not on this page. With the tool installed:</p><p><code>motionsim extract part.pdf -o part.observations.yaml</code><br/><code>motionsim build part.observations.yaml -o part.device.yaml</code></p><p class="quiet">Then drop <code>part.device.yaml</code> above. It stays in this browser and is sent nowhere. Or run <code>motionsim serve</code> to drop the PDF straight onto the page.</p></details>`;
  } else {
    how = `<details class="more" open><summary>${icon("info-circle")}To read a datasheet PDF here<span class="quiet">it needs your own key, on your own machine</span></summary><p class="quiet">Reading a datasheet is done by a language model, and that is a paid call. It is made from this machine with your own Anthropic API key, straight to Anthropic: this tool has no server of its own, keeps no key and sees none of your files. That is why it runs on your machine.</p><p class="quiet">Set the key in the terminal, then start the page again:</p><p><code>export ANTHROPIC_API_KEY=your-key</code><br/><code>motionsim serve</code></p><p class="quiet">Without a key everything else works: device files, your own measurements, and the made-up part.</p></details>`;
  }
  const outcome = reading?.refused
    ? refusal(reading.refused)
    : reading?.outcome
      ? `<div class="read-result" role="status"><p>${icon("circle-check")}<b>${escape(reading.outcome.device.name)}</b> ${reading.outcome.read.values ? `read: ${reading.outcome.read.values} table values and ${reading.outcome.read.curves} curves.` : "added."}</p>${reading.outcome.read.from_images ? `<p class="quiet">${reading.outcome.read.from_images} pages of this datasheet are pictures with no text. Their values were read from the picture, which is less sure than reading printed text: check the ratings against the datasheet.</p>` : ""}${reading.outcome.read.flagged.length ? `<p class="quiet">Set aside, because a check did not pass:</p><ul class="plain small">${reading.outcome.read.flagged.map((f) => `<li>${escape(f.what)}, page ${f.page}: ${escape(f.why)}</li>`).join("")}</ul>` : ""}</div>`
      : "";
  const list = parts.length
    ? `<h3>Your ${parts.length > 1 ? "parts" : "part"}</h3><p class="quiet">${parts.length > 1 ? "Tick the ones to test. More than one are compared under the same conditions." : "Ticked: this is the part under test."}</p><ul class="devices">${rows}</ul>`
    : "";
  const again = state.reached > DEVICE || state.added.length
    ? `<p class="aside"><button type="button" class="link" data-start-over>Start over: clear everything entered on this page</button></p>`
    : "";
  const example = setup.devices.some((d) => d.example) && !state.devices.includes("example")
    ? `<p class="aside"><button type="button" class="link" data-example>No part to hand? Try the tool with a made-up one.</button></p>`
    : "";
  return `<h2 tabindex="-1">The device you want to test</h2><p class="lead">Start with the power transistor or module you have in mind. Add its datasheet or your own data for it. Nothing is listed here that you did not bring.</p>
${drop}${outcome}${how}${list}${reviewBlock()}${example}${again}${nextButton(DEVICE)}`;
}

/* ---------- results ---------- */

function proposalTab(): string {
  if (!state.devices.length) return `<p class="empty">${icon("cpu")}No device is chosen. Go back to step 1 and tick the part you want to test.</p>`;
  if (!proposal) return waiting("Working out the losses.");
  const rows = proposal.candidates
    .map((c, k) => {
      const r = c.result;
      return `<details class="candidate ${c.level}"${c.id === focused()?.id ? " open" : ""}><summary data-focus="${escape(c.id)}"><span class="rank">${k + 1}</span><span class="cand-name">${escape(c.name)}<span class="quiet">${escape(c.technology)}</span></span><span class="num loss"><span class="cell-label">Loss </span>${r ? watts(r.loss) : "–"}</span><span class="num junction"><span class="cell-label">Junction </span>${r ? degrees(r.tj_peak) : "–"}</span><span class="num still"><span class="cell-label">Held still </span>${c.stall_tj != null ? degrees(c.stall_tj) : "–"}</span>${verdict(c.level)}</summary>
<div class="cand-body">${c.problem ? `<p class="fix"><b>${escape(sentence(c.problem))}.</b> ${escape(sentence(c.fix))}${c.fix ? "." : ""}</p>` : ""}${gateBlock(c)}${c.needs.length ? `<h4>What it needs around it</h4><ul class="plain">${c.needs.map((n) => `<li>${escape(sentence(n))}</li>`).join("")}</ul>` : ""}${c.checks.length ? `<h4>Checks</h4>${checkList(c.checks)}` : ""}</div></details>`;
    })
    .join("");
  const single = proposal.candidates.length === 1;
  const only = proposal.candidates[0];
  const headline = single
    ? only.level === "ok" ? `${only.name} suits this motor and these conditions.`
      : only.level === "caution" ? `${only.name} can do this, with cautions to read below.`
      : `${only.name} does not suit this motor and these conditions.`
    : null;
  const lead = headline ? `<p>${escape(headline)}</p>` : proposal.explain.map((l) => `<p>${escape(l)}</p>`).join("");
  return `<div class="explain">${lead}</div>
<div class="cand-head" aria-hidden="true"><span></span><span>Device</span><span class="num">Loss</span><span class="num">Junction</span><span class="num">Held still</span><span>Verdict</span></div>${rows}${adviceBlock()}`;
}

function lossesTab(): string {
  const c = focused();
  const r = c?.result;
  if (!r) return `<p class="empty">${icon("flame")}${c?.problem ? escape(sentence(c.problem)) + ". " + escape(sentence(c.fix)) + "." : "Choose a device to see where its loss goes."}</p>`;
  const hasDiode = r.hottest.diode_conduction + r.hottest.diode_recovery > 0;
  const positions = r.positions.length > 1
    ? `<h4>By position</h4><table class="data"><thead><tr><th scope="col">Position</th><th scope="col" class="num">Loss</th><th scope="col" class="num">Junction</th></tr></thead><tbody>${r.positions.map((p) => `<tr><td>${p.count} × ${escape(p.name)}</td><td class="num">${sig(p.total)} W</td><td class="num">${degrees(p.tj)}</td></tr>`).join("")}</tbody></table>`
    : "";
  const support = { interpolated: "Inside the datasheet's own curves.", extrapolated: "Partly outside the datasheet's data.", assumed: "Partly on table points with an assumed shape between them." }[r.validity] ?? r.validity;
  const list = (title: string, items: string[]) => (items.length ? `<details class="more"><summary>${title}<span class="quiet">${items.length}</span></summary><ul class="plain small">${items.map((n) => `<li>${escape(sentence(n))}</li>`).join("")}</ul></details>` : "");
  const compared = series();
  const side = compared.length < 2 ? ""
    : state.compare === "devices"
      ? `<h3>Loss of each device</h3>${compareBars(compared.map((x) => ({ name: x.name, parts: [{ value: x.candidate!.result!.conduction, tone: "cond" }, { value: x.candidate!.result!.switching, tone: "sw" }] })), "W")}<ul class="legend inline"><li><span class="key cond"></span>conduction</li><li><span class="key sw"></span>switching</li></ul>`
      : `<h3>Mean loss under each load</h3>${compareBars(compared.map((x) => { const g = cycles.get(x.key); return { name: x.name, parts: [{ value: g && !(g instanceof Refused) ? g.summary.mean_loss ?? 0 : 0, tone: "cond" }] }; }), "W")}`;
  return `${side}<h3>${escape(c!.name)}: one switch position</h3><p class="quiet">The hottest position. Conduction is the price of carrying current; switching is paid ${Math.round(state.conditions.f_khz * 1000).toLocaleString("en-US")} times a second.</p>
${lossBar(r.hottest, hasDiode)}${positions}
<h4>What this rests on</h4><p class="fact ${r.validity === "interpolated" ? "" : "warn"}">${icon(r.validity === "interpolated" ? "circle-check" : "alert-triangle")}<span>${support}</span></p>
${list("Where the data runs out", r.notes)}${list("Thermal values the tool had to compute", r.assumptions)}${list("Left out of the model", r.limits)}${list("Rating warnings", r.warnings)}`;
}

function motionTab(): string {
  if (!focused()?.result) return `<p class="empty">${icon("route")}Choose a device in step 1 first.</p>`;
  if (loading.has("cycle") || cycle === null) return waiting("Following the motion through time.");
  if (cycle instanceof Refused) return refusal(cycle);
  const s = cycle.summary;
  const saved = (s.forever ?? 0) - (s.peak ?? 0);
  const list = series();
  const drawn = list.map((x) => ({ x, g: cycles.get(x.key) })).filter((p): p is { x: Series; g: Cycle } => !!p.g && !(p.g instanceof Refused));
  const side = list.length < 2 ? ""
    : `<h3>${state.compare === "devices" ? "Each device through the motion" : "Each load's motion"}</h3>${drawn.length ? overlayChart(drawn.map((p) => ({ name: p.x.name, time: p.g.time, tj: p.g.tj })), Math.max(...drawn.map((p) => p.g.summary.tj_max ?? 150))) + legendOf(drawn.map((p) => p.x.name)) : waiting("Following each one through its motion.")}${list.filter((x) => cycles.get(x.key) instanceof Refused).map((x) => `<p class="fact warn">${icon("alert-triangle")}<span>${escape(x.name)}: ${escape(sentence((cycles.get(x.key) as Refused).reason))}.</span></p>`).join("")}`;
  return `${side}<h3>${escape(focused()!.name)} through the motion</h3>
<p class="quiet">The hottest junction reaches <b>${degrees(s.peak!)}</b>.${saved > 0.5 ? ` Solving each instant as if it lasted forever would say ${degrees(s.forever!)}: short peaks do not have time to heat the chip fully.` : ""}</p>
${timeChart(cycle)}
<dl class="facts"><div><dt>Lasts</dt><dd>${sig(s.duration!)} s</dd></div><div><dt>Mean loss</dt><dd>${watts(s.mean_loss!)}</dd></div><div><dt>Torque, rms</dt><dd>${sig(s.rms_torque!)} N·m</dd></div><div><dt>Energy to the shaft</dt><dd>${sig(s.shaft_energy!)} J</dd></div><div><dt>Energy lost</dt><dd>${sig(s.loss_energy!)} J</dd></div><div><dt>Returned by braking</dt><dd>${sig(s.returned ?? 0)} J</dd></div></dl>
${cycle.start.applies !== "none" || state.kind === "stepper" ? `<h4>Starting</h4><ul class="plain small">${cycle.start.lines.map((l) => `<li>${escape(sentence(l))}</li>`).join("")}</ul>` : ""}
${cycle.inrush ? `<h4>Charging the DC link at power-up</h4><ul class="plain small"><li>The link stores ${sig(cycle.inrush.energy)} J, and whatever limits the charging current absorbs as much again.</li><li>${cycle.inrush.peak !== null ? `Through your precharge resistance the current peaks at ${sig(cycle.inrush.peak)} A and the link is charged in about ${eng(cycle.inrush.time!, "s")}.` : "With no precharge resistance given, only the supply and the wiring limit the current. Give one in step 4 to see the peak."}</li></ul>` : ""}
${lifeBlock(cycle)}
<h4>Checks over the whole motion</h4>${checkList(cycle.checks)}
<p class="quiet">Change the load or the motion in step 4 and this redraws.</p>`;
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
  if (!focused()?.result) return `<p class="empty">${icon("map-2")}Choose a device in step 1 first.</p>`;
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
    body = `<div class="maps">${list.map((x) => { const g = grids.get(x.key); return `<figure class="map-one"><figcaption>${escape(x.name)}</figcaption>${g === undefined ? waiting("Solving this map.") : g instanceof Refused ? refusal(g) : heatMap(g, state.metric, atLoad ? load! : AT_MOTOR, true)}</figure>`; }).join("")}</div><p class="quiet small">Across each map: ${(atLoad ? load! : AT_MOTOR).speedLabel}. Up: ${(atLoad ? load! : AT_MOTOR).torqueLabel}.</p>`;
    return `<h3>Each device over the motor's range</h3>${controls}${side}<div id="map-body">${body}</div>`;
  }
  return `<h3>${escape(focused()!.name)} over the motor's range</h3>${controls}${side}<div id="map-body">${body}</div>`;
}

function settingsTab(): string {
  if (!focused()?.result) return `<p class="empty">${icon("settings")}Choose a device in step 1 first.</p>`;
  if (loading.has("recommend") || advised === null) return waiting("Working out starting values.");
  if (advised instanceof Refused) return refusal(advised);
  const names: Record<string, string> = { "gate resistors": "Gate resistors", "dead time": "Dead time", modulation: "Modulation", heatsink: "Heatsink" };
  const icons: Record<string, string> = { "gate resistors": "adjustments", "dead time": "ruler-measure", modulation: "wave-sine", heatsink: "temperature" };
  const value = (r: Recommendation): string => {
    const v = r.value;
    if (r.topic === "gate resistors" && v.rg_on) return `${sig(v.rg_on, 2)} Ω on, ${sig(v.rg_off, 2)} Ω off`;
    if (r.topic === "dead time" && v.t_dead) return eng(v.t_dead, "s", 2);
    if (r.topic === "heatsink" && v.rth_sink) return `${sig(v.rth_sink, 2)} K/W or lower`;
    if (r.topic === "modulation") return v.saving ? `${sig(v.saving)} W to save` : "Keep the usual scheme";
    return "Needs more from you";
  };
  return `<h3>Starting values for ${escape(focused()!.name)}</h3><p class="quiet">For a first prototype. Settle them on the bench, with a probe on the switch.</p>
${advised.map((r) => `<section class="rec${Object.keys(r.value).length ? "" : " open-question"}"><h4>${icon(icons[r.topic] ?? "settings")}${names[r.topic] ?? sentence(r.topic)}<span class="rec-value">${escape(value(r))}</span></h4><ul class="plain small">${r.lines.map((l) => `<li>${escape(sentence(l))}</li>`).join("")}</ul></section>`).join("")}`;
}

/** What is being compared: up to five devices on the load of step 4, or up to five loads
 *  on the device under test. One or the other; both at once is too much to read. */
interface Series { key: string; name: string; candidate: Candidate | null; item: LoadItem | null }

function series(): Series[] {
  if (state.compare === "loads") {
    const now = state.mission ? state.mission.name : state.loadTouched ? "Your load" : presets?.list.find((p) => p.id === state.loadKind)?.label ?? "Your load";
    return [{ key: "now", name: `${now} (step 4)`, candidate: focused(), item: null },
      ...state.loadSet.slice(0, MOST - 1).map((item) => ({ key: item.id, name: item.label, candidate: focused(), item }))];
  }
  return (proposal?.candidates ?? []).filter((c) => c.result).slice(0, MOST).map((c) => ({ key: c.id, name: c.name, candidate: c, item: null }));
}

const comparing = () => series().length > 1;

/** The main figures, one column for each thing compared. Devices are compared at the design
 *  point; loads are compared over their motion, since the design point is the same for all. */
function compareTable(): string {
  const list = series();
  const head = `<thead><tr><th scope="col"><span class="sr">Figure</span></th>${list.map((x, k) => `<th scope="col"><span class="key line s${k}"></span>${escape(x.name)}</th>`).join("")}</tr></thead>`;
  const line = (label: string, cells: string[], best = -1) => `<tr><th scope="row">${label}</th>${cells.map((v, k) => `<td class="${k === best ? "best" : ""}">${v}</td>`).join("")}</tr>`;
  if (state.compare === "devices") {
    const rs = list.map((x) => x.candidate!.result!);
    const least = rs.map((r) => r.loss).indexOf(Math.min(...rs.map((r) => r.loss)));
    return `<table class="data wide">${head}<tbody>
${line("Power-stage loss", rs.map((r) => watts(r.loss)), least)}
${line("Conduction", rs.map((r) => `${watts(r.conduction)} <span class="quiet">${percent(r.conduction / Math.max(r.loss, 1e-9), 0)}</span>`))}
${line("Switching", rs.map((r) => `${watts(r.switching)} <span class="quiet">${percent(r.switching / Math.max(r.loss, 1e-9), 0)}</span>`))}
${line("Hottest junction", rs.map((r) => `<span class="${r.tj_peak > r.tj_max ? "fail" : ""}">${degrees(r.tj_peak)}</span>`))}
${line("Shaft over DC power", list.map((x) => (x.candidate!.efficiency != null ? percent(x.candidate!.efficiency) : "n/a")))}
</tbody></table><p class="quiet small">At your design point. The lowest loss is marked.</p>`;
  }
  const got = list.map((x) => cycles.get(x.key));
  const cell = (pick: (c: Cycle) => string) => got.map((g) => (g === undefined ? "…" : g instanceof Refused ? "cannot run" : pick(g)));
  const means = got.map((g) => (g && !(g instanceof Refused) ? g.summary.mean_loss ?? Infinity : Infinity));
  const least = means.some(Number.isFinite) ? means.indexOf(Math.min(...means)) : -1;
  return `<table class="data wide">${head}<tbody>
${line("Mean loss", cell((c) => watts(c.summary.mean_loss!)), least)}
${line("Hottest junction reached", cell((c) => `<span class="${c.summary.peak! > c.summary.tj_max! ? "fail" : ""}">${degrees(c.summary.peak!)}</span>`))}
${line("Peak motor current", cell((c) => `${sig(Math.max(...c.i_peak.map((v) => v ?? 0)))} A`))}
${line("Energy lost", cell((c) => `${sig(c.summary.loss_energy!)} J`))}
${line("Returned by braking", cell((c) => `${sig(c.summary.returned ?? 0)} J`))}
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
  } else {
    items = all.map((x) => `<li class="chip-item">${escape(x.name)}${x.item ? `<button type="button" class="chip-x" data-drop-load="${escape(x.key)}" aria-label="Take ${escape(x.name)} out of the comparison">${icon("x")}</button>` : ""}</li>`).join("");
    const offered = (presets?.list ?? []).filter((p) => p.id !== state.loadKind && !state.loadSet.some((x) => x.id === p.id));
    add = full ? `<span class="quiet small">Five loads is the most.</span>`
      : `<label class="add-load"><span class="sr">Add a load to compare</span><select data-add-load><option value="">Add a load…</option><option value="own">Your own: the load of step 4 as it is now</option>${offered.map((p) => `<option value="${p.id}">${escape(p.label)}</option>`).join("")}</select></label>`;
  }
  return `<div class="compare-bar"><div class="segmented" role="group" aria-label="What is compared"><button type="button" data-compare="devices" aria-pressed="${mode === "devices"}" class="${mode === "devices" ? "is-on" : ""}">Compare devices</button><button type="button" data-compare="loads" aria-pressed="${mode === "loads"}" class="${mode === "loads" ? "is-on" : ""}">Compare loads</button></div>
<p class="quiet small">${mode === "devices" ? "Up to five devices, each on the motor and load you set." : `Up to five loads, each on ${escape(focused()?.name ?? "the device under test")}.`}</p>
<ul class="chip-list">${items}</ul>${add}${reading?.refused && mode === "devices" ? refusal(reading.refused) : ""}</div>`;
}

/** Up to five lines on one chart, told apart by weight and dash as well as by tone. */
const legendOf = (names: string[]) => `<ul class="legend inline series-legend">${names.map((n, k) => `<li><span class="key line s${k}"></span>${escape(n)}</li>`).join("")}</ul>`;

function resultsPanel(): string {
  const body = { proposal: proposalTab, losses: lossesTab, motion: motionTab, map: mapTab, settings: settingsTab }[state.tab]();
  return `<h2 tabindex="-1">Results</h2>${compareBar()}<div class="tabs" role="tablist" aria-label="Results">${TABS.map(([t, name]) => `<button type="button" role="tab" id="tab-${t}" aria-selected="${state.tab === t}" aria-controls="tab-body" tabindex="${state.tab === t ? 0 : -1}" data-tab="${t}">${name}</button>`).join("")}</div>
<div id="tab-body" role="tabpanel" aria-labelledby="tab-${state.tab}" tabindex="0">${body}</div>
<div class="actions"><button type="button" class="ghost" data-step="${LOAD}">${icon("arrow-left")}Back to the load</button><button type="button" class="ghost" data-report ${focused()?.result ? "" : "disabled"}>${icon("file-text")}Save a report</button></div>`;
}

function renderPanel(keepFocus = false): void {
  const panel = $("#panel");
  const body = [devicesPanel, motorPanel, supplyPanel, loadPanel, resultsPanel][state.step]();
  const banner = blocked && state.step !== RESULTS && state.step >= MOTOR && state.reached >= SUPPLY ? refusal(blocked) : fault ? `<div class="refusal" role="alert">${icon("alert-triangle")}<div><p><b>The engine stopped.</b> ${escape(fault)}</p><p class="fix">${api.mode() === "server" ? "Check that <code>motionsim serve</code> is still running." : "Reload the page to start it again."}</p></div></div>` : "";
  panel.innerHTML = `<div id="banner" aria-live="assertive">${banner}</div>${body}`;
  document.body.dataset.at = String(state.step);
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

function renderPreview(): void {
  const box = document.querySelector<HTMLElement>("#motion-preview");
  if (box) box.innerHTML = motionPreview(state.segments) + motionAgainstDesign();
}

/** Results change under the user's hands, so only the part that changed is redrawn. */
function refreshOutputs(): void {
  renderStage();
  renderRail();
  const banner = document.querySelector<HTMLElement>("#banner");
  if (banner) banner.innerHTML = blocked && state.step !== RESULTS && state.step >= MOTOR && state.reached >= SUPPLY ? refusal(blocked) : "";
  document.querySelectorAll<HTMLElement>(".field.is-wrong").forEach((e) => { e.classList.remove("is-wrong"); e.querySelector("input")?.removeAttribute("aria-invalid"); });
  if (blocked?.field) {
    const wanted = blocked.field === "point" ? ["conditions.rpm", "conditions.torque"] : [blocked.field];
    document.querySelectorAll<HTMLInputElement>("#panel [data-bind]").forEach((input) => {
      if (wanted.some((w) => input.dataset.bind === w || input.dataset.bind!.endsWith(`.${w}`))) {
        input.closest(".field")?.classList.add("is-wrong");
        input.setAttribute("aria-invalid", "true");
      }
    });
  }
  if (state.step === RESULTS) {
    const body = document.querySelector<HTMLElement>("#tab-body");
    if (body && !body.contains(document.activeElement)) renderPanel(true);
    else if (body && state.tab !== "map") renderPanel(true);
    else if (body) { const m = document.querySelector<HTMLElement>("#map-body"); if (m && grid && !(grid instanceof Refused)) m.innerHTML = heatMap(grid, state.metric); else renderPanel(true); }
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
      if (!focusPicked || !stillThere) state.focus = proposal.candidates.find((c) => c.result)?.id ?? null;
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
  cycles.clear(); grids.clear();
  refreshOutputs();
  if (fault) renderPanel(true);
  void deep();
}

/** The slower results, worked out only for the tab that is open. */
async function deep(): Promise<void> {
  const c = focused();
  if (state.step !== RESULTS || !c?.result || blocked) return;
  const req = { ...request(state), device: c.id };
  const run = async <T>(key: string, call: () => Promise<T>, store: (v: T | Refused) => void) => {
    // Only the results are redrawn by a slow answer: if the user has moved to another
    // step meanwhile, that step is theirs and is left as it is.
    if (loading.has(key) || state.step !== RESULTS) return;
    loading.add(key);
    renderPanel(true);
    try { store(await call()); } catch (e) { store(e instanceof Refused ? e : new Refused((e as Error).message, "", "")); }
    loading.delete(key);
    if (state.step === RESULTS) renderPanel(true);
  };
  // What is compared: each one's motion, and for devices each one's map.
  const list = series();
  const wide = list.length > 1;
  if (wide && (state.compare === "loads" || state.tab === "motion")) {
    for (const x of list) {
      if (state.step !== RESULTS) return;
      if (cycles.has(x.key) || !x.candidate) continue;
      const motion = x.item ? motionRequest({ ...state, load: x.item.load, segments: x.item.segments, mission: x.item.mission ?? null }) : motionRequest(state);
      await run(`cycle:${x.key}`, () => api.cycle({ ...request(state), device: x.candidate!.id, ...motion }), (v) => { cycles.set(x.key, v); });
      if (state.compare === "loads") renderStage();
    }
    const mine = cycles.get(state.compare === "loads" ? "now" : c.id);
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
  if (state.tab === "settings" && advised === null) await run("recommend", () => api.recommend({ ...req, t_ambient: Number(state.sink.t_ambient) || 40 }).then((x) => x.items), (v) => (advised = v));
}

/** Take in whatever the user dropped: a datasheet, a device file, or their own measurements. */
async function addPart(file: File): Promise<void> {
  reading = { name: file.name };
  renderPanel(true);
  const none = { values: 0, curves: 0, flagged: [] };
  try {
    let outcome: ReadOutcome;
    if (/\.json$/i.test(file.name)) {
      const target = state.devices.find((id) => !id.endsWith("-measured")) ?? ownDevices()[0]?.id;
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
    // The part just brought is the part under test.
    state.devices = [...new Set([...state.devices.filter((id) => id !== "example"), outcome.device.id])];
    state.added = [...new Set([...state.added.filter((id) => id !== "example"), outcome.device.id])];
    void suggestFor();
    focusPicked = false;
    schedule();
  } catch (e) {
    reading = { name: file.name, refused: e instanceof Refused ? e : new Refused((e as Error).message, api.mode() === "server" ? "check the terminal that runs motionsim serve" : "check the file and try again", "") };
  }
  renderPanel(true);
  renderRail();
  renderStage();
}

/* ---------- events ---------- */

function setPath(path: string, raw: string): void {
  const keys = path.split(".");
  let target: any = state;
  for (const k of keys.slice(0, -1)) target = target[k];
  const last = keys[keys.length - 1];
  const numeric = typeof target[last] === "number";
  target[last] = numeric ? (raw.trim() === "" || Number.isNaN(Number(raw)) ? target[last] : Number(raw)) : raw;
  if (keys[0] === "motors" && raw.trim() !== "" && !Number.isNaN(Number(raw))) target[last] = Number(raw);
  if (keys[0] === "motors" || keys[0] === "conditions") state.motorTouched = true;
  if (keys[0] === "load" || keys[0] === "segments") state.loadTouched = true;
}

function goTo(step: number): void {
  void suggestFor();
  if (step >= LOAD) void presetsFor();
  state.step = Math.max(0, Math.min(STEPS.length - 1, step));
  state.reached = Math.max(state.reached, state.step);
  save(state);
  const draw = () => { renderPanel(); renderRail(); renderStage(); };
  const doc = document as Document & { startViewTransition?: (f: () => void) => void };
  if (doc.startViewTransition && !reduced()) doc.startViewTransition(draw); else draw();
  if (conditionsGiven() && !proposal && !blocked) void compute(); else void deep();
}

function wire(): void {
  const app = $("#app");
  app.addEventListener("input", (e) => {
    const el = e.target as HTMLInputElement;
    if (!el.dataset.bind || el.tagName === "SELECT") return;
    setPath(el.dataset.bind, el.value);
    if (el.dataset.bind.startsWith("motors.")) renderStage(); // the drawing follows the motor's figures as they are typed
    if (el.dataset.bind.startsWith("segments")) renderPreview();
    if (el.dataset.bind.startsWith("map.")) { grid = null; clearTimeout(timer); timer = window.setTimeout(() => void deep(), 500); save(state); return; }
    schedule();
  });
  app.addEventListener("change", (e) => {
    const el = e.target as HTMLInputElement;
    if (el.matches("[data-load]")) {
      const picked = presets?.list.find((p) => p.id === el.value);
      if (picked) { state.loadTouched = false; state.mission = null; applyPreset(picked); cycles.clear(); renderPanel(true); renderPreview(); schedule(); document.querySelector<HTMLInputElement>(`[data-load][value="${picked.id}"]`)?.focus(); }
      return;
    }
    if (el.matches("[data-kind]")) {
      state.kind = el.value;
      state.motorTouched = true;
      const start = (suggestion?.id === state.devices[0] ? suggestion.data.motors[state.kind]?.start : null) ?? setup.motors[state.kind].start;
      Object.assign(state.conditions, { v_dc: start.v_dc, rpm: start.rpm, torque: start.torque, f_khz: start.f_sw / 1000, pwm: "" });
      state.map = { rpm_max: "", torque_max: "" };
      renderStage(); // the drawing shows the kind of motor at once
      renderPanel(true);
      document.querySelector<HTMLInputElement>(`[data-kind][value="${state.kind}"]`)?.focus();
      schedule();
    } else if (el.matches("[data-device]")) {
      const id = el.dataset.device!;
      state.devices = el.checked ? [...new Set([...state.devices, id])] : state.devices.filter((d) => d !== id);
      void suggestFor();
      focusPicked = false;
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
    } else if (el.dataset.addLoad !== undefined && el.value === "own" && series().length < MOST) {
      // The user's own load: what step 4 holds now, kept as it is. They can then change
      // step 4 and see the two side by side.
      const n = state.loadSet.filter((x) => x.id.startsWith("own-")).length + 1;
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
    } else if (el.tagName === "SELECT" && el.dataset.bind) {
      setPath(el.dataset.bind, el.value);
      if (el.dataset.bind.startsWith("motors.")) renderStage();
      if (el.dataset.bind === "start.method") { cycle = null; renderPanel(true); document.querySelector<HTMLElement>('[data-bind="start.method"]')?.focus(); }
      schedule();
    }
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
  }, true);
  app.addEventListener("click", (e) => {
    const el = (e.target as HTMLElement).closest<HTMLElement>("[data-step],[data-tab],[data-focus],[data-metric],[data-add],[data-remove],[data-example],[data-review],[data-forget-device],[data-start-over],[data-compare],[data-drop-device],[data-drop-load],[data-drop-mission],[data-resize-load],[data-report],[data-zoom],[data-equations],[data-map-at]");
    if (!el) return;
    if (el.dataset.zoom) {
      const at = ZOOMS.indexOf(state.pwmPeriods);
      state.pwmPeriods = ZOOMS[Math.min(Math.max((at < 0 ? 2 : at) + (el.dataset.zoom === "in" ? -1 : 1), 0), ZOOMS.length - 1)];
      save(state); renderStage();
      document.querySelector<HTMLElement>(`[data-zoom="${el.dataset.zoom}"]:not(:disabled), [data-zoom]:not(:disabled)`)?.focus();
      return;
    }
    if (el.dataset.equations !== undefined) { openEquations(); return; }
    if (el.dataset.forgetDevice !== undefined) {
      const id = el.dataset.forgetDevice;
      state.added = state.added.filter((d) => d !== id);
      state.devices = state.devices.filter((d) => d !== id);
      if (review?.id === id) review = null;
      if (reading?.outcome?.device.id === id) reading = null;
      focusPicked = false;
      renderPanel(true); renderRail(); renderStage(); schedule();
      return;
    }
    if (el.dataset.startOver !== undefined) {
      if (!window.confirm("Clear the parts, the motor, the load and everything else entered on this page?")) return;
      try { localStorage.clear(); } catch { /* a private window: nothing was kept */ }
      location.reload();
      return;
    }
    if (el.dataset.dropMission !== undefined) { state.mission = null; missionFault = null; cycle = null; cycles.clear(); save(state); renderPanel(true); schedule(); return; }
    if (el.dataset.report !== undefined) { void printReport(); return; }
    if (el.dataset.resizeLoad !== undefined) {
      const again = presets?.list.find((p) => p.id === state.loadKind);
      if (again) { state.loadTouched = false; applyPreset(again); cycles.clear(); renderPanel(true); renderPreview(); schedule(); }
      return;
    }
    if (el.dataset.mapAt) { state.mapAt = el.dataset.mapAt as "motor" | "load"; save(state); renderPanel(true); document.querySelector<HTMLElement>(`[data-map-at="${state.mapAt}"]`)?.focus(); return; }
    if (el.dataset.compare) { state.compare = el.dataset.compare as "devices" | "loads"; cycles.clear(); save(state); renderPanel(true); renderStage(); void deep(); document.querySelector<HTMLElement>(`[data-compare="${state.compare}"]`)?.focus(); return; }
    if (el.dataset.dropDevice !== undefined) { state.devices = state.devices.filter((d) => d !== el.dataset.dropDevice); focusPicked = false; renderPanel(true); schedule(); return; }
    if (el.dataset.dropLoad !== undefined) { state.loadSet = state.loadSet.filter((x) => x.id !== el.dataset.dropLoad); cycles.delete(el.dataset.dropLoad!); save(state); renderPanel(true); renderStage(); return; }
    if (el.dataset.review !== undefined) { void openReview(el.dataset.review); return; }
    if (el.dataset.example !== undefined) { state.devices = [...new Set([...state.devices, "example"])]; state.added = [...new Set([...state.added, "example"])]; save(state); void suggestFor(); renderPanel(true); renderRail(); renderStage(); schedule(); return; }
    if (el.dataset.step !== undefined) goTo(Number(el.dataset.step));
    else if (el.dataset.tab) { state.tab = el.dataset.tab as Tab; save(state); renderPanel(true); document.querySelector<HTMLElement>(`#tab-${state.tab}`)?.focus(); void deep(); }
    else if (el.dataset.focus) { focusPicked = true; if (state.focus !== el.dataset.focus) { state.focus = el.dataset.focus; cycle = grid = advised = null; save(state); renderStage(); if (!el.matches("summary")) renderPanel(true); void deep(); } }
    else if (el.dataset.metric) { state.metric = el.dataset.metric as State["metric"]; save(state); renderPanel(true); }
    else if (el.dataset.add !== undefined) { const last = state.segments[state.segments.length - 1]; state.segments.push({ duration: 1, speed_start: last?.speed_end ?? 0, speed_end: last?.speed_end ?? 0 }); renderPanel(true); schedule(); }
    else if (el.dataset.remove !== undefined) { state.segments.splice(Number(el.dataset.remove), 1); renderPanel(true); schedule(); }
  });
  app.addEventListener("keydown", (e) => {
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
  app.innerHTML = `<header class="top"><span class="brand">MotionSim</span><span class="top-note">Datasheets as models for motor drives</span><button type="button" class="top-button" data-equations>${icon("math-function")}<span>The equations</span></button><details class="about"><summary>${icon("info-circle")}Exploratory tool</summary><p>Results are estimates from what you bring (a datasheet, a device file or your own measurements), stated assumptions and simplified models. They can be wrong. Check them against the manufacturer's data and measure on real hardware before you rely on them.</p></details></header>
<dialog id="equations" aria-labelledby="equations-title"><div class="dialog-head"><h2 id="equations-title">How the results are worked out</h2><button type="button" class="ghost" data-close-equations>${icon("x")}Close</button></div><p class="lead">Every figure on this page comes from these equations and from the values read from your device. Nothing else is fitted or tuned.</p><div id="equations-body"></div></dialog>
<nav id="rail" aria-label="Steps"></nav>
<main id="stage"><div id="plate" class="plate" tabindex="0" role="group" aria-label="Power stage drawing"></div><p class="swipe-hint">${icon("arrow-right")}Slide the drawing sideways to see the motor.</p><div id="switcher" class="switcher"></div><dl id="readouts" class="readouts" aria-live="polite"></dl><div id="compare-table" class="compare-table" aria-live="polite"></div><section id="pwm" class="pwm-view" aria-label="Switching periods"></section></main>
<section id="panel" aria-label="Current step"></section>`;
  let engine: Awaited<ReturnType<typeof boot>>;
  try {
    engine = await boot((text) => { starting = text; renderStage(); });
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
  wire();
  renderRail();
  renderPanel(true);
  renderStage();
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
  await compute();
}

void start();
