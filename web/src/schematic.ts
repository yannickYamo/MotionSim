// The power stage, drawn as a circuit diagram that carries the result: each switch warms
// towards orange as its junction heats, and the motor is drawn as the kind of machine it is.

import type { Position, Result, Stage } from "./api";
import { degrees, escape, sig } from "./format";

const W = 760;
const H = 430;
const RAIL_TOP = 64;
const RAIL_BOTTOM = 366;
const MID = (RAIL_TOP + RAIL_BOTTOM) / 2;
const LEFT = 132;
const MOTOR_X = 660;

interface Drawn { letters: string[]; legs: number[]; label: string }

function layout(kind: string): Drawn {
  const bridge = kind === "dc" || kind === "dc_series";
  const count = bridge ? 2 : kind === "stepper" ? 4 : 3;
  const first = 232;
  const last = kind === "stepper" ? 520 : 500;
  const legs = Array.from({ length: count }, (_, k) => first + (k * (last - first)) / Math.max(count - 1, 1));
  const letters = kind === "stepper" ? ["A+", "A−", "B+", "B−"] : ["A", "B", "C", "D"].slice(0, count);
  const label = bridge ? "H-bridge" : kind === "stepper" ? "Two H-bridges" : "Three-phase inverter";
  return { letters, legs, label };
}

/** The result row that describes one drawn switch. */
function positionFor(result: Result | null, leg: number, side: "high" | "low", kind: string): Position | null {
  if (!result) return null;
  const all = result.positions;
  if (all.length === 1) return all[0];
  const letter = "ABCD"[leg];
  return (
    all.find((p) => p.name.includes(`leg ${letter} ${side}`)) ??
    all.find((p) => p.name.startsWith(side)) ??
    (kind === "stepper" ? all[0] : null)
  );
}

function heat(position: Position | null, result: Result | null, tSink: number): number {
  if (!position || !result) return 0;
  const span = Math.max(result.tj_max - tSink, 1);
  return Math.min(Math.max((position.tj - tSink) / span, 0), 1.15);
}

/** A transistor with its reverse diode, as the standard symbol, centred on (x, y). */
/** How the part is packaged: what is drawn around the switches and at their gates. */
export interface Packaging { positions: number; driver: boolean }

function transistor(x: number, y: number, id: string, level: number, text: string, over: boolean, fet: boolean, pack: Packaging | null): string {
  const glow = level > 0 ? `<circle class="heat${over ? " over" : ""}" cx="${x}" cy="${y}" r="${22 + 8 * Math.min(level, 1)}" style="--heat:${Math.min(level, 1).toFixed(3)}"/>` : "";
  // Gate from the left, channel in the middle, diode on the right.
  const body = fet
    ? `<path d="M${x - 22} ${y}h10M${x - 12} ${y - 13}v26M${x - 7} ${y - 15}v8M${x - 7} ${y - 4}v8M${x - 7} ${y + 7}v8M${x - 7} ${y - 11}h9v-12M${x - 7} ${y + 11}h9v12M${x - 7} ${y}h9v11"/><path class="solid" d="M${x - 6} ${y}l6 -3v6z"/>`
    : `<path d="M${x - 22} ${y}h11M${x - 11} ${y - 13}v26M${x - 11} ${y - 6}l13 -9v-8M${x - 11} ${y + 6}l13 9v8"/><path class="solid" d="M${x + 2} ${y + 15}l-7 -1l4 -6z"/>`;
  const diode = `<path d="M${x + 2} ${y - 23}h16v15M${x + 18} ${y + 23}h-16M${x + 18} ${y + 23}v-15"/><path class="solid" d="M${x + 12} ${y + 6}h12l-6 -11z"/><path d="M${x + 12} ${y - 5}h12"/>`;
  const label = text
    ? `<text class="reading" x="${x + 34}" y="${y + 5}">${escape(text)}</text>`
    : "";
  // A gate driver inside the package is drawn as a buffer on the gate; a gate driven from
  // outside ends in an open terminal on the package edge.
  // A gate driven from outside: its gate resistor, drawn as a resistor, then the terminal
  // the driver connects to. A driver inside the package: a block marked with a pulse.
  const gate = !pack ? ""
    : pack.driver ? `<rect class="driver" x="${x - 42}" y="${y - 9}" width="18" height="18" rx="2"/><path class="driver-mark" d="M${x - 39} ${y + 4}h3v-8h6v8h3"/><path d="M${x - 24} ${y}h2M${x - 48} ${y}h6"/>`
    : `<path d="M${x - 50} ${y}h4l2 -4l4 8l4 -8l4 8l4 -8l2 4h4"/><circle class="pin" cx="${x - 53}" cy="${y}" r="3"/>`;
  return `<g class="switch" data-level="${level.toFixed(2)}">${glow}<g class="symbol">${body}${diode}${gate}</g><text class="ref" x="${x - (pack && !pack.driver ? 31 : 26)}" y="${y - 18}" text-anchor="end">${id}</text>${label}</g>`;
}

/** The outline of each package: one a switch, one a leg, or one round the whole bridge. */
function packages(legs: number[], pack: Packaging): { drawing: string; count: number } {
  const top = RAIL_TOP + 68;
  const bottom = RAIL_BOTTOM - 68;
  const box = (x0: number, y0: number, x1: number, y1: number) =>
    `<rect class="package" x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" rx="5"/>`;
  if (pack.positions < 2) {
    const each = legs.flatMap((x) => [top, bottom].map((y) => box(x - 25, y - 30, x + 30, y + 30)));
    return { drawing: each.join(""), count: each.length };
  }
  const span = Math.max(1, Math.floor(pack.positions / 2)); // legs in one package
  // A driver inside the package is within its outline; a gate resistor is outside it.
  const left = pack.driver ? 54 : 25;
  const groups: string[] = [];
  for (let k = 0; k < legs.length; k += span) {
    const last = legs[Math.min(k + span, legs.length) - 1];
    groups.push(box(legs[k] - left, top - 32, last + 30, bottom + 32));
  }
  return { drawing: groups.join(""), count: groups.length };
}

/** The package in words, for the plate's title. */
function packageName(pack: Packaging, count: number): string {
  const many = count > 1;
  if (pack.positions < 2) return `${count} discrete parts`;
  const kind = pack.driver ? "IPM" : pack.positions >= 6 ? "six-pack module" : pack.positions >= 4 ? "two-leg module" : "half-bridge module";
  const drivers = pack.driver ? ", gate drivers built in" : "";
  return `${many ? count : "one"} ${kind}${many ? "s" : ""}${drivers}`;
}

/** Height at which leg k leaves for the motor. Staggered, so the output wires never overlap. */
function tapY(k: number, count: number): number {
  return MID + (k - (count - 1) / 2) * (count > 3 ? 18 : 26);
}

const R_STATOR = 60;
const R_ROTOR = 42;

/** Points on a circle about the motor's centre, for drawing rotors. */
const at = (radius: number, degrees: number): string => {
  const a = (degrees * Math.PI) / 180;
  return `${(MOTOR_X + radius * Math.cos(a)).toFixed(1)} ${(MID + radius * Math.sin(a)).toFixed(1)}`;
};
const arc = (radius: number, from: number, to: number) => `M${at(radius, from)}A${radius} ${radius} 0 0 1 ${at(radius, to)}`;

/** What the rotor drawing needs to know about the motor. */
export interface Rotor { kind: string; magnets: string; polePairs: number; steps: number }

const MOST_POLES = 48; // more than this cannot be told apart at the size drawn

/** The rotor of each kind of motor as its cross-section is drawn: as many poles as the
 *  motor has, with the magnets or barriers where they sit. */
function rotor(m: Rotor): { drawing: string; fixed: string; name: string } {
  const { kind, magnets } = m;
  const body = `<circle class="steel" cx="${MOTOR_X}" cy="${MID}" r="${R_ROTOR}"/>`;
  const shaft = `<circle class="shaft" cx="${MOTOR_X}" cy="${MID}" r="5"/>`;
  const count = Math.min(Math.max(2 * Math.round(m.polePairs || 1), 2), MOST_POLES);
  const pitch = 360 / count;
  const poles = Array.from({ length: count }, (_, k) => k * pitch);
  const said = `${2 * Math.round(m.polePairs || 1)} poles`;
  if (kind === "induction") {
    // A squirrel cage: bars near the surface, all round. Their number is the rotor's own,
    // not the pole count, which is set by the stator winding.
    const bars = Array.from({ length: 22 }, (_, k) => { const [x, y] = at(R_ROTOR - 6, (k * 360) / 22).split(" "); return `<circle class="bar" cx="${x}" cy="${y}" r="2.6"/>`; }).join("");
    return { drawing: body + bars + shaft, fixed: "", name: `induction, squirrel cage, ${said}` };
  }
  if (kind === "synrm") {
    // Flux barriers: curved slots in each pole, bowed towards the shaft, that make one
    // axis easy to magnetise and the other hard. One set a pole.
    const shown = Math.min(count, 12);
    const step = 360 / shown;
    const depth = shown <= 4 ? [15, 24, 33] : shown <= 8 ? [9, 16] : [8];
    const barriers = Array.from({ length: shown }, (_, k) => {
      const c = ((k * step + step / 2) * Math.PI) / 180;
      const far = R_ROTOR + (shown <= 4 ? 7 : 3);
      const cx = MOTOR_X + far * Math.cos(c);
      const cy = MID + far * Math.sin(c);
      return depth.map((radius) => {
        const half = Math.acos(Math.min(1, (radius * radius + far ** 2 - (R_ROTOR - 3) ** 2) / (2 * radius * far)));
        const point = (angle: number) => `${(cx + radius * Math.cos(c + Math.PI + angle)).toFixed(1)} ${(cy + radius * Math.sin(c + Math.PI + angle)).toFixed(1)}`;
        return `<path class="slot" d="M${point(-half)}A${radius} ${radius} 0 0 1 ${point(half)}"/>`;
      }).join("");
    }).join("");
    return { drawing: body + barriers + shaft, fixed: "", name: `reluctance rotor, no magnets, ${said}` };
  }
  if (kind === "dc" || kind === "dc_series") {
    // An armature with slots and a commutator; the brushes stay put.
    const slots = Array.from({ length: 10 }, (_, k) => `<path class="slot thin" d="M${at(R_ROTOR - 9, k * 36)}L${at(R_ROTOR, k * 36)}"/>`).join("");
    const commutator = `<circle class="steel" cx="${MOTOR_X}" cy="${MID}" r="15"/>` + Array.from({ length: 8 }, (_, k) => `<path class="slot thin" d="M${at(8, k * 45)}L${at(15, k * 45)}"/>`).join("");
    const brushes = `<rect class="brush" x="${MOTOR_X - 27}" y="${MID - 5}" width="11" height="10"/><rect class="brush" x="${MOTOR_X + 16}" y="${MID - 5}" width="11" height="10"/>`;
    const field = kind === "dc_series"
      ? `<path class="slot" d="${arc(R_STATOR - 7, 250, 290)}"/><path class="slot" d="${arc(R_STATOR - 7, 70, 110)}"/>`
      : `<path class="magnet north" d="${arc(R_STATOR - 6, 235, 305)}"/><path class="magnet south" d="${arc(R_STATOR - 6, 55, 125)}"/>`;
    return { drawing: body + slots + commutator + shaft, fixed: field + brushes, name: kind === "dc_series" ? "brushed DC, series field" : "brushed DC, magnet field" };
  }
  if (kind === "stepper") {
    // A hybrid stepper's rotor has a quarter as many teeth as the motor has steps.
    const teeth = Math.min(Math.max(Math.round((m.steps || 200) / 4), 4), 72);
    const rotorTeeth = Array.from({ length: teeth }, (_, k) => `<path class="slot thin" d="M${at(R_ROTOR - 4, (k * 360) / teeth)}L${at(R_ROTOR + 2.5, (k * 360) / teeth)}"/>`).join("");
    const statorTeeth = Array.from({ length: 8 }, (_, k) => `<path class="slot thin" d="M${at(R_STATOR - 9, k * 45 + 22.5)}L${at(R_STATOR - 2, k * 45 + 22.5)}"/>`).join("");
    return { drawing: `<circle class="steel" cx="${MOTOR_X}" cy="${MID}" r="${R_ROTOR - 4}"/>` + rotorTeeth + shaft, fixed: statorTeeth, name: `stepper, ${Math.round(m.steps || 200)} steps a turn, ${Math.round((m.steps || 200) / 4)} rotor teeth` };
  }
  // Permanent-magnet rotors: one magnet a pole, north and south in turn. Where the magnets
  // sit is what tells the kinds apart.
  const pole = (k: number) => (k % 2 ? "south" : "north");
  const gap = Math.min(0.12 * pitch, 8);
  if (magnets === "interior") {
    // Buried below the surface: a V a pole while there is room for one, a flat bar beyond.
    const buried = poles.map((p, k) => {
      const mid = p + pitch / 2;
      const half = pitch / 2 - gap;
      return count <= 8
        ? `<path class="magnet inner ${pole(k)}" d="M${at(R_ROTOR - 6, mid - half)}L${at(R_ROTOR - 6 - Math.min(16, 60 / count + 6), mid)}L${at(R_ROTOR - 6, mid + half)}"/>`
        : `<path class="magnet inner ${pole(k)}" d="M${at(R_ROTOR - 8, mid - half)}L${at(R_ROTOR - 8, mid + half)}"/>`;
    }).join("");
    return { drawing: body + buried + shaft, fixed: "", name: `magnets buried in the rotor, ${said}` };
  }
  const inset = magnets === "inset";
  const radius = inset ? R_ROTOR - 4.5 : R_ROTOR + 2.5;
  const onFace = poles.map((p, k) => `<path class="magnet ${pole(k)}" d="${arc(radius, p + gap / 2, p + pitch - gap / 2)}"/>`).join("");
  // Set into the face, steel stands between the magnets; on the face, nothing does.
  const ribs = inset ? poles.map((p) => `<path class="slot thin" d="M${at(R_ROTOR - 9, p)}L${at(R_ROTOR, p)}"/>`).join("") : "";
  const drawn = inset ? body + onFace + ribs : `<circle class="steel" cx="${MOTOR_X}" cy="${MID}" r="${R_ROTOR - 1}"/>` + onFace;
  const where = inset ? "magnets set into the rotor face" : "magnets on the rotor face";
  return { drawing: drawn + shaft, fixed: "", name: `${kind === "bldc" ? "brushless DC, " : ""}${where}, ${said}` };
}

/** What the drawn rotor is, in words, for the plate's note. */
export const motorName = (m: Rotor) => rotor(m).name;

function motor(m: Rotor, rpm: number, legs: number[], known: boolean): string {
  const taps = legs
    .map((x, k) => {
      const y = tapY(k, legs.length);
      const end = MOTOR_X - Math.sqrt(R_STATOR * R_STATOR - (y - MID) ** 2);
      return `<path class="wire" d="M${x} ${y}H${end.toFixed(1)}"/>`;
    })
    .join("");
  // Until the user has said what the motor is, it is drawn as the plain symbol for one.
  if (!known) return `${taps}<g class="motor"><circle class="stator" cx="${MOTOR_X}" cy="${MID}" r="${R_STATOR}"/><text class="motor-mark" x="${MOTOR_X}" y="${MID + 9}" text-anchor="middle">M</text></g>`;
  const r = rotor(m);
  // The rotor turns at a pace that follows the speed without becoming a blur, and stops with it.
  const period = rpm === 0 ? 0 : Math.min(Math.max(2400 / Math.abs(rpm), 0.9), 14);
  const spin = period ? ` style="animation-duration:${period.toFixed(2)}s;animation-direction:${rpm < 0 ? "reverse" : "normal"}"` : "";
  return `${taps}<g class="motor"><circle class="stator" cx="${MOTOR_X}" cy="${MID}" r="${R_STATOR}"/>${r.fixed}<g class="rotor${period ? " turning" : ""}"${spin}>${r.drawing}</g></g>`;
}

export interface SchematicInput {
  kind: string; stage: Stage | null; result: Result | null; tSink: number;
  vdc: number | null; // null until the user has given the supply
  fet: boolean; blocked: boolean; deviceName: string | null; battery: boolean;
  pack: Packaging | null;
  parallel: number; // devices side by side at each switch
  motorKnown: boolean; // false until the user has reached the motor step
  rotor: Rotor; rpm: number;
}

export function schematic(input: SchematicInput): string {
  const { kind, stage, result, tSink, vdc, fet, blocked, pack } = input;
  const { letters, legs, label: stageName } = layout(kind);
  // The kind of stage follows from the motor; before that it is not named.
  const label = input.motorKnown ? stageName : "Power stage";
  const right = legs[legs.length - 1];
  const rails = `<path class="wire" d="M${LEFT - 60} ${RAIL_TOP}H${right}M${LEFT - 60} ${RAIL_BOTTOM}H${right}"/>`;
  // A battery is drawn as cells; a supply that only delivers, as a source circle.
  const cells = `<path d="M${LEFT - 76} ${MID - 14}h32M${LEFT - 68} ${MID - 5}h16M${LEFT - 76} ${MID + 5}h32M${LEFT - 68} ${MID + 14}h16"/>`;
  const circle = `<circle class="source-ring" cx="${LEFT - 60}" cy="${MID}" r="14"/><path d="M${LEFT - 60} ${MID - 9}v6M${LEFT - 63} ${MID - 6}h6M${LEFT - 63} ${MID + 7}h6"/>`;
  const source = `<g class="source"><path class="wire" d="M${LEFT - 60} ${RAIL_TOP}V${MID - 14}M${LEFT - 60} ${MID + 14}V${RAIL_BOTTOM}"/>${input.battery ? cells : circle}${vdc === null ? "" : `<text x="${LEFT - 68}" y="${MID + 38}" text-anchor="end" class="reading">${sig(vdc)} V</text>`}<path class="wire" d="M${LEFT} ${RAIL_TOP}V${MID - 6}M${LEFT} ${MID + 6}V${RAIL_BOTTOM}"/><path d="M${LEFT - 13} ${MID - 6}h26M${LEFT - 13} ${MID + 6}h26"/></g>`;
  let n = 0;
  const drawn = legs
    .map((x, k) => {
      const hi = positionFor(result, k, "high", kind);
      const lo = positionFor(result, k, "low", kind);
      const text = (p: Position | null) => (p ? `${sig(p.total)} W  ${degrees(p.tj)}${p.count > 1 ? "  each" : ""}` : "");
      const over = (p: Position | null) => !!(p && result && p.tj > result.tj_max);
      // A reading is written once for a run of switches that share it, on the last of the run.
      const shown = (side: "high" | "low", p: Position | null) =>
        k === legs.length - 1 || positionFor(result, k + 1, side, kind) !== p ? text(p) : "";
      const top = transistor(x, RAIL_TOP + 68, `Q${++n}`, heat(hi, result, tSink), shown("high", hi), over(hi), fet, pack);
      const bottom = transistor(x, RAIL_BOTTOM - 68, `Q${++n}`, heat(lo, result, tSink), shown("low", lo), over(lo), fet, pack);
      const wires = `<path class="wire" d="M${x} ${RAIL_TOP}V${RAIL_TOP + 45}M${x} ${RAIL_TOP + 91}V${RAIL_BOTTOM - 91}M${x} ${RAIL_BOTTOM - 45}V${RAIL_BOTTOM}"/>`;
      const node = `<circle class="node" cx="${x}" cy="${tapY(k, legs.length)}" r="3"/><circle class="node" cx="${x}" cy="${RAIL_TOP}" r="3"/><circle class="node" cx="${x}" cy="${RAIL_BOTTOM}" r="3"/>`;
      const name = `<text class="leg" x="${x - 9}" y="${tapY(k, legs.length) - 8}" text-anchor="end">${letters[k]}</text>`;
      return wires + top + bottom + node + name;
    })
    .join("");
  const corners = [[18, 18], [W - 18, 18], [18, H - 18], [W - 18, H - 18]]
    .map(([x, y]) => `<path class="mark" d="M${x - 7} ${y}h14M${x} ${y - 7}v14"/>`)
    .join("");
  const outline = pack ? packages(legs, pack) : null;
  const beside = input.parallel > 1 ? `, ${input.parallel} in parallel at each switch` : "";
  const built = (outline ? packageName(pack!, outline.count) : `${legs.length * 2} switches`) + beside;
  const caption = `<text class="plate-title" x="34" y="32">${label} · ${built}</text><text class="plate-title part" x="34" y="52">${input.deviceName ? escape(input.deviceName.length > 64 ? `${input.deviceName.slice(0, 63)}…` : input.deviceName) : "no device chosen yet"}</text>`;
  const what = motorName(input.rotor);
  const scheme = `<text class="plate-note" x="34" y="${H - 44}">${stage ? escape(stage.scheme) : ""}</text><text class="plate-note" x="${W - 34}" y="${H - 28}" text-anchor="end">${input.motorKnown ? `Motor: ${what}` : ""}${stage ? ` · ${sig(stage.i_peak)} A peak` : ""}</text>`;
  const stop = blocked
    ? `<g class="blocked"><rect x="26" y="46" width="${W - 52}" height="${H - 92}"/><text x="${W / 2}" y="${MID + 6}" text-anchor="middle">This combination cannot run</text></g>`
    : "";
  return `<svg class="schematic${blocked ? " is-blocked" : ""}${stage ? " is-live" : ""}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}, ${built}${result ? `, total loss ${sig(result.loss)} watts, hottest junction ${degrees(result.tj_peak)}` : ""}">
<defs><pattern id="hatch" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><path d="M0 0v10" class="hatch-line"/></pattern></defs>
${corners}${caption}${outline?.drawing ?? ""}${rails}${source}${drawn}${motor(input.rotor, blocked ? 0 : input.rpm, legs, input.motorKnown)}${scheme}${stop}</svg>`;
}
