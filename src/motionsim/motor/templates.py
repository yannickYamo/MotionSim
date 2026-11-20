"""A motor file to start from for each kind of motor, describing a made-up motor of that kind."""

TEMPLATES = {
    "pmsm": """\
# Permanent-magnet synchronous motor (also a brushless motor run with sinusoidal
# currents and field-oriented control). The values below describe a made-up 48 V
# robot-joint motor. Replace them with your motor's.
type: pmsm
name: my motor
magnets: surface      # surface: magnets on the rotor surface (Ld = Lq). Inner or outer rotor alike
                      # inset: magnets set into the surface (Lq a little above Ld)
                      # interior: magnets buried in the rotor (Lq > Ld, adds reluctance torque)
pole_pairs: 7         # number of magnet poles divided by 2

# Back-EMF: give exactly one of the four.
kv: 100               # speed constant, rpm per volt (peak line-to-line)
# ke: 10.0            # back-EMF constant, peak line-to-line volts per 1000 rpm
# flux_linkage: 0.0079  # permanent-magnet flux linkage, Wb peak
# kt: 0.117           # torque constant, N·m per A rms of phase current (= 11.7 / kv)

# Inductance: one value for a surface-magnet motor, two for interior magnets.
l: 0.00012            # phase inductance, H (line-to-line inductance divided by 2)
# ld: 0.00010         # d-axis inductance, H
# lq: 0.00018         # q-axis inductance, H

rs: 0.045             # phase resistance, ohm (line-to-line resistance divided by 2)
i_max: 40             # optional: winding current limit, A rms
""",
    "synrm": """\
# Synchronous reluctance motor: a shaped steel rotor, no magnets. A made-up 400 V
# class motor of about 1.5 kW.
type: synrm
name: my motor
pole_pairs: 2
ld: 0.22              # inductance along the rotor's easy axis, H
lq: 0.045             # inductance across it, H (must be smaller than ld)
rs: 2.2               # phase resistance, ohm
i_max: 6              # optional: winding current limit, A rms
""",
    "induction": """\
# Induction motor. Per-phase equivalent-circuit values, rotor referred to the
# stator. A made-up 400 V class motor of about 1.5 kW.
type: induction
name: my motor
pole_pairs: 2         # 2 pole pairs: about 1500 rpm at 50 Hz
rs: 4.0               # stator resistance, ohm
rr: 3.5               # rotor resistance, ohm
lm: 0.32              # magnetising inductance, H
lls: 0.015            # stator leakage inductance, H
llr: 0.015            # rotor leakage inductance, H
i_magnetising: 2.4    # magnetising current at rated flux, A peak (about the no-load current)
i_max: 3.6            # optional: winding current limit, A rms
""",
    "bldc": """\
# Brushless DC motor driven with block (six-step, trapezoidal) commutation.
# A made-up 48 V robot-joint motor.
type: bldc
name: my motor
pole_pairs: 7
kt: 0.09              # torque constant, N·m per A  (= 9.55 / Kv in rpm per volt)
# kv: 106             # or the speed constant in rpm per volt in its place
r: 0.08               # phase-to-phase resistance, ohm
l: 0.00012            # optional: phase-to-phase inductance, H. Sets the current ripple
i_max: 40             # optional: winding current limit, A
""",
    "dc": """\
# Brushed DC motor on an H-bridge. A made-up 24 V gearmotor (values at the motor shaft).
type: dc
name: my motor
kt: 0.05              # torque constant, N·m per A
# kv: 191             # or the speed constant in rpm per volt in its place (kt = 9.55 / kv)
r: 0.4                # armature resistance, ohm
l: 0.0006             # optional: armature inductance, H. Sets the current ripple
i_max: 20             # optional: current limit, A
# drive: unipolar     # unipolar (default): one leg chops, lower loss
                      # bipolar: both legs switch every period
""",
    "dc_series": """\
# Brushed DC motor with a series field (power tools, starters, universal motors).
# A made-up 24 V motor.
type: dc_series
name: my motor
k: 0.004              # torque per current squared, N·m per A^2
r: 0.25               # armature plus field resistance, ohm
i_max: 30             # optional: current limit, A
""",
    "stepper": """\
# Bipolar stepper on two H-bridges with microstepping. A made-up NEMA 23 size motor.
type: stepper
name: my motor
steps_per_rev: 200    # 200 for a 1.8 degree motor
i_phase: 2.8          # phase current the driver is set to, A peak
r: 0.9                # phase resistance, ohm
l: 0.0025             # phase inductance, H
holding_torque: 1.2   # N·m at i_phase
""",
}
