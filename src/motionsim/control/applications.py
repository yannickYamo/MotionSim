"""More schemes a design can start from, by application and by method, each wired from the
same blocks and tuned by a stated rule (the rule travels with the value, as in presets.py):

- by application: a joint servo along an S-curve, traction torque control with the clamp
  placed online for least switching loss, a high-speed drive with no encoder at a low
  carrier ratio (three observers), and the same high-speed drive with an encoder and the
  discrete-time current regulator;
- by method: predictive control with the commutation charged by its switching energy,
  deadbeat current control, direct torque control, a switching frequency held to a ripple
  limit, a current reference of least total loss, dead-time compensation, and active
  thermal control.

Where a rule is this tool's own choice and not a published one, its text says so.
"""

from __future__ import annotations

import math
from dataclasses import replace

from motionsim.control.actuation import ripple_shape
from motionsim.control.blocks import BlockSpec
from motionsim.control.presets import (
    BUILDERS,
    MPC_RATE,
    Design,
    foc_high_speed,
    foc_servo,
    foc_torque,
    mpc_torque,
)
from motionsim.control.scheme import Scheme
from motionsim.control.sensing import MIN_LOSS

CURRENTS = {"i_a": "sample.i_a", "i_b": "sample.i_b", "i_c": "sample.i_c"}
FROM_FREQUENCY = {
    "kind": "duties",
    "wires": ["frequency.d_a", "frequency.d_b", "frequency.d_c"],
    "period": "frequency.period",
}


def _changed(scheme: Scheme, name: str, **changes) -> Scheme:
    """The scheme with one block's fields replaced."""
    return replace(scheme, blocks=[replace(b, **changes) if b.name == name else b for b in scheme.blocks])


def _with(scheme: Scheme, name: str, params: dict, sources: dict, inputs: dict | None = None) -> Scheme:
    """The scheme with parameters (and inputs) added to one block."""
    block = next(b for b in scheme.blocks if b.name == name)
    return _changed(
        scheme,
        name,
        params=block.params | params,
        sources=block.sources | sources,
        inputs=block.inputs | (inputs or {}),
    )


def _named(scheme: Scheme, ident: str, label: str, about: str) -> Scheme:
    return replace(scheme, id=ident, label=label, about=about)


def design_ripple(design: Design) -> float:
    """A peak, the largest ripple a carrier period makes over a turn of the output at the
    design point and the design's switching frequency, under space-vector modulation."""
    from motionsim.control.scenario import settled

    try:
        m = settled(design, design.rpm, design.torque)["modulation_index"]
    except Exception:
        m = 0.5
    worst = 0.0
    for k in range(60):
        angle = k * math.pi / 180.0
        u = [m * math.cos(angle - n * 2.0 * math.pi / 3.0) for n in range(3)]
        shift = -0.5 * (max(u) + min(u))
        worst = max(worst, ripple_shape(*(0.5 * (1.0 + x + shift) for x in u))[0])
    return worst * design.v_dc / (design.f_sw * min(design.ld, design.lq))


def mpc_step(design: Design) -> float:
    """A, the current the whole DC voltage moves through the winding in one sampling period of
    the predictive scheme: the scale its commutation weight is read against."""
    return design.v_dc / (MPC_RATE * design.f_sw * min(design.ld, design.lq))


def servo_joint(design: Design) -> Scheme:
    scheme = _with(
        foc_servo(design),
        "speed_ref",
        {"shape": "s-curve"},
        {"shape": "an S-curve: the acceleration itself comes up at a limited rate, so the joint is not jerked"},
    )
    return _named(
        scheme,
        "servo_joint",
        "Joint servo: speed and current control along an S-curve",
        "The cascade of a speed and a current regulator with the speed reference taken along an S-curve, so "
        "that neither the acceleration nor the torque steps: what a robot joint is moved with. No position "
        "loop is closed here: the speed reference is what a position loop or a trajectory would give.",
    )


# The observer five times faster than the loop: the loop's crossover is matched to the PI's
# (adrc_matched), a decade below the current loop, so the observer stays under the current
# loop and the torque it counts on is the one the current loop has made.
ADRC_OBSERVER = 5.0


def _crossover(num: list[float], den: list[float], ts: float, b0: float) -> float:
    """rad/s where |C(z)·P(z)| falls through one, P(z) = Ts·b0/(z − 1) the sampled shaft."""
    import numpy as np

    w = np.geomspace(1e-2, math.pi / ts, 4000)
    z = np.exp(1j * w * ts)
    gain = np.abs(np.polyval(num, z) / np.polyval(den, z) * ts * b0 / (z - 1.0))
    below = np.nonzero(gain < 1.0)[0]
    return float(w[below[0]]) if below.size else math.pi / ts


def adrc_matched(kp: float, ki: float, inertia: float, ts: float, observer: float) -> float:
    """Hz, the ADRC bandwidth whose loop crosses over where the PI's does on the same shaft:
    the two then answer a speed step as fast, and are compared on what else they do."""
    from motionsim.control.regulators import eso_gains

    target = _crossover([kp + ki * ts, -kp], [1.0, -1.0], ts, 1.0 / inertia)

    def crossing(hz: float) -> float:
        wc, l1, l2, b0 = eso_gains(hz, observer, inertia, ts)
        k0, k1 = wc / b0, 1.0 / b0
        m11, m12, m21, m22 = 1.0 - ts * b0 * k0 - l1, ts - ts * b0 * k1, -l2, 1.0
        num = [k0 * l1 + k1 * l2, -m22 * k0 * l1 + m12 * k0 * l2 + m21 * k1 * l1 - m11 * k1 * l2]
        return _crossover(num, [1.0, -(m11 + m22), m11 * m22 - m12 * m21], ts, b0)

    low, high = target / (2.0 * math.pi) / 50.0, target / (2.0 * math.pi)
    for _ in range(60):
        mid = math.sqrt(low * high)
        low, high = (mid, high) if crossing(mid) < target else (low, mid)
    return math.sqrt(low * high)


SENSINGS = ("sensor", "three", "two", "single")
SHUNT_INPUTS = (
    "window_a",
    "window_b",
    "window_c",
    "i_dc_1",
    "vector_1",
    "span_1",
    "i_dc_2",
    "vector_2",
    "span_2",
    "skip",
)


def shunted(scheme: Scheme, shunts: str, window: float = 2e-6) -> Scheme:
    """The scheme with its currents read through shunts in the stage in place of a current
    sensor: three or two under the low switches, or one in the DC link. The same gains, the
    same blocks otherwise; "sensor" leaves it as it is."""
    if shunts == "sensor":
        return scheme
    blocks = []
    for b in scheme.blocks:
        if b.kind == "current_sampling":
            inputs = {**{k: b.inputs[k] for k in ("i_a", "i_b", "i_c")}, **{k: f"inverter.{k}" for k in SHUNT_INPUTS}}
            said = {
                "shunts": "as the drive is built",
                "window": "settling and sampling, as is usual for a shunt amplifier",
            }
            b = replace(
                b, kind="shunt_sampling", inputs=inputs, params={"shunts": shunts, "window": window}, sources=said
            )
        blocks.append(b)
    return replace(scheme, blocks=blocks)


def servo_notch(design: Design) -> Scheme:
    """The joint servo with a notch on its torque, at the shaft's resonance as given."""
    scheme = servo_joint(design)
    notch = BlockSpec(
        "notch",
        "torque_notch",
        {"torque": "speed.torque"},
        {"frequency": 0.0, "width": 0.5, "depth": 0.05},
        {
            "frequency": "the shaft's resonance, where the request gives one (plant.coupling.resonance_hz); "
            "none here, so the torque passes",
            "width": "half: an octave either side taken down, so a resonance a little off its figure is still met",
            "depth": "a twentieth left at the centre (−26 dB)",
        },
    )
    blocks = []
    for b in scheme.blocks:
        if any(w == "speed.torque" for w in b.inputs.values()):
            b = replace(b, inputs={k: ("notch.torque" if w == "speed.torque" else w) for k, w in b.inputs.items()})
        blocks.append(b)
        if b.name == "speed":
            blocks.append(notch)
    return _named(
        replace(scheme, blocks=blocks),
        "servo_notch",
        "Joint servo with a notch at the shaft's resonance",
        "The joint servo with the frequency its shaft swings at taken out of the torque it asks: where the gear "
        "or coupling between motor and load twists, the loop no longer rings the swing. The notch is set from "
        "the resonance the request gives.",
    )


def servo_shaped(design: Design) -> Scheme:
    """The joint servo with its move shaped so that it leaves a load that swings still."""
    scheme = servo_joint(design)
    shaper = BlockSpec(
        "move_shaper",
        "input_shaper",
        {"ref": "speed_ref.ref"},
        {"shape": "zvd", "frequency": 0.0, "damping": 0.0},
        {
            "shape": "ZVD: three parts, a whole period of the swing late, robust to a mode a sixth off its figure",
            "frequency": "the least damped mode of the speed loop with its shaft, where the shaft twists; "
            "none here, so the move passes",
            "damping": "that mode's own",
        },
    )
    blocks = []
    for b in scheme.blocks:
        if b.inputs.get("ref") == "speed_ref.ref" and b.name != "move_shaper":
            b = replace(b, inputs={**b.inputs, "ref": "move_shaper.ref"})
        blocks.append(b)
        if b.name == "speed_ref":
            blocks.append(shaper)
    return _named(
        replace(scheme, blocks=blocks),
        "servo_shaped",
        "Joint servo whose moves leave the load still: input shaping",
        "The joint servo with each move given in three parts, timed to the swing of the load on its shaft, so "
        "that the swing the first part starts the last stops: the load arrives still, a period of the swing "
        "later. The loop itself is unchanged. The swing is the speed loop's own least damped mode with the "
        "shaft, worked out from the gains and the shaft the request gives.",
    )


def servo_adrc(design: Design) -> Scheme:
    scheme = servo_joint(design)
    pi = next(b for b in scheme.blocks if b.name == "speed")
    ts = 1.0 / design.f_sw
    hz = adrc_matched(pi.params["kp"], pi.params["ki"], design.shaft_inertia, ts, ADRC_OBSERVER)
    known = "" if design.inertia else " The inertia is not known: one the torque limit runs up in 0.25 s is taken."
    adrc = replace(
        pi,
        kind="speed_adrc",
        params={
            "bandwidth": hz,
            "observer": ADRC_OBSERVER,
            "inertia": design.shaft_inertia,
            "limit": pi.params["limit"],
        },
        sources={
            "bandwidth": "set so that the loop crosses over where the PI's does on the same shaft, a decade below "
            "the current loop: the two answer a speed step as fast, and are compared on the rest",
            "observer": f"{ADRC_OBSERVER:g} times the loop's: half the current loop's, so the torque it counts on "
            "has been made",
            "inertia": f"the shaft's inertia, {design.shaft_inertia:.3g} kg·m²." + known,
            "limit": pi.sources.get("limit", "the torque of the drive's current limit"),
        },
    )
    blocks = [adrc if b.name == "speed" else b for b in scheme.blocks]
    return _named(
        replace(scheme, blocks=blocks),
        "servo_adrc",
        "Joint servo that rejects the load: speed by disturbance observer",
        "The joint servo with its speed PI replaced by an observer of everything that is not the torque asked "
        "(the load, friction, an inertia other than the one assumed), which the torque cancels: a load step "
        "is rejected at the observer's rate, not the integral's, at the same bandwidth as the PI.",
    )


def torque_fw_feedback(design: Design) -> Scheme:
    from motionsim.control.presets import bandwidth

    scheme = foc_torque(design)
    wc = bandwidth(1.0 / design.f_sw, True)[0]
    loop = BlockSpec(
        "fw",
        "voltage_feedback_fw",
        {
            "i_d": "current_ref.i_d",
            "i_q": "current_ref.i_q",
            "v_d": "current.v_d",
            "v_q": "current.v_q",
            "v_dc": "plant.v_dc",
            "omega_e": "position.omega_e",
        },
        {"headroom": 0.95, "bandwidth": wc / 10.0 / (2.0 * math.pi), "i_limit": design.limit},
        {
            "headroom": "five percent of the voltage kept for the current regulator to move the current with",
            "bandwidth": "a decade below the current loop, as the speed loop is",
            "i_limit": "the motor's current limit" if design.i_limit else "1.5 times the design current",
        },
    )
    blocks = []
    for b in scheme.blocks:
        if b.name == "current":
            blocks.append(loop)
            b = replace(b, inputs=b.inputs | {"id_ref": "fw.i_d_out", "iq_ref": "fw.i_q_out"})
        blocks.append(b)
    return _named(
        replace(scheme, blocks=blocks),
        "torque_fw_feedback",
        "Torque control that weakens the field by the voltage it measures",
        "The torque scheme with least current and field weakening, and a loop on the voltage the current "
        "regulator asks that takes the d-axis current further negative where the model's field weakening "
        "falls short: the motor's flux higher than the controller holds, its iron saturated, its inductance "
        "not the one assumed.",
    )


def compressor_smooth(design: Design) -> Scheme:
    """The compressor's sensorless scheme with the torque of each turn learned and given ahead."""
    scheme = _sensorless(design, "emf")
    speed = next(b for b in scheme.blocks if b.name == "speed")
    # Read from the shaft, the load's torque is in step with the angle whatever the speed loop's
    # lag: three harmonics hold most of a single rotor's gas torque, each learned only while the
    # observer's phase-locked loop follows it (half its bandwidth: at the bandwidth itself the
    # harmonic is read late enough that learning it runs away).
    f_turn = max(abs(design.rpm) / 60.0, 1e-6)
    harmonics = 3
    observer = next(b for b in scheme.blocks if b.name == "observer")
    reach = 0.5 * observer.params["pll_bandwidth"]
    block = BlockSpec(
        "periodic",
        "periodic_compensation",
        {"torque": "speed.torque", "speed": speed.inputs["speed"]},
        {
            "harmonics": float(harmonics),
            "gain": 0.2,
            "inertia": design.shaft_inertia,
            "reach": reach,
            "floor": 0.1 * abs(design.omega),
        },
        {
            "harmonics": f"the first three harmonics of the turn ({f_turn:.3g} Hz at the design speed): most of a "
            "single rotor's gas torque",
            "gain": "a fifth of what a turn shows learned in that turn: five turns to most of it",
            "inertia": "the shaft's inertia, which the load's torque is read with",
            "reach": f"half the observer's phase-locked loop bandwidth ({observer.params['pll_bandwidth']:.3g} Hz): "
            "a harmonic above it is read too late to learn",
            "floor": "a tenth of the design speed: below it the turn is too slow to learn from",
        },
    )
    blocks = []
    for b in scheme.blocks:
        if b.name == "speed":
            blocks += [b, block]
            continue
        if any(w == "speed.torque" for w in b.inputs.values()):
            b = replace(
                b, inputs={k: ("periodic.torque_out" if w == "speed.torque" else w) for k, w in b.inputs.items()}
            )
        blocks.append(b)
    return _named(
        replace(scheme, blocks=blocks),
        "compressor_smooth",
        "Compressor drive that learns the torque of each turn",
        "The compressor's drive with no rotor sensor, with the torque its load asks at each angle of the turn "
        "learned turn by turn and given ahead of the speed loop: the shaft no longer slows and speeds up "
        "within each turn, which is what shakes a compressor and its pipes.",
    )


def traction_dpwm(design: Design) -> Scheme:
    scheme = _with(
        foc_torque(design),
        "modulator",
        {"pwm": MIN_LOSS, "threshold": 0.5, "advance": 1.5},
        {
            "advance": "the delay around the loop in sampling periods, as the angle is advanced: the clamp is "
            "chosen by the currents as they will stand when it applies",
            "pwm": "the leg carrying the most current is held to a rail and does not switch: half the switching "
            "loss of a continuous method while the current's peak lies within 30° of the voltage's "
            "(Hava, Kerkman and Lipo, 1998)",
            "threshold": "space-vector below a modulation index of 0.5, where a clamp costs more ripple than it "
            "saves: the rule is from the same analysis, the figure of 0.5 is this tool's choice",
        },
        CURRENTS | {"omega_e": "position.omega_e"},
    )
    return _named(
        scheme,
        "traction_dpwm",
        "Traction torque control with the clamp placed for least switching loss",
        "Torque control on the least-current line and into field weakening, with a discontinuous modulation "
        "whose clamp follows the current's peak instead of the voltage's: a third fewer commutations, and "
        "those left out are the ones at the largest current.",
    )


def _regulator(design: Design, scheme: Scheme) -> Scheme:
    """The scheme's PI current regulator replaced by the discrete-time one, and the angle's
    advance set as that regulator's model has it."""
    delay = bool(scheme.timing["delay"])
    current = next(b for b in scheme.blocks if b.name == "current")
    scheme = _changed(
        scheme,
        "current",
        kind="current_discrete_dq",
        params={"gain": 0.25, "voltage_share": 1.0},
        sources={
            "gain": "K = 0.25: both poles of z² − z + K at z = 0.5, the fastest answer with no overshoot, "
            "whatever the speed (direct discrete design on the winding's exact model with the delay in it, "
            "after Kim, Degner, Guerrero, Briz and Lorenz, 2010)"
        },
        inputs=dict(current.inputs),
    )
    return _with(
        scheme,
        "inverse_park",
        {"advance": 2.0 if delay else 1.0},
        {
            "advance": "the angle the rotor will have at the end of the period the voltage is held through: the "
            "regulator's model of the winding is exact for that advance"
        },
    )


def discrete_high_speed(design: Design) -> Scheme:
    return _named(
        _regulator(design, foc_high_speed(design)),
        "discrete_high_speed",
        "Speed control with a discrete-time current regulator (very low carrier ratio)",
        "The high-speed cascade with its current regulator designed at the sampling rate on the exact model "
        "of the winding and the delay: the loop's poles stay where they were put down to a handful of "
        "switching periods in a turn of the output, where the usual PI with fed-forward coupling oscillates.",
    )


def discrete_torque(design: Design) -> Scheme:
    return _named(
        _regulator(design, foc_torque(design)),
        "discrete_torque",
        "Torque control with a discrete-time current regulator",
        "Torque control with the current regulator designed at the sampling rate on the exact model of the "
        "winding and the delay, in place of the PI with fed-forward coupling: the loop's poles stay where "
        "they were put whatever the speed.",
    )


def mpc_loss_weighted(design: Design) -> Scheme:
    scheme = _with(
        mpc_torque(design),
        "predictive",
        {"weighting": "loss", "weight": 0.375 * mpc_step(design)},
        {
            "weighting": "a commutation is charged by the switching energy of that leg at its current, from "
            "the device's own figures: this tool's suggestion, not a published rule",
            "weight": "three eighths of the current the DC voltage moves in one sampling period: past half of "
            "it the controller stops following the reference. This tool's choice, to be swept",
        },
    )
    return _named(
        scheme,
        "mpc_loss_weighted",
        "Predictive torque control with commutations charged by their switching energy",
        "The finite-control-set controller with the cost of a commutation set to what it loses: the leg that "
        "carries little current is cheap to move, the one at the current's peak is dear. It moves the "
        "commutations to where they cost least instead of only making fewer of them.",
    )


def deadbeat_torque(design: Design) -> Scheme:
    scheme = foc_torque(design)
    current = next(b for b in scheme.blocks if b.name == "current")
    scheme = _changed(
        scheme,
        "current",
        kind="deadbeat_dq",
        params={"delay_compensation": True, "gain": 1.0, "voltage_share": 1.0},
        sources={
            "gain": "the whole step each period: the reference is reached two samples after it is asked, "
            "with the model right",
            "delay_compensation": "the current is predicted to the instant the voltage takes effect",
        },
        inputs=dict(current.inputs),
    )
    return _named(
        scheme,
        "deadbeat_torque",
        "Deadbeat predictive torque control (with a modulator)",
        "The PI current regulator replaced by one that asks, each period, the voltage the motor's model says "
        "will put the current on its reference: the fastest a modulated drive can answer, at a fixed "
        "switching frequency, and as good as the model's inductance is.",
    )


DTC_BAND = 0.05  # of the design torque, either side of the reference
DTC_FLOOR = 0.002  # of the torque limit, where the design asks next to no torque


def dtc_band(design: Design) -> tuple[float, str]:
    """N·m either side of the reference that direct torque control holds the torque within,
    and the rule in words. Relative to the torque the design asks, not to the drive's limit:
    a band of 5% of a limit ten times the design torque is half the design torque. And never
    under half of what the torque moves in one sampling period at the design speed: a band
    narrower than that is crossed whole in one period, the turn at its far side comes late
    every time, and the mean leaves the reference."""
    ts = 1.0 / (MPC_RATE * design.f_sw)
    per_volt = 1.5 * design.pole_pairs * design.psi * ts / design.lq  # N·m a volt of q-axis voltage, a period
    back = abs(design.omega) * design.pole_pairs * design.psi
    down, up = per_volt * back, per_volt * max(2.0 / 3.0 * design.v_dc - back, 0.0)
    step = max(down, up)
    by_design, by_step, by_limit = DTC_BAND * abs(design.torque), 0.5 * step, DTC_FLOOR * design.torque_limit
    band = max(by_design, by_step, by_limit)
    rule = (
        f"{100 * DTC_BAND:g} % of the design torque either side of the reference (the usual starting point for the "
        "scheme of Takahashi and Noguchi, 1986, taken of the torque the design asks and not of the drive's "
        "limit), and no less than half of what the torque moves in one sampling period at the design speed "
        f"(the zero state lets it fall {down:.3g} N·m and the full DC voltage raises it {up:.3g} N·m a period "
        f"here) nor than {100 * DTC_FLOOR:g} % of the torque limit: this tool's choice. "
    )
    if band == by_design:
        return band, rule + "The design torque decides here."
    if band == by_step:
        return band, rule + "The sampling period decides here: a narrower band would be crossed in one period."
    return band, rule + "The torque limit decides here: the design asks next to no torque."


def dtc_torque(design: Design) -> Scheme:
    scheme = mpc_torque(design)
    wired = next(b for b in scheme.blocks if b.name == "predictive").inputs
    flux = math.hypot(design.psi, design.lq * design.i_design)
    band, band_rule = dtc_band(design)
    scheme = _changed(
        scheme,
        "predictive",
        kind="dtc",
        params={"torque_band": band, "flux_band": 0.02 * flux},
        sources={
            "torque_band": band_rule,
            "flux_band": "2% of the stator flux at the design point either side",
        },
        inputs=dict(wired),
    )
    return _named(
        scheme,
        "dtc_torque",
        "Direct torque control (hysteresis bands, no modulator)",
        "The torque and the stator flux held inside two bands by a table of the legs' states: no current "
        f"regulator, no modulator, sampled at {MPC_RATE:g} times the design's switching frequency. Its "
        "switching frequency follows from the bands.",
    )


def vsf_torque(design: Design) -> Scheme:
    scheme = foc_torque(design)
    scheme = replace(
        scheme,
        blocks=[
            *scheme.blocks,
            BlockSpec(
                "frequency",
                "variable_frequency",
                {
                    "d_a": "modulator.d_a",
                    "d_b": "modulator.d_b",
                    "d_c": "modulator.d_c",
                    "v_dc": "plant.v_dc",
                    "omega_e": "position.omega_e",
                },
                {
                    "mode": "peak",
                    "ripple_limit": design_ripple(design),
                    "f_min": 0.5 * design.f_sw,
                    "f_max": 2.0 * design.f_sw,
                },
                {
                    "mode": "the peak of the ripple is held, period by period (Jiang and Wang, 2013)",
                    "ripple_limit": "the largest peak ripple the design's own fixed frequency makes over a turn "
                    "of the output at the design point: no period ripples more than the fixed drive's worst",
                    "f_min": "half the design's switching frequency",
                    "f_max": "twice the design's switching frequency",
                },
            ),
        ],
        actuation=FROM_FREQUENCY,
    )
    return _named(
        scheme,
        "vsf_torque",
        "Torque control with the switching frequency held to a ripple limit",
        "The carrier period is stretched, instant by instant, as far as the ripple the coming duty cycles "
        "will make allows: where a fixed frequency ripples less than its worst, this one switches more "
        "slowly and loses less. The regulators follow the period in use.",
    )


def least_loss_torque(design: Design) -> Scheme:
    scheme = _with(
        foc_torque(design),
        "current_ref",
        {"strategy": "least_loss"},
        {
            "strategy": "the pair of currents for which copper, iron and inverter together lose least "
            "(the loss-minimising reference of Morimoto and others, 1994, with the inverter's loss counted)"
        },
    )
    return _named(
        scheme,
        "least_loss_torque",
        "Torque control on the line of least total loss",
        "The torque is made with the pair of currents that loses least in the motor's copper, its iron and "
        "the inverter together, not with the least current: at speed, a little more current against the "
        "magnet saves more in the iron than it costs in the copper and the switches.",
    )


def foc_compensated(design: Design) -> Scheme:
    scheme = foc_torque(design)
    blocks = []
    for b in scheme.blocks:
        if b.name == "modulator":
            blocks.append(
                BlockSpec(
                    "compensation",
                    "dead_time_compensation",
                    {"alpha": "inverse_park.alpha", "beta": "inverse_park.beta", "v_dc": "plant.v_dc", **CURRENTS},
                    {"dead_time": design.t_dead, "drop": design.v_drop, "band": design_ripple(design), "share": 1.0},
                    {
                        "dead_time": "the dead time in use",
                        "drop": "the device's drop at the design current, where a device is known",
                        "band": "the ripple's peak at the design point: inside it the current crosses nought "
                        "within a period and its direction is not one sign",
                    },
                )
            )
            b = replace(b, inputs=b.inputs | {"alpha": "compensation.alpha", "beta": "compensation.beta"})
        blocks.append(b)
    return _named(
        replace(scheme, blocks=blocks),
        "foc_compensated",
        "Torque control with dead-time and device-drop compensation",
        "The voltage the stage loses to its dead time and its devices' drop is added to the voltage asked "
        "for, by the sign of each phase's current: the regulator no longer has to find it, and the current "
        "is not bent at each crossing.",
    )


def thermal_guard(design: Design) -> Scheme:
    stage = design.stage
    limit = (stage.tj_max if stage is not None else 150.0) - 10.0
    scheme = foc_torque(design)
    blocks = []
    for b in scheme.blocks:
        if b.name == "current_ref":
            blocks.append(
                BlockSpec(
                    "thermal",
                    "thermal_supervisor",
                    {
                        **CURRENTS,
                        "d_a": "modulator.d_a",
                        "d_b": "modulator.d_b",
                        "d_c": "modulator.d_c",
                        "f_sw": "frequency.f_sw",
                    },
                    {
                        "actuators": "all",
                        "limit": limit,
                        "t_clamp": limit - 45.0,
                        "t_frequency": limit - 30.0,
                        "t_derate": limit - 15.0,
                        "hysteresis": 15.0,
                        "f_step": 0.25,
                        "f_floor": 0.5,
                    },
                    {
                        "limit": "10 K under the device's rated junction temperature, for the estimate's own error"
                        if stage is not None
                        else "140 °C: no device is known",
                        "t_clamp": "45 K under the limit: the clamp costs only ripple and comes first (a clamp "
                        "above 140 °C with a 150 °C limit and back below 110 °C is reported for an induction drive)",
                        "t_frequency": "30 K under the limit",
                        "t_derate": "15 K under the limit: the current is given up last",
                        "f_step": "a quarter of the design's frequency a step, down to a half (8 to 6 to 4 kHz is "
                        "reported for a truck inverter)",
                    },
                )
            )
            b = replace(b, inputs=b.inputs | {"derate": "thermal.i_scale"})
        if b.name == "modulator":
            b = replace(
                b,
                inputs=b.inputs | CURRENTS | {"clamp": "thermal.clamp", "omega_e": "position.omega_e"},
                params=b.params | {"advance": 1.5},
                sources=b.sources
                | {"advance": "the delay around the loop in sampling periods, as the angle is advanced"},
            )
        blocks.append(b)
    blocks.append(
        BlockSpec(
            "frequency",
            "variable_frequency",
            {
                "d_a": "modulator.d_a",
                "d_b": "modulator.d_b",
                "d_c": "modulator.d_c",
                "v_dc": "plant.v_dc",
                "scale": "thermal.f_scale",
                "omega_e": "position.omega_e",
            },
            {"mode": "fixed"},
            {"mode": "the design's frequency, times the supervisor's factor"},
        )
    )
    return _named(
        replace(scheme, blocks=blocks, actuation=FROM_FREQUENCY),
        "thermal_guard",
        "Torque control with active thermal control",
        "A supervisor follows an estimate of each switch's junction temperature and, as the hottest nears "
        "its limit, clamps the leg carrying the most current, then lowers the switching frequency, then "
        "folds the current back: for a stall, a hold at very low speed or an overload, where one switch "
        "carries the peak current for longer than its junction takes to follow.",
    )


def _sensorless(design: Design, kind: str) -> Scheme:
    # Loaded here: sensorless.py is built on this module's own helpers.
    from motionsim.control.sensorless import sensorless

    return sensorless(design, kind)


def _injected(design: Design) -> Scheme:
    from motionsim.control.sensorless import injected

    return injected(design)


MORE = {
    "servo_joint": servo_joint,
    "servo_adrc": servo_adrc,
    "torque_fw_feedback": torque_fw_feedback,
    "compressor_smooth": compressor_smooth,
    "servo_notch": servo_notch,
    "servo_shaped": servo_shaped,
    "traction_dpwm": traction_dpwm,
    "discrete_high_speed": discrete_high_speed,
    "discrete_torque": discrete_torque,
    "sensorless_flux": lambda design: _sensorless(design, "flux"),
    "sensorless_emf": lambda design: _sensorless(design, "emf"),
    "sensorless_smo": lambda design: _sensorless(design, "smo"),
    "sensorless_hfi": lambda design: _injected(design),
    "mpc_loss_weighted": mpc_loss_weighted,
    "deadbeat_torque": deadbeat_torque,
    "dtc_torque": dtc_torque,
    "vsf_torque": vsf_torque,
    "least_loss_torque": least_loss_torque,
    "foc_compensated": foc_compensated,
    "thermal_guard": thermal_guard,
}
BUILDERS.update(MORE)
