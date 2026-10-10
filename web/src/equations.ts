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
      { is: "i_d chosen for the least current that gives the torque; made more negative when √(v_d² + v_q²) would pass what the supply can give", where: "Maximum torque per amp, then field weakening, down to the least voltage the torque can be had for; with buried magnets that lies beyond full opposition of the magnet. A motor that still cannot reach the point is refused." },
      { is: "ψ = 60 / (√3 · 2π · p · K_v)", where: "From the catalogue speed constant K_v in rpm per volt of peak line-to-line back-EMF." },
      { is: "Induction: i_d = magnetising current,  T = 3/2 · p · (L_m² / L_r) · i_d · i_q,  slip speed = R_r · i_q / (L_r · i_d)", where: "Rotor-flux orientation. The flux is weakened when the voltage runs out. Rotor loss is 3/2 · R_r · (L_m / L_r · i_q)²." },
      { is: "Brushed DC: I = T / K_t,   V = K_t · ω + R · I,   duty = |V| / V_dc", where: "Series-wound: T = k · I², V = k · I · ω + R · I." },
      { is: "Brushless DC, six-step: two phases carry I = T / K_t at a time; each switch conducts for a third of the turn", where: "" },
      { is: "P_iron(n) = P_0 · (½ · n/n_0 + ½ · (n/n_0)²),   T_asked = T + P_iron / ω", where: "Iron loss, when a no-load loss P_0 at a speed n_0 is given: half taken to rise with speed and half with its square. The windings supply it as extra torque." },
      { is: "L(i) = L_0 / √(1 + (i / i_sat)²)", where: "Saturation, when a saturation current is given: each axis by its own current, found again until the point settles." },
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
      { is: "E(V_dc) = E(V_test) · [E_fig(V_dc) / E_fig(V_test)]", where: "Where the datasheet has a figure of energy against voltage, inside its range. Without one the energy is scaled in proportion to voltage, which is the least a real device does, and the result says how much more it could be." },
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
    title: "Ripple at the switching frequency",
    about: "Within one PWM period the legs switch in a fixed order, so the current drawn from the link and the voltage across each motor phase are known in every state.",
    equations: [
      { is: "I_cap,rms² = average of (link current²) over the states of each period, over a turn − (average link current)²", where: "What the DC-link capacitor carries. For three sinusoidal currents it is I · √(2M · (√3/(4π) + cos²φ · (√3/π − 9M/16))), which the model is tested against." },
      { is: "ΔI_pp = 2 · max |∫ (v_phase − v̄_phase) dt| / L_phase", where: "Peak-to-peak ripple on a phase current, from the voltage across the phase in each state. For one leg chopping into a winding it is V_dc · D · (1 − D) / (L · f_sw)." },
      { is: "I_rms² = I² + ΔI_pp² / 12", where: "The ripple adds to conduction loss." },
      { is: "I_on = I − ΔI_pp / 2,   I_off = I + ΔI_pp / 2", where: "A switch turns on at the bottom of the ripple and off at the top, and its switching energies are taken at those currents. Where the ripple is more than twice the current the turn-on is at zero." },
      { is: "V_usable = V_ideal · (1 − 2 · (t_dead + t_min) · f_sw − V_on / (V_dc / 2))", where: "Dead time takes a slice off every pulse, the shortest pulse keeps the duty cycle off the rails, and the switch and diode drop a little of what is left. The motor's reach is worked out with the remainder." },
    ],
  },
  {
    title: "If the drive stops switching",
    about: "A turning magnet motor is a generator, and the diodes rectify it into the link.",
    equations: [
      { is: "V_back-EMF = √3 · p · ω · ψ", where: "Between lines, at the top speed. Above the supply it charges the link; above the device's rating it is a failure unless something shorts the motor or burns the energy." },
    ],
  },
  {
    title: "What the device can drive",
    about: "The same model, asked the other way round.",
    equations: [
      { is: "T_limit(n) = the largest torque at speed n for which every T_j ≤ T_j,max", where: "Found by halving. The largest load is found the same way: the load's inertia, friction, steady torque and mass are scaled together until a check fails." },
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
      { is: "N_f = A · ΔT_j^α · exp(E_a / (k_B · T_m)),   life = 1 / Σ (n_i / N_f,i)", where: "Life under thermal cycling: the swings of each chip's own temperature are counted, those of every turn of the motor included, and their damage added. A = 302500, α = −5.039, E_a = 9.89·10⁻²⁰ J: the LESIT fit for modules with aluminium bond wires. Generic." },
      { is: "R(T) = R_25 · (1 + 0.00393 · (T − 25)),   ψ(T) = ψ_25 · (1 − 0.0011 · (T − 25))", where: "A motor at its working temperature, when one is given: copper, and neodymium magnets." },
      { is: "I_hot = I · ρ / (ρ + n − 1)", where: "n devices in parallel: the typical part among parts at the datasheet's maximum, ρ times typical, carries the most. Temperatures are its own; the stage loses what it and the others lose together." },
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
      { is: "The control loop's own dynamics, distortion of the current by dead time, thermal rebalancing between devices in parallel, and layout effects beyond one loop inductance. Iron loss and saturation are in only when you give the motor's figures for them.", where: "Results are estimates. They are checked against formulas and an independent numerical integration, not yet against a measured loss." },
    ],
  },
];

/** Text with its subscripts set as subscripts: R_th,jc reads as R with th,jc below the line. */
const set = (text: string) => escape(text).replace(/_([A-Za-z0-9,\-]+)/g, "<sub>$1</sub>");

/** The equations as a page section: each on its own line in a figure of its own. */
export function equationsPage(): string {
  return SECTIONS.map((s) => `<section class="eq-section"><h3>${escape(s.title)}</h3>${s.about ? `<p class="quiet">${escape(s.about)}</p>` : ""}${s.equations.map((e) => `<div class="eq"><p class="eq-is">${set(e.is)}</p>${e.where ? `<p class="eq-where">${set(e.where)}</p>` : ""}</div>`).join("")}</section>`).join("");
}
