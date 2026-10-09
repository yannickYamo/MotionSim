// The equations the engine uses, written out. This page is a statement of the model, kept
// beside the code that implements it: src/motionsim/engine and src/motionsim/motor.

import { escape } from "./format";

interface Equation { is: string; where?: string }
interface Section { title: string; about: string; equations: Equation[] }

const SECTIONS: Section[] = [
  {
    title: "From the motor to the power stage",
    about: "The motor's speed and torque become a current, a voltage and a power factor. Each kind of motor has its own steady-state equations, solved at each instant.",
    equations: [
      { is: "T = 3/2 · p · (ψ · i_q + (L_d − L_q) · i_d · i_q)", where: "Permanent-magnet and reluctance motors (ψ = 0 for reluctance). p pole pairs, ψ magnet flux linkage, i_d and i_q the current along and across the rotor's axis." },
      { is: "v_d = R_s · i_d − ω · L_q · i_q        v_q = R_s · i_q + ω · (L_d · i_d + ψ)", where: "ω is the electrical speed, p times the shaft speed. Voltage and current amplitudes are √(v_d² + v_q²) and √(i_d² + i_q²)." },
      { is: "i_d chosen for the least current that gives the torque; made more negative when √(v_d² + v_q²) would pass what the supply can give", where: "Maximum torque per amp, then field weakening. A motor that still cannot reach the point is refused." },
      { is: "ψ = 60 / (√3 · 2π · p · K_v)", where: "From the catalogue speed constant K_v in rpm per volt of peak line-to-line back-EMF." },
      { is: "Induction: i_d = magnetising current,  T = 3/2 · p · (L_m² / L_r) · i_d · i_q,  slip speed = R_r · i_q / (L_r · i_d)", where: "Rotor-flux orientation. The flux is weakened when the voltage runs out. Rotor loss is 3/2 · R_r · (L_m / L_r · i_q)²." },
      { is: "Brushed DC: I = T / K_t,   V = K_t · ω + R · I,   duty = |V| / V_dc", where: "Series-wound: T = k · I², V = k · I · ω + R · I." },
      { is: "Brushless DC, six-step: two phases carry I = T / K_t at a time; each switch conducts for a third of the turn", where: "" },
      { is: "Stepper: phase current fixed at the set value; back-EMF amplitude = T_hold / (p · I) · ω", where: "The share of that back-EMF in phase with the current is the torque asked for over the holding torque." },
    ],
  },
  {
    title: "Modulation",
    about: "The voltage becomes a duty cycle for each switch through the output period.",
    equations: [
      { is: "m = V_peak / (V_dc / 2)", where: "Modulation index. Up to 1 for sine PWM, 2/√3 with a third harmonic or space-vector PWM." },
      { is: "d(θ) = 1/2 · (1 + m · sin θ + common-mode term)", where: "The common-mode term is what tells the schemes apart: none for sine, a third harmonic, the mid-value of the three phases for space vector, or a clamp to one rail for the discontinuous schemes, during which that leg does not switch." },
    ],
  },
  {
    title: "Conduction loss",
    about: "While a switch or diode carries the current it drops a voltage read from the datasheet's own curve at the junction temperature.",
    equations: [
      { is: "P_cond = average over the output period of  d(θ) · i(θ) · v_on(i, T_j)", where: "v_on is interpolated between the datasheet curves in current and temperature. For a transistor with a body diode, current the other way flows through the channel, less two dead times a period through the diode." },
    ],
  },
  {
    title: "Switching loss, from measured energy",
    about: "Where the datasheet gives turn-on and turn-off energy, that is used.",
    equations: [
      { is: "P_sw = f_sw · average of  [E_on(i, T_j) + E_off(i, T_j)] · V_dc / V_test", where: "Taken over the part of the period where that switch hard-switches the current. Energy is scaled in proportion to voltage from the datasheet's test voltage, and is at the datasheet's test gate resistor." },
      { is: "E(R_g) = E(R_g,test) · [E_fig(R_g) / E_fig(R_g,test)]", where: "Where the datasheet has a figure of energy against gate resistance and you give your own resistor. The figure is used only if it passes through the tabulated energy at the table's resistor, and never beyond its own range." },
      { is: "P_rr = f_sw · average of  E_rr(i, T_j) · V_dc / V_test", where: "Diode recovery. Where only a recovery charge is given: E_rr = 1/4 · Q_rr · V." },
    ],
  },
  {
    title: "Switching loss, from charge",
    about: "Where no energy is tabulated, it is estimated from the gate and output charges and the gate drive.",
    equations: [
      { is: "t_on = (Q_gs − Q_g,th + Q_gd) · R_g,on / (V_drive − V_plateau)", where: "The time the gate current takes to move the charge between threshold and the end of the plateau." },
      { is: "t_off = (Q_gs − Q_g,th + Q_gd) · R_g,off / V_plateau", where: "" },
      { is: "E_on = 1/2 · V_dc · I · t_on + (Q_oss + Q_rr) · V_dc", where: "The overlap of current and voltage, plus the output charge of the leg and the recovery charge taken through the full voltage." },
      { is: "E_off = 1/2 · V_dc · I · t_off", where: "" },
    ],
  },
  {
    title: "Gate resistors",
    about: "Left empty, the smallest resistors these limits allow are used, since the smallest loses least.",
    equations: [
      { is: "R_g,on ≥ V_dc · (V_drive − V_plateau) / (Q_gd · (dv/dt)_max)", where: "Voltage slew rate, 5 V/ns unless given." },
      { is: "R_g,off ≥ V_dc · V_plateau / (Q_gd · (dv/dt)_max)", where: "" },
      { is: "R_g,off ≥ L_loop · I · V_plateau / ((Q_gs − Q_g,th) · (0.8 · V_rated − V_dc))", where: "Turn-off overshoot, L_loop · di/dt, kept within 80% of the voltage rating." },
    ],
  },
  {
    title: "Junction temperature",
    about: "Losses and temperatures are solved together, because the losses depend on the temperature.",
    equations: [
      { is: "T_case = T_sink + R_th,case-sink · P_package", where: "A package carries the loss of its own legs. A stalled switch in a package of its own uses its loss at the worst rotor position." },
      { is: "T_j = T_case + R_th,jc · P_chip + R_th,mutual · (P_package − P_chip)", where: "The last term is heating by the other chips in the package, computed for a generic package when the datasheet gives none, and then shown as a range." },
      { is: "Z_th(t) = Σ R_i · (1 − e^(−t/τ_i))", where: "The datasheet's transient thermal impedance, as a Foster network. The peak within one output period is found by driving it with the loss waveform, repeated until it settles." },
      { is: "repeat: losses at T_j → new T_j, until it moves by less than 0.01 °C", where: "If it never settles the device is in thermal runaway and the result says so." },
    ],
  },
  {
    title: "Through a motion",
    about: "The load and its motion give the torque at each instant; the thermal network is followed through time.",
    equations: [
      { is: "T_motor = [J_load · α + T_friction + T_steady + k_fan · ω² + m · g · r · sin φ] / (N · η) + J_rotor · α · N", where: "N gear ratio, η gear efficiency (applied the other way when the load drives the motor), α acceleration. A vehicle adds rolling resistance, air drag and slope." },
      { is: "dT_i/dt = (R_i · P(t) − T_i) / τ_i", where: "Each stage of each chip's thermal network, stepped through the motion. A heatsink with heat capacity C warms by dT/dt = (P_total − (T − T_air) / R_sink) / C." },
      { is: "E_returned = ∫ −P_dc dt  while braking;   V_peak = √(V_dc² + 2 · E / C_link)", where: "Braking energy returned to the DC link, and the voltage it reaches on a supply that cannot take it back." },
    ],
  },
  {
    title: "What is not in the model",
    about: "",
    equations: [
      { is: "Current ripple at the switching frequency, iron loss in the motor, the control loop's own dynamics, and layout effects beyond one loop inductance.", where: "Results are estimates. They are checked against formulas and an independent numerical integration, not yet against a measured loss." },
    ],
  },
];

/** Text with its subscripts set as subscripts: R_th,jc reads as R with th,jc below the line. */
const set = (text: string) => escape(text).replace(/_([A-Za-z0-9,\-]+)/g, "<sub>$1</sub>");

/** The equations as a page section: each on its own line in a figure of its own. */
export function equationsPage(): string {
  return SECTIONS.map((s) => `<section class="eq-section"><h3>${escape(s.title)}</h3>${s.about ? `<p class="quiet">${escape(s.about)}</p>` : ""}${s.equations.map((e) => `<div class="eq"><p class="eq-is">${set(e.is)}</p>${e.where ? `<p class="eq-where">${set(e.where)}</p>` : ""}</div>`).join("")}</section>`).join("");
}
