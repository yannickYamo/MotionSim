"""The schemes with no encoder: an observer in the encoder's place, the open-loop start that
gets the motor to where the observer has something to read, and the speed loop tuned for a
speed that is estimated. One scheme for each of the three observers (observers.py); the
rules are stated with the values, and say where they are this tool's own."""

from __future__ import annotations

import math
from dataclasses import replace

from motionsim.control.applications import _regulator, _with
from motionsim.control.blocks import BlockSpec
from motionsim.control.presets import DUTIES, Design, _inner, _outer, _reference, bandwidth
from motionsim.control.scheme import Scheme

PLL_BELOW = 5.0  # the phase-locked loop's bandwidth below the current loop's, at the most
ESTIMATE_ERROR = 0.01  # share of the design speed an estimated speed is trusted to
INDUCTANCE_ERROR = 0.3  # share of Lq the controller's figure may be wrong by
PLL_LAG = math.radians(5.0)  # the most the phase-locked loop lags the rotor as the torque limit accelerates it


def _nth(n: float) -> str:
    return {2.0: "half", 5.0: "fifth", 10.0: "tenth", 20.0: "twentieth"}.get(n, f"1/{n:g}")


def _inductance_reach(design: Design) -> float:
    """rad²/s², what the speed loop's crossover times the phase-locked loop's bandwidth may
    be at the most, so that a wrong inductance cannot make the loop through the estimated
    speed oscillate (see _estimated_outer): 3·p²·ψ²/(2·J·ΔL)."""
    pairs_flux = design.pole_pairs * design.psi
    return 0.5 * 3.0 * pairs_flux * pairs_flux / (design.shaft_inertia * INDUCTANCE_ERROR * design.lq)


def pll_rho(design: Design, ts: float, kind: str) -> tuple[float, str]:
    """rad/s, the phase-locked loop's bandwidth, and its rule in words. A fifth of the current
    loop's bandwidth, unless that starves the speed loop: the speed loop sits a decade below
    the phase-locked loop and, on a motor whose armature reaction is large against its magnet
    (L·i/ψ), under K/ρ for a wrong inductance not to make it oscillate; the two limits meet at
    ρ = √(10·K). Never so low that the loop lags the rotor by more than 5° as the torque limit
    accelerates the shaft (a type-2 loop lags α/ρ²). The flux observer's loop is always the
    fastest: under its crossover its current model turns with the loop's own angle, and a slow
    loop loses the rotor through an open-loop start."""
    wc = bandwidth(ts, True)[0]
    ceiling = wc / PLL_BELOW
    if kind == "flux":
        return ceiling, (
            f"a {_nth(PLL_BELOW)} of the current loop's bandwidth and ten times the speed loop's, both poles at ρ: "
            "this tool's choice of spacing, kept for a flux observer whose current model turns with the loop's angle"
        )
    reach = _inductance_reach(design)
    j = design.shaft_inertia
    stiffest = design.torque_limit / (j * ESTIMATE_ERROR * max(abs(design.omega), 1e-9))
    # Lower than where the speed loop is held by something else gains nothing.
    wanted = max(math.sqrt(10.0 * reach), reach / stiffest)
    lag = math.sqrt(design.pole_pairs * design.torque_limit / j / PLL_LAG)
    rho = min(ceiling, max(wanted, lag))
    said = (
        f"a {_nth(PLL_BELOW)} of the current loop's bandwidth and ten times the speed loop's, both poles at ρ: "
        "this tool's choice of spacing"
    )
    if rho < ceiling:
        said = (
            f"ρ/2π = {rho / (2 * math.pi):.3g} Hz, under a {_nth(PLL_BELOW)} of the current loop's bandwidth: on this "
            "motor the armature reaction is large against the magnet, and a wrong inductance would hold a speed loop "
            "a decade under the faster one to a fraction of a hertz. Taken where that limit and the decade meet "
            "(ρ = √(10·K), K = 3·p²·ψ²/(2·J·ΔL)), and never where the loop lags the rotor by more than 5° at the "
            "torque limit's acceleration (α/ρ²): this tool's rule, both poles at ρ"
        )
    return rho, said


OBSERVERS = {
    "flux": ("observer_flux", "a flux observer"),
    "emf": ("observer_emf_pll", "a back-EMF observer with a phase-locked loop"),
    "smo": ("observer_smo", "a sliding-mode observer"),
}


def _observer(design: Design, kind: str, ts: float) -> BlockSpec:
    w_e = max(abs(design.omega) * design.pole_pairs, 1.0)
    f_out, rate = w_e / (2.0 * math.pi), 1.0 / ts
    rho, pll_rule = pll_rho(design, ts, kind)
    pll = rho / (2.0 * math.pi)
    inputs = {
        "v_alpha": "inverse_park.alpha",
        "v_beta": "inverse_park.beta",
        "i_alpha": "clarke.alpha",
        "i_beta": "clarke.beta",
        "theta_true": "plant.theta_e",
    }
    above = min(3.0 * f_out, rate / 8.0)
    above_rule = "three times the design's electrical frequency, and no more than an eighth of the sampling rate"
    if kind == "flux":
        params = {"crossover": max(0.1 * f_out, 1.0), "pll_bandwidth": pll}
        sources = {
            "crossover": "a tenth of the design's electrical frequency: the voltage model decides everywhere "
            "near the design speed, the current model only keeps it from drifting",
            "pll_bandwidth": pll_rule,
        }
    elif kind == "emf":
        params = {"bandwidth": above, "pll_bandwidth": pll}
        sources = {"bandwidth": above_rule, "pll_bandwidth": pll_rule}
    else:
        gain = 2.0 * w_e * design.psi + design.rs * design.limit
        reach = (1.0 - math.exp(-design.rs * ts / design.ld)) / design.rs if design.rs > 0 else ts / design.ld
        params = {"gain": gain, "boundary": gain * reach, "cutoff": above, "pll_bandwidth": pll}
        sources = {
            "gain": "twice the back-EMF at the design speed, and the resistive drop of the current limit: the "
            "switching term has to be able to outweigh the EMF for the observer to slide",
            "boundary": "the current error the full gain removes in one sampling period: inside it the "
            "observer reaches the measured current in one step and does not chatter",
            "cutoff": above_rule,
            "pll_bandwidth": pll_rule,
        }
    return BlockSpec("observer", OBSERVERS[kind][0], inputs, params, sources)


A_MOST = 4.0  # the widest spread of the symmetric optimum kept: see _estimated_outer


def _estimated_outer(design: Design, ts: float, delay: bool, kind: str) -> list[BlockSpec]:
    """The outer loop for a speed that is estimated: a decade below the phase-locked loop the
    speed comes from, whose two poles the symmetric optimum counts as delay."""
    wc, around, _ = bandwidth(ts, delay)
    rho = pll_rho(design, ts, kind)[0]
    j = design.shaft_inertia
    # An error of 1% of the design speed asks no more than the whole torque limit.
    stiffest = design.torque_limit / (j * ESTIMATE_ERROR * max(abs(design.omega), 1e-9))
    # A wrong inductance turns the estimated angle with the current, by ΔL·iq/ψ, so the
    # estimated speed is off by its rate of change: a loop from the speed regulator's torque
    # through the current back to the speed it reads, of gain J·ωs·ΔL·ρ / (3·p²·ψ²) at its
    # peak, where the phase-locked loop rolls it off. Held to a half for ΔL = 30% of Lq.
    steady = _inductance_reach(design) / rho
    ws = min(rho / 10.0, stiffest, steady)
    # The symmetric optimum puts the crossover a times above the integral's corner and a times
    # below the delay's: where the crossover is held lower still, the delay's phase is next to
    # nothing there and a larger a buys no margin, only an integral that takes a² times the
    # crossover's period to close the error. Kept at four: 62° of margin, less what the delay
    # takes.
    a = min(1.0 / (ws * (2.0 / rho + 1.0 / wc + around)), A_MOST)
    rule = (
        f"symmetric optimum a decade below the phase-locked loop the speed is estimated by (ωs/2π = "
        f"{ws / (2 * math.pi):.3g} Hz, a = {a:.3g}): an estimated speed lags the rotor by the loop's two poles, "
        "and a speed regulator any closer to it shares its phase. "
    )
    if ws == steady:
        rule = (
            f"held to where an inductance wrong by {100 * INDUCTANCE_ERROR:g} % cannot make the loop through the "
            f"estimated speed oscillate (ωs/2π = {ws / (2 * math.pi):.3g} Hz, a = {a:.3g}): a wrong inductance "
            "turns the estimated angle with the current, and the estimated speed is off by how fast it turns. "
            "J·ωs·ΔL·ρ/(3·p²·ψ²) is held to a half. This tool's own rule. "
        )
    elif ws == stiffest:
        rule = (
            f"held to where an error of {100 * ESTIMATE_ERROR:g} % of the design speed in the estimate asks the "
            f"whole torque limit (ωs/2π = {ws / (2 * math.pi):.3g} Hz, a = {a:.3g}): on this inertia a stiffer "
            "regulator turns the estimate's own error into the full torque. This tool's choice. "
        )
    out = []
    for b in _outer(design, ts, delay):
        if b.name == "speed":
            b = replace(
                b,
                inputs=b.inputs | {"open": "position.open"},
                params=b.params | {"kp": j * ws, "ki": j * ws * ws / a},
                sources=b.sources | {"kp": rule + f"Kp = J·ωs, J = {j:.3g} kg·m²", "ki": rule + "Ki = Kp·ωs/a"},
            )
        out.append(b)
    return out


def starting_torque(design: Design, current: float) -> float:
    """N·m a starting current of this peak makes at the most, with the rotor a quarter turn
    behind it: the magnet's torque alone, as the open-loop start is reckoned."""
    return 1.5 * design.pole_pairs * design.psi * current


def rest_load(design: Design) -> float:
    """N·m the shaft is run up against as it leaves rest: the load's mean over a turn, where
    it pulses with the angle (the inertia rides through its peak), else what it asks at rest."""
    mean = design.load_rest_mean
    return design.load_standstill if mean is None else mean


START_MARGIN = 2.0  # the starting current's torque over the load at rest, at the least


def start_current(design: Design) -> float:
    """A peak, the open-loop start's current: half the drive's limit, or more where that does
    not make twice the most the load asks of a shaft leaving rest, up to the whole limit: an
    open-loop start has no damping but the margin of its torque over the load."""
    half = 0.5 * design.limit
    per_amp = starting_torque(design, 1.0)
    needed = START_MARGIN * design.load_standstill / per_amp if per_amp > 0 else half
    return min(max(half, needed), design.limit)


def start_ramp(design: Design, current: float) -> float:
    """rad/s² the imposed electrical speed rises at for a starting current: a share of the
    acceleration that the current's torque, less what the load asks of a shaft leaving rest
    (its mean over a turn), gives the inertia. A quarter where the current makes more than the
    most the load asks in a turn: an open-loop start has no damping, and a load angle well
    short of pull-out keeps the rotor from swinging past the imposed angle as the load eases.
    Half where the load's peak asks more than the current makes: the shaft then has to ride
    through that peak on its inertia, and needs the speed to. Where the load asks more than
    the current gives on the mean there is no ramp the rotor follows: a fiftieth of the
    unloaded one is kept, and the start is said not to apply."""
    gives = starting_torque(design, current)
    spare = max(gives - rest_load(design), 0.02 * gives)
    share = 0.25 if gives > design.load_standstill else 0.5
    return design.pole_pairs * share * spare / design.shaft_inertia


HANDOVER_SHARE = 0.1  # of the design's electrical speed
HANDOVER_FLOOR = 10.0  # times the least back-EMF the phase-locked loop locks onto (observers.EMF_FLOOR)


def handover_speed(design: Design) -> float:
    """rad/s electrical, where the observer takes the angle over: a tenth of the design speed,
    and never under ten times the electrical frequency whose back-EMF the phase-locked loop
    still locks onto, so that the angle it hands the regulators is good to a few degrees;
    never past half the design speed."""
    from motionsim.control.observers import EMF_FLOOR

    w_e = max(abs(design.omega) * design.pole_pairs, 1.0)
    return min(max(HANDOVER_SHARE * w_e, HANDOVER_FLOOR * 2.0 * math.pi * EMF_FLOOR), 0.5 * w_e)


def _startup(design: Design) -> BlockSpec:
    current = start_current(design)
    # What the starting current can give beyond what the load asks of a shaft leaving rest:
    # half of it accelerates. Where the load asks more than the current gives there is no
    # ramp the rotor follows; a slow one is kept and the start is said not to apply.
    ramp = start_ramp(design, current)
    handover = handover_speed(design)
    return BlockSpec(
        "position",
        "if_startup",
        {
            "theta": "observer.theta",
            "omega_e": "observer.omega_e",
            "target": "cmd.speed",
        },
        {
            "current": current,
            "align": 0.02,
            "ramp": ramp,
            "handover": handover,
            "blend": 4.0 * math.pi / handover,
            "handback": 0.0,
        },
        {
            "current": "half the drive's current limit, or more, up to the whole limit, where that does not make "
            f"{START_MARGIN:g} times the most the load asks of a shaft leaving rest",
            "align": "20 ms for the current to come up: the simulated rotor starts aligned",
            "ramp": "a quarter of the acceleration that the starting current's torque, less the load's mean torque "
            "over a turn at rest, gives the inertia (half, where the load's peak in a turn asks more than the "
            "current makes and the shaft has to ride through it): an open-loop start has no damping but its "
            "margin. This tool's choice",
            "handover": "a tenth of the design speed, where the back-EMF is a tenth of its design value (the usual "
            "floor of an observer of the back-EMF), and no less than ten times the electrical frequency whose "
            "back-EMF the phase-locked loop still locks onto, nor more than half the design speed: this tool's "
            "choice",
            "blend": "two turns of the output at the hand-over speed",
            "handback": "off: the observer keeps the angle at any speed once it has it. Set to four fifths of "
            f"the hand-over speed ({0.8 * handover:.4g} rad/s), the most the hysteresis allows, to take a reversal "
            "through standstill open loop while the observer still reads the speed well (the C export does "
            "not carry it yet)",
        },
    )


def sensorless(design: Design, kind: str = "flux") -> Scheme:
    ts, delay = 0.5 / design.f_sw, True
    blocks = [
        BlockSpec("sample", "current_sampling", {"i_a": "plant.i_a", "i_b": "plant.i_b", "i_c": "plant.i_c"}),
        BlockSpec("clarke", "clarke", {"a": "sample.i_a", "b": "sample.i_b", "c": "sample.i_c"}),
        _observer(design, kind, ts),
        _startup(design),
        BlockSpec("park", "park", {"alpha": "clarke.alpha", "beta": "clarke.beta", "theta": "position.theta"}),
        *_estimated_outer(design, ts, delay, kind),
        _reference(design, "shaper.torque", "mtpa_fw"),
        BlockSpec(
            "start_current",
            "if_current",
            {
                "id_ref": "current_ref.i_d",
                "iq_ref": "current_ref.i_q",
                "current": "position.current",
                "mode": "position.mode",
            },
        ),
        *_inner(design, ts, delay),
    ]
    scheme = Scheme(
        f"sensorless_{kind}",
        f"Speed control with no encoder, started open loop ({OBSERVERS[kind][1]})",
        f"The rotor's angle and speed come from {OBSERVERS[kind][1]} in place of an encoder, the current "
        "regulator is the discrete-time one and the loop is sampled twice a carrier period, so that it holds "
        "down to a few switching periods in a turn of the output. From rest the motor is run up open loop "
        "with its current held and its angle imposed (I-f) and handed over to the observer, which has nothing "
        "to read at standstill: what an appliance's drive (a compressor, a washer, a fan, a pump, a vacuum "
        "cleaner) is started and run with.",
        blocks,
        dict(DUTIES),
        {"update": "double", "delay": delay, "f_control": None},
    )
    scheme = _regulator(design, scheme)
    return _with(scheme, "current", {}, {}, {"id_ref": "start_current.i_d", "iq_ref": "start_current.i_q"})


INJECTION_BELOW = 20.0  # the injection's phase-locked loop below the current loop's bandwidth
INJECTED_RIPPLE = 0.05  # of the drive's current limit: the injected square wave's current step
PULSE_SHARE = 0.5  # of the current limit: the polarity pulses' reach


def injection_timed(design: Design, ts: float) -> dict[str, float]:
    """The injection's figures that follow the sampling period: its loop a twentieth of the
    current loop's bandwidth, eight of the loop's time constants to lock, and a wave that steps
    the current by a share of the limit each period."""
    rho = bandwidth(ts, True)[0] / INJECTION_BELOW
    amplitude = INJECTED_RIPPLE * design.limit * min(design.ld, design.lq) / ts
    return {"amplitude": amplitude, "pll_bandwidth": rho / (2.0 * math.pi), "lock": 8.0 / rho}


def retuned_estimate(scheme: Scheme, design: Design, ts: float, delay: bool) -> dict[str, dict[str, float]]:
    """What an estimated scheme tunes by its sampling period, by its builder's own rules at
    another: the observer, the injection where it has one, and the speed loop under the
    estimated speed. Empty for a scheme with no observer."""
    observer = next((b for b in scheme.blocks if b.name == "observer"), None)
    kind = next((k for k, (block, _) in OBSERVERS.items() if observer and observer.kind == block), None)
    if kind is None:
        return {}
    outer = {b.name: b.params for b in _estimated_outer(design, ts, delay, kind)}
    return {
        "observer": _observer(design, kind, ts).params,
        "position": injection_timed(design, ts) if any(b.kind == "hf_injection" for b in scheme.blocks) else {},
        "speed": {k: outer["speed"][k] for k in ("kp", "ki")},
        "speed_ref": {"jerk": outer["speed_ref"]["jerk"]},
        "shaper": {k: outer["shaper"][k] for k in ("rate", "jerk") if k in outer["shaper"]},
    }


def injected(design: Design) -> Scheme:
    """The back-EMF scheme with its open-loop start replaced by high-frequency injection: the
    angle read at standstill, the magnet's polarity told, the observer handed over to at speed."""
    base = sensorless(design, "emf")
    timed = injection_timed(design, 0.5 / design.f_sw)
    handover = handover_speed(design)
    hfi = BlockSpec(
        "position",
        "hf_injection",
        {
            "i_alpha": "clarke.alpha",
            "i_beta": "clarke.beta",
            "theta_emf": "observer.theta",
            "omega_emf": "observer.omega_e",
            "theta_true": "plant.theta_e",
        },
        {
            **timed,
            "polarity": "pulses",
            "pulse": PULSE_SHARE * design.limit,
            "cycles": 20.0,
            "handover": handover,
            "cross": 0.0,
        },
        {
            "amplitude": f"a current step of {100 * INJECTED_RIPPLE:g} % of the drive's limit each sampling period, "
            "V = ΔI·L/Ts with the smaller inductance: enough to read, small against the load's current. This "
            "tool's choice",
            "pll_bandwidth": f"a {_nth(INJECTION_BELOW)} of the current loop's bandwidth: the regulator's own "
            "changes of current reach the injected signal up to its bandwidth, and a loop well under it averages "
            "them out. This tool's choice",
            "lock": "eight time constants of the loop",
            "polarity": "told by pulses, where the iron saturates",
            "pulse": f"{100 * PULSE_SHARE:g} % of the drive's current limit, far enough into the iron to tell its sides",
            "cycles": "twenty rounds, + and back, − and back",
            "handover": "the back-EMF observer's hand-over speed: the blend runs from it to twice it",
            "cross": "none: the controller is told nothing of the iron's coupling",
        },
    )
    blocks = []
    for b in base.blocks:
        if b.name == "position":
            b = hfi
        elif b.name == "park":
            b = replace(b, inputs=b.inputs | {"alpha": "position.i_alpha", "beta": "position.i_beta"})
        elif b.name == "current_ref" and "derate" not in b.inputs:
            # While injecting, the current is held to what keeps the angle read near the rotor's.
            b = replace(b, inputs=b.inputs | {"derate": "position.derate"})
        else:
            b = replace(
                b,
                inputs={
                    k: {"inverse_park.alpha": "inject.alpha", "inverse_park.beta": "inject.beta"}.get(w, w)
                    for k, w in b.inputs.items()
                },
            )
        blocks.append(b)
        if b.name == "inverse_park":
            blocks.append(
                BlockSpec(
                    "inject",
                    "injection_sum",
                    {
                        "alpha": "inverse_park.alpha",
                        "beta": "inverse_park.beta",
                        "h_alpha": "position.h_alpha",
                        "h_beta": "position.h_beta",
                    },
                )
            )
    return replace(
        base,
        id="sensorless_hfi",
        label="Speed control with no encoder, held at standstill by injection",
        about="The rotor's angle at standstill and low speed read from the current a small injected voltage makes, "
        "the magnet's polarity told by pulses, and the back-EMF observer handed over to once the motor turns "
        "fast enough: no encoder and no open-loop start, for a motor whose two axes differ in inductance "
        "(an interior-magnet one). What a drive that holds a load at zero speed with no sensor uses.",
        blocks=blocks,
    )


def coupling_turn(design: Design, i_q: float) -> float:
    """½·atan2(2·Ldq, Lqq − Ldd), in radians, at a q current, by the saturation map this tool takes
    for the motor (control/magnetics.py, usual). The iron's coupling of the axes puts the axis of
    least inductance at minus this angle from d, and an injection told nothing of it reads the
    rotor's angle off by that much: positive q current, a positive error for a negative turn."""
    from motionsim.control.magnetics import kind_of, usual

    ldd, ldq, lqq = usual(kind_of(design.ld, design.lq), design.ld, design.lq, design.psi, design.limit).inductances(
        0.0, i_q
    )
    # The incremental inductance matrix's axis of least inductance sits at ½·atan2(2·Ldq, Lqq − Ldd) from d.
    return 0.5 * math.atan2(2.0 * ldq, lqq - ldd)


def coupling_rate(design: Design) -> float:
    """The compensation, in radians per ampere of q current, that takes the coupling's turn back
    at half the drive's current limit, by the same map."""
    at = 0.5 * design.limit
    return -coupling_turn(design, at) / at
