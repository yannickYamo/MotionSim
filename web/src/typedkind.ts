// The kind of part being typed in: a MOSFET (silicon or silicon carbide), a GaN transistor or
// an IGBT with its diode. The kind says which figures the form asks for, and only that
// kind's figures are sent: what was typed for another kind is kept, and left out.

import type { Setup } from "./api";

export type TypedKind = "mosfet" | "gan" | "igbt";
export type TypedField = Setup["typed"]["fields"][number];

/** The kinds, in the order they are offered, each as the switch says it. */
export const TYPED_KINDS: [TypedKind, string][] = [
  ["mosfet", "MOSFET"],
  ["gan", "GaN"],
  ["igbt", "IGBT"],
];

/** The boxes that hold a name, not a figure. */
export const NAMES = ["part_number", "vendor"];

const GAN = "GaN HEMT";

/** The kind the form is on: the one picked, else the one its technology says. */
export function kindOf(typed: Record<string, string>, form: Setup["typed"]): TypedKind {
  const picked = typed.kind;
  if (picked === "mosfet" || picked === "gan" || picked === "igbt") return picked;
  if (typed.technology === GAN) return "gan";
  return form.igbt && typed.technology === form.igbt.technology ? "igbt" : "mosfet";
}

/** The figures the form asks for, for this kind. */
export function fieldsOf(kind: TypedKind, form: Setup["typed"]): TypedField[] {
  return kind === "igbt" && form.igbt ? form.igbt.fields : form.fields;
}

/** The technologies a MOSFET can be: every one the form knows but GaN. */
export const mosfetTechnologies = (form: Setup["typed"]): string[] => form.technologies.filter((t) => t !== GAN);

/** The technology sent for this kind: an IGBT's and GaN's are fixed, a MOSFET's is picked. */
export function technologyOf(kind: TypedKind, typed: Record<string, string>, form: Setup["typed"]): string {
  if (kind === "igbt") return form.igbt?.technology ?? "Si IGBT";
  if (kind === "gan") return GAN;
  const own = mosfetTechnologies(form);
  return own.includes(typed.technology) ? typed.technology : own[0];
}

/** What is sent to build the part: the name, the technology, and this kind's own figures and
 *  choices, nothing typed for another kind. */
export function sentFigures(
  kind: TypedKind,
  figures: Record<string, string>,
  form: Setup["typed"],
): Record<string, string> {
  const keys = [...NAMES, ...fieldsOf(kind, form).map((f) => f.key), kind === "igbt" ? "topology" : "outline"];
  const sent: Record<string, string> = { technology: technologyOf(kind, figures, form) };
  for (const key of keys) if (figures[key] !== undefined) sent[key] = figures[key];
  if (kind === "igbt" && !sent.topology && form.igbt) sent.topology = form.igbt.topologies[0];
  return sent;
}

/** The box a check about a figure takes the keyboard to: the cold energies are said as one,
 *  and the first of them is the box. */
export const boxOf = (field: string): string => (field === "e_cold" ? "e_on_cold" : field);
