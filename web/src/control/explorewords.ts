// How each exploration is shown on its card: the problem it answers, as an engineer meets
// it, and what running it gives back. The engine's own words (its title, question and
// method) stay under the card, opened on demand. An exploration this page does not know
// is shown by its question and what the engine expects of it.

import type { Exploration } from "./types";

export interface Pitch {
  /** The pain point, short: what is wrong on the bench. */
  pain: string;
  /** What running it shows, in one line. */
  outcome: string;
}

const PITCHES: Record<string, Pitch> = {
  observer_choice: {
    pain: "No encoder: what does it cost?",
    outcome: "Angle error and loss of three observers, set against the encoder.",
  },
  observer_discretisation: {
    pain: "Observer loses the angle at high speed",
    outcome: "Whether the discrete form holds when the rotor turns far in one sample.",
  },
  through_zero: {
    pain: "Sensorless drive loses the rotor reversing through standstill",
    outcome: "Angle error and speed, with and without handing back to open loop near nought.",
  },
  load_rejection: {
    pain: "Speed slow to come back after a load step",
    outcome: "A disturbance observer against the PI, at the same speed of response.",
  },
  fw_by_voltage: {
    pain: "Torque lost at speed when the magnet is off its figure",
    outcome: "Field weakening by the model against field weakening by the voltage measured.",
  },
  compressor_turn: {
    pain: "Speed swings through each turn of a compressor",
    outcome: "The speed's swing with and without the load's torque learned turn by turn.",
  },
  control_rate: {
    pain: "The controller cannot keep up with the switching",
    outcome: "The current loop updated from every fourth carrier period to eight times a period.",
  },
  injection_coupling: {
    pain: "The angle read at standstill drifts under load",
    outcome: "The angle injected for, with the iron's coupling taken back and without.",
  },
  shunt_sensing: {
    pain: "Shunts in place of a current sensor",
    outcome: "The current as read through three, two or one shunt, against a sensor.",
  },
  shunt_window: {
    pain: "One shunt misses the current at low speed",
    outcome: "The periods read and missed, with the timer's shift and without.",
  },
  stiff_servo_notch: {
    pain: "A stiffer servo rings the shaft's resonance",
    outcome: "The shaft's swing at six times the gains, with and without a notch.",
  },
  link_tie: {
    pain: "The DC link sags when the load comes on",
    outcome: "The link's lowest voltage and the mains current's shape, the two controls tied and not.",
  },
  link_capacitance: {
    pain: "A smaller or an aged link capacitor",
    outcome: "The link's ripple and its swing at all, half and a quarter of the capacitance.",
  },
  move_shaped: {
    pain: "The load swings on after every move",
    outcome: "The load's overshoot and swing, with the move shaped to the swing and without.",
  },
  sensorless_start: {
    pain: "Sensorless motor will not start under load",
    outcome: "The starting current that carries the load up the ramp.",
  },
  mismatch_deadbeat: {
    pain: "Deadbeat rings when the inductance is off",
    outcome: "How wrong the inductance can be before the current overshoots.",
  },
  mismatch_predictive: {
    pain: "Steady torque error from a wrong magnet flux",
    outcome: "The error a controller with no integrator leaves, flux by flux.",
  },
  mismatch_observer: {
    pain: "Estimated angle drifts with a wrong inductance",
    outcome: "Angle error against the inductance mismatch, either way.",
  },
  low_carrier_ratio: {
    pain: "Current loop rings at a low carrier ratio",
    outcome: "The textbook regulator against the discrete one, a few pulses a turn.",
  },
  dead_time: {
    pain: "Dead time distorts the current",
    outcome: "Distortion and torque with and without compensation.",
  },
  least_loss: {
    pain: "More loss than the torque needs",
    outcome: "What the current of least loss saves over the least current.",
  },
  mpc_weight: {
    pain: "Predictive control switches too often",
    outcome: "Switching loss against ripple as the weight λ rises.",
  },
  mpc_loss_weighting: {
    pain: "Commutations at the current peak cost the most",
    outcome: "Switching loss saved by charging a commutation by its energy.",
  },
  mpc_horizon: {
    pain: "Ripple too high for the switching allowed",
    outcome: "Whether looking two steps ahead cleans the current.",
  },
  predictive_vs_regulated: {
    pain: "Torque step too slow under the PI regulator",
    outcome: "Rise time, ripple and loss of four controllers on one step.",
  },
  sensor_noise: {
    pain: "Current-sensor noise shows in the torque",
    outcome: "How much noise the loop takes before the torque ripple rises.",
  },
  bandwidth: {
    pain: "Current loop too slow, or close to ringing",
    outcome: "Rise time, ripple, loss and stability against the loop gain.",
  },
  delay_compensation: {
    pain: "The one-sample delay spoils predictive control",
    outcome: "Ripple with and without delay compensation.",
  },
  update_rate: {
    pain: "Speed dips under a load step",
    outcome: "What sampling twice a carrier period buys.",
  },
  pwm_choice: {
    pain: "Switching loss too high under continuous PWM",
    outcome: "Loss saved by clamped modulation, and the ripple it costs.",
  },
  switching_frequency: {
    pain: "Loss or ripple: where to set the carrier",
    outcome: "Switching loss against ripple across carrier frequencies.",
  },
  variable_frequency: {
    pain: "Switching loss too high at light load",
    outcome: "Frequency and loss saved when the carrier follows a ripple limit.",
  },
  thermal_control: {
    pain: "Junction too hot at stall",
    outcome: "What active thermal control gives up to hold the junction down.",
  },
  low_speed_hold: {
    pain: "One switch overheats at very low speed",
    outcome: "Peak junction temperature as the output frequency falls.",
  },
};

const capital = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

/** The pain point and outcome of an exploration: this page's, or made from the engine's words. */
export function pitchOf(x: Exploration): Pitch {
  const known = PITCHES[x.id];
  if (known) return known;
  return {
    pain: x.question || x.title,
    outcome: x.expects ? `Expected: ${x.expects.replace(/\.$/, "")}.` : x.title,
  };
}

/** How each group of explorations is told apart at a glance: its icon, and its ink. */
export const GROUP_LOOK: Record<string, { icon: string; label: string }> = {
  losses: { icon: "bolt", label: "Losses" },
  dynamics: { icon: "wave-sine", label: "Dynamics" },
  sensing: { icon: "ruler-measure", label: "Sensing" },
  robustness: { icon: "adjustments", label: "Robustness" },
  thermal: { icon: "temperature", label: "Thermal" },
};

export const lookOf = (group: string): { icon: string; label: string } =>
  GROUP_LOOK[group] ?? { icon: "math-function", label: capital(group.replace(/_/g, " ")) };
