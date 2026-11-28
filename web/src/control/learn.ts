// The learning layer of a block: why a figure has the value it has, in one line (the rule it
// was tuned by), and what changing it does. The rule is the engine's own account of the value,
// cut to the line that carries its equation; the account in full stays one press away.

/** The longest a rule's line is shown before it is cut at a clause. */
const LINE = 90;

const upper = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

/** A clause cut from a long sentence: at the first comma or bracket past a few words. */
function clause(s: string): string {
  if (s.length <= LINE) return s;
  const cut = s.slice(30).search(/[,;(]\s|:\s/);
  const at = cut >= 0 ? cut + 30 : -1;
  if (at > 0 && at <= LINE + 20) return s.slice(0, at).trim();
  const space = s.lastIndexOf(" ", LINE);
  return `${s.slice(0, space > 30 ? space : LINE).trim()}…`;
}

/** The tuning rule of a value in one line: the last sentence of the engine's account that
 *  carries an equation ("Kp = J·ωs, J = 0.774 kg·m²"), else its first clause. */
export function ruleOf(source: string | undefined): string {
  const text = (source ?? "").trim().replace(/\s+/g, " ");
  if (!text) return "";
  const sentences = text
    .split(/(?<=\.)\s+(?=\S)/)
    .map((s) => s.replace(/\.$/, "").trim())
    .filter(Boolean);
  const withEquation = sentences.filter((s) => /\s=\s/.test(s));
  const short = withEquation.filter((s) => s.length <= LINE);
  const picked = short.length ? short[short.length - 1] : (withEquation[0] ?? sentences[0]);
  return upper(clause(picked));
}

/** What changing a figure does, in one line, by the figure's name and the kind of block. */
const EFFECTS: [RegExp, RegExp, string][] = [
  [/current/, /^gain$/, "Above 0.25 the poles turn complex: faster, with overshoot. Below: slower, none."],
  [/./, /^kp(_\w+)?$/, "Raise: faster answer, less phase margin, more noise passed on. Lower: slower, calmer."],
  [/./, /^ki(_\w+)?$/, "Raise: the error is taken out sooner, with more overshoot. Lower: slower recovery."],
  [/./, /^(limit|i_limit)$/, "The most it asks for. Reached, the integral holds and the block says At limit."],
  [/observer/, /^bandwidth$/, "Raise: the estimate follows faster, with more ripple and noise in it."],
  [/./, /^pll_bandwidth$/, "Raise: locks and follows acceleration faster, with more angle jitter."],
  [/./, /^slew$/, "Raise: the reference ramps faster and asks more torque on the way."],
  [/startup|if_/, /^current$/, "Raise: more starting torque, and more loss while starting."],
  [/./, /^handover$/, "Raise: the observer takes over later, with more back-EMF to read."],
  [/./, /^voltage_share$/, "Raise: more speed before the voltage runs out, nearer overmodulation."],
  [/./, /^rate$/, "Raise: torque steps arrive sooner, with more current overshoot."],
];

export function effectOf(kind: string, param: string): string {
  return EFFECTS.find(([k, p]) => k.test(kind) && p.test(param))?.[2] ?? "";
}
