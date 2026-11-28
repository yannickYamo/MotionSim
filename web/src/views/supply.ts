// The supply step: the bus, the design point, how the stage switches, and the cooling.

import { frontEndCard } from "./frontend";
import type { MotorKind } from "../api";
import { eng, escape, num, sentence, watts } from "../format";
import { ONE_PHASE_MOST, shaftPower } from "../follow";
import { icon } from "../icons";
import { sizedEarlier } from "../state";
import type { EdgeLimit, State } from "../state";
import { SUPPLY } from "../steps";
import { app, driversBuiltIn, focused, needsGate, res, ui, underTest } from "../store";
import { offerNow } from "../actions/cooling";
import { Refused } from "../api";
import { field, fold, select, spinner, waiting } from "./html";
import { nextButton } from "./rail";

type Conditions = State["conditions"];

/** What the gate fold says on its face: the drive in use, chosen or the user's own. */
function gateFace(): string {
  const used = focused()?.gate;
  if (!used?.rg_on) {
    return needsGate()
      ? "left empty, the gate resistors with the lowest loss within the limits are chosen for you"
      : "optional for your device";
  }
  const drive = used.v_drive ? `, ${num(used.v_drive, 2)} V` : "";
  const dead = used.t_dead ? `, ${eng(used.t_dead, "s", 2)} dead time` : "";
  const whose =
    used.kind === "given"
      ? "yours"
      : used.kind === "datasheet"
        ? "as the datasheet measured with"
        : "chosen for you, change them here";
  return `${num(used.rg_on, 2)} Ω on, ${num(used.rg_off ?? 0, 2)} Ω off${drive}${dead}: ${whose}`;
}

/** What the supply fold says on its face. */
const supplyFace = (): string => {
  const { state } = app;
  const motor = state.conditions.t_motor ? `at ${state.conditions.t_motor} °C` : "at 25 °C, as its figures are given";
  const mains = state.supply === "mains" ? `; mains at ${state.conditions.mains_f || 50} Hz` : "";
  return `motor ${motor}${mains}`;
};

/** What each kind of supply does with braking energy, under its list. */
const SUPPLY_HELP: Record<string, string> = {
  "one-way": "It does not take braking energy back.",
  battery: "It takes braking energy back.",
  mains: "A wall socket or a three-phase line. A PFC stage turns it into the DC link: recommended below.",
};

/** The kinds of supply, each one press: the mains is not hidden in a list. */
const SUPPLY_KINDS: [string, string][] = [
  ["one-way", "Power supply"],
  ["battery", "Battery"],
  ["mains", "AC mains"],
];

/** What the stage runs from, as three choices side by side. */
function supplyKind(): string {
  const { supply } = app.state;
  const option = ([value, label]: [string, string]) =>
    `<label><input type="radio" name="supply-kind" value="${value}" data-bind="supply"` +
    `${value === supply ? " checked" : ""}/><span>${escape(label)}</span></label>`;
  return (
    `<fieldset class="supply-kind" aria-describedby="supply-kind-h"><legend>Supply</legend>` +
    `<div class="segmented radios">${SUPPLY_KINDS.map(option).join("")}</div>` +
    `<p class="help" id="supply-kind-h">${escape(SUPPLY_HELP[supply] ?? "")}</p></fieldset>`
  );
}

/** A supply above the part's rating: one press puts it where this part starts. */
function suitPress(c: Conditions): string {
  const part = app.setup.devices.find((d) => d.id === underTest());
  const found = res.suggestion;
  const suits = found && found.id === underTest() ? found.data.v_supply : null;
  if (!part?.v_max || !suits || Number(c.v_dc) <= part.v_max) return "";
  return (
    `<div class="fe-lever supply-suit" role="status"><p>This part is rated ${escape(num(part.v_max))} V. ` +
    `Drives of its class run from about ${escape(num(suits))} V.</p>` +
    `<button type="button" class="ghost" data-suit-supply>${icon("check")}Use ${escape(num(suits))} V</button></div>`
  );
}

/** What the stage runs from, and its voltage: a DC supply's own, or the mains' with the
 *  link's voltage following from the stage in front of it. */
function supplyFields(c: Conditions): string {
  const { state } = app;
  const kind = supplyKind();
  if (state.supply !== "mains")
    return `${kind}${field("conditions.v_dc", "Supply voltage", c.v_dc, "V")}${suitPress(c)}`;
  const power = shaftPower(state);
  // One phase chosen for a point over what one phase gives: said where it is chosen.
  const over =
    c.mains_phases === "1" && power > ONE_PHASE_MOST
      ? `This point is ${watts(power)} at the shaft: one phase gives about ${watts(ONE_PHASE_MOST)}.`
      : "";
  const phases = select(
    "conditions.mains_phases",
    "Phases",
    c.mains_phases,
    [
      ["1", "One phase"],
      ["3", "Three phases"],
    ],
    over,
  );
  const volts = field(
    "conditions.mains_v",
    "Mains voltage",
    c.mains_v,
    "V",
    c.mains_phases === "3" ? "Line to line." : "",
  );
  const link = field(
    "conditions.v_dc",
    "DC-link voltage",
    c.v_dc,
    "V",
    c.link_own ? "As you typed it." : "What the front end holds. Type another to hold that.",
  );
  return `${kind}${volts}${phases}${link}`;
}

/** How the stage is modulated: the motor's own scheme where it has one, else the user's pick. */
function schemeField(c: Conditions, m: MotorKind): string {
  if (m.fixed_scheme) {
    const said = `Modulation: ${escape(m.fixed_scheme)}. This motor type decides it.`;
    return `<p class="fact">${icon("wave-sine")}<span>${said}</span></p>`;
  }
  const options: [string, string][] = [
    ["", `Usual for this motor (${m.default_pwm})`],
    ...app.setup.pwm.map((p) => [p, p] as [string, string]),
  ];
  const help = "Leave this on the usual scheme unless you know your controller uses another.";
  return select("conditions.pwm", "Modulation", c.pwm, options, help);
}

/** How the edge limit is offered, in order: each with what it is for and how fast it lets an edge be. */
export const EDGE_CHOICES: [EdgeLimit, string][] = [
  ["cable", "Motor on a cable: 5 V/ns"],
  ["close", "Motor close to the drive: 20 V/ns"],
  ["none", "No limit: as fast as the part allows"],
];

/** The edge limit as the gate fold says it on its face. */
const EDGE_FACE: Record<EdgeLimit, string> = {
  cable: "edges ≤ 5 V/ns",
  close: "edges ≤ 20 V/ns",
  none: "edges as fast as the part allows",
};

/** How fast the tool may let an edge be where it chooses the gate resistors: one press. */
function edgeLimitField(c: Conditions): string {
  if (driversBuiltIn()) return "";
  const option = ([value, label]: [EdgeLimit, string]) =>
    `<label><input type="radio" name="edge-limit" value="${value}" data-edge-limit` +
    `${value === c.edge_limit ? " checked" : ""}/><span>${escape(label)}</span></label>`;
  const help =
    "Fast edges cut switching loss but stress the motor's insulation and bearings, and radiate; " +
    "5 V/ns is the usual limit for a motor on a cable.";
  return (
    `<fieldset class="edge-limit" id="edge-limit" aria-describedby="edge-limit-h"><legend>Edge speed limit</legend>` +
    `<div class="segmented radios">${EDGE_CHOICES.map(option).join("")}</div>` +
    `<p class="help" id="edge-limit-h">${escape(help)}</p></fieldset>`
  );
}

/** The switching frequency, the devices sharing a switch, and the modulation. */
function switchingFields(c: Conditions, m: MotorKind): string {
  const frequency = field(
    "conditions.f_khz",
    "Switching frequency",
    c.f_khz,
    "kHz",
    "Above 20 kHz is inaudible. Lower loses less.",
  );
  const parallel = field(
    "conditions.parallel",
    "Devices in parallel",
    c.parallel,
    "a switch",
    "1 unless you put several side by side to share the current.",
  );
  return `${frequency}${parallel}<div class="wide">${schemeField(c, m)}</div>`;
}

/** What the devices sit on, to pick from. */
function coolingKind(c: Conditions): string {
  const options: [string, string][] = [
    ["held", "A heatsink, at a temperature I know (usual)"],
    ["heatsink", "A heatsink, in air"],
    ["none", "No heatsink: each part standing in the air"],
    ["board", "No heatsink: parts soldered to one board"],
  ];
  const help =
    c.cooling === "held"
      ? "Not sure of its temperature? Pick a heatsink in air, or no heatsink: " +
        "those start from the air's temperature."
      : "";
  return select("conditions.cooling", "What the devices sit on", c.cooling, options, help);
}

/** The air's temperature, with where it is taken said for the cooling in use. */
const airField = (c: Conditions, where: string) =>
  field("conditions.t_ambient", "Air temperature", c.t_ambient, "°C", where);

/** The junction-to-air figure of one package, for parts with no heatsink. */
const junctionField = (c: Conditions, help: string) =>
  field("conditions.rth_ja", "Junction to air, one package", c.rth_ja, "K/W", help);

/** The figures for parts soldered to one board, which warms them all. */
function boardFields(c: Conditions): string {
  return (
    junctionField(c, "RthJA on the datasheet, with the copper area its footnote gives.") +
    airField(c, "Around the board, inside the enclosure if there is one.") +
    sizedField(
      c,
      "board_area",
      field(
        "conditions.board_area",
        "Board area",
        c.board_area,
        "cm²",
        "Of the board the power stage is on. Everything the stage loses warms it, and it warms every part.",
      ),
    ) +
    coolingOffer() +
    field(
      "conditions.copper",
      "Copper for each part",
      c.copper,
      "cm²",
      "The pad each part is soldered to. Empty: what the datasheet's figure was taken on.",
    ) +
    field(
      "conditions.copper_ref",
      "Copper in the datasheet's figure",
      c.copper_ref,
      "cm²",
      "Empty: 6.45, one square inch, the usual footnote.",
    )
  );
}

/** The cooling figure the tool offers for an empty box, worked out from the loss at the
 *  design point, with the one press that takes it. Nothing where it cannot be offered: the
 *  box itself says what it needs. */
function coolingOffer(): string {
  const answer = offerNow();
  if (!answer) return "";
  if (answer === "asking")
    return `<div class="cooling-offer">${waiting("Working out the cooling this point needs.")}</div>`;
  if (answer instanceof Refused) return "";
  if (answer.value === null) {
    return `<div class="cooling-offer"><p class="help">${escape(sentence(answer.why ?? ""))}.</p></div>`;
  }
  const v = num(answer.value, 2);
  const said =
    answer.figure === "rth_sink"
      ? `To hold the heatsink at ${answer.held ?? 60} °C at this design point, it needs ${v} K/W or less.`
      : `About ${v} cm² of board keeps the hottest junction under its ${answer.tj_max ?? 150} °C limit ` +
        "at this design point.";
  const unit = answer.figure === "rth_sink" ? "K/W" : "cm²";
  const button = `<button type="button" class="ghost" data-use-sized>${icon("check")}Use ${v} ${unit}</button>`;
  return (
    `<div class="cooling-offer" role="status"><p>${escape(said)} ` +
    `<span class="quiet">The verdict then says the cooling was sized by the tool.</span></p><p>${button}</p></div>`
  );
}

/** A cooling box holding the figure the tool sized: marked so, until it is edited. */
function sizedField(c: Conditions, key: "rth_sink" | "board_area", html: string): string {
  if (c.sized !== key || String(c[key] ?? "").trim() === "") return html;
  if (!sizedEarlier(app.state)) {
    const tag = '<span class="tag sized">Sized for you</span>';
    return html.replace("</label>", ` ${tag}</label>`);
  }
  // Sized for a design point that has since moved: said so, with the way to size it again.
  const tag = '<span class="tag sized">Sized for an earlier point</span>';
  const r = ui.resizing;
  const asking = !!r && "asking" in r;
  const why = r && "why" in r ? `<p class="help said-wrong" role="alert">${escape(sentence(r.why))}.</p>` : "";
  const said =
    "The design point has moved since this was sized: it is not sized for the point as it now stands, " +
    "and the verdict is held at a caution.";
  const again =
    `<button type="button" class="ghost" data-resize-sized${asking ? ' disabled aria-busy="true"' : ""}>` +
    `${asking ? spinner : icon("rotate-clockwise")}Size it again for this point</button>`;
  const note = `<div class="cooling-offer sized-earlier"><p class="help">${said}</p>${why}<p>${again}</p></div>`;
  return html.replace("</label>", ` ${tag}</label>`) + note;
}

/** The figures the chosen cooling needs. */
function coolingFields(c: Conditions): string {
  if (c.cooling === "held") {
    const help = "What the heatsink sits at when warm. 60 is a fair start.";
    return field("conditions.t_sink", "Heatsink temperature", c.t_sink, "°C", help);
  }
  if (c.cooling === "heatsink") {
    const help = "From the heatsink's data, with every device on it. A smaller figure is a bigger heatsink.";
    return (
      sizedField(c, "rth_sink", field("conditions.rth_sink", "Heatsink to air", c.rth_sink, "K/W", help)) +
      airField(c, "Around the heatsink, inside the enclosure if there is one.") +
      coolingOffer()
    );
  }
  if (c.cooling === "none") {
    const help =
      "RthJA on the datasheet. Empty: the usual figure for a TO-220, TO-247 or TO-263, " +
      "where the part is one of those.";
    return junctionField(c, help) + airField(c, "Around the devices, inside the enclosure if there is one.");
  }
  return boardFields(c);
}

/** What lies between each package and the heatsink, where there is a heatsink. */
function mountingFold(c: Conditions): string {
  if (c.cooling !== "held" && c.cooling !== "heatsink") return "";
  const face =
    String(c.rth_case_sink ?? "").trim() !== ""
      ? `${c.rth_case_sink} K/W from each case to it`
      : c.interface === "pad"
        ? "on a thermal pad"
        : "on thermal grease";
  const under = select(
    "conditions.interface",
    "Under each package",
    c.interface,
    [
      ["", "Thermal grease"],
      ["pad", "A thermal pad"],
    ],
    "What lies between a package and the heatsink. " +
      "A pad is thicker than grease, so the package runs warmer on it.",
  );
  const resistance = field(
    "conditions.rth_case_sink",
    "Case to heatsink",
    c.rth_case_sink,
    "K/W",
    "Of one package. Empty: the device's own figure where its datasheet gives one for this layer, " +
      "else worked out. A figure given here stands, whatever the layer.",
  );
  const body = `<div class="fields">${under + resistance}</div>`;
  const holds = ["interface", "rth_case_sink"];
  return fold("mounting", "adjustments", "How the packages sit on the heatsink", face, body, holds);
}

/** What the supply does with braking energy, and how warm the winding is. */
function settingsFold(c: Conditions): string {
  const mains = app.state.supply === "mains" ? field("conditions.mains_f", "Mains frequency", c.mains_f, "Hz") : "";
  const motor = field(
    "conditions.t_motor",
    "Motor temperature",
    c.t_motor,
    "°C",
    "Empty: the motor's figures as given, at 25 °C. " +
      "A warm motor (80 to 120) needs more current for the same torque.",
  );
  const body = `<div class="fields">${motor}${mains}</div>`;
  const title = mains ? "Motor temperature and mains frequency" : "Motor temperature";
  return fold("more-settings", "adjustments", title, supplyFace(), body, ["t_motor"]);
}

/** The dead time alone, for a module that drives its own gates. */
function deadTimeFold(c: Conditions): string {
  const face = "the gate drive is inside this module, so there is no gate voltage or resistor to set";
  const summary = `<summary>${icon("adjustments")}Dead time<span class="quiet">${face}</span></summary>`;
  const dead = field("conditions.t_dead_ns", "Dead time", c.t_dead_ns, "ns");
  return `<details class="more">${summary}<div class="fields">${dead}</div></details>`;
}

/** The gate drive and the loop it switches in, open once a figure is given or refused. */
function gateDriveFold(c: Conditions): string {
  const refused = ["v_drive", "rg_on", "rg_off", "t_dead", "l_loop", "edge_limit"].includes(res.blocked?.field ?? "");
  const open = refused ? " open data-must-open" : c.v_drive || c.rg_on ? " open" : "";
  const edges = EDGE_FACE[c.edge_limit] ?? EDGE_FACE.cable;
  const face = `<span class="quiet">${escape(gateFace())}; ${edges}</span>`;
  const summary = `<summary>${icon("adjustments")}Gate drive and layout${face}</summary>`;
  const drive = field(
    "conditions.v_drive",
    "Gate drive voltage",
    c.v_drive,
    "V",
    "Often 10 to 12 for silicon, 15 to 20 for SiC, 5 for GaN.",
  );
  const dead = field("conditions.t_dead_ns", "Dead time", c.t_dead_ns, "ns");
  const shortest = field(
    "conditions.t_min_ns",
    "Shortest pulse",
    c.t_min_ns,
    "ns",
    "The shortest pulse your gate drive passes. It keeps the duty cycle off the rails.",
  );
  const on = field("conditions.rg_on", "Turn-on gate resistance", c.rg_on, "Ω");
  const off = field("conditions.rg_off", "Turn-off gate resistance", c.rg_off, "Ω");
  const loop = field(
    "conditions.l_loop_nh",
    "Loop inductance",
    c.l_loop_nh,
    "nH",
    "Of the switching loop on your board. 10 to 30 is typical for a careful layout.",
  );
  return (
    `<details class="more" data-fold="gate"${open}>${summary}<div class="fields">\n` +
    `${drive}${dead}${shortest}\n` +
    `${on}${off}\n` +
    `${loop}<div class="wide">${edgeLimitField(c)}</div></div></details>`
  );
}

export function supplyPanel(): string {
  const { state, setup } = app;
  const c = state.conditions;
  const m = setup.motors[state.kind];
  // What a drive designer sets first is in view: the bus, the point, how the stage switches,
  // how many devices share a switch, and the cooling. Second-order settings (what the supply
  // does with braking energy, the winding's temperature) are one press away, and so is the
  // gate drive, which the tool chooses and states when it is left open.
  const lead = '<p class="lead">The supply, and the hardest point the motor has to hold.</p>';
  const point = field("conditions.rpm", "Speed", c.rpm, "rpm") + field("conditions.torque", "Torque", c.torque, "N·m");
  return (
    `<h2 tabindex="-1">Supply and design point</h2>${lead}\n` +
    `<div class="fields">${supplyFields(c)}</div>\n` +
    `${frontEndCard()}\n` +
    `<div class="fields">${point}</div>\n` +
    `<h3>Switching</h3><div class="fields">${switchingFields(c, m)}</div>\n` +
    `<h3>Cooling</h3><div class="fields">${coolingKind(c)}\n` +
    `${coolingFields(c)}\n` +
    `</div>\n` +
    `${mountingFold(c)}\n` +
    `${settingsFold(c)}\n` +
    `${driversBuiltIn() ? deadTimeFold(c) : gateDriveFold(c)}\n` +
    `${nextButton(SUPPLY)}`
  );
}
