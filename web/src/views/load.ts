import { driveAssumed } from "../drive";
import type { LoadPreset } from "../api";
import { motionPreview } from "../charts";
import { escape, num, ratio, sentence, whole } from "../format";
import { icon } from "../icons";
import type { State } from "../state";
import { plainly } from "../parse";
import { LOAD } from "../steps";
import { app, res, ui } from "../store";
import { field, fold, idOf, refusal, saidAt, select } from "./html";
import { nextButton } from "./rail";
import { isProposed } from "../engine/proposed";
import { proposalBlock } from "./proposed";

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
  tumble_mass: ["Tumbling load", "kg", "Wet laundry lifted by the drum's paddles and let fall, once a turn."],
  tumble_radius: ["Drum radius", "m", ""],
  pulsation_torque: ["Torque pulse", "N·m", "Swings above and below the steady torque once a turn of the shaft."],
  breakaway_torque: ["Break-away torque", "N·m", "Asked on top at standstill, and gone by the speed below."],
  breakaway_rpm: ["Gone by", "rpm", "At the load's shaft."],
};

/** Under the load's inertia: the sum it follows while the user has not typed their own. */
function inertiaHelp(): string {
  const { load, inertiaOwn } = app.state;
  const derived =
    load.mass > 0 && load.arm > 0 && Math.abs(load.inertia - load.mass * load.arm ** 2) < 0.01 * load.inertia;
  if (inertiaOwn || !derived) return LOAD_FIELDS.inertia[2];
  return (
    `${plainly(load.mass)} kg × (${plainly(load.arm)} m)² = ${plainly(load.inertia)} kg·m², ` +
    "from the weight on the arm. " +
    "It follows them until you type your own."
  );
}

/** The figures a load is described by when no kind of load is chosen. */
const OWN_LOAD_FIELDS = [
  "gear_ratio",
  "gear_efficiency",
  "inertia",
  "motor_inertia",
  "friction_coulomb",
  "friction_viscous",
  "mass",
  "arm",
  "start_angle_deg",
];

/** The ways a drive without flux to build can find its rotor. */
const START_METHODS: [string, string][] = [
  ["sensor", "With a position sensor (encoder or Hall)"],
  ["open_loop", "Sensorless: aligns, then ramps up open loop"],
  ["injection", "Sensorless: finds the rotor by signal injection"],
];

/** What an open-loop start holds and for how long, before normal control takes over. */
function openLoopFields(st: State["start"]): string {
  return (
    field(
      "start.current",
      "Start current",
      st.current,
      "A rms",
      "Held through alignment and the ramp. Empty: the current at your design point.",
    ) +
    field("start.align_time", "Alignment time", st.align_time, "s", "Empty: 0.5 s.") +
    field(
      "start.handover_rpm",
      "Handover speed",
      st.handover_rpm,
      "rpm",
      "Where normal control takes over. Empty: a tenth of the design speed.",
    )
  );
}

/** Starting an induction motor: only the time the flux takes to build is asked. */
function fluxStart(st: State["start"]): string {
  const help = "The flux is built before there is torque. Leave empty for three rotor time constants.";
  return field("start.flux_time", "Flux build-up time", st.flux_time, "s", help);
}

/** How the drive gets this motor going. What can be chosen depends on the kind of motor. */
function startFields(): string {
  const { state } = app;
  const st = state.start;
  const kind = state.kind;
  if (kind === "induction") return fluxStart(st);
  if (!["pmsm", "bldc", "synrm"].includes(kind)) return "";
  const open = st.method === "open_loop";
  const method = select(
    "start.method",
    "The drive starts",
    st.method,
    START_METHODS,
    "A sensorless drive that reads the back-EMF sees nothing at standstill, " +
      "so it holds a set current until the motor turns fast enough.",
  );
  return `<div class="wide">${method}</div>\n${open ? openLoopFields(st) : ""}`;
}

/** The mission profile in use, said in a sentence, with the way to take it out again. */
function missionSet(m: NonNullable<State["mission"]>): string {
  // A long log has more instants than a call takes arguments: the largest is found one by one.
  const most = (values: number[]) => values.reduce((a, b) => Math.max(a, Math.abs(b)), 0);
  const top = most(m.rpm);
  const peak = most(m.torque);
  const lasts = num(m.time[m.time.length - 1] - m.time[0]);
  return (
    `<div class="read-result" role="status"><p>${icon("circle-check")}<b>${escape(m.name)}</b> is the motion: ` +
    `${m.time.length} instants over ${lasts} s, up to ${num(top)} rpm and ${num(peak)} N·m at the motor.</p>` +
    ui.missionNotes.map((n) => `<p class="quiet">${escape(n)}</p>`).join("") +
    `<p class="quiet">The load figures below are not used while a mission profile is set.</p>` +
    `<p><button type="button" class="ghost" data-drop-mission>${icon("x")}Take the profile out</button></p></div>` +
    `${ui.missionFault ? refusal(ui.missionFault) : ""}`
  );
}

/** A mission profile in use takes the place of the load and the motion, and is said above them. */
function missionBlock(): string {
  const m = app.state.mission;
  return m ? missionSet(m) : "";
}

/** The last line of the motion: a measured or planned motion brought as a file instead. */
function missionLine(): string {
  const fault = ui.missionFault;
  return (
    `<div class="mission-line"><p class="quiet"><b>Or bring a mission profile</b>: measured or planned ` +
    `speed and torque as a CSV file, three columns, one row an instant: time in seconds, motor speed in rpm, ` +
    `motor torque in N·m. A first row of headings is fine. It takes the place of the load and the motion.</p>` +
    `<label class="ghost add-part"><input type="file" data-mission-file accept=".csv,text/csv,.txt" class="sr"/>` +
    `${icon("upload")}Choose a CSV file</label>${fault ? refusal(fault) : ""}</div>`
  );
}

/** How long a motion lasts, in minutes once it is long; the most it lasts (`upTo`) where a
 *  stretch of it ends as soon as the junction is steady. */
export function lasting(seconds: number, upTo = false): string {
  if (!(seconds > 0)) return "";
  const head = upTo ? "Up to" : "About";
  if (seconds < 120) return `${head} ${num(seconds, 2)} s`;
  const min = Math.round(seconds / 60);
  return min >= 120 ? `${head} ${num(min / 60, 2)} h` : `${head} ${min} min`;
}

/** Whether a stretch of the motion ends as soon as the junction is steady. */
type Stretch = { until_steady?: boolean };
const endsSteady = (p: { segments?: Stretch[]; phases?: { segments: Stretch[] }[] | null }): boolean =>
  [...(p.segments ?? []), ...(p.phases ?? []).flatMap((x) => x.segments)].some((x) => x.until_steady === true);

/** The motor such products usually have, and whether the user's can run the application:
 *  offered, never put in for them. */
function usualMotor(p: LoadPreset): string {
  if (!p.motor) return "";
  const m = p.motor;
  const kind = m.kind === "bldc" ? "brushless DC" : "permanent-magnet";
  const poles = Number(m.values.pole_pairs) * 2;
  const can = p.runs && !p.runs.ok ? `Your motor cannot run it: ${escape(p.runs.why)}. ` : "";
  const button =
    `<button type="button" class="ghost" data-usual-motor="${escape(p.id)}">${icon("arrow-right")}` +
    `Use the motor this application usually has</button>`;
  const said =
    `${can}Such products usually have a ${poles}-pole ${kind} motor, here wound for your ` +
    `${num(m.v_dc)} V supply and judged at ${num(m.point.rpm)} rpm and ${num(m.point.torque)} N·m. ` +
    "Using it fills in only the motor's figures and design point you have not typed yourself.";
  const sign = icon(can ? "alert-triangle" : "info-circle");
  return `<p class="fact${can ? " warn" : ""}">${sign}<span>${said} ${button}</span></p>`;
}

/** Where each figure of the application comes from: a typical product of the kind. */
function whyList(p: LoadPreset): string {
  if (!p.why?.length || !p.usage) return "";
  const use = p.usage;
  const usage = `<li>${escape(sentence(use.said))}: ${num(use.per_year)} ${use.unit} a year, for its life.</li>`;
  const lines = p.why.map((w) => `<li>${escape(sentence(w))}.</li>`).join("");
  return `<h4>Where the figures come from</h4><ul class="plain small">${lines}${usage}</ul>`;
}

/** The head of an application's one line: up to its first colon or comma. */
const firstClause = (about: string): string => about.split(/[:,] /)[0];

/** The kinds of load this motor commonly drives, one to pick: a name, one line and how long its
 *  motion lasts; nothing while there are none to show. The chosen one's story is one press away. */
function loadKinds(list: LoadPreset[]): string {
  if (!list.length) return "";
  const { state } = app;
  const kind = (p: LoadPreset, k: number) => {
    const on = p.id === state.loadKind;
    const tag = k === 0 ? '<span class="tag">usual for this motor</span>' : "";
    const lasts = p.duration
      ? `<span class="kind-time">${lasting(p.duration, endsSteady(p))
          .replace(/^About /, "")
          .replace(/^Up to/, "up to")}</span>`
      : "";
    return (
      `<label class="kind${on ? " is-on" : ""}" title="${escape(p.about)}">` +
      `<input type="radio" name="load-kind" value="${p.id}" data-load ${on ? "checked" : ""}/>` +
      `<span class="kind-name">${escape(p.label)}${tag}</span>${lasts}` +
      `<span class="kind-about">${escape(firstClause(p.about))}</span></label>`
    );
  };
  return (
    `<fieldset class="kinds loads compact"><legend>Kind of load</legend>` +
    `<div class="family">${list.map(kind).join("")}</div></fieldset>`
  );
}

/** The chosen kind's story, folded: what its motion is, the motor such products have, and
 *  where its figures come from. */
function storyFold(p: LoadPreset, sized: string): string {
  const steady = endsSteady(p);
  const time = p.duration
    ? ` ${lasting(p.duration, steady)}${steady ? ": the run ends once the junction is steady" : ""}.`
    : "";
  const about = `<p>${escape(sentence(p.about))}.${time}</p>`;
  return (
    `<details class="more" data-fold="load-story"><summary>${icon("plus")}About this load` +
    `<span class="quiet">${escape(p.label)}${p.motor ? ", with its own motor" : ""}</span></summary>` +
    `${about}${sized}${usualMotor(p)}${whyList(p)}</details>`
  );
}

/** The load's figures, folded away: the ones this kind of load uses, then every other. */
function loadFigures(shown: string[]): string {
  const { state } = app;
  const l = state.load as Record<string, number>;
  const rest = Object.keys(LOAD_FIELDS).filter((k) => !shown.includes(k));
  const one = (k: string) =>
    field(`load.${k}`, LOAD_FIELDS[k][0], l[k], LOAD_FIELDS[k][1], k === "inertia" ? inertiaHelp() : LOAD_FIELDS[k][2]);
  const every =
    `<details class="more"><summary>${icon("adjustments")}Every load figure` +
    `<span class="quiet">the ones this kind of load does not use</span></summary>` +
    `<div class="fields">${rest.map(one).join("")}</div></details>`;
  return fold(
    "load-figures",
    "adjustments",
    "Change the load's figures",
    state.loadTouched ? "yours" : `${isProposed() ? "proposed for this part" : "sized to your motor"}: put in your own`,
    `<div class="fields">${shown.map(one).join("")}</div>${every}`,
    Object.keys(LOAD_FIELDS),
  );
}

/** One stretch of the motion as a row: how long it lasts, the speeds it runs between, and its removal. */
function stretchRow(s: State["segments"][number], k: number): string {
  const n = k + 1;
  const cell = (label: string, key: "duration" | "speed_start" | "speed_end", unit: string) => {
    const path = `segments.${k}.${key}`;
    const said = saidAt(path, s[key]);
    const flags = said.text ? ` aria-invalid="true" aria-describedby="${idOf(path)}-n"` : "";
    const input =
      `<input data-bind="${path}" id="${idOf(path)}" inputmode="decimal" autocomplete="off" ` +
      `value="${escape(said.raw)}"${flags}/>`;
    // The column heads name each box to the eye; its own label names it to everyone else.
    const named = `<label class="sr" for="${idOf(path)}">Stretch ${n} ${label}</label>`;
    const control = `<div class="control">${input}<span class="unit">${unit}</span></div>`;
    return `<td${said.text ? ' class="is-unread"' : ""}>${named}${control}${said.text}</td>`;
  };
  const only = app.state.segments.length < 2;
  return (
    `<tr>${cell("duration in seconds", "duration", "s")}` +
    `${cell("starting speed", "speed_start", "rpm")}${cell("ending speed", "speed_end", "rpm")}` +
    `<td><button type="button" class="icon-button" data-remove="${k}" aria-label="Remove stretch ${n}" ` +
    `${only ? "disabled" : ""}>${icon("trash")}</button></td></tr>`
  );
}

/** A duty's phases, one row each: how often it repeats, how long it lasts and how fast it runs. */
function phasesTable(phases: NonNullable<State["phases"]>): string {
  const row = (p: (typeof phases)[number]) => {
    const lasts = p.segments.reduce((n, x) => n + x.duration, 0);
    const top = Math.max(...p.segments.map((x) => Math.max(Math.abs(x.speed_start), Math.abs(x.speed_end))));
    const how = [
      p.segments.some((x) => x.at_limit) ? "at the current limit" : "",
      p.segments.some((x) => x.until_steady) ? "until steady" : "",
    ].filter(Boolean);
    return (
      `<tr><th scope="row">${escape(p.name)}</th><td>${p.repeat > 1 ? `${p.repeat} ×` : ""}</td>` +
      `<td>${num(lasts)} s</td><td>${whole(top)} rpm` +
      `${how.length ? ` <span class="quiet">${how.join(", ")}</span>` : ""}</td></tr>`
    );
  };
  const head =
    `<thead><tr><th scope="col">Phase</th><th scope="col">Repeats</th><th scope="col">Lasts</th>` +
    `<th scope="col">Up to</th></tr></thead>`;
  return (
    `<table class="segments phases">${head}<tbody>${phases.map(row).join("")}</tbody></table>` +
    `<p class="quiet small">Changing a stretch below makes the motion those stretches alone, ` +
    `without the phases or the run until steady.</p>`
  );
}

/** The motion as a table of stretches, folded away under what it adds up to. */
function stretchesFold(): string {
  const { state } = app;
  const phases = state.phases?.length ? phasesTable(state.phases) : "";
  const open = res.blocked?.field === "motion" || !!ui.missionFault;
  const seconds = state.segments.reduce((n, x) => n + Number(x.duration || 0), 0);
  const total = num(seconds);
  const head =
    `<thead><tr><th scope="col">Lasts</th><th scope="col">From</th><th scope="col">To</th>` +
    `<th scope="col"><span class="sr">Remove</span></th></tr></thead>`;
  const table = `<table class="segments">${head}<tbody>${state.segments.map(stretchRow).join("")}</tbody></table>`;
  const stretches = phases
    ? `<details class="more" data-fold="stretches"><summary>Every stretch, written out` +
      `<span class="quiet">${state.segments.length}</span></summary>\n${table}</details>`
    : table;
  const said = phases
    ? `${state.phases!.length} phases, ${lasting(seconds, endsSteady({ phases: state.phases })).toLowerCase()}`
    : `${state.segments.length} stretches, ${total} s`;
  return (
    `<details class="more" data-fold="motion"${open ? " open" : ""}><summary>${icon("adjustments")}Change the motion` +
    `<span class="quiet">${said}: ` +
    `load speed in straight lines between the values you give</span></summary>\n` +
    `${phases}${stretches}\n` +
    `<button type="button" class="ghost" data-add>${icon("plus")}Add a stretch</button>${missionLine()}</details>`
  );
}

/** The heatsink's own figures, for the kinds of cooling that have a heatsink to follow. */
function heatsinkFields(): string {
  const { sink, conditions } = app.state;
  const cooling = conditions.cooling;
  const toAir =
    cooling === "held"
      ? field(
          "sink.rth",
          "Heatsink to air",
          sink.rth,
          "K/W",
          "With its heat capacity, the heatsink warms up during the motion.",
        )
      : "";
  const capacity =
    cooling === "none" || cooling === "board"
      ? ""
      : field(
          "sink.capacity",
          "Heatsink heat capacity",
          sink.capacity,
          "J/K",
          cooling === "heatsink"
            ? "About 900 for each kilogram of aluminium. Given, the heatsink is followed as it warms " +
                "from the air's temperature. Empty, a motion a few minutes long or longer takes the usual " +
                "for its resistance (it reaches 63% of its rise in 5 minutes) and says so; a shorter " +
                "one is taken as already warm."
            : "About 900 for each kilogram of aluminium.",
        );
  return toAir + capacity;
}

/** What surrounds the stage through the motion, all of it optional: the heatsink and the DC link. */
function sinkFold(): string {
  const { sink, conditions } = app.state;
  const precharge = field(
    "sink.precharge",
    "Precharge resistance",
    sink.precharge,
    "Ω",
    "What limits the current when the link is first charged.",
  );
  const air = conditions.cooling === "held" ? field("sink.t_ambient", "Air temperature", sink.t_ambient, "°C") : "";
  const link = field(
    "sink.c_link_uf",
    "DC-link capacitance",
    sink.c_link_uf,
    "µF",
    "Braking energy charges it when the supply cannot take it back.",
  );
  const start = startFields();
  const opened = sink.rth || sink.c_link_uf || app.state.start.method !== "sensor";
  const title = start ? "Starting, heatsink and DC link" : "Heatsink and DC link";
  return (
    `<details class="more" data-fold="around"${opened ? " open" : ""}><summary>${icon("temperature")}` +
    `${title}<span class="quiet">optional</span></summary><div class="fields">\n` +
    `${start}${heatsinkFields()}\n` +
    `${precharge}${air}${link}\n` +
    `${field("sink.repeats", "Repeat the motion", sink.repeats, "times")}</div></details>`
  );
}

export function loadPanel(): string {
  const { state } = app;
  const list = res.presets?.list ?? [];
  const chosen = list.find((p) => p.id === state.loadKind);
  const shown = chosen?.fields ?? OWN_LOAD_FIELDS;
  const kinds = loadKinds(list);
  // The duty leads the step; what the part could carry is offered under it, as a proposal.
  const proposal = `<div id="load-proposal">${proposalBlock()}</div>`;
  // Until the user changes a figure or takes the load as theirs, it is the page's assumption,
  // and said to be: opening the step is not choosing it.
  const assumed = driveAssumed(state);
  // Taking the load is its own line under the words: a button set inside a sentence pushes the
  // line it is on apart from the others.
  const take = assumed
    ? `<p class="use-load-line"><button type="button" class="ghost use-load" data-use-load>` +
      `${icon("circle-check")}Use this load</button></p>`
    : "";
  const lead =
    `<p class="lead">${assumed ? "Assumed duty" : "Your duty"}: what the motor drives, with its usual load and ` +
    `motion. Change any figure below.</p>${take}`;
  // Your own figures are said in the open; how a kind was sized is part of its story.
  const note = !state.mission && state.loadTouched ? loadNote("") : "";
  const extra = !state.mission && chosen ? storyFold(chosen, state.loadTouched ? "" : loadNote(chosen.link ?? "")) : "";
  return (
    `<h2 tabindex="-1">What the motor moves</h2>${lead}\n` +
    `${missionBlock()}${state.mission ? "" : kinds}\n` +
    `${proposal}<div id="load-note">${note}${extra}</div>\n` +
    `${loadFigures(shown)}\n` +
    `<h3>The motion</h3>\n` +
    `<div id="motion-preview"></div>\n` +
    `${stretchesFold()}\n` +
    `${sinkFold()}${nextButton(LOAD)}`
  );
}

/** What the motion asks of the motor, set against the design point of step 3: the two are
 *  entered on different steps and have to agree. */
function motionAgainstDesign(): string {
  const { state } = app;
  if (state.mission) return "";
  const gear = Number(state.load.gear_ratio) || 1;
  const top = Math.max(...state.segments.flatMap((g) => [Math.abs(g.speed_start), Math.abs(g.speed_end)]), 0) * gear;
  const design = Math.abs(state.conditions.rpm);
  const round = (v: number) => whole(v);
  const over = top > design * 1.01;
  const geared = gear !== 1 ? ` (load × ${ratio(gear)}:1 gear)` : "";
  const against = over
    ? `, above the ${round(design)} rpm design point: the part was judged at the lower speed. ` +
      `Raise the design speed, or slow the motion.`
    : `; design point ${round(design)} rpm.`;
  return (
    `<p class="fact${over ? " warn" : ""}">${icon(over ? "alert-triangle" : "info-circle")}` +
    `<span>Top speed at the motor ${round(top)} rpm${geared}${against}</span></p>`
  );
}

/** Under the kinds of load: how this one was sized, or that its figures are now the user's own. */
function loadNote(link: string): string {
  return app.state.loadTouched
    ? `<p class="fact">${icon("info-circle")}<span>Your own figures: kept when the motor or the design point ` +
        `changes. ` +
        `<button type="button" class="link" data-resize-load>Size this load to the motor again</button></span></p>`
    : `<p class="fact">${icon("info-circle")}<span>${escape(link)}</span></p>`;
}

export function renderPreview(): void {
  const { state } = app;
  const box = document.querySelector<HTMLElement>("#motion-preview");
  if (!box) return;
  box.innerHTML = state.mission
    ? `<p class="quiet">The mission profile above is the motion. ` +
      `The stretches below are not used while it is there.</p>`
    : motionPreview(state.segments) + motionAgainstDesign();
}
