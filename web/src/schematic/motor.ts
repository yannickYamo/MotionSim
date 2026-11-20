// The motor at the right of the plate, drawn as the kind of machine it is: its stator, and a
// rotor with as many poles as it has, turning with the speed.

import { MID, MOTOR_X, R_ROTOR, R_STATOR, tapY } from "./geometry";

/** Points on a circle about the motor's centre, for drawing rotors. */
const at = (radius: number, degrees: number): string => {
  const a = (degrees * Math.PI) / 180;
  return `${(MOTOR_X + radius * Math.cos(a)).toFixed(1)} ${(MID + radius * Math.sin(a)).toFixed(1)}`;
};
const arc = (radius: number, from: number, to: number) =>
  `M${at(radius, from)}A${radius} ${radius} 0 0 1 ${at(radius, to)}`;

/** What the rotor drawing needs to know about the motor. */
export interface Rotor {
  kind: string;
  magnets: string;
  polePairs: number;
  steps: number;
}

const MOST_POLES = 48; // more than this cannot be told apart at the size drawn

/** A rotor as it is drawn: what turns, what stays put around it, and what it is in words. */
interface RotorDrawing {
  drawing: string;
  fixed: string;
  name: string;
}

/** The steel of a rotor, and the shaft through it. */
const ROTOR_BODY = `<circle class="steel" cx="${MOTOR_X}" cy="${MID}" r="${R_ROTOR}"/>`;
const SHAFT = `<circle class="shaft" cx="${MOTOR_X}" cy="${MID}" r="5"/>`;

/** A line across the steel, from one radius to another at one angle. */
const spoke = (inner: number, outer: number, angle: number) =>
  `<path class="slot thin" d="M${at(inner, angle)}L${at(outer, angle)}"/>`;

/** The rotor of an induction motor. */
function cageRotor(said: string): RotorDrawing {
  // A squirrel cage: bars near the surface, all round. Their number is the rotor's own,
  // not the pole count, which is set by the stator winding.
  const bars = Array.from({ length: 22 }, (_, k) => {
    const [x, y] = at(R_ROTOR - 6, (k * 360) / 22).split(" ");
    return `<circle class="bar" cx="${x}" cy="${y}" r="2.6"/>`;
  }).join("");
  return { drawing: ROTOR_BODY + bars + SHAFT, fixed: "", name: `induction, squirrel cage, ${said}` };
}

/** The flux barriers of one pole of a reluctance rotor, one at each depth. */
function poleBarriers(k: number, shown: number, depth: number[]): string {
  const step = 360 / shown;
  const c = ((k * step + step / 2) * Math.PI) / 180;
  const far = R_ROTOR + (shown <= 4 ? 7 : 3);
  const cx = MOTOR_X + far * Math.cos(c);
  const cy = MID + far * Math.sin(c);
  return depth
    .map((radius) => {
      const half = Math.acos(Math.min(1, (radius * radius + far ** 2 - (R_ROTOR - 3) ** 2) / (2 * radius * far)));
      const point = (angle: number) => {
        const a = c + Math.PI + angle;
        return `${(cx + radius * Math.cos(a)).toFixed(1)} ${(cy + radius * Math.sin(a)).toFixed(1)}`;
      };
      return `<path class="slot" d="M${point(-half)}A${radius} ${radius} 0 0 1 ${point(half)}"/>`;
    })
    .join("");
}

/** The rotor of a synchronous reluctance motor. */
function reluctanceRotor(count: number, said: string): RotorDrawing {
  // Flux barriers: curved slots in each pole, bowed towards the shaft, that make one
  // axis easy to magnetise and the other hard. One set a pole.
  const shown = Math.min(count, 12);
  const depth = shown <= 4 ? [15, 24, 33] : shown <= 8 ? [9, 16] : [8];
  const barriers = Array.from({ length: shown }, (_, k) => poleBarriers(k, shown, depth)).join("");
  return { drawing: ROTOR_BODY + barriers + SHAFT, fixed: "", name: `reluctance rotor, no magnets, ${said}` };
}

/** One brush of a brushed motor, at its place beside the commutator. */
const brush = (x: number) => `<rect class="brush" x="${x}" y="${MID - 5}" width="11" height="10"/>`;

/** The field of a brushed motor: a winding on each side for a series motor, a magnet otherwise. */
function brushedField(kind: string): string {
  if (kind === "dc_series") {
    const upper = `<path class="slot" d="${arc(R_STATOR - 7, 250, 290)}"/>`;
    return `${upper}<path class="slot" d="${arc(R_STATOR - 7, 70, 110)}"/>`;
  }
  const north = `<path class="magnet north" d="${arc(R_STATOR - 6, 235, 305)}"/>`;
  return `${north}<path class="magnet south" d="${arc(R_STATOR - 6, 55, 125)}"/>`;
}

/** The rotor of a brushed DC motor, with the field and brushes that stand around it. */
function brushedRotor(kind: string): RotorDrawing {
  // An armature with slots and a commutator; the brushes stay put.
  const slots = Array.from({ length: 10 }, (_, k) => spoke(R_ROTOR - 9, R_ROTOR, k * 36)).join("");
  const commutator =
    `<circle class="steel" cx="${MOTOR_X}" cy="${MID}" r="15"/>` +
    Array.from({ length: 8 }, (_, k) => spoke(8, 15, k * 45)).join("");
  const brushes = brush(MOTOR_X - 27) + brush(MOTOR_X + 16);
  return {
    drawing: ROTOR_BODY + slots + commutator + SHAFT,
    fixed: brushedField(kind) + brushes,
    name: kind === "dc_series" ? "brushed DC, series field" : "brushed DC, magnet field",
  };
}

/** The rotor of a stepper, with the stator's teeth around it. */
function stepperRotor(steps: number): RotorDrawing {
  // A hybrid stepper's rotor has a quarter as many teeth as the motor has steps.
  const teeth = Math.min(Math.max(Math.round((steps || 200) / 4), 4), 72);
  const rotorTeeth = Array.from({ length: teeth }, (_, k) => spoke(R_ROTOR - 4, R_ROTOR + 2.5, (k * 360) / teeth)).join(
    "",
  );
  const statorTeeth = Array.from({ length: 8 }, (_, k) => spoke(R_STATOR - 9, R_STATOR - 2, k * 45 + 22.5)).join("");
  const said = `${Math.round(steps || 200)} steps a turn, ${Math.round((steps || 200) / 4)} rotor teeth`;
  return {
    drawing: `<circle class="steel" cx="${MOTOR_X}" cy="${MID}" r="${R_ROTOR - 4}"/>` + rotorTeeth + SHAFT,
    fixed: statorTeeth,
    name: `stepper, ${said}`,
  };
}

/** Which way the magnet of pole k faces. */
const pole = (k: number) => (k % 2 ? "south" : "north");

/** Where each pole of a magnet rotor starts, how wide it is, and the space left between magnets. */
function magnetPoles(count: number): { poles: number[]; pitch: number; gap: number } {
  const pitch = 360 / count;
  const poles = Array.from({ length: count }, (_, k) => k * pitch);
  return { poles, pitch, gap: Math.min(0.12 * pitch, 8) };
}

/** A rotor with its magnets inside the steel. */
function buriedRotor(count: number, said: string): RotorDrawing {
  const { poles, pitch, gap } = magnetPoles(count);
  // Buried below the surface: a V a pole while there is room for one, a flat bar beyond.
  const buried = poles
    .map((p, k) => {
      const mid = p + pitch / 2;
      const half = pitch / 2 - gap;
      const tip = R_ROTOR - 6 - Math.min(16, 60 / count + 6);
      const d =
        count <= 8
          ? `M${at(R_ROTOR - 6, mid - half)}L${at(tip, mid)}L${at(R_ROTOR - 6, mid + half)}`
          : `M${at(R_ROTOR - 8, mid - half)}L${at(R_ROTOR - 8, mid + half)}`;
      return `<path class="magnet inner ${pole(k)}" d="${d}"/>`;
    })
    .join("");
  return { drawing: ROTOR_BODY + buried + SHAFT, fixed: "", name: `magnets buried in the rotor, ${said}` };
}

/** A rotor with its magnets at its face, on it or set into it. */
function faceRotor(kind: string, inset: boolean, count: number, said: string): RotorDrawing {
  const { poles, pitch, gap } = magnetPoles(count);
  const radius = inset ? R_ROTOR - 4.5 : R_ROTOR + 2.5;
  const onFace = poles
    .map((p, k) => `<path class="magnet ${pole(k)}" d="${arc(radius, p + gap / 2, p + pitch - gap / 2)}"/>`)
    .join("");
  // Set into the face, steel stands between the magnets; on the face, nothing does.
  const ribs = inset ? poles.map((p) => spoke(R_ROTOR - 9, R_ROTOR, p)).join("") : "";
  const drawn = inset
    ? ROTOR_BODY + onFace + ribs
    : `<circle class="steel" cx="${MOTOR_X}" cy="${MID}" r="${R_ROTOR - 1}"/>` + onFace;
  const where = inset ? "magnets set into the rotor face" : "magnets on the rotor face";
  return { drawing: drawn + SHAFT, fixed: "", name: `${kind === "bldc" ? "brushless DC, " : ""}${where}, ${said}` };
}

/** The rotor of each kind of motor as its cross-section is drawn: as many poles as the
 *  motor has, with the magnets or barriers where they sit. */
function rotor(m: Rotor): RotorDrawing {
  const { kind, magnets } = m;
  const count = Math.min(Math.max(2 * Math.round(m.polePairs || 1), 2), MOST_POLES);
  const said = `${2 * Math.round(m.polePairs || 1)} poles`;
  if (kind === "induction") return cageRotor(said);
  if (kind === "synrm") return reluctanceRotor(count, said);
  if (kind === "dc" || kind === "dc_series") return brushedRotor(kind);
  if (kind === "stepper") return stepperRotor(m.steps);
  // Permanent-magnet rotors: one magnet a pole, north and south in turn. Where the magnets
  // sit is what tells the kinds apart.
  if (magnets === "interior") return buriedRotor(count, said);
  return faceRotor(kind, magnets === "inset", count, said);
}

/** What the drawn rotor is, in words, for the plate's note. */
export const motorName = (m: Rotor) => rotor(m).name;

/** The ring of the stator, inside which the rotor is drawn. */
const STATOR = `<circle class="stator" cx="${MOTOR_X}" cy="${MID}" r="${R_STATOR}"/>`;

/** The plain symbol for a motor: a circle with an M in it. */
const MOTOR_MARK = `<text class="motor-mark" x="${MOTOR_X}" y="${MID + 9}" text-anchor="middle">M</text>`;

export function motor(m: Rotor, rpm: number, legs: number[], known: boolean): string {
  const taps = legs
    .map((x, k) => {
      const y = tapY(k, legs.length);
      const end = MOTOR_X - Math.sqrt(R_STATOR * R_STATOR - (y - MID) ** 2);
      return `<path class="wire" d="M${x} ${y}H${end.toFixed(1)}"/>`;
    })
    .join("");
  // Until the user has said what the motor is, it is drawn as the plain symbol for one.
  if (!known) return `${taps}<g class="motor">${STATOR}${MOTOR_MARK}</g>`;
  const r = rotor(m);
  // The rotor turns at a pace that follows the speed without becoming a blur, and stops with it.
  const period = rpm === 0 ? 0 : Math.min(Math.max(2400 / Math.abs(rpm), 0.9), 14);
  const spin = period
    ? ` style="animation-duration:${period.toFixed(2)}s;animation-direction:${rpm < 0 ? "reverse" : "normal"}"`
    : "";
  const turning = `<g class="rotor${period ? " turning" : ""}"${spin}>${r.drawing}</g>`;
  return `${taps}<g class="motor">${STATOR}${r.fixed}${turning}</g>`;
}
