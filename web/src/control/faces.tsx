// The face of a block: a drawing of what the block does, alive with the run. It is most of
// the block. A Clarke transform shows three phases adding up to one vector, a Park transform
// the vector and the rotor's frame with what falls on each of its axes, a regulator its error
// and the parts of its answer adding up to its output between the limit's rails, the
// modulator its carrier, its duties and the pulses they make, the inverter its three legs,
// the motor its rotor turning under the current. What a block is, is read from its ports,
// never from its name: a kind this page has never seen still gets a face, the trace of what
// it puts out. With nothing run yet, every face rests in a quiet pose.

import type { LNode } from "./layout";
import { puts, takes, type FaceProps } from "./facekit";
import { ClarkeFace, InverseParkFace, ParkFace, VectorFace } from "./facesframe";
import { AngleFace, PlaneFace, RotorFace } from "./facesrotor";
import { CarrierFace, LegsFace, RegulatorFace, StatesFace } from "./facespower";
import { LimitFace, PhasesFace, TraceFace } from "./facestrace";

export type FaceKind =
  | "clarke"
  | "park"
  | "ipark"
  | "vector"
  | "regulator"
  | "carrier"
  | "states"
  | "legs"
  | "rotor"
  | "angle"
  | "phases"
  | "plane"
  | "limit"
  | "reference"
  | "trace";

/** The faces a block of the scheme may wear, the first that fits its ports being the one. */
export const FITS: [FaceKind, (n: LNode) => boolean][] = [
  ["clarke", (n) => takes(n, ["a", "b", "c"]) && puts(n, ["alpha", "beta"])],
  ["park", (n) => takes(n, ["alpha", "beta", "theta"]) && puts(n, ["d", "q"])],
  ["ipark", (n) => takes(n, ["d", "q", "theta"]) && puts(n, ["alpha", "beta"])],
  ["vector", (n) => puts(n, ["alpha", "beta"])],
  // What gives an angle is a sensor or an observer, whatever else it puts out.
  ["angle", (n) => puts(n, ["theta"])],
  ["regulator", (n) => n.outputs.some((o) => /^err/.test(o.name))],
  ["states", (n) => puts(n, ["s_a", "s_b", "s_c"])],
  ["carrier", (n) => puts(n, ["d_a", "d_b", "d_c"])],
  ["phases", (n) => puts(n, ["i_a", "i_b", "i_c"])],
  ["plane", (n) => puts(n, ["i_d", "i_q"])],
  ["limit", (n) => typeof n.block?.params.limit === "number" && n.inputs.length === 1 && n.outputs.length > 0],
  ["reference", (n) => n.role === "reference" || /^reference/.test(n.hint)],
];

/** Which face a block wears, from what it takes in and puts out. */
export function faceOf(n: LNode): FaceKind {
  if (n.role === "inverter") return "legs";
  if (n.role === "motor") return "rotor";
  return FITS.find(([, fits]) => fits(n))?.[0] ?? "trace";
}

/** What each face shows, for one who cannot see it. */
export const FACE_WORDS: Record<FaceKind, string> = {
  clarke: "the three phase currents along their axes, adding up to the one vector along the stator's axes",
  park: "the vector, the rotor's axes turning under it, and what falls on each of them",
  ipark: "the vector asked for along the rotor's axes, and what falls on each of the stator's axes",
  vector: "the vector it takes and the vector it puts out, along the stator's axes",
  regulator:
    "the error, and the proportional and the integral part adding up to the output, between the rails of the limit",
  carrier: "the carrier over one period, the three duty cycles set against it and the pulse each makes",
  states: "the voltage each state of the three legs applies, the one chosen marked, the dearer ones fainter",
  legs: "the three legs between the DC rails, with the switch that conducts in each drawn closed",
  rotor: "the rotor and its magnet turning, the vector of the stator current and the angle between them",
  angle: "the angle it gives beside the true angle of the rotor, and the error between them",
  phases: "the three phase currents as it samples them",
  plane: "the current it asks for along the d and the q axis, inside the circle of the current limit",
  limit: "what comes in against what goes out, flat where the limit holds",
  reference: "what is asked for through the run, with the cursor on it",
  trace: "what it puts out through the run, with the cursor on it",
};

/** What each face is called over it: what it shows, at the cursor. */
export const FACE_TITLES: Record<FaceKind, string> = {
  clarke: "Phase currents to the stator's α, β axes",
  park: "Stator vector onto the rotor's d, q axes",
  ipark: "Rotor-frame vector onto the stator's α, β axes",
  vector: "Vector in and out, on the stator's axes",
  regulator: "Regulator output, part by part",
  carrier: "Duty cycles against the carrier",
  states: "Voltage vectors of the inverter",
  legs: "Inverter legs between the DC rails",
  rotor: "Rotor angle and stator current",
  angle: "Angle given against the true rotor angle",
  phases: "Phase currents at the cursor",
  plane: "Current asked for, in the d, q plane",
  limit: "Limiter: what comes in against what goes out",
  reference: "What is asked for, through the run",
  trace: "Output through the run",
};

/** The title of a block's face: a trace is named by what it traces. */
export function faceTitle(node: LNode): string {
  const kind = faceOf(node);
  const out = node.outputs[0];
  if ((kind === "trace" || kind === "reference") && out) {
    const what = out.about ? out.about.charAt(0).toUpperCase() + out.about.slice(1) : out.name.replace(/_/g, " ");
    return `${what}, through the run`;
  }
  return FACE_TITLES[kind];
}

export const FACES: Record<FaceKind, (p: FaceProps) => React.ReactNode> = {
  clarke: ClarkeFace,
  park: ParkFace,
  ipark: InverseParkFace,
  vector: VectorFace,
  regulator: RegulatorFace,
  carrier: CarrierFace,
  states: StatesFace,
  legs: LegsFace,
  rotor: RotorFace,
  angle: AngleFace,
  phases: PhasesFace,
  plane: PlaneFace,
  limit: LimitFace,
  reference: TraceFace,
  trace: TraceFace,
};

/** The face of a block. */
export function Face({ node, scheme, children }: FaceProps & { children?: React.ReactNode }) {
  const kind = faceOf(node);
  const Drawn = FACES[kind];
  return (
    <div className={`lab-face is-${kind}`} data-face={kind}>
      <p className="lab-face-title">{faceTitle(node)}</p>
      {children}
      <Drawn node={node} scheme={scheme} />
    </div>
  );
}
