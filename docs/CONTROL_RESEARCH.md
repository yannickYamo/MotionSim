# Control schemes for the control lab: what the literature offers, 2021 to 2026

The research note behind the control lab (a sampled time-domain simulation of motor, inverter and controller; [CONTROL.md](CONTROL.md) describes what was built). It asks one question: which control and modulation schemes change the inverter's losses and junction temperature enough to be worth offering, and what each needs to be simulated honestly.

Method, in one line: arXiv (eess.SY, eess.SP, cs.SY), IEEE-indexed work through its open abstracts, and openly hosted full texts, as of 23 November 2026.

How to read the sources. Each entry in the source list at the end carries one of two marks:

- **[body]**: the paper's text was read, and the numbers quoted were found in it.
- **[abstract]**: only the open abstract was read. Claims are limited to what the abstract states.

Where a statement is this note's own engineering judgment and not a paper's finding, it says so. arXiv has almost nothing on four of the most loss-relevant topics (variable switching frequency, discontinuous PWM, active thermal control, loss-minimising current references that count the inverter), so those rest on IEEE abstracts and a few open full texts.

The six levers used in the tables:

| Code | What the scheme changes |
|---|---|
| I | the current the switches carry (rms and peak) |
| N | the number of switching events |
| Isw | the current at each switching instant |
| H | the harmonic current in the motor (ripple, and its copper and iron loss) |
| Tj | the transient junction temperature (swing, peak, distribution between chips) |
| S | sensing or observer error (which turns into extra current or lost torque) |

---

## 1. Candidate schemes

Baseline for comparison: field-oriented control with PI current regulators and space-vector PWM at a fixed carrier.

| # | Scheme | Changes | Reported effect | Needs, to be simulated honestly | Cost in a sampled simulator | Sources |
|---|---|---|---|---|---|---|
| 1 | Discontinuous PWM with the clamp placed on the current peak (generalised DPWM, minimum-switching-loss DPWM) | N (one third fewer), Isw (the phase carrying the most current is not switched) | Switching loss 50% of continuous PWM when the 60° clamp sits on the current peak; between 50% and 75% when power factor pushes the peak outside the reachable range; ripple worse at low modulation index, so the algorithm uses SVPWM below a threshold and DPWM above. On a 2.2 kW SiC drive the minimum-loss variant gave the best measured efficiency and least common-mode current (no figure in the abstract) | Per-phase switching energy as a function of the instantaneous current; power-factor angle from measured or reference current; ripple calculation per switching sequence; dead-time effect in the clamped region | **Low.** A zero-sequence term added to the three duty cycles | [S1] body, [S2] abstract, [S3] abstract |
| 2 | Variable switching frequency PWM held to a ripple limit | N, H | The carrier period is recomputed each interrupt from a ripple prediction, to hold either the peak or the rms ripple; "could improve EMI and efficiency without impairing power quality" (no figure in the abstract) | Ripple prediction from duty cycles, DC voltage and the motor's high-frequency inductance; variable sample period in the controller (gains and delay compensation scale with it) | **Medium.** The simulator's fixed step and the controller's sample clock must both follow a changing period | [S4] abstract, [S5] abstract |
| 3 | Switching frequency chosen per operating point for least motor-plus-inverter loss | N, H | Coupled FEM and inverter-loss simulation of an IPM traction drive: optimum between 10 and 50 kHz for SiC, up to 20 kHz away from the IGBT optimum; over WLTC, 10.78% less energy loss (SiC) and 4.17% less (IGBT) than a fixed frequency. Simulation only | Motor harmonic loss against ripple (iron loss coefficients that move with frequency: the paper finds up to 80% error with fixed ones); inverter switching energy map | **Low** as a lookup; the motor harmonic-loss model is the expensive part | [S6] body, [S7] abstract |
| 4 | Active thermal control: frequency, modulation and gate voltage moved to limit junction swing and peak | Tj (through N and Isw) | Electric truck climbing a kerb (IGBT module, simulation): frequency 8 to 6 or 4 kHz, DPWM, gate voltage 15 to 19 V, alone and combined; best combinations cut junction-to-ambient peak by up to 26%, or allow about 20% more current at the 150 °C limit; repetitions to failure up 1.6 to 2.6 times for single measures, nearly 5 times combined. Induction drive (simulation): switching to DPWM2 above 140 °C cut IGBT loss 20% and raised overload from 43% to 73% | Per-chip loss at low output frequency (one chip holds the peak for a long time); thermal network with the short time constants; a junction estimate inside the controller, with its own error; lifetime model for the payoff | **Medium.** The control law is a few lines; the per-chip electro-thermal loop inside the time step is the work | [S8] body, [S9] body, [S10] abstract, [S11] abstract |
| 5 | Common-mode injection at standstill to spread loss between chips | Tj | Proposed to reduce the current derating of SiC inverters at low output frequency, with junction temperature fed back from on-resistance (no figure in the abstract) | Per-chip loss with unequal duty between high and low side; on-resistance against temperature | **Low** once row 4 exists | [S12] abstract |
| 6 | Finite-control-set MPC with a switching penalty or a switching-frequency limit | N, Isw, H | With a slack-variable limit on switching frequency in place of frequency tracking: current distortion 4.95% to 4.70% at about 250 Hz average device frequency (three-level grid converter, simulation). Multi-step against one-step FCS-MPC on a PMSM: current THD down 22% (experiment), 27% (simulation). A simulation comparison at matched average switching frequency found deadbeat control with a modulator generally gave lower THD than one-step FCS-MPC [S15]. A 2026 review with bench tests finds the plain current cost gives the best current quality at the lowest switching burden, and torque-and-flux costs lower torque ripple at a higher average switching frequency [S16] | Sampling much faster than the resulting switching frequency (25 to 50 µs is typical in the papers); one-step delay compensation; exact motor parameters or an explicit mismatch study; the spread of switching events over time, since frequency is not fixed | **Medium** for one step (enumerate 7 or 8 vectors); **high** for long horizons (sphere decoding) | [S13] body, [S14] body, [S15] body, [S16] abstract |
| 7 | Optimised pulse patterns, with a pattern controller (MP3C, gradient-based) | N (few, fixed per fundamental), H, Isw (pulse positions) | Medium-voltage induction drive, three-level, simulation: at 150 Hz device frequency current THD 7.36% against 15.5% for SVM; at 250 Hz 4.13% against 7.71%; at 400 Hz 3.63% against 4.52%. For PMSMs with saliency, a 2026 study optimises switching loss and current THD together as a Pareto front and finds experiment and prediction mostly agree (no figure in the abstract) | Offline pattern optimisation per modulation index and pulse number; anisotropic harmonic model (Ld, Lq) for salient machines; asynchronous sampling of the fundamental; a pattern controller for transients | **High.** Offline optimiser, pattern storage, and event-timed switching instead of a carrier | [S17] body, [S18] abstract, [S19] abstract, [S20] abstract, [S21] abstract, [S22] abstract |
| 8 | Overmodulation and six-step in field weakening | N (six per fundamental), I (less weakening current), H (low-order harmonics) | Model-predictive direct self-control in six-step against FOC: up to 18% less current at the same torque and speed, up to 15% more torque at the same current, 2.3 ms rise to maximum torque (experiment). Railway drive: synchronous PWM with variable frequency into six-step, to cut switching loss under natural cooling (no figure in the abstract) | Voltage hexagon limit; current harmonics of order 5 and 7 and their torque ripple; a controller that stays stable with no voltage margin; low sampling-to-fundamental ratio | **Medium.** The modulator is easy; a current controller that works at the voltage limit is the hard part | [S23] abstract, [S24] abstract, [S25] abstract, [S26] abstract |
| 9 | Loss-minimising current reference that counts the inverter (maximum efficiency per ampere) | I | Posed as a constrained optimisation over id and iq inside a predictive torque controller; efficiency gain validated in simulation and experiment (no figure in the abstract) | Iron loss model; inverter loss as a function of current, power factor and modulation; the operating point's voltage limit | **Low.** A reference generator ahead of the current loop | [S27] abstract |
| 10 | Variable DC-link voltage | Isw and N cost (switching energy scales with voltage), H | Experiment on a 5 kW machine with a multilevel DC source: system efficiency up at least 2%, 4% at low speed and 2% at high speed once inverter savings are counted, falling to about 1% with battery loss included. A 135 kW six-phase traction drive adapts the link online for best converter efficiency (no figure in the abstract) | A DC/DC stage or battery model; switching energy against voltage | **Medium.** Outside the inverter proper; a second converter to model | [S28] body, [S29] abstract |
| 11 | Dead-time optimisation and compensation | Isw and conduction (body-diode or third-quadrant time), H, S (voltage error at low speed) | Three 200 to 300 kW traction inverters measured: dead time can be more than 10% of total inverter loss in dense SiC designs at 10 kHz; optimised dead times cut total loss by up to 5% in the Si/SiC hybrid and THD at light load by up to 4 to 5%. GaN drives run tens of nanoseconds, which removes most of the need for compensation | Third-quadrant conduction characteristic; output capacitance charge; current-polarity-dependent voltage error; sub-step timing (dead time is far shorter than a control step) | **Medium.** Needs event-accurate edges, or an averaged voltage-error and loss model per period | [S30] abstract, [S31] abstract, [S3] abstract, [S33] abstract |
| 12 | Discrete-time current control for low sampling-to-fundamental ratios, with delay compensation | S, H, I (oscillation and cross-coupling become extra current) | Decoupled tracking up to 15% of the switching frequency, oscillation reduced 30% against conventional PI (5 kW high-speed drive, experiment). For a robot joint, direct discrete synthesis with the delay modelled gives the minimum sampling frequency and link voltage for a required bandwidth | Exact discretisation of the plant in the rotating frame; 1.5-sample delay; angle advance | **Low.** A different regulator on the same loop | [S34] abstract, [S35] abstract, [S36] abstract, [S37] abstract, [S38] body (abstract and method) |
| 13 | Sensorless observers at high speed and low carrier ratio (flux, sliding-mode, extended-EMF) | S | Flux observer at 20 000 r/min, 4 kHz, carrier ratio 6: forward Euler fails, fourth-order Runge-Kutta or a hybrid discretisation holds; current THD 4.71% sensorless against 3.98% with a sensor at ratio 6, and 3.35% against 2.83% at ratio 12. A discrete complex-vector flux observer verified at ratio 5.2 | The observer discretised as the firmware would; parameter mismatch (R, L, flux); inverter voltage error | **Medium.** Several observers and a mismatch harness | [S39] body, [S40] abstract, [S41] abstract |
| 14 | Parameter-robust sensorless (adaptive flux, model-free position) | S | Equivalent-flux compensation removes the steady-state effect of resistance and flux mismatch and part of inductance mismatch (experiment, no figure in the abstract) | As row 13, plus a mismatch sweep | **Medium** | [S42] abstract, [S43] abstract, [S44] abstract |
| 15 | Deadbeat predictive current control and its robust variants | H, S (mismatch gives steady error and oscillation) | Fast response; accuracy depends on parameters. Ultra-local variants estimate the model online and are reported better than conventional deadbeat and FOC in experiment (no figure in the abstract) | Mismatch in L, R and flux; one-step delay | **Low** | [S45] abstract, [S15] body |
| 16 | Model-free predictive current control (ultra-local model, extended state observer) | S, H | A 2026 preprint (simulation only): near-unchanged performance with R, L and flux varied together to 20% and 200% of nominal, lowest THD among four controllers. A double-vector variant on a 2 kW bench reduces ripple | Current measurement noise (the model is estimated from current differences); delay | **Low to medium** | [S46] body, [S47] abstract, [S48] abstract |
| 17 | Long-horizon and approximate optimal control for the switching-against-ripple trade-off | N, H | Horizon-one control with an offline value function: trade-off comparable to FCS-MPC with horizon 3 at 90 µs against 13 400 µs per step (PI with SVM: 5.5 µs), simulation at 50 kHz. Data-driven predictive control with a finite control set: none of the tested solvers met a 25 µs sample time | As row 6 | **High** | [S49] body, [S50] body |
| 18 | Reinforcement-learning current and torque control | I, N (if the reward says so), S | DDPG current control of a PMSM run on a real bench with "promising" performance; a deep Q direct torque controller with efficiency in the reward compared with model-predictive torque control; a finite-set safe-learning controller learns a torque policy in ten minutes on hardware. No loss figures in the abstracts | A training loop, a reward that includes loss, a safety layer | **High.** Training infrastructure outside the simulator's core | [S51] abstract, [S52] abstract, [S53] abstract, [S54] abstract, [S55] abstract |
| 19 | Spread-spectrum and random PWM | H (spectrum shape, not total), N (mean unchanged) | Two variable-frequency schemes on a 1.07 kW PMSM: up to 27% less torque ripple, 51.8% lower dominant harmonic. Random SVPWM can null chosen frequencies. Loss effects are not reported | Spectrum of current and force; mean switching frequency held | **Low** | [S56] abstract, [S57] abstract |
| 20 | Harmonic current references for torque ripple and copper loss | I, torque quality | For a six-phase non-salient machine with non-sinusoidal back-EMF, offline lookup tables give current references with minimum copper loss and torque ripple over the full torque-speed range; the paper shrinks the tables with negligible loss of performance (simulation) | Back-EMF harmonics in the motor model | **Medium.** The motor model must carry harmonics, which the present engine does not | [S58] abstract |
| 21 | Online parameter identification; position-sensor harmonic compensation | S | Recursive prediction-error tracking of magnet flux and resistance on a 3 kW drive; extremum-seeking compensation of position harmonics that otherwise cause torque ripple | Temperature drift of R and flux; sensor error harmonics | **Medium** | [S59] abstract, [S60] abstract |
| 22 | Hardware levers a control lab should let the user compare against (current-source inverter for very high speed; hybrid Si/SiC bridge) | H, N | 100 W, 100 000 r/min GaN current-source drive at 200 kHz: position error below 5°. Hybrid bridge with IGBT high side and SiC low side and a modified SVPWM: partial-load loss down by two thirds against all-IGBT | Different topology | **High.** Out of scope for a first lab; listed so the comparison is known | [S61] body, [S62] abstract |

Two things stand out. First, the levers with the largest and best-documented effect on inverter loss are in the modulator and the operating-point supervisor (rows 1 to 5, 8, 10, 11), not in the current regulator. Second, the regulator and observer rows (12 to 16) matter for loss mainly where the carrier ratio is low or parameters are wrong, which is exactly the vacuum-cleaner and deep field-weakening cases.

---

## 2. Shortlist beyond the baseline

Ranked by what each adds to a loss-centred tool for the cost of building it. Formulations below are the standard ones; where a cited paper was read only as an abstract, the equations are this note's statement of the method and not copied from that paper.

Notation: Ts control period, fsw switching frequency, Vdc link voltage, d_x duty of phase x in [0, 1], v_x* phase voltage reference, i_x phase current, φ power-factor angle, L the motor's high-frequency (ripple) inductance.

### 1. Loss-optimal discontinuous PWM, selected online

**Why it is distinctive here.** It is the cheapest change with the largest switching-loss effect, and its benefit depends on things the tool already knows per instant: power factor, modulation index and the device's switching energy against current. A textbook demo shows the waveform; this tool can show the watts and the kelvins, and the ripple paid for them.

**Formulation.**

1. Compute the three sinusoidal references v_a*, v_b*, v_c*.
2. Choose which phase to clamp. Minimum-loss rule: among the phases that can be clamped without leaving the linear range (the phase with the largest and the phase with the smallest reference), clamp the one with the larger |i_x|. Generalised rule (Hava): shift the references by an angle ψ in [0, 60°] before the max-magnitude test; ψ = 30° + φ centres the clamp on the current peak for |φ| ≤ 30°.
3. Zero-sequence: v0 = +Vdc/2 − v_x* if phase x is clamped high, −Vdc/2 − v_x* if clamped low. Add v0 to all three references.
4. Below a modulation-index threshold, use SVPWM (v0 = −(v_max + v_min)/2) because DPWM's ripple is worse there.

Knobs: ψ or the current-based rule; the modulation-index threshold; whether the carrier is raised by 1.5 to hold the same number of events (same loss, less ripple at high modulation index).

**Experiment.** Sweep power factor from −60° to +60° and modulation index from 0.2 to 1.15 at fixed current. Plot switching loss relative to SVPWM (expect 0.5 at the centre, rising to 0.75 [S1]), rms ripple, and junction swing. Then run the vehicle hill and the washer spin with the selector on and off.

**Failure modes.** At low modulation index the ripple penalty exceeds the loss gain. The clamped phase gets no dead-time error while the others do, so the voltage error steps every 60° and distorts the current unless compensated [S3]. At standstill a clamp holds one switch on continuously, concentrating conduction loss in one chip. Bootstrap gate supplies limit how long a high-side switch can stay on. With current measured by low-side shunts, a phase clamped high cannot be sampled.

**Sources.** [S1] body, [S2] abstract, [S3] abstract.

### 2. Switching frequency as a controlled variable: ripple-limited within a cycle, and loss-optimal per operating point

**Why it is distinctive here.** The tool already computes ripple from the switching sequence and motor inductance (LIMITS section 4). Making fsw a controlled quantity turns that calculation into a control law and shows the loss, ripple and temperature consequence together. Most vendor calculators fix fsw.

**Formulation.**

- *Within the fundamental (VSFPWM).* Each period, predict the ripple the coming duty cycles will produce at the nominal period T0: the three-phase ripple is piecewise linear, with slopes (v_k − v*)/L for each applied vector v_k and durations set by the duties, so its peak and rms over the period scale linearly with the period. Then set Ts = T0 · (ripple limit) / (predicted ripple at T0), clipped to [T_min, T_max]. Two variants [S4]: hold the peak, or hold the rms.
- *Per operating point.* Choose fsw(torque, speed) to minimise P_inv,sw(fsw) + P_motor,harmonic(fsw). The first rises linearly with fsw; the second falls roughly with the square of the ripple, that is with 1/fsw², until iron loss terms that rise with frequency take over. A lookup table is enough.

Knobs: the ripple limit and whether it is peak or rms; frequency bounds; rate limit on fsw changes; whether regulator gains and delay compensation follow Ts.

**Experiment.** (a) At one operating point, compare fixed fsw against peak-limited and rms-limited VSFPWM at equal rms ripple: report mean switching frequency, switching loss and the current spectrum. (b) Over the vehicle's town ride, compare fixed 10 kHz against the per-point optimum and report accumulated inverter and motor harmonic energy; [S6] reports 10.78% (SiC) and 4.17% (IGBT) in simulation as the order to expect, for the whole drive system.

**Failure modes.** A regulator tuned for one Ts changes bandwidth and delay as Ts moves. Low fsw at high speed lowers the carrier ratio into the range where row 12's problems appear. Motor harmonic loss is the uncertain half of the trade: [S6] finds up to 80% error in core loss if iron-loss coefficients are held fixed across frequency. Audible tones move with the frequency. The inductance that sets ripple is the high-frequency one, not the datasheet Ld or Lq.

**Sources.** [S4] abstract, [S5] abstract, [S6] body, [S7] abstract.

### 3. Active thermal control at low speed, stall and overload

**Why it is distinctive here.** The tool's strength is per-chip junction temperature and life through a real motion. Thermal control closes that loop: the controller gives up some ripple or efficiency to protect the chip the motion strains most. No drive demo without a thermal engine can show this, and the published results are almost all simulation, so a transparent open implementation is useful in itself.

**Formulation.**

1. Estimator inside the controller: per-chip loss from measured current, duty and a loss table; a Foster network from junction to the sensed point (case, NTC or heatsink); output the estimated junction temperature and its swing over the last fundamental period.
2. Actuators, in order of cost: (a) DPWM in place of SVPWM (fewer events); (b) lower fsw in steps, for example 8 to 6 to 4 kHz [S8]; (c) at near-zero output frequency, a common-mode offset that moves conduction between the high and low chip of the loaded phase [S12]; (d) torque or current derating as the last resort.
3. Law: hysteresis on the estimated peak (for example, switch to DPWM above 140 °C and back below 110 °C [S9]) or on the swing; a slower outer rule on mean temperature. The fuzzy scheme of [S10] takes the minimum of two frequency demands, one from the transient swing and one from the mean.

Knobs: thresholds and hysteresis; minimum fsw (set by ripple and control needs); which actuators are allowed.

**Experiment.** The robot joint holding a load at standstill, the vehicle held on a hill, and the washer's tumble reversal. Report peak junction temperature, swing, cycles to failure and the ripple and loss cost, with thermal control off, with each actuator alone and combined. [S8] gives the scale to expect in simulation: up to 26% lower junction-to-ambient peak, or 20% more current.

**Failure modes.** The controller's junction estimate carries the loss-model error and the thermal-model error; a 20% loss error moves the estimate by 20% of the rise. Lower fsw raises ripple, motor loss and noise. Raising loss at light load to flatten swings (a known variant) costs efficiency and mean temperature [S11]. Frequency steps disturb the current loop. The lifetime gain is as uncertain as the lifetime model.

**Sources.** [S8] body, [S9] body, [S10] abstract, [S11] abstract, [S12] abstract.

### 4. Finite-control-set MPC with switching effort in the cost

**Why it is distinctive here.** It is the one scheme where the loss objective is written directly into the controller, and where the tool can put a number on the trade the papers describe in THD and switching frequency only. It also exposes an honest comparison the literature often skips: against a modulator-based controller at the same average switching frequency [S15].

**Formulation (two-level inverter, PMSM, dq frame, one-step with delay compensation).**

- Prediction model, forward Euler at period Ts (use the exact discretisation of row 12 when ω·Ts is not small):
  id[k+1] = id[k] + (Ts/Ld)·(vd[k] − R·id[k] + ω·Lq·iq[k])
  iq[k+1] = iq[k] + (Ts/Lq)·(vq[k] − R·iq[k] − ω·Ld·id[k] − ω·ψ)
- Delay compensation: predict i[k+1] with the vector already being applied, then evaluate the eight candidate switch states u in {0,1}³ for the step k+1 to k+2.
- Cost: J(u) = |i*[k+2] − i(u)[k+2]|² + λu·|u − u[k]|₁ , with the constraint |i| ≤ I_max handled by a large penalty.
- Loss-weighted variant (this note's suggestion, not verified in a paper that was read): replace the count |u − u[k]|₁ by the sum over phases that switch of E_sw(|i_x|, Vdc), so a transition in the phase carrying little current is cheap.
- Frequency-limit variant [S13]: track the device switching frequency with a second-order IIR filter of the transition count, add a slack s = max(f_est − f_max, 0) and penalise λsw·s²; the current term is then not disturbed while the frequency is under the limit.
- Longer horizons (2 to 5 steps) by enumeration with pruning; beyond that a sphere decoder [S13].

Knobs: λu or f_max; Ts; horizon; one or two vectors per period.

**Experiment.** For one motor and device, sweep λu and plot the Pareto front of switching loss against rms ripple; overlay FOC with SVPWM and with DPWM at carrier frequencies giving the same loss. Expect, from [S15] (simulation), that the modulator-based schemes win on THD at equal average frequency in steady state, and that the MPC's advantage is in transients and at very low switching frequency [S13, S17].

**Failure modes.** Parameter mismatch gives a steady current error because there is no integrator. The switching frequency varies with operating point and spreads the spectrum. The sampling rate must be several times the resulting switching frequency (the cited studies use 25 to 100 µs), so the control period in the simulator is short. Losses are uneven between phases and over time, which matters for the junction calculation. Long horizons may not finish within the period [S50].

**Sources.** [S13] body, [S14] body, [S15] body, [S16] abstract, [S49] body, [S50] body.

### 5. Synchronous optimised pulse patterns, with six-step as the limit case

**Why it is distinctive here.** At low pulse number (traction in field weakening, a vacuum motor above 1 kHz electrical with silicon or a modest carrier) the pattern, not the carrier, decides both switching loss and harmonic loss. A 2026 open-access study treats switching loss and current THD as a joint Pareto problem for salient PMSMs [S20]; a loss-centred tool is the natural place to show that front for the user's own device.

**Formulation.**

- Pattern: d switching angles per quarter period (quarter-wave symmetry) or per half period (half-wave symmetry, more freedom, recommended in [S20]).
- Offline problem, per modulation index m and pulse number d: minimise the weighted harmonic current, Σ over n = 5, 7, 11, … of (V_n / (n·ω·L_n))², subject to the fundamental equal to m and to ordered angles. For a salient machine L_n depends on the harmonic's sequence and on Ld and Lq [S19]. Loss-aware version: add a term Σ over switching instants of E_sw(|i(α_k)|), which requires the fundamental current phase, and trace the Pareto front [S20].
- Six-step is d = 0: one transition per phase per half period.
- Online, simplest faithful form: slow FOC loop sets voltage magnitude and angle; the modulator reads the stored angles; the current is sampled so that the pattern's ripple is not fed back (average over a sixth of the period or subtract the stored ripple).
- Online, fast form (MP3C [S17]): compute the flux (or current) error against the pattern's optimal trajectory and remove it over a short horizon by shifting the coming switching instants, Δt_x = −(error component along phase x)/(Vdc·Δu_x), distributed over the transitions inside the horizon.

Knobs: pulse number against speed (hysteresis at the changes); symmetry class; the loss-against-THD weight; horizon of the pattern controller.

**Experiment.** At fixed fundamental and device switching frequency, compare SVPWM, synchronous SVPWM and the optimised pattern at pulse numbers 3, 5, 7 and six-step: harmonic current, switching loss, torque ripple. [S17] reports about half the current THD of SVM at the same device frequency for a medium-voltage induction drive in simulation; whether a low-voltage PMSM shows the same ratio was not verified.

**Failure modes.** Patterns are optimal for the inductances assumed; saturation moves them [S19]. Transitions between pulse numbers cause current transients. A plain PI loop sees the pattern's ripple as error. Six-step leaves no voltage margin for current control, so torque is controlled by voltage angle or by a predictive scheme [S24, S25]. Low-order harmonics (5th, 7th) produce sixth-order torque ripple.

**Sources.** [S17] body, [S18] abstract, [S19] abstract, [S20] abstract, [S21] abstract, [S23] abstract, [S24] abstract, [S25] abstract, [S28] body.

### 6. Current reference for least system loss (motor plus inverter)

**Why it is distinctive here.** LIMITS section 4 already notes that the least-current reference is not the least-loss one, and the engine holds both loss models. This is a reference generator, cheap to add, and it is the scheme whose answer changes with the device chosen, which is the tool's purpose.

**Formulation.** For each torque T and speed ω, choose (id, iq) to minimise
P = 1.5·R·(id² + iq²) + P_fe(ω, ψd, ψq) + P_inv(Is, φ, m, fsw, Vdc, Tj)
subject to T = 1.5·p·(ψ·iq + (Ld − Lq)·id·iq), Is ≤ I_max, and the voltage limit |v| ≤ m_max·Vdc/√3.
P_inv is the engine's own conduction and switching model. Solve offline into a table, or online by a one-dimensional search along the constant-torque curve. Optional second variable: fsw (shortlist item 2). Optional third: Vdc where a DC/DC stage exists [S28, S29].

Knobs: which loss terms are counted; table resolution; the iron-loss model.

**Experiment.** Efficiency maps under least-current, least-motor-loss and least-system-loss references, and the difference map between them; then the energy over the vehicle's ride and the compressor's hour. No inverter-inclusive figure was verified in a paper that was read, so the size of the effect is an open result the lab would produce, not confirm.

**Failure modes.** Iron-loss parameters are rarely on a motor datasheet; with a poor iron-loss model the "optimum" is noise. Away from the least-current point, torque per ampere falls, so peak torque capability must not be traded. The optimum shifts with winding and magnet temperature.

**Sources.** [S27] abstract, [S6] body, [S28] body, [S29] abstract.

### 7. Discrete-time current control and observers for low carrier ratio

**Why it is distinctive here.** It is the precondition for simulating the vacuum-cleaner and deep field-weakening cases at all: a continuous-design PI loop and a forward-Euler observer misbehave below a carrier ratio of roughly 10 to 15, and what looks like a loss result is then a control artefact. Offering both designs shows the user where their firmware's assumptions end.

**Formulation (surface-magnet machine, complex-vector form; this note's statement of the standard model).**

- Plant with zero-order hold in the stationary frame, seen in the rotor frame:
  i_dq[k+1] = e^(−jωTs)·( a·i_dq[k] + b·v_dq[k] ) − (back-EMF term), with a = e^(−R·Ts/L), b = (1 − a)/R.
- One period of computation delay: the voltage computed at k is applied from k+1. Half a period of PWM delay on average.
- Regulator: a complex-vector PI or a deadbeat-PI designed on that model, cancelling the complex pole a·e^(−jωTs) [S34, S35, S37]; output rotated forward by 1.5·ω·Ts before the modulator to compensate the delay.
- Baseline to compare against: PI with feed-forward decoupling designed in continuous time, discretised by Tustin, no angle advance.
- Observer: a flux or extended-EMF observer discretised exactly or by a high-order method. [S39] shows forward Euler failing at ratio 6 where fourth-order Runge-Kutta and a cheaper hybrid (Euler on the linear part, Runge-Kutta on the nonlinear part) hold; [S40] derives the observer directly in discrete time and verifies it at 5.2.

Knobs: carrier ratio; single or double update per carrier; bandwidth as a fraction of fsw; observer gains.

**Experiment.** Hold fsw and raise speed until the ratio falls from 30 to 5. Plot current-loop damping, d-q cross-coupling, rms current for a fixed torque, position error and loss, for the baseline and the discrete design. Repeat with inductance wrong by ±30%.

**Failure modes.** Exact models assume known L and R; mismatch brings the coupling back [S42]. Salient machines need the matrix form, not the complex one. At ratios below about 6 the fundamental's sampling and the PWM sidebands alias; synchronous modulation (shortlist item 5) is then the better tool.

**Sources.** [S34] abstract, [S35] abstract, [S36] abstract, [S37] abstract, [S38] body (abstract and method), [S39] body, [S40] abstract, [S41] abstract.

Left off the shortlist, with the reason: dead-time optimisation (row 11) is a hardware setting more than a control scheme, but its measured share of loss (more than 10% in SiC traction inverters at 10 kHz [S30]) says the lab's inverter model must include it whatever control is chosen. Reinforcement learning (row 18) needs training infrastructure and has no verified loss result. Model-free predictive control (row 16) answers a robustness question, not a loss question.

---

## 3. By application

"What industry uses" below is common practice as this note understands it, supported where a published design guide or paper was read; it is not a survey.

### Robot-joint servo (tens of volts, low inductance)

**Baseline.** Cascaded position, velocity and current loops; FOC with PI current regulators; SVPWM; an encoder; in-line or shunt phase-current sensing synchronised to the carrier. GaN reference designs for this use run 40 to 100 kHz with dead times of tens of nanoseconds [S63, S64]. Low inductance makes ripple, not fundamental current, the reason for the high carrier.

**Shortlisted schemes that matter.** 3 (thermal control at standstill under load, where one chip carries the current), 2 (ripple-limited frequency, since ripple is the design driver), 1 (DPWM, with the standstill caveat), 7 in its delay-aware form ([S38] derives the minimum sampling frequency and link voltage for a required joint bandwidth).

**Explorations to offer.**

1. *Holding a load at standstill.* Rotor angle swept; SVPWM, DPWM and common-mode shifting compared on the hottest chip's temperature and the life it leaves.
2. *How fast must it switch?* Carrier from 20 to 100 kHz against current ripple, torque ripple, loss and current-loop bandwidth, for a given motor inductance; VSFPWM as the alternative to a fixed answer.
3. *Dead time and current sensing.* Dead time from 20 to 500 ns: loss, voltage error at low speed and its torque ripple, with and without compensation.

### Traction drive (hundreds of kilowatts, field weakening)

**Baseline.** Torque control by FOC with current references from lookup tables (least current below base speed, field weakening above, flux maps with saturation); SVPWM at about 10 kHz (stated as typical for automotive in [S30]), changing to DPWM, overmodulation and in some drives six-step at high speed; resolver. Public benchmarking of a production hybrid shows inverter efficiency maps at three link voltages, since that vehicle varies its DC link [S65].

**Shortlisted schemes that matter.** 1 (DPWM at high modulation index), 2 (frequency by operating point), 5 (pulse patterns and six-step in field weakening), 6 (least system loss), 3 (hill hold and kerb climbing), 4 as a comparison.

**Explorations to offer.**

1. *Modulation over a drive cycle.* SVPWM only; SVPWM with DPWM above a threshold; plus six-step. Energy lost, junction swings on the hill, torque ripple.
2. *Switching frequency map.* Fixed 10 kHz against the per-point optimum for an IGBT and a SiC module on the same motor: energy over the ride and where the optimum sits.
3. *Hill hold and launch.* Thermal control on and off at near-zero speed: how much torque can be held for how long.

### High-speed vacuum motor (100 000 r/min and above, sensorless)

**Baseline.** Two-pole motor, so about 1.7 kHz electrical at 100 000 r/min. Sensorless FOC with SVPWM where the inverter can switch fast: a GaN reference inverter for a 25.2 V vacuum motor runs sensorless FOC at 80 kHz with 50 ns dead time, shown at 50 000 r/min [S66]. Lower-cost designs with silicon MOSFETs run lower carrier ratios or six-step (block) commutation with back-EMF zero-crossing detection; this second statement is common knowledge and is not sourced here. Start-up is open loop (alignment, ramp, handover), as LIMITS section 4 already represents.

**Shortlisted schemes that matter.** 7 (low carrier ratio regulator and observer; the central one), 5 (synchronous patterns and six-step when the ratio is single-digit), 2 (frequency against ripple in a very low inductance motor), 1 (DPWM to halve switching loss at the high carrier).

**Explorations to offer.**

1. *Carrier ratio.* Same motor at 100 000 r/min with the carrier from 10 to 100 kHz: loss, ripple, rotor-position error and whether the loop stays stable, for the textbook and the discrete-time design.
2. *Observer and wrong parameters.* Flux observer against sliding-mode, each with resistance and inductance off by ±30%: position error, the extra current it costs and the loss that follows.
3. *Six-step against sinusoidal.* Block commutation, synchronous patterns and SVPWM at the same speed and torque: switching loss falls, harmonic current and torque ripple rise; show both.

---

## 4. Accuracy: what can be claimed

### What published comparisons report

| What was compared | Finding | Source |
|---|---|---|
| Switching energy from a datasheet-parameter model against double-pulse measurement, 1200 V SiC MOSFET with SiC diode | Turn-on within 9%; turn-off off by 12 to 37%; the sum within 6% (the two errors partly cancel). Junction temperature within 3.2 °C (6.17%) in a short thermal test. The model's agreement with the datasheet degrades above about 100 °C | [S67] body |
| Conventional loss model against one with commutation detail and parasitics, SiC, current-source inverter, against double-pulse and power-analyser measurement | Switching energy error 10.1 to 24.5% conventional, 4.0 to 9.6% with parasitics. Inverter loss error 14.6 to 19.6% conventional, 3.9 to 5.6% improved | [S68] body |
| Datasheet-only switching model with parasitic inductance neglected, SiC bare die, against measured converter efficiency | Efficiency error (MMAPE) at most 0.51% at 80 kHz. Note that this is an error in efficiency: at 98% efficiency, half a point of efficiency is a quarter of the loss. The authors state that parasitic inductances cannot be had without a measurement or a vendor SPICE model | [S69] body |
| Effect of DC-link loop inductance on a 1200 V-class SiC module, measured, 23 to 37 nH | Turn-on energy 14.3 to 10.4 mJ (down 27%); turn-off 17.0 to 21.8 mJ (up 28%); the sum nearly unchanged (31.3 to 32.2 mJ). When the gate resistor is then raised to hold the same peak voltage, turn-on rises from 18.2 to 31.4 mJ. So layout changes the split strongly and the total mainly through the gate resistor it forces | [S70] body |
| How switching energy is measured at all on fast SiC modules | The usual product of terminal voltage and current is in error because capacitive current is counted at turn-off and the internal discharge at turn-on is invisible at the terminals; probe delay mismatch adds more | [S71] abstract |
| Junction temperature from a conventional datasheet-loss method against an electro-thermal model with temperature feedback and parasitics, SiC DC/DC converter, measured | Maximum error 22.34% conventional, under 5.28% with the electro-thermal model | [S72] body |
| Simulated against measured efficiency maps, IGBT and SiC traction inverters, switching loss from the authors' own double-pulse tests | Efficiency errors mostly under 1 point; larger at the lowest-efficiency points, attributed to busbar and DC-link capacitor loss not in the model. As above, 1 point of efficiency is a large fraction of the loss | [S73] body |
| Dead time as a loss term, three 200 to 300 kW traction inverters, measured | More than 10% of total inverter loss in dense SiC designs at 10 kHz | [S30] abstract |
| Board parasitics from field simulation, GaN half-bridge module, loss and temperature | With parasitics included, the rise in turn-off energy offset the fall in turn-on energy and the predicted peak temperature matched the one without parasitics | [S74] body |
| This project's own Level D check (48 V, 30 MOSFETs, measured with a power analyser) | Model 10 to 31% below measurement; frequency-dependent part about 30% low at low current and a third high at high current | docs/VALIDATION.md |

### What a datasheet-based tool can claim

The figures below are this note's judgment from the table above and the project's own check, not a published standard.

| Loss component | From datasheet alone | Why | What calibration buys |
|---|---|---|---|
| Conduction, at a known current and junction temperature | About ±10% for a typical part; the part-to-part spread to the datasheet maximum is larger than the model error and should be shown separately, as the tool does | The curve is printed; error comes from temperature and from reading typical values | A measured on-resistance or forward drop for the actual part removes the spread |
| Switching, from printed energy curves, at the datasheet's own gate resistor and a similar layout | ±10 to 25% on the sum; the turn-on and turn-off split can be wrong by 30% or more | [S67], [S68], [S70]: layout inductance and the diode or opposite switch used in the datasheet test differ from the application | One double-pulse measurement on the real layout brings the published models to 4 to 10% [S68] |
| Switching, estimated from charges and times where no energy is printed | ±30% or worse | The project's own check: 30% low to a third high on one board | Same as above; it is the component most worth one measurement |
| Dead-time conduction and output-capacitance loss | Can be modelled to first order from printed data; if omitted, the error can exceed 10% of the total [S30] | Needs the third-quadrant curve and the dead time actually used | The firmware's dead time, which the user knows |
| Board copper, connectors, shunts, capacitor ESR, snubbers | Not available from a device datasheet | In the project's check these were about three times the transistors' conduction loss at the highest current | Layout extraction or one resistance measurement per phase |
| Junction temperature rise | The loss error carries through in proportion, plus the thermal path: junction-to-case is printed, case-to-ambient is the user's. Published validations that get the loss right land within about 3 to 6 °C or about 5% [S67], [S72] | Thermal coupling between chips and the interface material are not on the datasheet | One temperature reading (NTC, case thermocouple or infrared) at a known load fixes the case-to-ambient path |

A fair statement for the control lab: comparisons between control schemes on the same device and board are much more trustworthy than absolute watts, because the layout-dependent errors are common to both sides. The exception is any scheme that changes the current at the switching instant (DPWM clamping, pulse patterns, loss-weighted MPC): its benefit depends on the shape of the switching-energy curve against current, so there the error in the turn-on and turn-off split matters.

### Public references that could serve for validation

"Measured" means the document reports a measurement, not that raw data files are published. No open dataset of raw measured inverter loss or junction temperature was found. Makers' design guides are described by what they hold and are not named, as everywhere in this project.

| Reference | What is measured | Link |
|---|---|---|
| 48 V, 16 A three-phase GaN inverter reference design (design guide) | Board loss against phase current at 40, 60 and 80 kHz (9.66 W at 40 kHz and 10.5 W at 80 kHz, at 14.8 A rms); no-load loss against switching frequency compared with simulated output-capacitance loss; thermal images | [S63] |
| 48 V, 10 A three-phase GaN inverter reference design (design guide) | Board loss against current at 40 and 100 kHz (4.95 W and 5.65 W at 7 A rms); efficiency driving a servo motor (94.3% and 93.6% at 83 W); thermal image | [S64] |
| 48 V, 85 A three-phase MOSFET inverter reference design (design guide) | Thermal image and MOSFET temperature rise (45.5 °C at 26.2 A rms, no heatsink) | [S75] |
| 300 kW SiC three-phase inverter reference design (user guide) | One point: about 2.6 kW total loss processing 300 kW into an inductive load at 10 kHz, 300 Hz, up to 360 A rms, 25 °C coolant | [S76] |
| National-laboratory teardown of a 2010 production hybrid drive | Inverter efficiency contours at 650, 500 and 225 V DC; motor and combined maps; temperatures in continuous tests | [S65] |
| GaN inverter evaluation board and vacuum-cleaner application note | Operating conditions (80 kHz, 50 ns dead time, 25.2 V, 50 000 r/min), phase-current waveforms, thermal behaviour | [S66], [S77] |
| Paper: SiC and IGBT traction inverters, modelled and measured | Measured and simulated efficiency maps for both inverters, tabulated extremes | [S73] |
| Paper: three traction inverters (IGBT, SiC, hybrid), dead-time study | Measured loss against dead time; infrared thermal measurement on one | [S30] (abstract only read) |
| Data set: 57 kW PMSM with a two-level IGBT inverter, about 40 million samples | Currents, voltages and switching states for model identification under FCS-MPC with a 50 µs cycle. Useful for validating the electrical model and inverter voltage error, not loss | [S78] |
| The reference design already used in docs/VALIDATION.md Level D | Whole-inverter loss at 8 and 10 kHz from 27 to 131 A | docs/VALIDATION.md |

---

## 5. Open questions and what could not be verified

**Not verified, and therefore left as abstract-level claims or omitted.**

- Several key papers were read as abstracts only: the measured dead-time study [S30], the SiC DPWM comparison [S2], the fuzzy thermal control paper [S10], the active thermal control review [S11] and the low-frequency derating paper [S12]. Their numbers here are the abstracts' numbers.
- IEEE papers were read as abstracts unless an author or repository copy was found. No figure is quoted from an IEEE paper body unless marked [body].
- **Variable switching frequency PWM**: the size of the loss saving at equal ripple was not verified. A figure of about 19% circulates in secondary text; the primary paper's abstract [S4] gives none.
- **Minimum-loss DPWM on SiC**: no measured percentage verified beyond the 1998 analysis [S1].
- **Loss-minimising references that include inverter loss**: no measured figure verified.
- **High-frequency injection**: no paper quantifying its added inverter or motor loss was read. It is absent from the table for that reason, not because it is unimportant.
- **Random PWM**: effect on losses not reported in what was read.
- **Pulse patterns on low-voltage PMSMs**: the halving of current THD in [S17] is for a medium-voltage induction drive in simulation. The PMSM papers [S18, S20] were abstracts without figures.
- **Reinforcement learning**: no loss or efficiency number verified.
- **Six-step in silicon vacuum-cleaner drives**: stated as common practice, not sourced.
- **Loss-weighted FCS-MPC cost** (transition cost equal to switching energy at the phase current): suggested here; not confirmed in a paper that was read.
- **Raw validation data**: none found in public. All references in section 4 are figures and tables in documents.
- arXiv identifiers beginning 26 are 2026 preprints, several of them not yet peer reviewed ([S46] in particular is simulation only).

**Open questions for the lab's design.** The lab as built takes a side on three of them: its switched stage is followed edge by edge within each period (question 2), the loss model reads each switch's own commutations and not a per-fundamental average (question 3), and the thermal supervisor runs on the controller's own estimate, whose error can be set (question 4). The others stand.

1. **Motor harmonic loss.** Shortlist items 2, 5 and 6 trade inverter loss against harmonic copper and iron loss. The engine has ripple but no validated harmonic iron-loss model, and [S6] shows fixed coefficients can be 80% off. Without it, the lab can report inverter loss and ripple honestly but not the system optimum.
2. **Time resolution.** Dead time (tens of nanoseconds to microseconds) and pulse-pattern edges do not fit a fixed control-rate step. Either the inverter is event-timed within each period, or dead-time and edge effects enter as per-period averaged voltage error and loss. The second is cheaper and matches the existing engine; whether it is accurate enough at carrier ratios below 10 needs a check against an event-timed reference.
3. **Per-chip loss with variable switching.** FCS-MPC and pulse patterns load the six switches unevenly over time. The junction calculation must take the actual event sequence, not a per-fundamental average.
4. **The controller's own thermal estimate.** Thermal control (shortlist item 3) should run on an estimate with deliberately imperfect loss and thermal parameters, otherwise the lab shows a result no drive could achieve.
5. **Fair comparison rule.** The literature compares schemes at equal sampling rate, equal average switching frequency or equal THD, and conclusions change with the choice [S15]. The lab should fix one rule and say it; equal switching loss, or equal rms ripple, are the two that fit a loss-centred tool.
6. **Salient machines.** The low-carrier-ratio regulator and the pulse-pattern optimisation are simplest for surface-magnet motors. The traction case is an interior-magnet machine with saturation; the matrix forms and flux maps are more work and should be scoped before item 5 is promised for traction.

---

## Sources

[body] or [abstract] as defined at the top. A maker's design guide or application note is described by what it holds, without its name or number.

**Modulation and switching frequency**

- [S1] A. M. Hava, R. J. Kerkman, T. A. Lipo, "A high-performance generalized discontinuous PWM algorithm," IEEE Trans. Industry Applications, 1998. [body] https://doi.org/10.1109/28.720446 (open copy: https://minds.wisconsin.edu/bitstream/1793/9932/1/file_1.pdf)
- [S2] H. Lin, J. Xu, "Performance Evaluation of SiC-Based Two-Level VSIs with Generalized Carrier-Based PWM Strategies in Motor Drive Applications," Electronics, 2022. [abstract] https://doi.org/10.3390/electronics11244136
- [S3] R. Asrar Ghaderloo et al., "Dead-time Compensation Method for Bus-clamping Modulated Voltage Source Inverter," arXiv:2307.11868, 2023. [abstract] https://arxiv.org/abs/2307.11868 (100 kHz inverter with bus-clamping PWM; the PDF text could not be extracted, so only the abstract was read)
- [S4] D. Jiang, F. Wang, "Variable Switching Frequency PWM for Three-Phase Converters Based on Current Ripple Prediction," IEEE Trans. Power Electronics, 2013. [abstract] https://doi.org/10.1109/tpel.2013.2240701
- [S5] Y. He et al., "An Adaptive Control Strategy for Minimizing Losses in EV Traction Systems Under Variable Speed Demands," IEEE DMC, 2024. [abstract] https://doi.org/10.1109/dmc62632.2024.10812141
- [S6] S. Amirpour et al., "Adaptive Determination of Optimum Switching Frequency in SiC-PWM-Based Motor Drives: A Speed-Dependent Core Loss Correction Approach," IEEE Open J. Industrial Electronics Society, 2025. [body] https://doi.org/10.1109/ojies.2025.3569349 (open copy: https://research.chalmers.se/publication/546713/file/546713_Fulltext.pdf)
- [S7] C. Sachs et al., "Optimization-Based Comparative System Evaluation of Single and Dual Traction Inverters with Focus on Partial Load Efficiency and Chip Area," arXiv:2507.03573, 2025. [body] https://arxiv.org/abs/2507.03573 (topology comparison with a 175 °C limit and optimum switching frequencies of 16 to 18 kHz for the designs studied)
- [S56] M. Khalid et al., "A Modified Variable Switching Frequency Spread-Spectrum PWM Technique With Reduced Torque Ripple for a Vector-Controlled PMSM Drive," IEEE Access, 2022. [abstract] https://doi.org/10.1109/access.2022.3230906
- [S57] J. Wen et al., "Selective Noise Suppression Methods Using Random SVPWM to Shape the Noise Spectrum of PMSMs," arXiv:2302.08053, 2023. [abstract] https://arxiv.org/abs/2302.08053

**Thermal control**

- [S8] E. Agirrezabala et al., "Enhancing Overload Capability of Electric Truck Inverters via Active Thermal Control," IEEE VPPC, 2025. [body] https://doi.org/10.1109/vppc66000.2025.11392945 (open copy at the Mondragon University repository, handle 20.500.11984/14053)
- [S9] "Active temperature control of inverters for applications in electric drives: Action on modulation strategies," Congresso Brasileiro de Automática, 2024. [body] https://doi.org/10.20906/cba2024/4485
- [S10] W. Wang et al., "A dual fuzzy logic controller-based active thermal control strategy of SiC power inverter for electric vehicles," IET Electric Power Applications, 2021. [abstract] https://doi.org/10.1049/elp2.12146
- [S11] A. Ibrahim et al., "Review of Active Thermal Control for Power Electronics: Potentials, Limitations, and Future Trends," IEEE Open J. Power Electronics, 2024. [abstract] https://doi.org/10.1109/ojpel.2024.3376086
- [S12] F. Stella et al., "Mitigation of the Performance Derating in SiC Motor Drive Inverters Operating at Low Output Current Frequency," IEEE ECCE, 2023. [abstract] https://doi.org/10.1109/ecce53617.2023.10362432

**Predictive control**

- [S13] L. M. Hartmann, O. Karaca, T. Dorfling, T. Geyer, "Switching Frequency Limitation with Finite Control Set Model Predictive Control via Slack Variables," arXiv:2312.05916, 2023. [body] https://arxiv.org/abs/2312.05916
- [S14] H. Yang et al., "Improved Multi-step FCS-MPCC with Disturbance Compensation for PMSM Drives: Methods and Experimental Validation," arXiv:2205.07213, 2022. [body] https://arxiv.org/abs/2205.07213
- [S15] O. E. Özçiflikçi, "Performance Assessment of FCS-MPCC and DPCC for PMSM Drives Under Matched Average Switching Frequency Conditions," Turkish J. Electrical Power and Energy Systems, 2026. [body] https://doi.org/10.67047/tepes.1922611
- [S16] Z. Q. Zhu et al., "Review of Cost-Function Design in Finite-Control-Set MPC for PMSM Drives," IEEE Access, 2026. [abstract] https://doi.org/10.1109/access.2026.3704303
- [S45] Y. Zhang, W. Shen, H. Yang, "An Improved Deadbeat Predictive Current Control of PMSM Drives Based on the Ultra-local Model," Chinese J. Electrical Engineering, 2023. [abstract] https://doi.org/10.23919/cjee.2023.000020
- [S46] Y. Li, S. Liang, H. Ma, "Model-Free Current Control of Permanent Magnet Synchronous Motors via ESO-Based Disturbance Feedforward and Data-Driven H-infinity Residual Feedback," arXiv:2609.25759, 2026. [body] https://arxiv.org/abs/2609.25759
- [S47] Z. Zhu et al., "Double-Vector Model-Free Predictive Current Control for PMSMs With Influence Rejection of DC Voltage Mismatch," IEEE Trans. Transportation Electrification, 2024. [abstract] https://doi.org/10.1109/tte.2024.3498950
- [S48] P. Wang et al., "An Improved Model Free Predictive Current Control for PMSM With Current Prediction Error Variations," IEEE Access, 2022. [abstract] https://doi.org/10.1109/access.2022.3175501
- [S49] H.-T. Do et al., "Computationally Efficient Near-Optimal Control for Current Ripple Reduction and Optimization of Three-Phase Motors via LMIs," arXiv:2607.01215, 2026. [body] https://arxiv.org/abs/2607.01215
- [S50] M. Klädtke, M. Schulze Darup, D. E. Quevedo, "Extending direct data-driven predictive control towards systems with finite control sets," arXiv:2404.02727, 2024. [body] https://arxiv.org/abs/2404.02727

**Pulse patterns, overmodulation, six-step, DC link**

- [S17] T. Geyer, N. Oikonomou, G. Papafotiou, F. Kieferndorf, "Model Predictive Pulse Pattern Control," author's copy of the 2011 conference paper (journal version: IEEE Trans. Industry Applications, 2012). [body] http://tobiasgeyer.org/GOPK11_MP3C.pdf
- [S18] A. Benevieri et al., "Gradient-Based Predictive Pulse Pattern Control for Low Switching Frequency Permanent-Magnet Synchronous Motor Drives," IEEE Trans. Energy Conversion, 2026. [abstract] https://doi.org/10.1109/tec.2026.3738212
- [S19] N. Hartgenbusch, A. Thünen, R. W. De Doncker, "Optimized Pulse Patterns for Salient Synchronous Machines," IEEJ J. Industry Applications, 2021. [abstract] https://doi.org/10.1541/ieejjia.21001231
- [S20] S. Aleff et al., "Multi-Objective Pulse Pattern Optimization for Synchronous Machine Drives Considering Different Symmetry Properties," IEEE Open J. Power Electronics, 2026. [abstract] https://doi.org/10.1109/ojpel.2026.3707411
- [S21] M. A. W. Begh, P. Karamanakos, T. Geyer, "Gradient-Based Predictive Pulse Pattern Control of Medium-Voltage Drives," Parts I and II, IEEE Trans. Power Electronics, 2022. [abstract] https://doi.org/10.1109/tpel.2022.3190708 and https://doi.org/10.1109/tpel.2022.3190713
- [S22] J. Miller, P. Karamanakos, "Optimal Pulse Patterns through a Hybrid Optimal Control Perspective," arXiv:2512.07585, 2025. [abstract] https://arxiv.org/abs/2512.07585
- [S23] M. Peña et al., "Model Predictive Direct Self-Control for Six-Step Operation of Permanent-Magnet Synchronous Machines," IEEE Trans. Power Electronics, 2023. [abstract] https://doi.org/10.1109/tpel.2023.3286713
- [S24] A. Brosch, O. Wallscheid, J. Böcker, "Model Predictive Control of Permanent Magnet Synchronous Motors in the Overmodulation Region Including Six-Step Operation," IEEE Open J. Industry Applications, 2021. [abstract] https://doi.org/10.1109/ojia.2021.3066105
- [S25] H. El Khatib, D. Gerling, M. Saur, "Deadbeat Flux Vector Control as a One Single Control Law Operating in the Linear, Overmodulation, and Six-Step Regions With Time-Optimal Torque Control," IEEE Open J. Industry Applications, 2022. [abstract] https://doi.org/10.1109/ojia.2022.3222852
- [S26] J.-H. Park et al., "Variable Switching Frequency Control-Based Six-Step Operation Method of a Traction Inverter for Driving an Interior Permanent Magnet Synchronous Motor for a Railroad Car," IEEE Access, 2022. [abstract] https://doi.org/10.1109/access.2022.3162877
- [S27] S. Wang et al., "An Enhanced Model Predictive Torque Control With Online Loss Minimization Tracking for SPMSM Drive," IEEE Trans. Industrial Electronics, 2024. [abstract] https://doi.org/10.1109/tie.2024.3493173
- [S28] L. Liu et al., "Loss Minimization of Traction Systems in Battery Electric Vehicles Using Variable DC-link Voltage Technique: Experimental Study," arXiv:2007.07321, 2020. [body] https://arxiv.org/abs/2007.07321
- [S29] P. Pescetto et al., "Active Control of Variable DC-Link for Maximum Efficiency of Traction Motor Drives," IEEE Trans. Industry Applications, 2023. [abstract] https://doi.org/10.1109/tia.2023.3267770

**Dead time**

- [S30] T. Reiter et al., "PWM Dead Times in Automotive Traction Inverters using IGBT, SiC MOSFET, or Si/SiC Fusion Switch Power Modules," IET Power Electronics, 2026. [abstract] https://doi.org/10.1049/pel2.70185
- [S31] F. Mandrile, S. Musumeci, M. Palma, "Dead Time Management in GaN Based Three-Phase Motor Drives," EPE ECCE Europe, 2021. [abstract] https://doi.org/10.23919/epe21ecceeurope50061.2021.9570665
- [S33] P. B. C. Costa, S. F. Pinto, J. F. Silva, "A Novel Analytical Formulation of SiC-MOSFET Losses to Size High-Efficiency Three-Phase Inverters," Energies, 2023. [abstract] https://doi.org/10.3390/en16020818

**Low carrier ratio, delay, sensorless**

- [S34] M. Wang et al., "Decoupled Discrete Current Control for AC Drives at Low Sampling-to-Fundamental Frequency Ratios," IEEE J. Emerging and Selected Topics in Power Electronics, 2022. [abstract] https://doi.org/10.1109/jestpe.2022.3179184
- [S35] M. Wang et al., "2-DOF Decoupled Discrete Current Control for AC Drives at Low Sampling-to-Fundamental Frequency Ratios," IEEE Trans. Transportation Electrification, 2022. [abstract] https://doi.org/10.1109/tte.2022.3210909
- [S36] Z. Sun et al., "Discrete Current Controller with Accurate Digital Delay Compensation Based on Active Damping for PMSM Drives," IEEE Trans. Transportation Electrification, 2026. [abstract] https://doi.org/10.1109/tte.2026.3722504
- [S37] Z. Zhang et al., "A Deadbeat PI Controller With Modified Feedforward for PMSM Under Low Carrier Ratio," IEEE Access, 2021. [abstract] https://doi.org/10.1109/access.2021.3075486
- [S38] E. Pozo Fortunić, M. C. Yildirim, S. Haddadin, "From Continuous Design to Delay-Aware Discrete Synthesis: Guaranteed High-Bandwidth Joint Control for PMSM Drives," arXiv:2608.14937, 2026. [body: abstract, model and synthesis sections; no result figures extracted] https://arxiv.org/abs/2608.14937
- [S39] Z. Lin, S. Jin, H. Wang, F. Zhang, "Robust sensorless control of high speed PMSM drives under low carrier ratios and parameter uncertainties," Scientific Reports, 2026. [body] https://doi.org/10.1038/s41598-026-41212-z
- [S40] M. Su et al., "Discrete-Time Nonlinear Flux Observer for Sensorless SPMSM Drives With Low Carrier Ratios," IEEE Trans. Power Electronics, 2026. [abstract] https://doi.org/10.1109/tpel.2026.3687870
- [S41] C. J. Volpato Filho et al., "Observers for High-Speed Sensorless PMSM Drives: Design Methods, Tuning Challenges and Future Trends," IEEE Access, 2021. [abstract] https://doi.org/10.1109/access.2021.3072360
- [S42] F. Zhou et al., "Equivalent Flux Compensation for SPMSM Sensorless Control under Parameter Mismatch," arXiv:2609.29313, 2026. [abstract] https://arxiv.org/abs/2609.29313
- [S43] F. Zhou et al., "Parameter-Robust Sensorless Control of IPMSM Drives With Adaptive Flux Observer," arXiv:2609.39840, 2026. [abstract] https://arxiv.org/abs/2609.39840
- [S44] F. Zhou et al., "Temporal Regression-Based Model-Free Sensorless Control of Permanent Magnet Synchronous Motor," arXiv:2609.29290, 2026. [abstract] https://arxiv.org/abs/2609.29290
- [S61] N. Tosun et al., "High-Performance Sensorless Control for High-Speed PMSM with Current Source Inverters," arXiv:2609.25878, 2026. [body] https://arxiv.org/abs/2609.25878

**Learning-based control**

- [S51] G. Book et al., "Transferring Online Reinforcement Learning for Electric Motor Control From Simulation to Real-World Experiments," IEEE Open J. Power Electronics, 2021. [abstract] https://doi.org/10.1109/ojpel.2021.3065877
- [S52] M. Schenke, O. Wallscheid, "A Deep Q-Learning Direct Torque Controller for Permanent Magnet Synchronous Motors," IEEE Open J. Industrial Electronics Society, 2021. [abstract] https://doi.org/10.1109/ojies.2021.3075521
- [S53] M. Schenke, B. Haucke-Korber, O. Wallscheid, "Finite-Set Direct Torque Control via Edge-Computing-Assisted Safe Reinforcement Learning for a Permanent-Magnet Synchronous Motor," IEEE Trans. Power Electronics, 2023. [abstract] https://doi.org/10.1109/tpel.2023.3303651
- [S54] D. Jakobeit, M. Schenke, O. Wallscheid, "Meta-Reinforcement-Learning-Based Current Control of Permanent Magnet Synchronous Motor Drives for a Wide Range of Power Classes," IEEE Trans. Power Electronics, 2023. [abstract] https://doi.org/10.1109/tpel.2023.3256424
- [S55] S. Zhang, O. Wallscheid, M. Porrmann, "Machine Learning for the Control and Monitoring of Electric Machine Drives: Advances and Trends," arXiv:2110.05403, 2021. [abstract] https://arxiv.org/abs/2110.05403

**Other rows**

- [S58] A. G. Yepes et al., "Optimization of Current Lookup Tables for Minimum Stator Copper Loss and Torque Ripple in the Full Torque-Speed Range for a Six-Phase PMSM With Nonsinusoidal Back-EMF," arXiv:2607.24395, 2026. [abstract] https://arxiv.org/abs/2607.24395
- [S59] A. Perera, R. Nilsen, "Recursive Prediction Error Gradient-Based Algorithms and Framework to Identify PMSM Parameters Online," arXiv:2209.05094, 2022. [abstract] https://arxiv.org/abs/2209.05094
- [S60] G. V. Dissanayake, S. S. Kuruppu, "Extremum Seeking Control Based Adaptive Compensation of Position Sensor Harmonics in PMSM Drives," arXiv:2606.07906, 2026. [abstract] https://arxiv.org/abs/2606.07906
- [S62] S. Gick et al., "Simple Hybrid Integration of SiC MOSFETs in a B6 Converter for Enhanced Partial Load Efficiency," IEEE Open J. Power Electronics, 2025. [abstract] https://doi.org/10.1109/ojpel.2025.3589026

**Accuracy and validation references**

- [S63] A semiconductor maker's design guide for a 48 V, 16 A small three-phase GaN inverter reference design. [body]
- [S64] A semiconductor maker's design guide for a 48 V, 10 A high-frequency three-phase GaN inverter reference design. [body]
- [S65] T. A. Burress et al., evaluation of a 2010 production hybrid vehicle's drive system, national-laboratory technical report ORNL/TM-2010/253, 2011. [body: list of figures and test scope; contour values not extracted]
- [S66] A semiconductor maker's application note on designing a vacuum-cleaner motor drive inverter with its GaN evaluation board. [body]
- [S67] J. Zheng et al., "Accurate Time-segmented Loss Model for SiC MOSFETs in Electro-thermal Multi-Rate Simulation," arXiv:2311.07029, 2023. [body] https://arxiv.org/abs/2311.07029
- [S68] F. Chen, S. Lee, T. M. Jahns, B. Sarlioglu, "A High-Accuracy Power Loss Model of SiC MOSFETs in Current Source Inverter Considering Current Commutation and Parasitic Parameters," conference paper, open copy at OSTI. [body] https://www.osti.gov/servlets/purl/2535656
- [S69] Bianchini, Vogni, Chini et al., "Switching Loss Model for SiC MOSFETs Based on Datasheet Parameters Enabling Virtual Junction Temperature Estimation," Sensors, 2025. [body] https://pmc.ncbi.nlm.nih.gov/articles/PMC12197205/
- [S70] A semiconductor maker's application note on the effect of stray inductance on the switching of its SiC and IGBT power modules. [body]
- [S71] D. Zięba, J. Rąbkowski, "Problems related to the correct determination of switching power losses in high-speed SiC MOSFET power modules," Bulletin of the Polish Academy of Sciences: Technical Sciences, 2022. [abstract] https://doi.org/10.24425/bpasts.2022.140695
- [S72] D. P. Nayak, S. K. Pramanick, "Implementation of an Electro-Thermal Model for Junction Temperature Estimation in a SiC MOSFET Based DC/DC Converter," CPSS Trans. Power Electronics and Applications, 2023. [body] https://file.cpss.org.cn/uploads/tpea/v8n12023/10.24295CPSSTPEA.2023.00005.pdf
- [S73] H. Su et al., "Modeling and Evaluation of SiC Inverters for EV Applications," Energies (archived copy LAPSE-2023.9127). [body] https://psecommunity.org/wp-content/plugins/wpor/includes/file/2302/LAPSE-2023.9127-1v1.pdf
- [S74] A. H. Mohamed, H. Vansompel, P. Sergeant, "Electrothermal Design of a Discrete GaN-Based Converter for Integrated Modular Motor Drives," IEEE J. Emerging and Selected Topics in Power Electronics, 2021. [body] https://doi.org/10.1109/jestpe.2021.3058107 (open copy: https://biblio.ugent.be/publication/8693293/file/8698593.pdf)
- [S75] A semiconductor maker's design guide for a 48 V, 85 A small three-phase MOSFET inverter reference design. [body]
- [S76] A semiconductor maker's user guide for a 300 kW SiC three-phase inverter reference design, 2024. [body]
- [S77] The quick-start guide of the GaN evaluation board of [S66]. [body]
- [S79] P. Xin, P. Liu, P. Qu, "High-Performance Speed Control of PMSM Using Fuzzy Sliding Mode with Load Torque Observer," Applied Sciences 15(13):7053, 2025. [abstract] https://doi.org/10.3390/app15137053 (simulation: ADRC dips 3.7 r/min and recovers in about 0.02 s, PID with a load observer 4.1 r/min and 0.03 s; against a PI that has its own load observer the observer's lead is a few tens of percent, not the factors reported against a plain PI)
- [S80] T. Zhou, F. Chen, X. He, L. Li, Z. Wang, "PMSM Speed Regulation Using an Inverse Hyperbolic Sine Function-Based Active Disturbance Rejection Control Strategy," Electronics 15(22):5383, 2026. [abstract] https://doi.org/10.3390/electronics15225383 (experiment under an 8 N·m load: speed drop 8.4% at 100 r/min against the PI's 41.1%)
- [S83] G. Ellis, R. D. Lorenz, "Resonant load control methods for industrial servo drives," IEEE Industry Applications Conference, 2000. [abstract] https://doi.org/10.1109/IAS.2000.882073 (a compliant coupling between motor and load limits the servo's gain; filters in the loop, a notch among them, are the usual cure)
- [S84] N. C. Singer, W. P. Seering, "Preshaping command inputs to reduce system vibration," Journal of Dynamic Systems, Measurement, and Control 112(1), 1990. [abstract] https://doi.org/10.1115/1.2894142 (commands shaped so a move ends without residual vibration, at a move-time penalty of about one period of the first mode; robust to parameter uncertainty, open or closed loop; 25 times less endpoint vibration on a manipulator simulator)
- [S82] C. Zhang, Y. Yang, Y. Gong, Y. Guo, H. Song, J. Zhang, "Adaptive periodic speed fluctuation suppression for permanent magnet compressor drives," Sensors 25(7), 2074, 2025. [abstract] https://doi.org/10.3390/s25072074 (a compressor's load torque, periodic in the shaft's angle, learned and given ahead of the speed loop of a drive with no rotor sensor)
- [S81] J.-M. Kim, S.-K. Sul, "Speed control of interior permanent magnet synchronous motor drive for the flux weakening operation," IEEE Trans. Industry Applications 33(1), 1997. [abstract] https://doi.org/10.1109/28.567075 (field weakening closed on the voltage the current regulator asks, not on the motor's figures, so that it holds under parameter error and a varying DC link)
- [S78] S. Hanke, O. Wallscheid, J. Böcker, "Data Set Description: Identifying the Physics Behind an Electric Motor: Data-Driven Learning of the Electrical Behavior (Part II)," arXiv:2003.06268, 2020. [body] https://arxiv.org/abs/2003.06268 (the data set is linked from the paper)
