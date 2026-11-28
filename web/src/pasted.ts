// A datasheet's figures pasted in one go: a row, a few rows or a whole table copied from the
// PDF. Each figure is found by its symbol (VDS, RDS(on), Qgd…), its conditions ("VGS = 10 V")
// are set aside, and of min, typ and max the typical is taken. What is found is put in the
// typed part's boxes as text, with its unit, so the one reader of every box reads it.

import type { TypedKind } from "./typedkind";

/** Symbols as datasheets print them, folded to lower case with no spaces, brackets, dashes or
 *  underscores, for each box of the typed part. The first kind listed is where a symbol
 *  shared by both goes when the kind says nothing. */
const SYMBOLS: Record<string, { kinds: TypedKind[]; names: string[] }> = {
  v_rated: { kinds: ["mosfet", "gan", "igbt"], names: ["vds", "vdss", "vbrdss", "bvdss", "vces", "vcesmax", "vdsmax"] },
  i_rated: { kinds: ["mosfet", "gan", "igbt"], names: ["id", "idnom", "ic", "icnom", "id25", "ic100", "idc"] },
  tj_max: { kinds: ["mosfet", "gan", "igbt"], names: ["tj", "tjmax", "tvj", "tvjop", "tvjmax", "tjop"] },
  rth_jc: { kinds: ["mosfet", "gan", "igbt"], names: ["rthjc", "rθjc", "rthjcigbt", "rthjct", "rthjcmax"] },
  rth_jc_diode: { kinds: ["igbt"], names: ["rthjcd", "rthjcdiode", "rthjcfwd"] },
  rds_on: { kinds: ["mosfet", "gan"], names: ["rdson", "rdsonmax", "rdsontyp"] },
  v_th: { kinds: ["mosfet", "gan"], names: ["vgsth", "vth", "vgsto"] },
  v_plateau: { kinds: ["mosfet", "gan"], names: ["vplateau", "vpl", "vgp", "vgsplateau", "vgspl"] },
  q_gs: { kinds: ["mosfet", "gan"], names: ["qgs", "qgs1"] },
  q_gd: { kinds: ["mosfet", "gan"], names: ["qgd"] },
  q_g: { kinds: ["mosfet", "gan"], names: ["qg", "qgtot", "qgtotal"] },
  q_oss: { kinds: ["mosfet", "gan"], names: ["qoss"] },
  c_oss: { kinds: ["mosfet", "gan"], names: ["coss"] },
  q_rr: { kinds: ["mosfet", "gan"], names: ["qrr"] },
  v_sd: { kinds: ["mosfet", "gan"], names: ["vsd"] },
  rg_internal: { kinds: ["mosfet", "gan"], names: ["rg", "rgint", "rgi"] },
  vce_sat: { kinds: ["igbt"], names: ["vcesat", "vce"] },
  vf: { kinds: ["igbt"], names: ["vf", "vec"] },
  e_on: { kinds: ["igbt"], names: ["eon"] },
  e_off: { kinds: ["igbt"], names: ["eoff"] },
  e_rr: { kinds: ["igbt"], names: ["err", "erec", "erecdiode"] },
};

/** A token as a symbol: lower case, without spaces, brackets, dashes, dots or underscores. */
const fold = (s: string): string =>
  s
    .toLowerCase()
    .replace(/[θϑ]/g, "θ")
    .replace(/[\s()[\]{},._\-–:]/g, "");

const BY_SYMBOL = new Map<string, string>();
for (const [key, { names }] of Object.entries(SYMBOLS)) for (const n of names) BY_SYMBOL.set(n, key);

/** A number as a datasheet prints it, with an optional unit after it. */
const FIGURE =
  /([+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?)\s*(m?Ω|mohm|ohm|[kmµun]?[VAJCF]|[µun]C|nC|pF|mJ|µJ|K\/W|°C|C\/W)?/g;

/** A condition a figure was measured at ("VGS = 10 V", "Tj=25°C", "ID = 30 A"): set aside. */
const NUMBER = String.raw`[+-]?\d+(?:[.,]\d+)?`;
const CONDITION = new RegExp(
  String.raw`\b[A-Za-zθ][\w()θ,.-]*\s*[=≤≥<>]\s*${NUMBER}` +
    String.raw`(?:\s*(?:to|…|\.\.\.?|–|-)\s*${NUMBER})?\s*(?:[kmµun]?[A-Za-zΩ°/]+)?`,
  "g",
);

/** The unit each box's figure is in, by its last letters: a figure in another unit on the same
 *  row (a test current beside a charge) is not the box's. */
const UNIT_OF: Record<string, RegExp> = {
  v_rated: /V$/,
  i_rated: /A$/,
  rth_jc: /W$/,
  rth_jc_diode: /W$/,
  rds_on: /(Ω|ohm)$/,
  v_th: /V$/,
  v_plateau: /V$/,
  q_gs: /C$/,
  q_gd: /C$/,
  q_g: /C$/,
  q_oss: /C$/,
  c_oss: /F$/,
  q_rr: /C$/,
  v_sd: /V$/,
  rg_internal: /(Ω|ohm)$/,
  vce_sat: /V$/,
  vf: /V$/,
  e_on: /J$/,
  e_off: /J$/,
  e_rr: /J$/,
};

export interface Pasted {
  /** Box by box, the text to put in it: a figure and its unit. */
  figures: Record<string, string>;
  /** What was read from what, said once, box by box. */
  notes: Record<string, string>;
  /** The kind the symbols point to, where they point to one: an IGBT's VCES, a MOSFET's RDS(on). */
  kind: TypedKind | null;
}

/** The typical of what a datasheet row gives: min, typ and max → typ; two → the first, which is
 *  the typical where a row gives typ and max; one → itself. A junction rating's range ("-55 …
 *  175") is the other way: its top. */
function typical(key: string, values: { v: string; unit: string }[]): { v: string; unit: string; said: string } {
  const unit = values.find((x) => x.unit)?.unit ?? "";
  if (key === "tj_max") {
    const top = values.reduce((a, b) => (Number(b.v.replace(",", ".")) > Number(a.v.replace(",", ".")) ? b : a));
    return { v: top.v, unit, said: values.length > 1 ? "the top of its range" : "" };
  }
  if (values.length >= 3) return { v: values[1].v, unit, said: "typ of min, typ, max" };
  if (values.length === 2) return { v: values[0].v, unit, said: "typ of typ, max" };
  return { v: values[0].v, unit, said: "" };
}

/** The symbol that starts at word k: the longest run of up to three words that folds to one,
 *  and how many words it took. */
function symbolAt(words: string[], k: number): { key: string; taken: number } | null {
  for (let n = Math.min(3, words.length - k); n >= 1; n--) {
    const key = BY_SYMBOL.get(fold(words.slice(k, k + n).join("")));
    if (key) return { key, taken: n };
  }
  return null;
}

/** The figures after a symbol, in the box's unit where the row gives that unit. */
function figuresIn(key: string, tail: string): { v: string; unit: string }[] {
  const all = [...tail.matchAll(FIGURE)].map((m) => ({ v: m[1], unit: m[2] ?? "" }));
  const want = UNIT_OF[key];
  // A row with the box's unit keeps the figures in it, and the bare ones beside them.
  return want && all.some((x) => want.test(x.unit)) ? all.filter((x) => !x.unit || want.test(x.unit)) : all;
}

/** An IGBT's second junction-to-case resistance, or one said to be the diode's, is the diode's. */
function boxOf(key: string, raw: string, kindNow: TypedKind, figures: Record<string, string>): string {
  if (key !== "rth_jc" || kindNow !== "igbt") return key;
  return /diode|fwd|\bD\b/i.test(raw) || figures.rth_jc ? "rth_jc_diode" : key;
}

/** One line as plain words: its conditions and its dotted leaders set aside. */
const wordsOf = (raw: string): string[] =>
  raw
    .replace(CONDITION, " ")
    .replace(/\b[A-Za-zθ][\w()θ]*\s*=\s*[A-Za-zθ][\w()θ]*(?=[\s,;]|$)/g, " ")
    .replace(/\.{2,}|…/g, " ")
    .split(/[\s\t]+/)
    .filter(Boolean);

/** Read what was pasted. Lines are read one by one; a line with several symbols on it (a row
 *  copied across a table) is cut at each. */
export function readPasted(text: string, kindNow: TypedKind): Pasted {
  const figures: Record<string, string> = {};
  const notes: Record<string, string> = {};
  const votes: Record<TypedKind, number> = { mosfet: 0, gan: 0, igbt: 0 };
  const take = (key: string, raw: string, tail: string) => {
    const box = boxOf(key, raw, kindNow, figures);
    const values = figuresIn(key, tail);
    if (!values.length || box in figures) return;
    const t = typical(box, values);
    figures[box] = t.unit ? `${t.v} ${t.unit}` : t.v;
    if (t.said) notes[box] = `Read as ${figures[box]}: ${t.said}.`;
    const kinds = SYMBOLS[key].kinds;
    if (kinds.length === 1) votes[kinds[0]]++;
    else if (!kinds.includes("igbt")) votes.mosfet++;
  };
  for (const raw of text.split(/\r?\n|\t{2,}|;/)) {
    const words = wordsOf(raw);
    let k = 0;
    while (k < words.length) {
      const hit = symbolAt(words, k);
      if (!hit) {
        k++;
        continue;
      }
      // Its figures run until the next symbol.
      let end = k + hit.taken;
      while (end < words.length && !BY_SYMBOL.has(fold(words[end]))) end++;
      take(hit.key, raw, words.slice(k + hit.taken, end).join(" "));
      k = end;
    }
  }
  const mosfet = kindNow === "gan" ? "gan" : "mosfet";
  const kind = votes.igbt > votes.mosfet ? "igbt" : votes.mosfet > votes.igbt ? mosfet : null;
  return { figures, notes, kind };
}

/** A range typed in one box ("2–4", "2 to 4", "2…4 V"): the middle, said as such. Null where the
 *  text is no range. */
export function middleOf(text: string): { text: string; note: string } | null {
  const m = /^\s*([+-]?\d+(?:[.,]\d+)?)\s*(?:–|—|-|to|\.\.\.?|…)\s*([+-]?\d+(?:[.,]\d+)?)\s*(\S.*)?$/.exec(text);
  if (!m) return null;
  const a = Number(m[1].replace(",", "."));
  const b = Number(m[2].replace(",", "."));
  if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) return null;
  const mid = Number(((a + b) / 2).toPrecision(6));
  const unit = m[3] ? ` ${m[3].trim()}` : "";
  return { text: `${mid}${unit}`, note: `Read as ${mid}${unit}: the middle of ${m[1]}–${m[2]}.` };
}
