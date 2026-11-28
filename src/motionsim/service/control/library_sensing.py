"""The explorations of sensing without an encoder and of robustness to a wrong model: the
second half of the library (library.py)."""

from __future__ import annotations

import math

from motionsim.control.presets import Design, chosen
from motionsim.control.scenario import ROOM, _speed_time, longest, run_up
from motionsim.control.sensorless import coupling_rate, handover_speed, sensorless
from motionsim.control.startup import HYSTERESIS
from motionsim.service.control.exploring import (
    START_CURRENTS,
    Exploration,
    _dead_short,
    _high_ratio,
    _hold,
    _no_iron,
    _no_start,
    _ratio,
    _rounded,
    _schemes,
    _short_start,
    _step,
    _values,
)
from motionsim.text import written


def _reversal(design) -> dict:
    """From half the design speed to half of it the other way, through standstill: given the
    run-down and the run-up at the torque the drive has to spare, the open-loop stretch either
    side of standstill (the imposed speed ramped from the hand-over speed one way to it the
    other, and the two blends), and the speed loop's own settling."""
    scheme = sensorless(design, "smo")
    half = _rounded(0.5 * design.rpm, 4)
    p = next(b for b in scheme.blocks if b.kind == "if_startup").params
    through = 2.0 * float(p["handover"]) / float(p["ramp"]) + 2.0 * float(p["blend"])
    run = 2.0 * ROOM * run_up(design, 0.0, abs(half) * math.pi / 30.0)
    need = 0.02 + run + through + _speed_time(design, scheme)
    return {
        "kind": "speed_step",
        "from_rpm": half,
        "to_rpm": -half,
        "duration": _rounded(min(need, longest(design, scheme))),
    }


def _no_pulse(design: Design) -> str | None:
    """Where the load asks the same torque all through the turn, there is nothing to learn."""
    speed = abs(design.omega)
    if design.load_at is None or design.load_peak_at is None or not speed:
        return "the load is not known here; give the machine's load (a compressor's) to see its turn"
    if design.load_peak_at(speed) <= 1.05 * abs(design.load_at(speed)):
        return "this load asks the same torque all through the turn: there is no pulse within it to smooth"
    if chosen(design)[0] != "sensorless_emf":
        return (
            "this part's drive is chosen with a rotor sensor: the learning shown here is for a drive without one "
            "(a compressor's, a washer's)"
        )
    from motionsim.control.applications import compressor_smooth

    reach = next(b for b in compressor_smooth(design).blocks if b.kind == "periodic_compensation").params["reach"]
    turn = abs(design.rpm) / 60.0
    if turn > reach:
        return (
            f"the shaft turns {written(turn, 3)} times a second, and the speed this drive senses without a sensor "
            f"follows only up to {written(reach, 3)} Hz: the turn's pulse cannot be read in time to be learned"
        )
    return None


def _fw_hold(design: Design) -> dict:
    """A hold both schemes are read after the same time of: the twenty time constants the field
    weakening on the voltage is given to settle (its bandwidth a decade under the current loop's),
    so that the scheme without it is not read sooner."""
    from motionsim.control.presets import bandwidth

    wc = bandwidth(1.0 / design.f_sw, True)[0]
    return {"kind": "hold", "periods": 4, "settle": _rounded(min(200.0 / wc, 1.5), 3)}


def _no_servo(design: Design) -> str | None:
    """A stiff speed servo is the question of a drive that reads its rotor's position."""
    if chosen(design)[0] == "sensorless_emf":
        return (
            "this part's drive has no rotor sensor, as its machine is (a compressor's, a fan's): a stiff speed "
            "servo on a twisting shaft is a robot joint's or a machine axis's question"
        )
    return None


SLOW_LOAD = 0.3  # the load's swing, as a share of the rule's speed loop: slower than the loop answers
PLANNED = 0.3  # the move's acceleration, as a share of what the torque limit gives the shaft unloaded


def _jerk_rate(design: Design) -> float:
    """1/s, the rate the joint servo's S-curve brings its acceleration up at: its speed loop's."""
    from motionsim.control.presets import bandwidth

    return bandwidth(1.0 / design.f_sw, True)[0] / 10.0


def _planned_move(design: Design) -> dict:
    """A speed step low in the speed range, where the drive has torque to spare, long enough for
    the move along its plan and four periods of the swing after it (the swing is read over the
    last quarter of the run)."""
    top = 0.3 * abs(design.rpm)
    low = 0.2 * abs(design.rpm)
    rise = (top - low) * math.pi / 30.0 / (PLANNED * design.torque_limit / design.shaft_inertia)
    swing = 1.0 / (0.55 * SLOW_LOAD * _speed_rule_hz(design))  # s, about the antiresonance's period
    sign = math.copysign(1.0, design.rpm or 1.0)
    return {
        "kind": "speed_step",
        "from_rpm": _rounded(sign * low),
        "to_rpm": _rounded(sign * top),
        "duration": _rounded(0.02 + rise + 2.0 / _jerk_rate(design) + 4.0 * swing),
    }


def _speed_rule_hz(design: Design) -> float:
    """Hz, the speed loop's bandwidth by the rule it is tuned by: a decade below the current loop's."""
    from motionsim.control.presets import bandwidth

    return bandwidth(1.0 / design.f_sw, True)[0] / 10.0 / (2.0 * math.pi)


def _alike_axes(design: Design) -> str | None:
    """Why injection cannot read this motor: its two axes are alike to the controller."""
    from motionsim.control.presets import offered

    if offered("sensorless_hfi", design):
        return None
    return (
        "injection reads the rotor's angle from the difference between the two axes' inductances, and this motor's "
        "are alike (surface magnets): give the motor its Ld and Lq, as an interior-magnet motor has them"
    )


def _slow_hold(design: Design) -> dict:
    """A slow speed held under half the design torque: where no back-EMF has anything to read."""
    return {
        "kind": "speed_step",
        "from_rpm": 0.0,
        "to_rpm": _rounded(0.01 * design.rpm),
        "load": _rounded(0.5 * design.torque),
    }


SENSING_AND_ROBUSTNESS: tuple[Exploration, ...] = (
    Exploration(
        "observer_choice",
        "No encoder: three observers against the encoder",
        "What does running without an encoder cost at this speed?",
        "The design point held with an encoder and with each of three observers in its place. Look at the "
        "angle error, and at the current and loss it turns into: an angle that is off puts part of the "
        "current on the wrong axis, where it makes heat and no torque.",
        "sensing",
        "discrete_high_speed",
        _hold(),
        lambda d: _schemes(
            "angle from", ["discrete_high_speed", "sensorless_flux", "sensorless_emf", "sensorless_smo"]
        ),
        ("sensing.angle_error_rms", "channels.i_switch_rms", "losses.loss", "channels.torque_ripple_pp"),
        ("S39", "S41"),
        expects="each observer holds the angle within a few degrees, and the loss within a few percent of the encoder's",
    ),
    Exploration(
        "observer_discretisation",
        "No encoder: how the observer is discretised",
        "Does the observer hold when the rotor turns a large angle each sampling period?",
        "The back-EMF observer stepped exactly and by the naive forward-Euler form firmware often has. Look "
        "at the angle error: the shortcuts are each an error in proportion to the angle turned in a period, "
        "small at a high carrier ratio and tens of degrees at a low one.",
        "sensing",
        "sensorless_emf",
        _hold(),
        lambda d: _values("discretisation", "", "scheme.blocks.observer.discretisation", ["exact", "euler"], "exact"),
        ("sensing.angle_error_rms", "channels.i_switch_rms", "losses.loss"),
        ("S39",),
        why_not=_high_ratio,
        expects="the angle error is larger in the forward-Euler form",
    ),
    Exploration(
        "sensorless_start",
        "No encoder: starting from rest",
        "How is a motor with no encoder started, and what does the starting current decide?",
        "An observer has nothing to read at standstill, so the motor is run up open loop and handed over. "
        "Look at the starting current against the time to speed and the peak current: too little and the "
        "rotor cannot follow the ramp, more than needed and it is only heat.",
        "sensing",
        "sensorless_flux",
        _short_start,
        lambda d: _values(
            "starting current",
            "A peak",
            "scheme.blocks.position.current",
            [_rounded(k * d.limit) for k in START_CURRENTS],
            _rounded(0.5 * d.limit),
        ),
        ("step.rise_time", "channels.i_switch_peak", "sensing.angle_error_rms"),
        ("S41",),
        fidelity="averaged",
        why_not=_no_start,
        expects="the motor reaches its speed with a starting current that covers the load and the ramp; with less "
        "the rotor falls behind the ramp, and the run says whether the speed was reached",
    ),
    Exploration(
        "through_zero",
        "No encoder: reversing through standstill",
        "Does the drive keep the rotor when it reverses through standstill?",
        "The speed asked for goes from half the design speed one way to half the other way, with the observer "
        "kept on through standstill and with the start's hand-back, which takes the drive open loop under the "
        "observer's floor and hands over again past the hand-over speed. Look at the largest angle error while "
        "the scheme is on the observer, and at whether the speed gets there.",
        "sensing",
        "sensorless_smo",
        _reversal,
        lambda d: _values(
            "hand-back speed",
            "rad/s",
            "scheme.blocks.position.handback",
            [0.0, _rounded(HYSTERESIS * handover_speed(d))],
            0.0,
        ),
        ("sensing.angle_error_peak", "step.steady_state_error", "channels.i_switch_peak"),
        fidelity="averaged",
        why_not=_no_start,
        expects="with the hand-back the angle stays on the rotor's while the observer has it, and the speed reaches "
        "its target; without it the observer loses the rotor at standstill",
    ),
    Exploration(
        "injection_coupling",
        "No encoder at standstill: the iron's coupling under load",
        "Does the angle read at standstill hold when the motor carries a load?",
        "A slow speed held under half the design torque, with the angle read by injection and the iron "
        "saturating. Under load the iron couples the two axes, which turns the axis the injection reads by "
        "several degrees; a compensation in radians per ampere of q current, from the motor's own saturation "
        "map, takes it back. Look at the mean angle error, and at the current it costs.",
        "sensing",
        "sensorless_hfi",
        _slow_hold,
        lambda d: _values(
            "coupling compensation",
            "rad/A",
            "scheme.blocks.position.cross",
            [0.0, float(f"{coupling_rate(d):.3g}")],
            0.0,
        ),
        ("sensing.angle_error_mean", "channels.i_switch_rms", "losses.loss"),
        fidelity="averaged",
        fixed=lambda d: {"plant.iron": "saturating"},
        why_not=_alike_axes,
        expects="without the compensation the angle sits several degrees off under load; with it, close to the "
        "rotor's, and the same torque takes less current",
    ),
    Exploration(
        "shunt_sensing",
        "Currents: shunts in the stage in place of a sensor",
        "What does reading the currents through shunts cost, against a current sensor?",
        "The design point held with a current sensor and with the currents read through shunts in the stage: "
        "three or two under the low switches, or one in the DC link, each with the timer shifting its edges "
        "where a window would be too short, as a drive does. Look at the current as read against the true "
        "one, and at the distortion and torque ripple it turns into: a low-side shunt reads only while its "
        "low switch is on, and one in the DC link reads two phases a period, each in its own vector.",
        "sensing",
        "foc_servo",
        _hold(),
        lambda d: _values(
            "currents read through", "", "scheme.sensing", ["sensor", "three", "two", "single"], "sensor"
        ),
        ("channels.read_error_rms", "channels.unread_share", "channels.thd", "channels.torque_ripple_pp"),
        expects="three and two shunts read nearly as the sensor does; one in the DC link reads each phase at another "
        "time in the period and its shift adds ripple, so it reads furthest off the true current",
    ),
    Exploration(
        "shunt_window",
        "Currents: one shunt, and where its window is too short",
        "What does the timer's shift buy a drive with one shunt in the DC link?",
        "One shunt in the DC link, with the timer shifting the vectors apart where one would stand shorter "
        "than the window and with nothing done. Look at the periods in which a phase could not be read and was "
        "kept from before: at a low modulation, and wherever two references meet, the vectors are too short "
        "without the shift.",
        "sensing",
        "foc_servo",
        _hold(),
        lambda d: _values("the timer", "", "scheme.blocks.sample.fix", ["shift", "none"], "none"),
        ("channels.unread_share", "channels.read_error_rms", "channels.thd", "channels.torque_ripple_pp"),
        fixed=lambda d: {"scheme.sensing": "single"},
        expects="with the shift nearly every period is read; without it a phase is kept from before in a share of "
        "the periods",
    ),
    Exploration(
        "mismatch_deadbeat",
        "Deadbeat control: a wrong inductance",
        "How wrong can the inductance be before deadbeat control rings?",
        "The motor's inductance from 60% to 160% of what the controller holds. Look at the overshoot of a "
        "torque step: with the motor's inductance below the controller's the step overshoots and rings, and "
        "below half of it the loop no longer settles at all.",
        "robustness",
        "deadbeat_torque",
        _step,
        lambda d: _values(
            "motor's inductance, of the controller's",
            "×",
            "mismatch.ld",
            [0.6, 0.8, 1.0, 1.25, 1.6],
            1.0,
            ("mismatch.lq",),
        ),
        ("step.overshoot", "step.settling_time", "channels.ripple_rms"),
        ("S45", "S15"),
        fidelity="averaged",
        expects="the overshoot is largest with the motor's inductance furthest below the controller's",
    ),
    Exploration(
        "mismatch_predictive",
        "Predictive control: a wrong flux",
        "What steady error does a controller with no integrator make of a wrong magnet flux?",
        "The magnet's flux from 80% to 120% of what the controller holds, under the predictive controller. "
        "Look at the steady torque error: nothing integrates the error away, so the model's mistake stays in "
        "the current, where the PI regulator would have removed it.",
        "robustness",
        "mpc_torque",
        _step,
        lambda d: _values("motor's flux, of the controller's", "×", "mismatch.flux", [0.8, 0.9, 1.0, 1.1, 1.2], 1.0),
        ("step.steady_state_error", "channels.ripple_rms"),
        ("S13", "S15"),
        expects="the steady torque error grows as the flux leaves the controller's figure",
    ),
    Exploration(
        "mismatch_observer",
        "No encoder: a wrong inductance in the observer",
        "How far does a wrong inductance turn the estimated angle?",
        "The motor's q-axis inductance from 70% to 130% of what the flux observer holds. Look at the mean "
        "angle error: the observer takes Lq·i from the flux it integrated to find the rotor, and what is "
        "left over from a wrong Lq turns the angle by about atan(ΔLq·iq/ψ).",
        "robustness",
        "sensorless_flux",
        _hold(),
        lambda d: _values(
            "motor's inductance, of the observer's",
            "×",
            "mismatch.lq",
            [0.7, 0.85, 1.0, 1.15, 1.3],
            1.0,
            ("mismatch.ld",),
        ),
        ("sensing.angle_error_mean", "channels.i_switch_rms", "losses.loss"),
        ("S39", "S42"),
        fixed=lambda d: {"conditions.rpm": _rounded(0.5 * d.rpm, 4), "conditions.torque": _rounded(0.5 * d.torque, 4)},
        expects="the angle error grows with the mismatch, with opposite signs either side of 1",
    ),
    Exploration(
        "low_carrier_ratio",
        "Low carrier ratio: the textbook regulator against the discrete one",
        "Does the current loop still hold when the stage switches only a few times a turn?",
        "The switching frequency lowered until the stage switches ten times in a turn of the output, under "
        "the PI regulator with fed-forward coupling and under the regulator designed in discrete time. Look "
        "at the overshoot of a torque step and at whether the linear analysis, which takes each axis alone, "
        "still describes what the run does.",
        "robustness",
        "foc_torque",
        _step,
        lambda d: _schemes("current regulator", ["foc_torque", "discrete_torque"]),
        ("step.overshoot", "step.settling_time", "channels.ripple_rms"),
        ("S34", "S37", "S38"),
        fidelity="averaged",
        fixed=lambda d: {"conditions.f_sw": _rounded(10.0 * max(d.f_out, 1.0), 4)} if _ratio(d) > 10.0 else {},
        expects="the discrete regulator overshoots less",
    ),
    Exploration(
        "dead_time",
        "Dead time: with and without compensation",
        "What does the dead time do to the current, and does compensating it put it right?",
        "The stage simulated with its dead time, and the share of the lost voltage that is added back from "
        "none to all. Look at the current's distortion, and at the torque where the drive is at its voltage "
        "limit: the dead time takes a square wave in step with each phase's current out of the voltage, and "
        "voltage the stage cannot give is torque the motor does not make.",
        "robustness",
        "foc_compensated",
        _hold(),
        lambda d: _values("share compensated", "", "scheme.blocks.compensation.share", [0.0, 0.5, 1.0], 0.0),
        ("channels.thd", "torque_mean", "losses.loss"),
        ("S3", "S30"),
        fixed=lambda d: {"inverter.dead_time": True},
        why_not=_dead_short,
        expects="with the compensation the current's distortion does not rise and the torque does not fall",
    ),
    Exploration(
        "least_loss",
        "Current reference: least current against least loss",
        "Where does the pair of least loss leave the pair of least current, and what does it save?",
        "The design point held on the least-current line and on the line of least total loss, the motor's "
        "copper and iron and the inverter together. Look at the system loss and at the d-axis current: "
        "weakening the field a little saves more in the iron than it costs in copper and switches.",
        "losses",
        "foc_torque",
        _hold(),
        lambda d: _schemes("current reference", ["foc_torque", "least_loss_torque"]),
        ("losses.system", "losses.motor_iron", "losses.motor_copper", "losses.loss"),
        ("S27", "S6"),
        fidelity="averaged",
        why_not=_no_iron,
        expects="the system loss is no higher on the line of least loss",
    ),
    Exploration(
        "load_rejection",
        "A load that steps: the speed PI against an observer of the load",
        "At the same speed of response, which loop gets the speed back sooner after a load step?",
        "The joint servo held at speed while the load steps up, once with its speed PI and once with the PI "
        "replaced by an observer that estimates everything that is not the torque asked (the load, friction, "
        "an inertia other than the one assumed) and cancels it. The observer's loop is tuned to cross over "
        "where the PI's does, so the two answer a speed step as fast: what differs is the rest. Look at the "
        "time to recover, which the observer shortens because it does not wait for an integral to fill, at "
        "the dip, which the crossover sets for both, and at the speed loop's phase margin in the lens, which "
        "is what the observer costs.",
        "robustness",
        "servo_joint",
        lambda d: {"kind": "load_step"},
        lambda d: _schemes("speed loop", ["servo_joint", "servo_adrc"]),
        ("step.recovery_time", "step.deviation", "channels.torque_ripple_pp"),
        ("S79", "S80"),
        expects="the observer recovers the speed in well under the PI's time, with a dip about as deep",
    ),
    Exploration(
        "fw_by_voltage",
        "Field weakening when the motor is not the one the controller holds",
        "If the magnet is stronger than its figure, does field weakening still hold the torque at speed?",
        "Half as fast again as the design speed, with the motor's magnet 15% stronger than the figure the "
        "controller works from (a cold magnet, a datasheet's typical value, a batch at its tolerance). Field "
        "weakening worked out from the model asks too little negative d current, the voltage runs out and "
        "the current regulator loses the current; a loop on the voltage itself takes the d current as far "
        "as the motor needs. Look at the torque made against the torque asked, and at the peak current, "
        "which is what holding it costs.",
        "robustness",
        "foc_torque",
        _fw_hold,
        lambda d: _schemes("field weakening", ["foc_torque", "torque_fw_feedback"]),
        ("torque_mean", "channels.i_switch_peak", "channels.thd"),
        ("S81",),
        fidelity="averaged",
        fixed=lambda d: {"mismatch.flux": 1.15, "conditions.rpm": _rounded(1.5 * d.rpm, 4)},
        expects="by the model the torque is lost; by the voltage it is held, at more current",
    ),
    Exploration(
        "compressor_turn",
        "A compressor's shaft through each turn",
        "Does my compressor's shaft slow and speed up through each turn, and can the drive smooth it?",
        "A rotary compressor asks a torque that rises and falls with the angle of its shaft, the same every "
        "turn. Its speed loop answers only the error it sees, so the shaft slows and speeds up through each "
        "turn, which shakes the compressor and its pipes. Here the drive with no rotor sensor holds the "
        "design speed against the compressor's own load, first as it is, then with the torque of each turn "
        "learned from the shaft and given ahead of the loop. Look at the speed's swing within the turn, and "
        "at the torque's: smoothing the shaft means the motor now gives the load's pulse itself.",
        "dynamics",
        "sensorless_emf",
        lambda d: {"kind": "hold", "against": "load", "periods": min(200, 4 * d.pole_pairs)},
        lambda d: _schemes("smoothing over the turn", ["sensorless_emf", "compressor_smooth"]),
        ("channels.speed_ripple_pp", "channels.torque_ripple_pp", "channels.i_switch_rms"),
        ("S82",),
        fidelity="averaged",
        why_not=_no_pulse,
        expects="learned, the speed's swing within the turn falls many times over; the torque's rises to the load's own",
    ),
    Exploration(
        "stiff_servo_notch",
        "A stiffer servo on a shaft that twists",
        "If I make my servo six times stiffer, does the shaft's resonance make it ring, and does a notch let me keep the gain?",
        "Between a servo's motor and its load there is always some give: a gear, a coupling, a belt. Motor and "
        "load then swing against each other at the shaft's resonance. At the gains the rule sets the loop damps "
        "that swing itself, and a notch only costs it phase. Made six times stiffer, as an engineer does for "
        "a faster axis, the loop starts to feed the swing through the motor's speed, here with the shaft "
        "resonating eight times above the rule's speed loop. Both runs take the same stiffer gains and the same "
        "shaft; one takes the resonance out of the torque it asks. Look at how much the shaft is still swinging "
        "near the end of the step, and at what the notch costs in overshoot.",
        "dynamics",
        "servo_joint",
        lambda d: {"kind": "speed_step"},
        lambda d: _schemes("notch at the resonance", ["servo_joint", "servo_notch"]),
        ("channels.shaft_swing_pp", "step.overshoot", "step.settling_time"),
        ("S83",),
        fidelity="averaged",
        fixed=lambda d: {
            "plant.coupling": {"resonance_hz": _rounded(8.0 * _speed_rule_hz(d), 3)},
            "scheme.gains.speed": 6.0,
        },
        why_not=_no_servo,
        expects="with the gains raised the plain loop rings on; with the notch the swing dies out, at some overshoot",
    ),
    Exploration(
        "move_shaped",
        "A load that swings after each move",
        "My load swings on after every move: does shaping the move leave it still, and how much later does it arrive?",
        "An arm on a long gear, a tool on a belt, a load on a slender shaft: the load swings against the motor "
        "slower than the speed loop answers, so the loop holds the motor still and the load swings on with "
        "only the shaft's own damping, long after the move. A notch cannot help here: the swing is not in the "
        "loop. Shaping the move can: given in three parts timed to the swing, the swing the first part starts "
        "the last one stops. Both runs make the same move, planned within the torque the drive has to spare "
        "(at the torque limit nothing the reference does reaches the shaft); one takes it shaped for the swing "
        "the loop leaves the load in, worked out from the gains and the shaft. Look at how far the load "
        "overshoots, how much it is still swinging after the move, and how much later it arrives.",
        "dynamics",
        "servo_joint",
        lambda d: _planned_move(d),
        lambda d: _schemes("the move shaped", ["servo_joint", "servo_shaped"]),
        ("step.load.overshoot", "channels.shaft_swing_pp", "step.load.settling_time"),
        ("S84",),
        fidelity="averaged",
        fixed=lambda d: {
            "plant.coupling": {"resonance_hz": _rounded(SLOW_LOAD * _speed_rule_hz(d), 3)},
            "scheme.blocks.speed_ref.slew": _rounded(PLANNED * d.torque_limit / d.shaft_inertia),
            "scheme.blocks.speed_ref.jerk": _rounded(PLANNED * d.torque_limit / d.shaft_inertia * _jerk_rate(d)),
        },
        why_not=_no_servo,
        expects="shaped, the load overshoots and swings several times less, arriving about a period of the swing later",
    ),
)
