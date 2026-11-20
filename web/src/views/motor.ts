// The motor step: the kind of motor, its catalogue figures, and whether it fits the part.

import { Refused } from "../api";
import type { MotorKind, Suggest } from "../api";
import { escape, sentence } from "../format";
import { icon } from "../icons";
import { constantOf, hasConstant, hasWiring, shownAs, shownText } from "../motorentry";
import { MOTOR } from "../steps";
import { app, res, underTest } from "../store";
import { field, select, together } from "./html";
import { nextButton } from "./rail";

type Kind = [string, MotorKind];
type Fits = Suggest["motors"] | null;
type Figures = Record<string, string | number>;

/** One thing the engine says of the motor on the part, with the mark that goes with it. */
const fitLine = (tone: string, glyph: string, text: string) =>
  `<p class="fact ${tone}">${icon(glyph)}<span>${together(escape(sentence(text)))}.</span></p>`;

/** What the engine says of this motor on this part, before any design point is set. */
export function fitBlock(): string {
  const fit = res.fit;
  if (!fit) return "";
  if (fit instanceof Refused) {
    const said = `<b>This motor cannot be worked out yet.</b> ${escape(sentence(fit.reason))}.`;
    return `<p class="fact warn" role="alert">${icon("alert-triangle")}<span>${said}</span></p>`;
  }
  const raised = fit.lines.filter((x) => x.level !== "ok");
  const fine = fit.lines.filter((x) => x.level === "ok");
  const head = `<h3>${icon("alert-triangle")}This motor does not fit the part as it is</h3>`;
  const warned = raised.map((x) => fitLine("warn", "alert-triangle", x.text)).join("");
  const above = raised.length ? `<div class="fit-raised" role="alert">${head}${warned}</div>` : "";
  return `${above}${fine.map((x) => fitLine("fits", "circle-check", x.text)).join("")}`;
}

/** One kind of motor to pick, with what the device under test makes of it. */
function kindOption([k, x]: Kind, fits: Fits): string {
  const { state } = app;
  const fit = fits?.[k];
  const tag = fit?.fit === "recommended" ? '<span class="tag recommended">Starting point for your device</span>' : "";
  const why = fit && fit.fit !== "suits" ? `<span class="kind-why">${escape(sentence(fit.why))}.</span>` : "";
  const on = k === state.kind ? " is-on" : "";
  const rec = fit?.fit === "recommended" ? " is-rec" : "";
  const radio = `<input type="radio" name="kind" value="${k}" data-kind ${k === state.kind ? "checked" : ""}/>`;
  const name = `<span class="kind-name">${escape(x.label)}${tag}</span>`;
  const about = `<span class="kind-about">${escape(x.about)}</span>`;
  return `<label class="kind${on}${rec}">${radio}${name}${about}${why}</label>`;
}

/** Kinds of motor set out under the family each belongs to. */
function kindGroups(subset: Kind[], fits: Fits): string {
  const families = [...new Set(subset.map(([, x]) => x.family))];
  const one = (family: string) => {
    const options = subset
      .filter(([, x]) => x.family === family)
      .map((kind) => kindOption(kind, fits))
      .join("");
    const name = `<p class="family-name">${escape(family)}</p>`;
    return `<div class="family" role="group" aria-label="${escape(family)}">${name}${options}</div>`;
  };
  return families.map(one).join("");
}

/** Every kind of motor there is to pick from. */
function kindList(fits: Fits): string {
  const { state, setup } = app;
  const kinds = Object.entries(setup.motors);
  const unusual = (k: string) => fits?.[k]?.fit === "unusual";
  // The kinds that make sense with the device come first; the rest stay one press away.
  const usual = kinds.filter(([k]) => !unusual(k));
  const rest = kinds.filter(([k]) => unusual(k));
  if (!rest.length) return kindGroups(usual, fits);
  const note = '<span class="quiet">unusual with your device, each with the reason</span>';
  const summary = `<summary>${icon("adjustments")}Other kinds of motor${note}</summary>`;
  const open = unusual(state.kind) ? " open" : "";
  const others = `<details class="more other-kinds"${open}>${summary}${kindGroups(rest, fits)}</details>`;
  return kindGroups(usual, fits) + others;
}

/** One catalogue figure of the motor, in the datasheet's terms where the engine takes it otherwise. */
function motorField(f: MotorKind["fields"][number], v: Figures): string {
  const { kind, motorEntry } = app.state;
  const path = `motors.${kind}.${f.key}`;
  if (f.options) {
    const options = f.options.map((o) => [o, o] as [string, string]);
    return select(path, f.label, String(v[f.key] ?? f.options[0]), options, f.help);
  }
  const shown = shownAs(kind, f.key, motorEntry, f.label, f.help);
  if (!shown) return field(path, f.label, v[f.key] ?? "", f.unit, f.help);
  const engine = Number(v[f.key]);
  const help = shown.help(v[f.key] === "" || !Number.isFinite(engine) ? null : engine);
  return field(path, shown.label, shownText(shown, v[f.key]), shown.unit, help);
}

/** The catalogue figures of the kind of motor picked. */
const motorFields = (m: MotorKind, v: Figures): string => m.fields.map((f) => motorField(f, v)).join("");

/** Two ways to give the same figures, as a pair of choices: switching shows the motor's
 *  figures the other way, and the motor stays the same. */
function entrySwitch(name: string, legend: string, now: string, options: [string, string][]): string {
  const choices = options
    .map(([value, label]) => {
      const on = value === now ? " checked" : "";
      const radio = `<input type="radio" name="entry-${name}" value="${value}" data-entry="${name}"${on}/>`;
      return `<label class="entry-choice">${radio}<span>${escape(label)}</span></label>`;
    })
    .join("");
  return `<fieldset class="entry-switch"><legend>${escape(legend)}</legend>${choices}</fieldset>`;
}

/** How the motor's figures are given: between two terminals or for one phase, and which of
 *  its constants. Only where the kind of motor has the choice. */
function entrySwitches(kind: string): string {
  const e = app.state.motorEntry;
  const wiring = hasWiring(kind)
    ? entrySwitch("wiring", "Resistance and inductance are given", e.wiring, [
        ["line", "line to line"],
        ["phase", "per phase"],
      ])
    : "";
  const constant = hasConstant(kind)
    ? entrySwitch("constant", "The motor's constant is given as", constantOf(kind, e) ?? "", [
        ["kv", "speed constant Kv"],
        ["kt", "torque constant Kt"],
      ])
    : "";
  if (!wiring && !constant) return "";
  const why = '<p class="help">Switching shows the same motor\'s figures the other way.</p>';
  return `<div class="entry-switches">${wiring}${constant}${why}</div>`;
}

/** The figures the motor can do without, folded until one of them is given. */
function optionalFold(m: MotorKind, v: Figures): string {
  if (!m.optional?.length) return "";
  const open = m.optional.some((f) => v[f.key] !== undefined && v[f.key] !== "") ? " open" : "";
  const saturation = m.optional.some((f) => f.key === "i_sat") ? " and saturation" : "";
  const face = `optional: iron loss${saturation}. Left empty, they are left out and the result says so`;
  const summary = `<summary>${icon("adjustments")}More about this motor<span class="quiet">${face}</span></summary>`;
  const fields = m.optional
    .map((f) => field(`motors.${app.state.kind}.${f.key}`, f.label, v[f.key] ?? "", f.unit, f.help))
    .join("");
  return `<details class="more"${open}>${summary}<div class="fields">${fields}</div></details>`;
}

export function motorPanel(): string {
  const { state, setup } = app;
  const m = setup.motors[state.kind];
  const v = state.motors[state.kind];
  const suggestion = res.suggestion && res.suggestion.id === underTest() ? res.suggestion : null;
  const fits = suggestion ? suggestion.data.motors : null;
  const device = setup.devices.find((d) => d.id === underTest());
  const suits =
    suggestion && device
      ? ` The example is wound for your ${Math.round(device.v_max)} V device, ` +
        `on about ${Math.round(suggestion.data.v_supply)} V.`
      : "";
  const lead = `<p class="lead">Pick the motor and put in its catalogue figures.${suits}</p>`;
  return (
    `<h2 tabindex="-1">The motor it drives</h2>${lead}\n` +
    `<fieldset class="kinds"><legend>Kind of motor</legend>${kindList(fits)}</fieldset>\n` +
    `${entrySwitches(state.kind)}<div class="fields">${motorFields(m, v)}</div>\n` +
    `<div id="motor-fit" aria-live="polite">${fitBlock()}</div>\n` +
    `${optionalFold(m, v)}${nextButton(MOTOR)}`
  );
}
