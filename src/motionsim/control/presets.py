"""The schemes a design starts from, each wired and tuned from the figures the design already
holds: the motor, the supply, the switching frequency and the load. Every gain comes from a
stated rule, and the rule goes with the gain so that a page can say where it came from.

The rules:

- Current loop: the regulator's zero cancels the winding's pole, Kp = ωc·L and Ki = ωc·R,
  for a bandwidth ωc/2π of a twentieth of the sampling rate, and never more than the delay
  around the loop allows for a phase margin of 60°: 1/(12·Td), with Td the half period the
  voltage is held for and the period of computation where there is one.
- Speed loop: a decade below the current loop, ωs = ωc/10, by symmetric optimum: Kp = J·ωs
  and Ti = a/ωs, with a = 1/(ωs·τ) and τ = 1/ωc + Td what the current loop takes to answer.
- The schemes of applications.py state their own rules with their values.
- Limits: the drive's current limit is the motor's, or 1.5 times the design point's current
  where the motor gives none; the torque limit is the torque of that current.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

from motionsim.control.blocks import SPEED_REGULATORS, BlockSpec, Context
from motionsim.control.scheme import Scheme
from motionsim.control.stage import StageModel
from motionsim.engine.modulation import Pwm
from motionsim.errors import Refusal
from motionsim.motor import pmsm
from motionsim.text import whole

LOW_CARRIER_RATIO = 30.0  # switching periods in a turn of the output, below which the ratio is low
# Below this the regulator designed in continuous time no longer holds its margins: the
# research note puts the edge between 10 and 15 switching periods a turn.
VERY_LOW_CARRIER_RATIO = 12.0
MARGIN = math.radians(60.0)
# A motor whose Lq is at least this many times its Ld has buried magnets: reluctance torque
# worth taking. A surface-magnet motor reads 1.0 to about 1.05 from saturation and end effects
# alone; buried-magnet motors run from about 1.5 to 4. Below it the two currents' torque is
# the magnet's, and a speed cascade is the default as for any surface motor.
SALIENT = 1.1
MPC_RATE = 5.0  # sampling instants of the predictive scheme in a switching period of the design


@dataclass(frozen=True)
class Design:
    """What the presets are tuned from."""

    rs: float
    ld: float
    lq: float
    psi: float
    pole_pairs: int
    v_dc: float
    f_sw: float
    pwm: Pwm
    rpm: float
    torque: float
    i_design: float  # A peak, at the design point
    i_limit: float | None = None  # A peak, the motor's own limit
    inertia: float | None = None  # kg·m2 at the motor's shaft
    usable: float = 1.0  # share of the ideal voltage the stage really gives
    application: str | None = None
    t_dead: float = 0.0  # s, the dead time in use
    v_drop: float = 0.0  # V across a conducting device at the design current
    stage: StageModel | None = None  # the controller's figures of the stage, where a device is known
    iron: Callable[[float], float] | None = None  # the motor's iron loss at a speed in rpm, W
    load_standstill: float = 0.0  # N·m the load asks of a shaft that is just leaving rest, at its peak in a turn
    load_rest_mean: float | None = None  # N·m: the same, its mean over a turn (None: taken as the peak)
    load_at: Callable[[float], float] | None = None  # N·m the load asks at a shaft speed in rad/s, over a turn
    load_peak_at: Callable[[float], float] | None = None  # N·m: the same, the most it asks in the turn
    inertia_assumed: bool = False  # the inertia is the one taken where none is given (shaft_inertia)
    weight: float = 0.0  # N·m at the motor's shaft a weight on the load asks with its arm level, friction aside
    gear: float = 1.0  # motor turns per turn of the load

    @property
    def omega(self) -> float:
        return self.rpm * math.pi / 30.0

    @property
    def f_out(self) -> float:
        return abs(self.omega) * self.pole_pairs / (2 * math.pi)

    @property
    def limit(self) -> float:
        """The drive's current limit, A peak."""
        return self.i_limit if self.i_limit else 1.5 * max(self.i_design, 1e-3)

    @property
    def torque_limit(self) -> float:
        """The torque of the current limit, taken along the least-current line."""
        i, gap = self.limit, self.lq - self.ld
        i_d = (self.psi - math.sqrt(self.psi**2 + 8.0 * gap**2 * i**2)) / (4.0 * gap) if gap > 0 else 0.0
        i_q = math.sqrt(max(i**2 - i_d**2, 0.0))
        return 1.5 * self.pole_pairs * (self.psi * i_q + (self.ld - self.lq) * i_d * i_q)

    @property
    def shaft_inertia(self) -> float:
        """The inertia at the shaft: the load's, or one the torque limit runs up to the
        design speed in a quarter of a second where none is known."""
        if self.inertia:
            return self.inertia
        return self.torque_limit * 0.25 / max(abs(self.omega), 1.0)


def context(design: Design, scheme: Scheme, seed: int = 0) -> Context:
    """What the blocks of a scheme read, for a design."""
    states = scheme.actuation["kind"] == "states"
    ts = scheme.control_period(design.f_sw)
    return Context(
        ts=ts,
        f_carrier=1.0 / ts if states else design.f_sw,
        v_dc=design.v_dc,
        rs=design.rs,
        ld=design.ld,
        lq=design.lq,
        psi=design.psi,
        pole_pairs=design.pole_pairs,
        delay=bool(scheme.timing["delay"]),
        pwm=design.pwm,
        i_limit=design.limit,
        inertia=design.shaft_inertia,
        seed=seed,
        t_dead=design.t_dead,
        stage=design.stage,
        iron=design.iron,
    )


def _hz(w: float) -> str:
    return f"{whole(w / (2 * math.pi))} Hz"


def bandwidth(ts: float, delay: bool) -> tuple[float, float, str]:
    """The current loop's bandwidth in rad/s by the rule, the delay around the loop in s, and
    the rule as it applied."""
    around = (1.5 if delay else 0.5) * ts
    by_rate, by_delay = 2 * math.pi / (20.0 * ts), (math.pi / 2 - MARGIN) / around
    wc = min(by_rate, by_delay)
    why = (
        f"a twentieth of the {whole(1 / ts)} Hz sampling rate"
        if wc == by_rate
        else f"what a delay of {around * 1e6:.3g} µs around the loop leaves for a 60° phase margin"
    )
    return wc, around, why


def _current_gains(design: Design, ts: float, delay: bool) -> tuple[dict, dict]:
    wc, _, why = bandwidth(ts, delay)
    rule = f"pole-zero cancellation at ωc/2π = {_hz(wc)} ({why}): "
    # A winding idealised to no resistance has no pole to cancel: the integral is then set
    # a decade below the bandwidth.
    ki = {
        axis: wc * design.rs if design.rs > 0 else 0.1 * wc * wc * l for axis, l in (("d", design.ld), ("q", design.lq))
    }
    params = {"kp_d": wc * design.ld, "ki_d": ki["d"], "kp_q": wc * design.lq, "ki_q": ki["q"]}
    sources = {
        "kp_d": rule + "Kp = ωc·Ld",
        "ki_d": rule + "Ki = ωc·Rs",
        "kp_q": rule + "Kp = ωc·Lq",
        "ki_q": rule + "Ki = ωc·Rs",
    }
    return params, sources


def _speed_gains(design: Design, ts: float, delay: bool) -> tuple[dict, dict]:
    wc, around, _ = bandwidth(ts, delay)
    ws = wc / 10.0
    a = 1.0 / (ws * (1.0 / wc + around))
    j = design.shaft_inertia
    rule = f"symmetric optimum a decade below the current loop (ωs/2π = {_hz(ws)}, a = {a:.3g}): "
    known = "" if design.inertia else " The inertia is not known: one the torque limit runs up in 0.25 s is taken."
    params = {"kp": j * ws, "ki": j * ws * ws / a, "limit": design.torque_limit}
    sources = {
        "kp": rule + f"Kp = J·ωs, J = {j:.3g} kg·m²." + known,
        "ki": rule + "Ki = Kp·ωs/a",
        "limit": "the torque of the drive's current limit",
    }
    return params, sources


def _measuring() -> list[BlockSpec]:
    """The blocks every field-oriented scheme measures with."""
    return [
        BlockSpec("sample", "current_sampling", {"i_a": "plant.i_a", "i_b": "plant.i_b", "i_c": "plant.i_c"}),
        BlockSpec("position", "position_sensing", {"theta": "plant.theta_e", "omega_m": "plant.omega_m"}),
        BlockSpec("clarke", "clarke", {"a": "sample.i_a", "b": "sample.i_b", "c": "sample.i_c"}),
        BlockSpec("park", "park", {"alpha": "clarke.alpha", "beta": "clarke.beta", "theta": "position.theta"}),
    ]


def _reference(design: Design, torque_wire: str, strategy: str) -> BlockSpec:
    return BlockSpec(
        "current_ref",
        "current_reference",
        {"torque": torque_wire, "omega_m": "position.omega_m", "v_dc": "plant.v_dc"},
        {
            "strategy": strategy,
            "i_limit": design.limit,
            "voltage_share": pmsm.WEAKENING_HEADROOM * design.usable,
            "torque_grid": max(design.torque_limit, abs(design.torque)) / 64.0,
            "speed_grid": max(abs(design.omega), 1.0) / 64.0,
        },
        {
            "i_limit": "the motor's current limit"
            if design.i_limit
            else "1.5 times the design point's current: the motor gives no limit",
            "voltage_share": "95% of the share of the ideal voltage the stage gives at the design point (dead "
            "time, shortest pulse and the devices' drop): the 5% a drive keeps for its current regulator, as the "
            "loss engine takes it",
            "torque_grid": "1/64 of the torque limit",
            "speed_grid": "1/64 of the design speed",
        },
    )


def _shaper(design: Design, torque_wire: str, ts: float, delay: bool) -> BlockSpec:
    ws = bandwidth(ts, delay)[0] / 10.0
    limit = design.torque_limit
    return BlockSpec(
        "shaper",
        "torque_shaper",
        {"torque": torque_wire},
        {"shape": "step", "limit": limit, "rate": 2.0 * limit * ws, "jerk": 8.0 * limit * ws * ws},
        {
            "limit": "the torque of the drive's current limit",
            "rate": "the whole torque limit in half the speed loop's time constant, 1/(2·ωs)",
            "jerk": "that rate reached in a quarter of the speed loop's time constant",
        },
    )


def _inner(design: Design, ts: float, delay: bool) -> list[BlockSpec]:
    """Current regulator, back to the stator's frame, and the modulator."""
    params, sources = _current_gains(design, ts, delay)
    advance = 1.5 if delay else 0.5
    return [
        BlockSpec(
            "current",
            "current_pi_dq",
            {
                "id_ref": "current_ref.i_d",
                "iq_ref": "current_ref.i_q",
                "i_d": "park.d",
                "i_q": "park.q",
                "omega_e": "position.omega_e",
                "v_dc": "plant.v_dc",
            },
            params,
            sources,
        ),
        BlockSpec(
            "inverse_park",
            "inverse_park",
            {"d": "current.v_d", "q": "current.v_q", "theta": "position.theta", "omega_e": "position.omega_e"},
            {"advance": advance},
            {"advance": "the delay around the loop in sampling periods: half the hold, and the computation"},
        ),
        BlockSpec(
            "modulator",
            "modulator",
            {"alpha": "inverse_park.alpha", "beta": "inverse_park.beta", "v_dc": "plant.v_dc"},
            {"pwm": design.pwm.value},
            {"pwm": "the modulation of the design"},
        ),
    ]


def _outer(design: Design, ts: float, delay: bool) -> list[BlockSpec]:
    """Speed reference, speed regulator and the shaping of its torque."""
    params, sources = _speed_gains(design, ts, delay)
    slew = design.torque_limit / design.shaft_inertia
    ws = bandwidth(ts, delay)[0] / 10.0
    return [
        BlockSpec(
            "speed_ref",
            "speed_reference",
            {"target": "cmd.speed"},
            {"shape": "step", "slew": slew, "jerk": slew * ws},
            {
                "slew": "the acceleration the torque limit gives the inertia with no load",
                "jerk": "that acceleration reached in one time constant of the speed loop",
            },
        ),
        BlockSpec("speed", "speed_pi", {"ref": "speed_ref.ref", "speed": "position.omega_m"}, params, sources),
        _shaper(design, "speed.torque", ts, delay),
    ]


DUTIES = {"kind": "duties", "wires": ["modulator.d_a", "modulator.d_b", "modulator.d_c"]}


def foc_servo(design: Design) -> Scheme:
    ts, delay = 1.0 / design.f_sw, True
    blocks = [
        *_measuring(),
        *_outer(design, ts, delay),
        _reference(design, "shaper.torque", "mtpa_fw"),
        *_inner(design, ts, delay),
    ]
    return Scheme(
        "foc_servo",
        "Cascaded speed and current control (servo)",
        "A speed regulator asks a torque, a current regulator in the rotor's frame makes it: the usual "
        "field-oriented servo, sampled once a carrier period with one period of computation.",
        blocks,
        dict(DUTIES),
        {"update": "single", "delay": delay, "f_control": None},
    )


def foc_torque(design: Design) -> Scheme:
    ts, delay = 1.0 / design.f_sw, True
    blocks = [
        *_measuring(),
        _shaper(design, "cmd.torque", ts, delay),
        _reference(design, "shaper.torque", "mtpa_fw"),
        *_inner(design, ts, delay),
    ]
    return Scheme(
        "foc_torque",
        "Torque control with least current and field weakening (traction)",
        "The torque asked for goes straight to the currents that make it with least current, and into field "
        "weakening where the voltage runs out; no speed regulator. What the loss engine's settled result is "
        "the end state of.",
        blocks,
        dict(DUTIES),
        {"update": "single", "delay": delay, "f_control": None},
    )


def foc_high_speed(design: Design) -> Scheme:
    ts, delay = 0.5 / design.f_sw, True
    blocks = [
        *_measuring(),
        *_outer(design, ts, delay),
        _reference(design, "shaper.torque", "mtpa_fw"),
        *_inner(design, ts, delay),
    ]
    return Scheme(
        "foc_high_speed",
        "Speed control at a low carrier ratio (high speed)",
        "The same cascade sampled twice a carrier period, at its peak and its valley, with the angle advanced "
        "for the delay: for a motor that turns through a large angle in one switching period.",
        blocks,
        dict(DUTIES),
        {"update": "double", "delay": delay, "f_control": None},
    )


def mpc_torque(design: Design) -> Scheme:
    rate = MPC_RATE * design.f_sw
    blocks = [
        *_measuring(),
        _shaper(design, "cmd.torque", 1.0 / design.f_sw, True),
        _reference(design, "shaper.torque", "mtpa_fw"),
        BlockSpec(
            "predictive",
            "fcs_mpc",
            {
                "id_ref": "current_ref.i_d",
                "iq_ref": "current_ref.i_q",
                "i_d": "park.d",
                "i_q": "park.q",
                "theta": "position.theta",
                "omega_e": "position.omega_e",
                "v_dc": "plant.v_dc",
            },
            {"weight": 0.0, "delay_compensation": True},
            {"weight": "no weight on commutations: the least current error, whatever it costs in switching"},
        ),
    ]
    return Scheme(
        "mpc_torque",
        "Predictive torque control with no modulator (finite control set)",
        "The same torque-to-current reference, with the regulator and the modulator replaced by a controller "
        "that picks the legs' states directly. Its switching frequency is not set: it follows from the weight "
        "on commutations.",
        blocks,
        {"kind": "states", "wires": ["predictive.s_a", "predictive.s_b", "predictive.s_c"]},
        {"update": "single", "delay": True, "f_control": rate},
    )


BUILDERS = {
    "foc_servo": foc_servo,
    "foc_torque": foc_torque,
    "foc_high_speed": foc_high_speed,
    "mpc_torque": mpc_torque,
}


# What a low carrier ratio asks of a scheme, one rule for the scheme a design starts on
# (`chosen`) and for the verdict's word on a run (verdict.py): below LOW_CARRIER_RATIO the
# loop is sampled twice a period with the angle advanced, or its current regulator is designed
# at the sampling rate; below VERY_LOW_CARRIER_RATIO only a regulator designed at the sampling
# rate on the exact model of the winding and the delay keeps its margins.
DISCRETE_REGULATORS = ("current_discrete_dq",)


RATES = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)  # updates a carrier period a scheme of duties may run at


def timing_at(rate: float) -> dict:
    """The timing of a scheme updated `rate` times a carrier period: below one, once every so
    many carrier periods; one and two, at the carrier's peak (and valley); above, the compare
    values reloaded through the period."""
    if rate not in RATES:
        raise Refusal(
            f"a scheme is updated one of {', '.join(f'{r:g}' for r in RATES)} times a carrier period",
            "give one of those",
            "scheme.rate",
        )
    if rate < 1.0:
        return {"update": "every", "carriers": round(1.0 / rate)}
    if rate <= 2.0:
        return {"update": "single" if rate == 1.0 else "double"}
    return {"update": "multi", "per_carrier": int(rate)}


def rate_of(timing: dict) -> float:
    """Updates a carrier period, of a scheme's timing."""
    update = timing.get("update")
    if update == "every":
        return 1.0 / int(timing.get("carriers", 2))
    if update == "multi":
        return float(timing.get("per_carrier", 4))
    return 2.0 if update == "double" else 1.0


def retimed(scheme: Scheme, design: Design, rate: float) -> Scheme:
    """The scheme updated `rate` times a carrier period, with what the presets tune by the
    sampling period tuned again by the same rules at the new one: the current regulator's
    gains, the speed regulator's, and the shaping of the torque and of the speed asked. What
    is not tuned by the period (a discrete-time regulator, designed per sample) keeps its own."""
    if scheme.actuation["kind"] != "duties" or scheme.actuation.get("period"):
        raise Refusal(
            f"the scheme {scheme.named} has no carrier of its own to be updated against",
            "vary the rate of a scheme with a modulator",
            "scheme.rate",
        )
    timing = {k: v for k, v in scheme.timing.items() if k not in ("per_carrier", "carriers")} | timing_at(rate)
    delay = bool(timing["delay"])
    ts = replace(scheme, timing=timing).control_period(design.f_sw)
    said = f"tuned again by the same rule at {rate:g} updates a carrier period"
    current, current_why = _current_gains(design, ts, delay)
    speed, speed_why = _speed_gains(design, ts, delay)
    ws = bandwidth(ts, delay)[0] / 10.0
    limit, slew = design.torque_limit, design.torque_limit / design.shaft_inertia
    by_kind: dict[str, dict] = {
        "current_pi_dq": current,
        "speed_pi": {k: speed[k] for k in ("kp", "ki")},
        "torque_shaper": {"rate": 2.0 * limit * ws, "jerk": 8.0 * limit * ws * ws},
        "speed_reference": {"jerk": slew * ws},
    }
    why = current_why | speed_why
    # A scheme whose speed is estimated is tuned by its builder's rules: its speed loop under the
    # estimate's lag, its observer, and its injection where it has one.
    from motionsim.control.sensorless import retuned_estimate

    by_name = retuned_estimate(scheme, design, ts, delay)
    blocks = []
    for b in scheme.blocks:
        own = by_name.get(b.name) if by_name and b.kind != "current_pi_dq" else None
        new = {k: v for k, v in (by_kind.get(b.kind, {}) if own is None else own).items() if k in b.params}
        if new:
            sources = {**b.sources, **{k: f"{why.get(k, 'the rule of the presets')}; {said}" for k in new}}
            b = replace(b, params={**b.params, **new}, sources=sources)
        blocks.append(b)
    return replace(scheme, timing=timing, blocks=blocks)


def carrier_need(ratio: float | None) -> str | None:
    """What a carrier ratio asks of a scheme: None, "double" (sampled twice a period, or a
    regulator designed at the sampling rate) or "discrete" (a regulator designed at the
    sampling rate)."""
    if ratio is None or not math.isfinite(ratio):
        return None
    if ratio < VERY_LOW_CARRIER_RATIO:
        return "discrete"
    if ratio < LOW_CARRIER_RATIO:
        return "double"
    return None


def carrier_meets(need: str | None, update: str | None, regulators: list[str] | tuple[str, ...]) -> bool:
    """Whether a scheme sampled so (`update`) with these current regulators' kinds meets it."""
    discrete = any(kind in DISCRETE_REGULATORS for kind in regulators)
    if need == "discrete":
        return discrete
    if need == "double":
        return discrete or update in ("double", "multi")
    return True


def carrier_scheme(ratio: float | None, by_torque: bool) -> str | None:
    """The preset a carrier ratio asks for, of the family the test needs: a torque scheme where
    a torque is commanded, a speed scheme where a speed is; None where the ratio asks nothing."""
    need = carrier_need(ratio)
    if need is None:
        return None
    if by_torque:
        return "discrete_torque"  # the one torque scheme whose regulator is designed at the sampling rate
    return "discrete_high_speed" if need == "discrete" else "foc_high_speed"


@dataclass(frozen=True)
class Practice:
    """How products of an application are controlled, as the industry builds them: the scheme
    they start on where the carrier ratio asks nothing of it, the family a low carrier ratio
    keeps to, and why, in one line."""

    scheme: str
    family: str  # "speed", "torque" or "sensorless": what a low carrier ratio keeps to
    why: str
    sealed: bool = False  # no rotor sensor can be fitted at all, whatever the start asks


# One row an application the page offers (service/applications.py). The physics that decides
# each row: whether the product has to hold or be loaded at standstill or at speeds where no
# observer reads the rotor (a measured angle: joint, axis, tool), whether a torque is asked and
# the speed follows from the load over a range far into field weakening (vehicle, tool), and
# whether the product is built without a rotor sensor (appliances, for cost, or sealed in a
# shell) and so must be started open loop, under load where it is (washer, compressor,
# conveyor). The carrier ratio and the start's torque are read after (see `chosen`).
#
# Sources, by author and title:
# - encoder servo cascade for joints and axes: W. Leonhard, Control of Electrical Drives;
#   G. Ellis, Control System Design Guide; S-curve references: L. Biagiotti and
#   C. Melchiorri, Trajectory Planning for Automatic Machines and Robots.
# - traction torque control on the least-current line and into field weakening: T. M. Jahns,
#   G. B. Kliman and T. W. Neumann, Interior permanent-magnet synchronous motors for
#   adjustable-speed drives (1986); S. Morimoto, Y. Takeda, T. Hirasa and K. Taniguchi,
#   Expansion of operating limits for permanent magnet motor by current vector control
#   considering inverter capacity (1990); K. H. Nam, AC Motor Control and Electrical Vehicle
#   Applications. A clamped (discontinuous) modulation is a lever where switching dominates
#   the loss (A. M. Hava, R. J. Kerkman and T. A. Lipo, 1998), not where every design starts.
# - Hall sensors in low-cost brushless drives that start loaded (tools): R. Krishnan,
#   Permanent Magnet Synchronous and Brushless DC Motor Drives.
# - appliance drives with no rotor sensor, the back-EMF read by an observer and a
#   phase-locked loop: Z. Chen, M. Tomita, S. Doki and S. Okuma, An extended electromotive
#   force model for sensorless control of interior permanent-magnet synchronous motors
#   (2003); S. Morimoto, K. Kawamoto, M. Sanada and Y. Takeda, Sensorless control strategy
#   for salient-pole PMSM based on extended EMF in rotating reference frame (2002, a
#   compressor's drive); at tens of thousands of rpm and few switching periods a turn:
#   B.-H. Bae, S.-K. Sul, J.-H. Kwon and J.-S. Byeon, Implementation of sensorless vector
#   control for super-high-speed PMSM of turbo-compressor (2003).
# - the open-loop start with the current held and the angle imposed (I-f), handed over to the
#   observer: M. Fatu, R. Teodorescu, I. Boldea, G.-D. Andreescu and F. Blaabjerg, I-F
#   starting method with smooth transition to EMF based motion-sensorless vector control of
#   PM synchronous motor/generator (2008).
_ON_OBSERVER = (
    "an observer of the back-EMF with a phase-locked loop gives the angle, and an open-loop start with the "
    "current held and the angle imposed (I-f) runs it up from rest, where the observer has nothing to read"
)
PRACTICE: dict[str, Practice] = {
    "joint": Practice(
        "servo_joint",
        "speed",
        "a robot joint holds its arm against gravity at standstill and follows a trajectory, which takes a measured "
        "angle: the speed and current cascade on its encoder, the speed reference along an S-curve",
    ),
    "axis": Practice(
        "foc_servo",
        "speed",
        "a positioning axis moves and stops on a position, down to standstill where no observer reads the rotor: "
        "the speed and current cascade on its encoder",
    ),
    "vehicle": Practice(
        "foc_torque",
        "torque",
        "the pedal asks a torque and the road sets the speed, far into field weakening: torque control on the "
        "least-current line, on the rotor's resolver",
    ),
    "tool": Practice(
        "foc_torque",
        "torque",
        "a power tool is started into the work and bogged down near a stall, loaded where no observer reads the "
        "rotor: torque control on rotor position sensors (Hall sensors in practice), the speed following the work",
    ),
    "drum": Practice(
        "sensorless_emf",
        "sensorless",
        "a washer's direct drive is built with no rotor sensor for its cost, and is started under the wet "
        "laundry: " + _ON_OBSERVER,
    ),
    "compressor": Practice(
        "sensorless_emf",
        "sensorless",
        "sealed in its shell with the refrigerant, a compressor's motor cannot carry a rotor sensor, and is started "
        "against the pressure left in it: " + _ON_OBSERVER,
        sealed=True,
    ),
    "vacuum": Practice(
        "sensorless_emf",
        "sensorless",
        "a vacuum cleaner's motor runs at tens of thousands of rpm with no rotor sensor: " + _ON_OBSERVER,
    ),
    "drone": Practice(
        "sensorless_emf",
        "sensorless",
        "a drone's propulsion drive runs at tens of thousands of rpm with no rotor sensor, for its weight and cost, "
        "and its propeller asks next to nothing at rest: " + _ON_OBSERVER,
    ),
    "ceiling_fan": Practice(
        "sensorless_emf",
        "sensorless",
        "a ceiling fan's drive is built with no rotor sensor for its cost, and only ever turns one way at a "
        "speed: " + _ON_OBSERVER,
    ),
    "fan": Practice(
        "sensorless_emf",
        "sensorless",
        "a pump's or a fan's drive is built with no rotor sensor for its cost, and its load asks next to nothing "
        "at rest: " + _ON_OBSERVER,
    ),
    "conveyor": Practice(
        "sensorless_emf",
        "sensorless",
        "a conveyor's general-purpose drive holds a speed with no rotor sensor, and is started with the belt "
        "loaded: " + _ON_OBSERVER,
    ),
}
WITH_SENSOR = "foc_servo"  # where no open-loop start lifts the load, what a product that can carry a sensor runs on


def _carrier(design: Design, scheme: str, family: str, why: str) -> tuple[str, str]:
    """The scheme as a low carrier ratio asks it, by the rule the verdict judges a run by
    (carrier_need, carrier_meets, carrier_scheme), and the why with what it changed."""
    ratio = design.f_sw / design.f_out if design.f_out > 0 else math.inf
    need = carrier_need(ratio)
    if need is None:
        return scheme, why
    built = BUILDERS[scheme](design)
    if carrier_meets(need, built.timing.get("update"), [b.kind for b in built.blocks]):
        if family == "sensorless":
            why += (
                f". At the design speed the stage switches {ratio:.3g} times in a turn of the output, and this scheme "
                "is already sampled twice a period with a current regulator designed at the sampling rate"
            )
        return scheme, why
    to = carrier_scheme(ratio, by_torque=family == "torque") or scheme  # None only where nothing is needed
    edge = VERY_LOW_CARRIER_RATIO if need == "discrete" else LOW_CARRIER_RATIO
    how = (
        "with a current regulator designed at the sampling rate on the exact model of the winding and the delay"
        if need == "discrete" or to == "discrete_torque"
        else "sampled twice a period, with the angle advanced for the delay"
    )
    said = (
        f"at the design speed the stage switches only {ratio:.3g} times in a turn of the output, fewer than "
        f"{edge:g}: {how}"
    )
    if scheme == "servo_joint":
        said += "; the joint's S-curve is not on this scheme: set the speed reference's shape to s-curve"
    return to, (why + ". But " + said) if why else said


def offered(scheme: str, design: Design) -> bool:
    """Whether a scheme is one this design can run: injection reads the difference between the
    two axes' inductances, and is offered only where the controller holds one."""
    if scheme == "sensorless_hfi":
        from motionsim.control.injection import SALIENCY_LEAST

        return abs(design.lq - design.ld) >= SALIENCY_LEAST * max(design.ld, design.lq)
    return True


def chosen(design: Design) -> tuple[str, str]:
    """The scheme a design starts on, and why: by its application as such products are built
    (PRACTICE), then by the physics of this design: whether an open-loop start can lift the
    load at rest within the current limit, and what its carrier ratio asks."""
    from motionsim.control.sensorless import rest_load, starting_torque

    practice = PRACTICE.get(design.application or "")
    if practice is None:
        if design.lq > SALIENT * design.ld:
            scheme, why = (
                "foc_torque",
                f"no application is given, and a motor with buried magnets (Lq {design.lq / design.ld:.3g} times "
                "Ld) is taken for a traction motor, which is asked a torque: torque control. This tool's assumption; "
                "the speed cascade takes the same least-current line and field weakening, where a speed is to be held",
            )
        else:
            scheme, why = (
                "foc_servo",
                "a speed is held against the load: the usual cascade of a speed and a current regulator",
            )
        family = "torque" if scheme == "foc_torque" else "speed"
        scheme, why = _carrier(design, scheme, family, why)
        return scheme, why + _assumed(design, family)
    scheme, family, why = practice.scheme, practice.family, practice.why
    if family == "sensorless":
        gives, asks = starting_torque(design, design.limit), rest_load(design)
        if gives <= asks:
            short = (
                f"; but the drive's current limit makes {gives:.3g} N·m at most, and the load asks {asks:.3g} N·m of a "
                "shaft leaving rest: no open-loop start follows"
            )
            if practice.sealed:
                why += short + ". Kept, since no sensor can be fitted: a larger current limit is needed"
            else:
                scheme, family = WITH_SENSOR, "speed"
                why += short + ", so it is started on a rotor sensor: the speed and current cascade"
    scheme, why = _carrier(design, scheme, family, why)
    return scheme, why + _assumed(design, family)


def _assumed(design: Design, family: str) -> str:
    """What the scheme chosen is tuned on that the design does not give, in words: the
    inertia a speed loop and an open-loop start are worked out from, and the current limit
    the start is sized to."""
    said = ""
    if family != "torque" and (design.inertia is None or design.inertia_assumed):
        said += (
            f". No inertia is given: {design.shaft_inertia:.3g} kg·m², which the torque limit runs up to the design "
            "speed in a quarter of a second, is taken, and the speed loop"
            + (" and the open-loop start are" if family == "sensorless" else " is")
            + " tuned on it: give the shaft's own"
        )
    if family == "sensorless" and design.i_limit is None:
        said += (
            ". The motor gives no current limit: 1.5 times the design point's current is taken, and the open-loop "
            "start is sized to it"
        )
    return said


def presets(design: Design) -> tuple[str, str, list[Scheme]]:
    """The scheme chosen for a design, why, and every scheme tuned for it."""
    first, why = chosen(design)
    return first, why, [build(design) for build in BUILDERS.values()]


def limited(scheme: Scheme, design: Design, i_limit: float, shape: str | None) -> Scheme:
    """The scheme with the drive's current limit moved (A peak) and the way the torque comes
    up to it chosen: what a start against a load is run with."""
    capped = replace(design, i_limit=i_limit)
    blocks = []
    for b in scheme.blocks:
        params = dict(b.params)
        if b.kind == "current_reference":
            params["i_limit"] = i_limit
        if b.kind in ("torque_shaper", *SPEED_REGULATORS):
            params["limit"] = capped.torque_limit
        if b.kind == "torque_shaper" and shape is not None:
            params["shape"] = shape
        if b.kind == "if_startup":
            params["current"] = min(params["current"], i_limit)
        blocks.append(replace(b, params=params))
    return replace(scheme, blocks=blocks)
