"""The exploration library: questions a user of the control lab would ask, each as a sweep
that is ready to run on the design at hand. An exploration names a scheme, a test, the one
thing that is varied and the figures to read; /api/control/sweep runs it.

Every exploration here is also a test (tests/test_control_explore.py runs each on two
designs and holds its headline to the direction the physics gives). The sources are works
docs/CONTROL_RESEARCH.md lists as opened, with the mark it gives each: read in full, or
only as an abstract.
"""

from __future__ import annotations

from motionsim.control.applications import design_ripple, mpc_step
from motionsim.control.presets import Design
from motionsim.control.sensing import MIN_LOSS
from motionsim.service.control.exploring import (
    Exploration,
    _hold,
    _no_device,
    _noise,
    _rounded,
    _schemes,
    _stall,
    _step,
    _thermal_fixed,
    _values,
)
from motionsim.service.control.library_sensing import SENSING_AND_ROBUSTNESS
from motionsim.service.control.works import WORKS


def _small_step(design: Design) -> dict:
    """A small torque step at a tenth of the design speed: what the current loop answers, not the
    voltage left over."""
    return {
        "kind": "torque_step",
        "from": _rounded(0.4 * design.torque),
        "to": _rounded(0.5 * design.torque),
        "rpm": _rounded(0.1 * design.rpm),
    }


LOSSES_AND_DYNAMICS: tuple[Exploration, ...] = (
    Exploration(
        "mpc_weight",
        "Predictive control: the weight on a commutation",
        "What does a heavier switching weight buy and cost?",
        "The predictive controller trades current error against commutations by one number, λ. Look at the "
        "switching loss and the mean switching frequency fall as λ rises, and at the ripple that pays for it: "
        "the weight is the knob that moves a device between its switching and its ripple limits.",
        "losses",
        "mpc_torque",
        _hold(),
        lambda d: _values(
            "λ",
            "A",
            "scheme.blocks.predictive.weight",
            [_rounded(k * mpc_step(d)) for k in (0.0, 0.125, 0.25, 0.375, 0.5)],
            0.0,
        ),
        ("losses.switching", "channels.f_switch_mean", "channels.ripple_rms", "losses.tj_peak"),
        ("S13", "S15", "S16"),
        expects="switching loss and switching frequency fall, ripple rises",
    ),
    Exploration(
        "mpc_loss_weighting",
        "Predictive control: charging a commutation by its energy",
        "Does it pay to charge each commutation by what it loses, not by a count?",
        "With the same weight, a commutation costs either one unit or the switching energy of that leg at "
        "its current, over the mean of one through a turn. Look at the current at which the legs commutate "
        "and at the switching loss: charged by energy, the controller moves the leg that carries little and "
        "leaves the one at the peak alone, and pays for it in ripple.",
        "losses",
        "mpc_torque",
        _hold(),
        lambda d: _values(
            "commutation charged by", "", "scheme.blocks.predictive.weighting", ["count", "loss"], "count"
        ),
        ("channels.i_at_commutation", "losses.switching", "channels.ripple_rms"),
        ("S3", "S2"),
        fixed=lambda d: {"scheme.blocks.predictive.weight": _rounded(0.375 * mpc_step(d))},
        why_not=_no_device,
        expects="the mean current at commutation and the switching loss fall",
    ),
    Exploration(
        "mpc_horizon",
        "Predictive control: one step ahead or two",
        "Does looking two steps ahead give a cleaner current for the same weight?",
        "A second step lets the controller see that a commutation now saves one later. Look at the ripple "
        "and the switching frequency together: the papers report less distortion from a longer horizon, at "
        "the price of sixty-four candidates a step instead of eight.",
        "losses",
        "mpc_torque",
        _hold(),
        lambda d: _values("steps ahead", "", "scheme.blocks.predictive.horizon", [1, 2], 1),
        ("channels.ripple_rms", "channels.f_switch_mean", "losses.switching"),
        ("S14",),
        fixed=lambda d: {"scheme.blocks.predictive.weight": _rounded(0.25 * mpc_step(d))},
        expects="at equal weight the ripple does not rise with the second step",
    ),
    Exploration(
        "predictive_vs_regulated",
        "Torque step: regulated, deadbeat, predictive, direct",
        "How much faster is a model-based controller than the PI regulator, and what does it cost?",
        "The same torque step under four controllers. Look at the rise time, then at the ripple and the "
        "switching loss each leaves once the step is over: the fastest answer is not the cleanest current.",
        "dynamics",
        "foc_torque",
        _step,
        lambda d: _schemes("controller", ["foc_torque", "deadbeat_torque", "mpc_torque", "dtc_torque"]),
        ("step.rise_time", "step.overshoot", "channels.ripple_rms", "losses.switching"),
        ("S15", "S16"),
        fixed=lambda d: {"scheme.blocks.shaper.shape": "step"},
        expects="deadbeat rises no slower than the PI regulator, and the predictive controller faster",
    ),
    Exploration(
        "sensor_noise",
        "Current sensing: noise",
        "How much current-sensor noise can the loop take before the torque shows it?",
        "Gaussian noise on each current sample, from none to 5% of the design current. Look at the torque "
        "ripple and the current's distortion: the regulator passes on what lies inside its bandwidth, and a "
        "wider bandwidth passes more.",
        "sensing",
        "foc_torque",
        _hold(),
        lambda d: _values("noise", "A rms", "scheme.blocks.sample.noise", _noise(d), 0.0),
        ("channels.torque_ripple_pp", "channels.ripple_rms", "losses.loss"),
        (),
        expects="torque ripple rises with the noise",
    ),
    Exploration(
        "bandwidth",
        "Current loop: gain against ripple, loss and stability",
        "What does a faster current loop buy, and where does it stop holding?",
        "The current regulator's gains from a quarter to four times the tuning rule's, with 2% sensor noise. "
        "Look at the rise time fall, the noise passed on rise, and at the top of the range the linear "
        "analysis finding a pole outside the unit circle: that run goes ahead and shows the oscillation.",
        "dynamics",
        "foc_torque",
        _step,
        lambda d: _values("gain, times the rule's", "×", "scheme.gains.current", [0.25, 0.5, 1.0, 2.0, 4.0], 1.0),
        ("step.rise_time", "step.overshoot", "channels.ripple_rms", "losses.loss"),
        ("S38",),
        fixed=lambda d: {"scheme.blocks.sample.noise": _rounded(0.02 * d.i_design)},
        expects="the rise time falls as the gain rises",
    ),
    Exploration(
        "control_rate",
        "Current loop: how often it is updated against the carrier",
        "What does updating the control more or less often than once a carrier period buy, and cost?",
        "The same small torque step at a tenth of the design speed, the control updated once every four carrier "
        "periods (a controller slower than its stage, as at a high switching frequency) up to eight times a "
        "period (the timer's compare values reloaded mid-slope), the gains tuned again by the same rule at each. "
        "Look at the loop's crossover and the settling time, then at the overshoot and the switching at the top "
        "of the range: a duty cycle reloaded mid-slope can cross the carrier twice.",
        "dynamics",
        "foc_torque",
        _small_step,
        lambda d: _values("updates a carrier period", "", "scheme.rate", [0.25, 0.5, 1.0, 2.0, 4.0, 8.0], 1.0),
        ("loops.current_hz", "step.settling_time", "step.overshoot", "channels.f_switch_mean"),
        expects="the loop's crossover rises with the updates and the step settles sooner; at the most updates the "
        "step overshoots more and the legs switch a little more often",
    ),
    Exploration(
        "delay_compensation",
        "Predictive control: with and without delay compensation",
        "What does the one-sample delay do if the controller ignores it?",
        "The predictive controller either predicts the current to the instant its choice takes effect, or "
        "decides on the sample it has. Look at the ripple: a choice made for a current that has already "
        "moved on is a period late, and the current overshoots its band both ways.",
        "dynamics",
        "mpc_torque",
        _hold(),
        lambda d: _values("delay compensation", "", "scheme.blocks.predictive.delay_compensation", [True, False], True),
        ("channels.ripple_rms", "channels.thd", "channels.torque_ripple_pp"),
        ("S13",),
        expects="ripple rises without the compensation",
    ),
    Exploration(
        "update_rate",
        "Sampling once or twice a carrier period",
        "What does sampling at the carrier's valley as well as its peak buy?",
        "The same cascade, sampled once and twice a carrier period and tuned by the same rule each time. "
        "Look at the rise time of a speed step: twice the sampling rate is half the delay, and the rule then "
        "allows twice the bandwidth at the same switching loss.",
        "dynamics",
        "foc_servo",
        lambda d: {"kind": "load_step", "torque": _rounded(0.25 * abs(d.torque))},
        lambda d: _schemes("sampled", ["foc_servo", "foc_high_speed"]),
        ("step.deviation", "step.recovery_time", "losses.switching"),
        ("S38",),
        fidelity="averaged",
        expects="the speed dips less under the load step sampled twice a period",
    ),
    Exploration(
        "pwm_choice",
        "Modulation: continuous, clamped, clamped for least loss",
        "How much switching loss does a discontinuous modulation save here, and what ripple does it cost?",
        "Space-vector modulation, the clamp at the voltage's peaks, and the clamp on the leg carrying the "
        "most current. Look at the switching loss and the current at commutation against the ripple: the "
        "clamp removes a third of the commutations, and the last variant removes the ones at the peak.",
        "losses",
        "traction_dpwm",
        _hold(),
        lambda d: _values(
            "modulation", "", "scheme.blocks.modulator.pwm", ["space-vector", "discontinuous", MIN_LOSS], "space-vector"
        ),
        ("losses.switching", "channels.i_at_commutation", "channels.ripple_rms", "losses.tj_peak"),
        ("S1", "S2"),
        fixed=lambda d: {"scheme.blocks.modulator.threshold": 0.0},
        expects="switching loss falls from continuous to clamped, and is least with the clamp on the current",
    ),
    Exploration(
        "switching_frequency",
        "Switching frequency: loss against ripple",
        "What would another switching frequency cost in loss and buy in ripple?",
        "The carrier from half to twice the design's, every regulator retuned by the same rule. Look at the "
        "switching loss rise in proportion and the ripple fall in inverse proportion: the junction and the "
        "motor's harmonic loss pull opposite ways, and the design's frequency is where they were balanced.",
        "losses",
        "foc_torque",
        _hold(),
        lambda d: _values(
            "switching frequency",
            "Hz",
            "conditions.f_sw",
            [_rounded(k * d.f_sw) for k in (0.5, 0.75, 1.0, 1.5, 2.0)],
            d.f_sw,
        ),
        ("losses.switching", "channels.ripple_pp", "losses.tj_peak", "losses.loss"),
        ("S6",),
        expects="switching loss rises and ripple falls with the frequency",
    ),
    Exploration(
        "variable_frequency",
        "Switching frequency held to a ripple limit",
        "How much switching can be saved by letting the frequency follow the ripple?",
        "The carrier period is stretched until the predicted ripple reaches a limit, from the fixed drive's "
        "own worst ripple to twice that. Look at the mean switching frequency and the switching loss against "
        "the ripple's peak, which stays at the limit instead of under it most of the turn.",
        "losses",
        "vsf_torque",
        _hold(),
        lambda d: _values(
            "ripple limit",
            "A peak",
            "scheme.blocks.frequency.ripple_limit",
            [_rounded(k * design_ripple(d)) for k in (0.75, 1.0, 1.5, 2.0)],
            _rounded(design_ripple(d)),
        ),
        ("channels.f_switch_mean", "losses.switching", "channels.ripple_pp", "channels.ripple_rms"),
        ("S4",),
        expects="a wider limit lowers the mean switching frequency and the switching loss",
    ),
    Exploration(
        "thermal_control",
        "Stall: active thermal control against none",
        "Held at standstill at full torque, what does active thermal control give up to keep the junction down?",
        "The same stall with no supervisor, with the clamp alone, with the clamp and a lower switching "
        "frequency, and with the current folded back as well. Look at the peak junction temperature from a "
        "cold start, then at the torque that was held: each measure costs more than the last.",
        "thermal",
        "thermal_guard",
        _stall,
        lambda d: _values(
            "measures allowed",
            "",
            "scheme.blocks.thermal.actuators",
            ["none", "clamp", "clamp+frequency", "all"],
            "none",
        ),
        ("losses.tj_peak_from_start", "torque_mean", "losses.loss", "losses.switching"),
        ("S8", "S9"),
        fidelity="averaged",
        fixed=_thermal_fixed,
        why_not=_no_device,
        expects="the peak junction temperature does not rise as measures are added, and falls with all of them",
    ),
    Exploration(
        "low_speed_hold",
        "Very low speed: the junction against output frequency",
        "How slowly can the motor turn at full torque before one switch carries it all?",
        "Full torque at a falling speed with no thermal control. Look at the peak junction temperature from "
        "a cold start and at its swing: once a turn of the output takes longer than the junction takes to "
        "follow, each switch in turn sees the peak current as if it were standing still.",
        "thermal",
        "foc_torque",
        lambda d: {"kind": "stall", "torque": _rounded(d.torque_limit, 4), "duration": 1.0},
        lambda d: _values(
            "speed",
            "rpm",
            "scenario.rpm",
            [_rounded(60.0 * f / d.pole_pairs) for f in (50.0, 10.0, 2.0, 0.0)],
            _rounded(60.0 * 50.0 / d.pole_pairs),
        ),
        ("losses.tj_peak_from_start", "losses.tj_swing", "losses.loss"),
        ("S8",),
        fidelity="averaged",
        expects="the peak junction temperature rises as the speed falls to nought",
    ),
)

# For a drive fed from the mains through a front end: the two controls on one link.
FRONT_END = (
    Exploration(
        "link_tie",
        "The two controls: tied or each on its own",
        "How far does the DC link fall on a load step when the front end is not told of it?",
        "The front end's link loop is slow on purpose, so that it does not bend the mains current. Alone, it "
        "sees a load step only once the link has fallen; told the power the motor's control is about to draw, "
        "it answers as the load comes on, and draws from the mains whatever the motor draws: with a load that "
        "swings, the swing reaches the mains current. Look at the lowest link voltage and the current's shape.",
        "dynamics",
        "foc_servo",
        lambda d: {"kind": "load_step"},
        lambda d: _values("tie", "", "front_end.feed_forward", ["on", "off"], "on"),
        ("link.v_min", "link.ripple", "link.thd"),
        fidelity="averaged",
        expects="on a steady load, tied, the link falls less on the step than alone; on a load that swings "
        "within a turn, tied passes the swing to the mains current and alone the capacitor takes it",
        mains=True,
    ),
    Exploration(
        "link_capacitance",
        "The link capacitor: full, half, a quarter",
        "What does a smaller or an aged link capacitor cost the link?",
        "The capacitor carries the drive between the mains' crests and through a load step. Halved, by choice "
        "or by age, the ripple at twice the mains doubles on one phase and a step falls twice as far before "
        "the front end has answered.",
        "robustness",
        "foc_servo",
        lambda d: {"kind": "load_step"},
        lambda d: _values("link capacitance", "× the design's", "link.capacitance", [1.0, 0.5, 0.25], 1.0),
        ("link.ripple", "link.v_min", "link.v_max"),
        fidelity="averaged",
        expects="the ripple and the sag grow as the capacitance falls",
        mains=True,
    ),
)

EXPLORATIONS: tuple[Exploration, ...] = LOSSES_AND_DYNAMICS + SENSING_AND_ROBUSTNESS

BY_ID = {e.id: e for e in EXPLORATIONS + FRONT_END}


def described(e: Exploration, design: Design) -> dict:
    """An exploration as a page lists it, for a design."""
    why = e.why_not(design)
    return {
        "id": e.id,
        "title": e.title,
        "question": e.question,
        "about": e.about,
        "group": e.group,
        "applies": why is None,
        "why_not": why,
        "scheme": e.scheme,
        "scenario": e.scenario(design),
        "fidelity": e.fidelity,
        "vary": e.vary(design),
        "fixed": e.fixed(design),
        "reads": list(e.reads),
        "expects": e.expects,
        "sources": [
            {"title": WORKS[key][0], "year": WORKS[key][1], "link": WORKS[key][2], "read": WORKS[key][3]}
            for key in e.sources
        ],
    }
