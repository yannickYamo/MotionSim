// Reading what was typed. One reader for every box on the page, so that a figure means the
// same in each: a number is taken only when it can be read one way.

export type Read =
  /** comma: a comma was read as the decimal point, which the box then says.
   *  echo: what a figure typed with a unit or a prefix came to in the box's unit ("= 0.00012 H").
   *  hz: a kHz box was given a figure in hertz, and took it as such. */
  | { ok: true; value: number; comma?: boolean; echo?: string; hz?: boolean }
  /** empty: nothing was typed. bad: something was, and `why` says what to do about it. */
  | { ok: false; empty: boolean; why: string };

const PLAIN = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;
/** A comma where a decimal point goes: how half the world writes a number. */
const DECIMAL_COMMA = /^[+-]?(\d+,\d*|,\d+)([eE][+-]?\d+)?$/;
/** Three figures after each comma: one thousand five hundred to some, one and a half to others. */
const GROUPED_BY_COMMA = /^[+-]?[1-9]\d{0,2}(,\d{3})+$/;
/** Thousands set apart by a space, as the page itself prints them: read one way only. */
const GROUPED_BY_SPACE = /^[+-]?\d{1,3}([ \u00a0\u202f]\d{3})+([.,]\d+)?$/;
/** A figure, then whatever follows it: a unit, a prefix, or something that is neither. */
const FIGURE_THEN = /^([+-]?[\d.,\s\u00a0\u202f]*\d[.,]?(?:[eE][+-]?\d+)?)\s*([^\d\s.,].*)$/;

/** The SI prefixes a figure may be typed with. Their case is kept: m is a thousandth and M a
 *  million, so "20 mhz" is never read as megahertz. A capital K before a unit is a kilo too,
 *  as it is often written ("20 KHz"); alone it is not, since a kelvin is a K. */
const PREFIX: Record<string, number> = { p: 1e-12, n: 1e-9, µ: 1e-6, m: 1e-3, k: 1e3, M: 1e6, G: 1e9 };
const prefixOf = (letter: string, beforeUnit: boolean): number | undefined =>
  PREFIX[letter] ?? (letter === "K" && beforeUnit ? 1e3 : undefined);

/** Whether a box's unit is a mass or holds a metre: there a lone m is a metre, not a thousandth. */
const metric = (base: string): boolean =>
  base
    .split(" ")[0]
    .split(/[·/()²]+/)
    .some((t) => t === "m" || t === "g");
/** Units a prefix is never put before. */
const BARE = new Set(["°C", "%", "cm²", "times", "deg", "°"]);
/** The units the page's boxes are in, by their base. A box in mΩ is one in Ω, a thousand
 *  times smaller. */
const BASES = new Set([
  "H",
  "Ω",
  "V",
  "A",
  "W",
  "Hz",
  "s",
  "C",
  "F",
  "J",
  "rpm",
  "K/W",
  "N·m",
  "N·m/A",
  "N·m/A²",
  "g",
  "m",
  "g·m²",
  "rpm/V",
  "V·s/rad",
  "Wb",
  "rad/s",
  "N",
  "N·m/(rad/s)",
  "N·m/(rad/s)²",
]);

/** A unit as it may be typed, spelled as the page spells it. */
function spelled(unit: string): string {
  return unit
    .trim()
    .replace(/[\u2126]/g, "Ω")
    .replace(/[μu](?=\S)/, "µ")
    .replace(/^u$/, "µ")
    .replace(/μ/g, "µ")
    .replace(/ohms?$/i, "Ω")
    .replace(/hz$/i, "Hz")
    .replace(/rpm$/i, "rpm")
    .replace(/\^?2$/, "²")
    .replace(/\^?3$/, "³")
    .replace(/(?<=[A-Za-zΩ])\s*[*.]\s*(?=[A-Za-z])/g, "·")
    .replace(/^(k?)gm²$/, "$1g·m²")
    .replace(/Nm/g, "N·m")
    .replace(/\s+(rms|peak)$/i, " $1")
    .replace(/(?<=A)(rms|peak)$/i, " $1");
}

/** A box's unit as its base and the scale of its prefix: mΩ is Ω at 1e-3, kHz is Hz at 1e3.
 *  A qualifier ("A rms") stays with the base. */
function baseOf(unit: string): { base: string; scale: number; bare: boolean } {
  const u = spelled(unit);
  const [head, ...rest] = u.split(" ");
  const tail = rest.length ? ` ${rest.join(" ")}` : "";
  if (BARE.has(u)) return { base: u, scale: 1, bare: true };
  if (BASES.has(head)) return { base: head + tail, scale: 1, bare: false };
  const p = prefixOf(head[0], true);
  if (p && BASES.has(head.slice(1))) return { base: head.slice(1) + tail, scale: p, bare: false };
  return { base: u, scale: 1, bare: true };
}

/** A figure written out plainly, as far as it was given. */
export const plainly = (v: number) => String(Number(v.toPrecision(10)));

/** The number alone: a point or a comma, thousands set apart by spaces. */
function readPlain(text: string): Read {
  let t = text;
  if (GROUPED_BY_COMMA.test(t)) {
    const whole = t.replace(/,/g, "");
    const parts = t.split(",");
    const decimal = `${parts[0]}.${parts.slice(1).join("")}`;
    return bad(`${t} can be read two ways. Write ${whole}, or ${decimal} with a point.`);
  }
  if (GROUPED_BY_SPACE.test(t)) t = t.replace(/[ \u00a0\u202f]/g, "");
  const comma = DECIMAL_COMMA.test(t);
  if (comma) t = t.replace(",", ".");
  if (!PLAIN.test(t)) return bad("Not a number.");
  const value = Number(t);
  if (!Number.isFinite(value)) return bad("Too large to be a figure.");
  return comma ? { ok: true, value, comma } : { ok: true, value };
}

const bad = (why: string): Read => ({ ok: false, empty: false, why });

/** A box's unit as its base, the scale of its prefix and whether a prefix may go before it. */
type Base = ReturnType<typeof baseOf>;
type Taken = Extract<Read, { ok: true }>;

/** A kHz box takes a figure of 10 000 or more as one in hertz, and says so. */
function inKilohertz(plain: Taken, box: Base | null): Read {
  if (!box || box.base !== "Hz" || box.scale !== 1e3 || Math.abs(plain.value) < 10000) return plain;
  const value = plain.value / 1000;
  return {
    ...plain,
    value,
    hz: true,
    echo: `Read as ${plainly(value)} kHz: a figure of 10 000 or more is taken to be in Hz.`,
  };
}

/** What a figure typed with a unit or a prefix is multiplied by to be in the box's base unit,
 *  and the prefix it was typed with. Null where what follows the figure is no unit the box takes. */
function scaleOf(typed: string, box: Base | null, bareBase: string): { scale: number | null; prefix: string } {
  if (!box) return { scale: PREFIX[typed] ?? null, prefix: "" };
  if (box.bare) return { scale: typed === box.base ? 1 : null, prefix: "" };
  // A box in A rms takes "12 A": the box says which current it is.
  if (typed === box.base || typed === bareBase) return { scale: 1, prefix: "" };
  if (prefixOf(typed[0], true) && [box.base, bareBase].includes(typed.slice(1))) {
    return { scale: prefixOf(typed[0], true)!, prefix: typed[0] };
  }
  // A lone m, in a box of a mass or of something in metres, is a metre: refused below.
  if (PREFIX[typed] !== undefined && !(typed === "m" && metric(box.base)))
    return { scale: PREFIX[typed], prefix: typed };
  return { scale: null, prefix: "" };
}

/** Why a figure followed by something that is no unit of the box's is not taken. */
function notInUnit(typed: string, said: string, shown: string): Read {
  if (!/^[A-Za-zµΩ°%·/²³() ]+$/.test(typed) || /^[eE]$/.test(typed)) return bad("Not a number.");
  if (!shown) return bad(`${said} is not a plain number, which this box takes.`);
  return bad(`${said} is not a figure in ${shown}.`);
}

/** How a figure was written: the unit typed after it, the box's own unit as the page spells
 *  it, the box's base without a qualifier, and the box's unit read as a base and a scale. */
interface Written {
  typed: string;
  shown: string;
  bareBase: string;
  box: Base | null;
}

/** The figure in the box's unit, and what it came to where that is worth saying. */
function scaled(read: Taken, scale: number, w: Written): Read {
  const { typed, shown, bareBase, box } = w;
  const value = Number(((read.value * scale) / (box && !box.bare ? box.scale : 1)).toPrecision(15));
  if (!Number.isFinite(value)) return bad("Too large to be a figure.");
  const out: Read = { ok: true, value };
  if (read.comma) out.comma = true;
  if (typed !== shown && !(typed === bareBase && scale === 1 && box?.scale === 1))
    out.echo = `= ${plainly(value)}${shown ? ` ${shown}` : ""}`;
  return out;
}

/** A figure followed by a unit or a prefix, turned into the box's unit, or why it is not taken. */
function readWithUnit(t: string, unit: string | undefined, box: Base | null): Read {
  const [, figure, after] = FIGURE_THEN.exec(t)!;
  const read = readPlain(figure.trim());
  if (!read.ok) return read;
  const written: Written = {
    typed: spelled(after),
    shown: unit ? spelled(unit) : "",
    bareBase: box ? box.base.split(" ")[0] : "",
    box,
  };
  const { scale, prefix } = scaleOf(written.typed, box, written.bareBase);
  if (prefix === "m" && written.bareBase === "Hz") {
    // No switching frequency is a thousandth of a hertz: what was meant cannot be told.
    const said = `${figure.trim()} ${after}`.replace(/\s+$/, "");
    return bad(
      `${said} would be a millihertz, which no switching frequency is. Write it in kHz, or MHz with a capital M.`,
    );
  }
  if (scale === null) return notInUnit(written.typed, `${figure.trim()} ${after}`, written.shown);
  return scaled(read, scale, written);
}

/**
 * The number in what was typed, in the box's unit, or why it cannot be taken as one.
 * `unit`: the unit the box is in, when it has one. A figure may then be typed with that
 * unit or none, and with an SI prefix: "120 µH", "120u", "45 mΩ", "2k". It is turned into
 * the box's unit, and `echo` says what it came to. A unit of another kind is refused with
 * the box's own unit named. A kHz box takes a figure of 10 000 or more as one in hertz.
 */
export function readNumber(text: string | number | null | undefined, unit?: string): Read {
  if (typeof text === "number") return Number.isFinite(text) ? { ok: true, value: text } : bad("Not a number.");
  const t = String(text ?? "").trim();
  if (t === "") return { ok: false, empty: true, why: "Empty." };
  const box = unit ? baseOf(unit) : null;
  const plain = readPlain(t);
  if (plain.ok) return inKilohertz(plain, box);
  if (plain.why !== "Not a number." || !FIGURE_THEN.test(t)) return plain;
  return readWithUnit(t, unit, box);
}

/** The number typed, or null for a box left empty or holding something that is not one. */
export function numberOr(
  text: string | number | null | undefined,
  otherwise: number | null = null,
  unit?: string,
): number | null {
  const read = readNumber(text, unit);
  return read.ok ? read.value : otherwise;
}

/** Several figures typed in one box, parted by spaces or semicolons, or by a comma followed
 *  by a space: a comma alone between figures is a decimal point. Each figure is read as any
 *  box reads one: with the box's unit or a prefix, and with its thousands set apart by a
 *  space ("1 500" is one figure). Where words run on, the longest that read as one figure do. */
export function readList(text: string, unit?: string): Read[] {
  const out: Read[] = [];
  for (const part of text.split(/;|,\s+/)) {
    const words = part
      .trim()
      .replace(/,$/, "")
      .split(/\s+/)
      .filter((w) => w !== "");
    let k = 0;
    while (k < words.length) {
      const [taken, read] = readAt(words, k, unit);
      out.push(read);
      k += taken;
    }
  }
  return out;
}

/** The figure that starts at word k: the longest run of words that reads as one figure, and
 *  how many words it took. */
function readAt(words: string[], k: number, unit?: string): [number, Read] {
  let taken = 1;
  let read = readNumber(words[k], unit);
  for (let n = words.length - k; n > 1; n--) {
    const longer = readNumber(words.slice(k, k + n).join(" "), unit);
    if (longer.ok) {
      [taken, read] = [n, longer];
      break;
    }
  }
  // A figure followed by a unit of another kind is refused as that, naming the box's unit.
  const next = words[k + 1];
  if (taken === 1 && unit && next && !/^[+-]?[\d.,]/.test(next)) {
    const withUnit = readNumber(`${words[k]} ${next}`, unit);
    if (!withUnit.ok) [taken, read] = [2, withUnit];
  }
  return [taken, read];
}

/** The temperatures of the typed form: above 25 °C, where everything else is above zero. */
const TEMPERATURES = new Set(["tj_max", "rds_hot_tj", "hot_tj"]);

/** The most characters in a part's name or maker. */
export const MOST_NAME = 80;

interface TypedRead {
  /** The figures as the engine reads them: each numeric box as every box on the page is. */
  figures: Record<string, string>;
  /** Every box that cannot be used, with why: all of them at once, not one at a time. */
  wrong: Record<string, string>;
  /** What a box says of a figure it took: a comma read as a decimal point. */
  notes: Record<string, string>;
}

/**
 * The figures of the part typed in, checked as far as the page can without the engine: the
 * name is not too long, every figure the form needs is given, each one is a number, and each
 * is above zero (a temperature above 25 °C), or nought where `nought` names it. A name left
 * empty is the engine's to give, by the kind of part. The engine has the last word on the rest.
 */
export function typedFigures(
  typed: Record<string, string>,
  numeric: { key: string; label: string; unit?: string; required?: boolean }[],
  nought: ReadonlySet<string> = new Set(),
): TypedRead {
  const figures = { ...typed };
  const wrong: Record<string, string> = {};
  const notes: Record<string, string> = {};
  const name = String(typed.part_number ?? "").trim();
  if (name.length > MOST_NAME) wrong.part_number = `A part number of ${MOST_NAME} characters at most.`;
  for (const { key, unit, required } of numeric) {
    const read = readNumber(typed[key], unit);
    if (!read.ok) {
      if (!read.empty) wrong[key] = read.why;
      else if (required) wrong[key] = "Needed: copy it from the datasheet.";
      continue;
    }
    figures[key] = String(read.value);
    // A figure that may be nought (a GaN part's recovery charge, which it has none of) is
    // taken as left empty.
    if (read.value === 0 && nought.has(key)) delete figures[key];
    else if (TEMPERATURES.has(key) ? read.value <= 25 : read.value <= 0) {
      wrong[key] = TEMPERATURES.has(key) ? "Has to be above 25 °C." : "Has to be above zero.";
    } else if (read.comma) notes[key] = `Read as ${read.value}: the comma is taken as the decimal point.`;
    else if (read.echo) notes[key] = read.echo;
  }
  return { figures, wrong, notes };
}
