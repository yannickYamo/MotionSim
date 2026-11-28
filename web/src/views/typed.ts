// A part typed in from its datasheet: the boxes of its figures, what is wrong with each, and
// the button that adds it.

import { escape, sentence } from "../format";
import { icon } from "../icons";
import { MOST_NAME } from "../parse";
import { app, ui } from "../store";
import type { TypedField, TypedKind } from "../typedkind";
import { fieldsOf, kindOf, mosfetTechnologies, NAMES as NAME_KEYS, TYPED_KINDS } from "../typedkind";
import { refusal, waiting } from "./html";

/** The boxes that hold a name, not a figure: a fault in one is never "check the figure". */
const NAMES = new Set(NAME_KEYS);

/** The figures shown with the needed ones: needed, or taken by the tool when left empty. */
const isMain = (f: TypedField): boolean => f.required || !!f.main;

/** What is wrong with the figure in this box, said at the box: what the page found itself,
 *  else the engine's refusal of it. */
export function wrongWords(key: string): string | null {
  const own = ui.typedWrong[key];
  if (own) return own;
  const refused = ui.typedRefused;
  if (!refused || (refused.field ?? "") !== key) return null;
  const fix = refused.fix && !NAMES.has(key) ? ` ${sentence(refused.fix).replace(/\.?$/, ".")}` : "";
  return `${sentence(refused.reason).replace(/\.?$/, ".")}${fix}`;
}

/** The box of one figure of the typed part. `described`: the ids of what is said of it. */
function typedInput(key: string, unit: string, wrong: boolean, described: string): string {
  const id = `t-${key}`;
  const long = NAMES.has(key) ? `maxlength="${MOST_NAME}" ` : "";
  return (
    `<input id="${id}" data-typed="${key}" ${unit ? 'inputmode="decimal"' : ""} autocomplete="off" ${long}` +
    `value="${escape(app.state.typed[key] ?? "")}" ${wrong ? 'aria-invalid="true"' : ""} ` +
    `${described ? `aria-describedby="${described}"` : ""}/>`
  );
}

/** One figure of the typed part: its box, its unit, and what is wrong with it if refused. */
function typedField(key: string, label: string, unit: string, required: boolean, help: string, wide = false): string {
  const id = `t-${key}`;
  const words = wrongWords(key);
  const bad = words ? `<p class="help said-wrong" id="${id}-w">${escape(words)}</p>` : "";
  const noted = !words && ui.typedNotes[key] ? `<p class="help" id="${id}-c">${escape(ui.typedNotes[key])}</p>` : "";
  const described = [bad ? `${id}-w` : "", noted ? `${id}-c` : "", help ? `${id}-h` : ""].filter(Boolean).join(" ");
  const name = `${escape(label)}${required ? "" : ' <span class="quiet">optional</span>'}`;
  const input = typedInput(key, unit, !!bad, described);
  const unitTag = unit ? `<span class="unit">${escape(unit)}</span>` : "";
  const helpLine = help ? `<p class="help" id="${id}-h">${escape(help)}</p>` : "";
  return (
    `<div class="field${words ? " is-wrong" : ""}${wide ? " wide" : ""}"><label for="${id}">${name}</label>` +
    `<div class="control">${input}${unitTag}</div>${bad}${noted}${helpLine}</div>`
  );
}

/** One choice of the typed part from a short list; `last` names the choice of none of them,
 *  and `said` how a choice is written where it is not as it is sent. */
function typedPick(
  key: string,
  label: string,
  options: string[],
  last: string,
  help: string,
  said: Record<string, string> = {},
): string {
  const t = app.state.typed;
  const choices = [...options, ...(last ? [""] : [])]
    .map((o) => {
      const selected = (t[key] ?? (last ? "" : options[0])) === o ? " selected" : "";
      return `<option value="${escape(o)}"${selected}>${escape(said[o] ?? (o || last))}</option>`;
    })
    .join("");
  return (
    `<div class="field"><label for="t-${key}">${escape(label)}</label><div class="control">` +
    `<select id="t-${key}" data-typed="${key}">${choices}</select></div><p class="help">${escape(help)}</p></div>`
  );
}

/** An IGBT's arrangements as they are said. */
const ARRANGED: Record<string, string> = { discrete: "Discrete", half_bridge: "Half bridge", six_pack: "Six-pack" };

/** The boxes for a list of the form's figures. */
const typedFields = (fields: TypedField[]): string =>
  fields.map((f) => typedField(f.key, f.label, f.unit, f.required, f.help)).join("");

/** What the folded figures of each kind are, said on the fold. */
const MORE: Record<TypedKind, string> = {
  mosfet: "hot on-resistance, total, output and recovery charge, body diode",
  gan: "hot on-resistance, total and output charge, reverse conduction",
  igbt: "the recovery test voltage and the three energies at 25 °C",
};

/** The figures the part can do without, folded away until wanted or at fault. */
function typedMore(wrong: string, kind: TypedKind): string {
  const extra = fieldsOf(kind, app.setup.typed).filter((f) => !isMain(f));
  const t = app.state.typed;
  const inUse = extra.some((f) => f.key === wrong || f.key in ui.typedWrong || String(t[f.key] ?? "").trim() !== "");
  const open = inUse ? " open" : "";
  const about = `<span class="quiet">optional: ${MORE[kind]}. Each one sharpens the result</span>`;
  const summary = `<summary>${icon("adjustments")}More figures${about}</summary>`;
  const fields = typedFields(extra);
  return `<details class="more" data-fold="typed-more"${open}>${summary}<div class="fields">${fields}</div></details>`;
}

/** The button that adds the typed part, held while it is being added, with what it waits
 *  for: the engine still starting in this browser, or the part being built. */
function typedAdd(): string {
  const busy = ui.typedBusy;
  const label = `${icon("plus")}${busy ? "Adding" : "Add this part"}`;
  const button = `<button type="button" class="ghost" data-add-typed ${busy ? "disabled" : ""}>${label}</button>`;
  const count = Object.keys(ui.typedWrong).length;
  const wrong = count
    ? `<p class="help said-wrong" role="alert">${count === 1 ? "One box needs" : `${count} boxes need`} a change: ` +
      "each says why.</p>"
    : "";
  const why = !busy
    ? ""
    : ui.starting
      ? waiting("The figures are checked. Waiting for the engine to start in this browser: the part is added then.")
      : waiting("Building the part from its figures.");
  return `${wrong}<p>${button}</p>${why}`;
}

/** The switch between the kinds of part: one press, checked all at once like the figures. */
export function kindSwitch(kind: TypedKind): string {
  const option = ([k, label]: [TypedKind, string]) =>
    `<label><input type="radio" name="typed-kind" value="${k}" data-typed-kind${k === kind ? " checked" : ""}/>` +
    `<span>${label}</span></label>`;
  return (
    `<fieldset class="typed-kind"><legend>Kind of part</legend>` +
    `<div class="segmented radios">${TYPED_KINDS.map(option).join("")}</div></fieldset>`
  );
}

/** The choices beside the name, by kind: a MOSFET's material and package, an IGBT's
 *  arrangement. GaN has its own material, and no package list of its own. */
function kindChoices(kind: TypedKind): string {
  const form = app.setup.typed;
  const outline = typedPick(
    "outline",
    "Package",
    form.outlines,
    "another package",
    "Sets what lies between the case and a heatsink.",
  );
  if (kind === "gan") return outline;
  if (kind === "igbt") {
    const arranged = form.igbt?.topologies ?? ["discrete"];
    return typedPick(
      "topology",
      "Arrangement",
      arranged,
      "",
      "Discrete is one IGBT; a half bridge two, a six-pack six, each figure for one of them.",
      ARRANGED,
    );
  }
  const material = typedPick(
    "technology",
    "Material",
    mosfetTechnologies(form),
    "",
    "Silicon unless the datasheet says otherwise.",
  );
  return `${material}${outline}`;
}

/** How the figures are copied, and what an empty box marked optional comes to. */
const COPY =
  "Copy each figure as the datasheet prints it, typical values where it gives them. A box marked optional " +
  "may be left empty: the tool then takes a figure, says which, and holds the verdict at a caution until " +
  "the datasheet's is given.";

/** What the form is, said on its fold. */
const ABOUT = "MOSFET, GaN or IGBT, from the figures of its tables: no file, no key";

/** A transistor typed in from its datasheet: the figures of its tables, in their own units. */
export function typedForm(): string {
  const form = app.setup.typed;
  const t = app.state.typed;
  const kind = kindOf(t, form);
  const fields = fieldsOf(kind, form);
  const typedRefused = ui.typedRefused;
  const wrong = typedRefused?.field ?? "";
  const open =
    ui.typedOpen || Object.entries(t).some(([k, v]) => k !== "kind" && String(v ?? "").trim() !== "") ? " open" : "";
  const title = `${icon("adjustments")}Type in the figures from its datasheet`;
  const summary = `<summary>${title}<span class="quiet">${ABOUT}</span></summary>`;
  const named = "Left empty, it is called by its kind and numbered.";
  const partNumber = typedField("part_number", "Part number", "", false, named);
  const maker = typedField("vendor", "Maker", "", false, "");
  const elsewhere = typedRefused && !fields.some((f) => f.key === wrong) && !NAMES.has(wrong);
  return `<details class="more typed"${open}>${summary}
${kindSwitch(kind)}
<p class="quiet">${COPY}</p>
<div class="fields">${partNumber}${maker}
${kindChoices(kind)}
${typedFields(fields.filter(isMain))}</div>
${typedMore(wrong, kind)}
${elsewhere ? refusal(typedRefused) : ""}
${typedAdd()}</details>`;
}
