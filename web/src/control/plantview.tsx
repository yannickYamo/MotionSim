// The motor and load as the engine simulates them, where they may differ from the model the
// controller is tuned on: a shaft that twists between the rotor and its load, and iron that
// saturates. Both are off until asked for, so that a run is first of the drive as designed;
// each is said beside the run once it is taken. Shown on the motor's own inspector, as the
// figures of the thing simulated, never in a menu of their own.

import { KeyChoice, KeyFigure } from "./keycontrols";
import { askLoops, rerunSoon } from "./actions";
import { lab, type LabState, useLab } from "./store";
import type { Plant, PlantField, PlantOptions, Scheme } from "./types";

const hadRun = (s: LabState): boolean => !!s.run.answer;

/** The iron a scheme is run on unless another is asked for: saturating where it injects, as the
 *  injection tells the magnet's side from the iron's saturation; else the controller's own. */
export const usualIron = (scheme: Scheme | null | undefined): string =>
  scheme?.blocks.some((b) => b.kind === "hf_injection") ? "saturating" : "linear";

/** The motor and load as simulated, changed: what was run is marked as of the motor before,
 *  run again once the changing pauses, its loops asked again, and the explorations asked
 *  again for it (a card may apply, or not, to a shaft that twists). */
export function setPlant(change: Plant): void {
  lab.set((s) => {
    const plant: Plant = { ...s.plant, ...change };
    if (!plant.coupling) delete plant.coupling;
    if (!plant.iron || plant.iron === usualIron(s.scheme)) delete plant.iron;
    return {
      plant,
      run: { ...s.run, refused: s.run.refused?.field.startsWith("plant") ? null : s.run.refused, stale: hadRun(s) },
      library: { ...s.library, status: "idle", sweep: null, open: null },
      plotted: null,
      pins: {},
    };
  });
  askLoops();
  rerunSoon();
}

/** Each figure of the shaft as its box names it. */
const NAMES: Record<string, string> = {
  resonance_hz: "Resonance",
  motor_share: "Rotor's share of the inertia",
  damping_ratio: "Damping ratio",
  backlash_deg: "Play",
};

const SHAFT = ["rigid", "twists"];

function ShaftFigure({ field, coupling }: { field: PlantField; coupling: Record<string, number> }) {
  const problem = useLab((s) => {
    const p = s.run.refused ?? s.loops.refused;
    return p && p.field === `plant.coupling.${field.name}` ? `${p.reason}. ${p.fix}` : "";
  });
  const value = coupling[field.name] ?? field.default;
  const put = (v: number) => setPlant({ coupling: { ...coupling, [field.name]: v } });
  return (
    <KeyFigure
      id={`lab-plant-${field.name}`}
      word="Usual"
      label={NAMES[field.name] ?? field.name}
      unit={field.unit}
      value={value}
      tuned={field.default}
      source={field.about}
      low={field.low}
      high={field.high}
      name={field.name}
      problem={problem}
      put={put}
      reset={() => put(field.default)}
    />
  );
}

/** The section itself: the shaft, rigid or twisting with its four figures, and the iron. */
export function PlantSettings({ options }: { options: PlantOptions | undefined }) {
  const plant = useLab((s) => s.plant);
  const usual = useLab((s) => usualIron(s.scheme));
  if (!options) return null;
  const coupling = plant.coupling;
  const suggested = Object.fromEntries(options.coupling.map((f) => [f.name, f.default]));
  return (
    <section className="lab-keys lab-plant" aria-labelledby="lab-plant-h">
      <h4 id="lab-plant-h">The motor as simulated</h4>
      <p className="quiet">
        The controller is tuned on a rigid shaft and constant inductances. Here the simulated motor can differ from that
        model, as the real one does; the controller is not told.
      </p>
      <KeyChoice
        id="lab-plant-shaft"
        word="Usual"
        label="Shaft to the load"
        value={coupling ? "twists" : "rigid"}
        options={SHAFT}
        tuned="rigid"
        source="the controller's own model"
        pick={(v) => setPlant({ coupling: v === "twists" ? (coupling ?? suggested) : undefined })}
        reset={() => setPlant({ coupling: undefined })}
      />
      {coupling ? options.coupling.map((f) => <ShaftFigure key={f.name} field={f} coupling={coupling} />) : null}
      <KeyChoice
        id="lab-plant-iron"
        word="Usual"
        label="Iron"
        value={plant.iron ?? usual}
        options={options.iron.choices}
        tuned={usual}
        source={
          usual === "saturating"
            ? "for injection: it tells the magnet's side from the iron's saturation, as a motor's iron does"
            : options.iron.about
        }
        pick={(v) => setPlant({ iron: v })}
        reset={() => setPlant({ iron: undefined })}
      />
    </section>
  );
}
