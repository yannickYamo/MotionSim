"""A run of the control lab: the design, the scheme and the test brought together, taken
through the kernel, and handed to the loss engine; and the two addresses that describe a
design without running it (the presets and the linear analysis)."""

from __future__ import annotations

import math
from collections.abc import Generator
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from motionsim import guard
from motionsim.control import linear, report, scenario, verdict
from motionsim.control.blocks import BLOCKS, Context, describe
from motionsim.control.kernel import FIDELITIES, MOST_STEPS, Inverter, Kernel, Trace, Unstable
from motionsim.control.losses import Cost, cost
from motionsim.control.metrics import ripple
from motionsim.control.plant import Coupling, Machine, Plant
from motionsim.control.presets import (
    BUILDERS,
    VERY_LOW_CARRIER_RATIO,
    Design,
    bandwidth,
    chosen,
    context,
    limited,
    offered,
)
from motionsim.control.references import total_loss
from motionsim.control.safestate import bridge_speed
from motionsim.control.scheme import SOURCES, Compiled, Scheme, compile_scheme
from motionsim.errors import Refusal
from motionsim.service.control import linking
from motionsim.service.control.asking import (
    FIELDS,
    MOST_POINTS,
    SCENARIOS,
    WORDED,
    _asked,
    _inverter,
    _mismatch,
    _window,
    coupling_of,
)
from motionsim.service.control.checks import current_overshoot, lost, tracking
from motionsim.service.control.design import _design_out, _designed, _load_torque, _scheme
from motionsim.service.control.judging import quality
from motionsim.service.control.motion import Motion, against_floor, motion_of, window_of
from motionsim.service.control.reading import RUN_BUDGET, SWEEP_BUDGET, over, seconds, shape
from motionsim.service.validate import _count
from motionsim.service.workspace import Workspace
from motionsim.text import written

LOOPS = (("current_d", "d-axis current"), ("current_q", "q-axis current"), ("speed", "speed"))
# A slow outer loop has poles so near z = 1 that the roots of its polynomial are only good to
# about a millionth: a pole no further outside the circle than that is not called unstable.
ON_THE_CIRCLE = 1e-6


def _fields(kind: str, defaults: dict) -> list[dict]:
    """A test's figures as a form draws them: the default is the chosen scheme's (`defaults`
    has every scheme's), and a figure that is a word has its choices and no bounds."""
    out = []
    for name, (unit, said, low, high) in FIELDS[kind].items():
        worded = name in WORDED
        out.append(
            {
                "name": name,
                "unit": unit,
                "about": said,
                "default": defaults.get(name),
                "low": None if worded else low,
                "high": None if worded else high,
                "choices": list(WORDED[name]) if worded else [],
            }
        )
    return out


# The tests that read a command a scheme may lack: a torque step and a stall a torque command,
# a speed step and a load step a speed command (scenario._needs refuses them otherwise).
NEEDS = {"torque_step": "cmd.torque", "stall": "cmd.torque", "speed_step": "cmd.speed", "load_step": "cmd.speed"}


def accepted(scheme: Scheme) -> list[str]:
    """The tests a scheme can be given, in the order the tests are listed."""
    return [kind for kind in scenario.KINDS if kind not in NEEDS or scheme.reads(NEEDS[kind])]


def simulated_by(scheme: Scheme) -> dict[str, str | None]:
    """For each loop of the linear analysis, the test whose run answers it in time: a torque
    step for the current loop of a scheme given a torque, a speed step for a speed loop; None
    where the scheme accepts no such test."""
    tests = accepted(scheme)
    torque = "torque_step" if "torque_step" in tests else None
    return {"current_d": torque, "current_q": torque, "speed": "speed_step" if "speed_step" in tests else None}


def _aside(scheme: str, design: Design) -> str | None:
    """Why a scheme, though this design can run it, is not one to set beside the others for it:
    made for a drive and a load this design does not have. None for every other. The rule is the
    one its exploration is offered by (library_sensing._no_pulse)."""
    if scheme != "compressor_smooth":
        return None
    speed = abs(design.omega)
    pulses = (
        design.load_at is not None
        and design.load_peak_at is not None
        and bool(speed)
        and design.load_peak_at(speed) > 1.05 * abs(design.load_at(speed))
    )
    if pulses and chosen(design)[0] == "sensorless_emf":
        return None
    return "made for a drive with no rotor sensor on a load whose torque rises and falls within each turn"


def presets(data: dict, workspace: Workspace) -> dict:
    """The scheme chosen for this design, the alternatives, and every kind of block."""
    notes = shape("presets", data)
    design, rest = _designed(data, workspace)
    rest["taken"] += notes
    first, why = chosen(design)
    # A scheme that reads what this motor does not have is not offered for it (injection, on a
    # motor whose two axes the controller holds alike); asked for by name, its block says why.
    schemes = [build(design) for name, build in BUILDERS.items() if offered(name, design)]
    by_id = {s.id: s for s in schemes}
    for scheme in schemes:
        compile_scheme(scheme, context(design, scheme))  # a preset that could not run is a fault, found here
    return {
        "chosen": first,
        "why": why,
        "schemes": [s.data() | {"tests": accepted(s), "aside": _aside(s.id, design)} for s in schemes],
        "blocks": {kind: describe(cls) for kind, cls in sorted(BLOCKS.items())},
        "sources": [{"name": name, "unit": unit, "about": about} for name, (unit, about) in SOURCES.items()],
        "scenarios": [
            {
                "kind": kind,
                "label": label,
                "about": about,
                "needs": needs,
                "fields": _fields(kind, scenario.defaults(kind, design, by_id[first])),
                "defaults": {s.id: scenario.defaults(kind, design, s) for s in schemes},
            }
            for kind, (label, about, needs) in SCENARIOS.items()
        ],
        "fidelities": list(FIDELITIES),
        "limits": {
            "duration": scenario.MOST_DURATION,
            "steps": MOST_STEPS,
            "points": MOST_POINTS,
            "seconds": RUN_BUDGET,
            "sweep_seconds": SWEEP_BUDGET,
        },
        "design": _design_out(design),
        "plant": _plant_out(design),
        "taken": rest["taken"],
    }


def _plant_out(design: Design) -> dict:
    """The motor and load as the engine can simulate them beyond the controller's own model:
    the shaft that twists (its figures as a form draws them, the resonance suggested being
    eight times the speed loop's rule bandwidth, where a stiff servo starts to ring) and the
    iron that saturates. Neither is simulated unless the request asks for it."""
    from motionsim.service.control.asking import COUPLING
    from motionsim.service.control.library_sensing import _speed_rule_hz

    suggested = {
        "resonance_hz": float(f"{8.0 * _speed_rule_hz(design):.3g}"),
        "motor_share": 0.3,
        "damping_ratio": 0.02,
        "backlash_deg": 0.0,
    }
    return {
        "coupling": [
            {"name": k, "unit": unit, "about": said, "default": suggested[k], "low": lo, "high": hi}
            for k, (unit, said, lo, hi) in COUPLING.items()
        ],
        "iron": {
            "choices": ["linear", "saturating"],
            "about": "linear: the inductances the controller is tuned with; saturating: they fall with the current, as "
            "is usual for this kind of motor, while the controller keeps its constant figures",
        },
    }


def loops(data: dict, workspace: Workspace) -> dict:
    """The linear analysis of a scheme for this design."""
    notes = shape("loops", data)
    design, rest = _designed(data, workspace)
    scheme = _notched(data, _scheme(data, design), rest["taken"])
    ctx = context(design, scheme)
    wc, around, rule = bandwidth(ctx.ts, ctx.delay)
    coupling = coupling_of(data, ctx.inertia, rest["taken"]) if ctx.inertia > 0 else None
    return {
        "taken": rest["taken"] + notes,
        "scheme": scheme.data(),
        "tuning": {"bandwidth_hz": wc / (2 * math.pi), "delay_s": around, "rule": rule},
        "tests": accepted(scheme),
        "simulated_by": simulated_by(scheme),
        **linear.loops(compile_scheme(scheme, ctx), ctx, coupling),
    }


def _engine(rest: dict, design: Design) -> dict | None:
    """The rest of the tool's answer at the design point, to set a held point beside."""
    from motionsim.drivers import at_speed_and_torque
    from motionsim.engine.limits import hottest
    from motionsim.service.shapes import _result

    found = at_speed_and_torque(rest["device"], rest["motor"], design.rpm, rest["torque"], rest["op"])
    shaped = _result(found.result, rest["device"].ratings.tj_max, rest["op"].parallel)
    return {
        "loss": shaped["loss"],
        "conduction": shaped["conduction"],
        "switching": shaped["switching"],
        "tj_peak": hottest(found.result),
        "ripple_pp": found.ripple_pp,
    }


def stability(compiled: Compiled, ctx: Context, found: dict | None = None, ratio: float | None = None) -> dict:
    """What the linear analysis says of the gains before the run: whether every closed loop
    it can work out has its poles inside the unit circle, and which pole is not, in words.
    Gains that do not hold are run all the same: the voltage limit holds such a loop in an
    oscillation short of running away, and that limit cycle is the thing to look at.
    The analysis takes each axis alone, as with the rotor still. Given the design's carrier
    ratio, under VERY_LOW_CARRIER_RATIO switching periods a turn it is said to be of the rotor
    still only: the turn within a period couples the axes, and the run is what shows it."""
    found = linear.loops(compiled, ctx) if found is None else found
    analysed = [name for key, name in LOOPS if found[key] is not None]
    for key, name in LOOPS:
        loop = found[key]
        if loop is None or loop["stable"]:
            continue
        worst = max(loop["poles"], key=lambda pole: math.hypot(pole["re"], pole["im"]))
        size = math.hypot(worst["re"], worst["im"])
        if size < 1.0 + ON_THE_CIRCLE:
            continue
        return {
            "linear_stable": False,
            "analysed": True,
            "loop": key,
            "pole": {"re": worst["re"], "im": worst["im"], "abs": size, "hz": worst["hz"]},
            "said": f"the loop is unstable with these gains by its linear analysis: the closed {name} loop has a "
            f"pole at |z| = {written(size, 3)}, outside the unit circle"
            + (f", an oscillation near {written(worst['hz'], 3)} Hz" if worst["hz"] else "")
            + ". The run goes ahead: what it shows is the oscillation the voltage limit holds that loop in",
        }
    if not analysed:
        why = found["missing"][0] if found["missing"] else "the scheme has no loop with a transfer function"
        return {"linear_stable": True, "analysed": False, "loop": None, "pole": None, "said": f"not analysed: {why}"}
    return {
        "linear_stable": True,
        "analysed": True,
        "loop": None,
        "pole": None,
        "said": f"every pole of the closed {' and '.join(analysed)} loop lies inside the unit circle"
        + (
            f" with the rotor still; at {written(ratio, 2)} switching periods a turn of the output the axes "
            "are coupled within a period, which this analysis leaves out: read the run"
            if ratio is not None and ratio < VERY_LOW_CARRIER_RATIO
            else ""
        ),
    }


@dataclass
class Ran:
    """A run that is over, with everything an answer is made from."""

    design: Design
    rest: dict
    scheme: Scheme
    kind: str
    asked: dict
    ctx: Context
    inverter: Inverter
    planned: scenario.Plan
    trace: Trace
    found: Cost
    rippled: dict | None
    checks: list[dict]
    stability: dict
    machine: Machine
    duration: float
    linear: dict | None = None  # the linear analysis of the scheme run
    pulsed: dict | None = None  # the current held against the pulsed rating, and the overshoot it was given
    floor: dict | None = None  # the observer's floor, and where the design and its motion sit against it
    window: dict | None = None  # how a run of a motion's window followed it
    coupling: Coupling | None = None  # the shaft that twisted, where the run had one

    @property
    def quality(self) -> dict | None:
        """The ripple a drive's running is read by; none of a trip, whose stretch is the stage
        switched off and the shaft coasting, not a drive's quality."""
        return None if self.kind == "trip" else self.rippled


def _sensing(trace: Trace, scheme: Scheme) -> dict | None:
    """How far an observer's angle and speed are from the rotor's, over the analysed stretch
    once the scheme is on the observer: an open-loop start's alignment, ramp and blend are left
    out, since the angle in use until then is the imposed one and not the observer's. None for
    a scheme that measures them, or one that never handed over."""
    observer = next((b for b in scheme.blocks if b.kind.startswith("observer_")), None)
    # Where the angle at standstill is injected for, the angle in use is the injection's,
    # blended over to the observer's at speed: read once the polarity is told.
    injected = next((b for b in scheme.blocks if b.kind == "hf_injection"), None)
    observer = injected or observer
    if observer is None:
        return None
    kept = trace.time >= trace.gather_from - 1e-12
    start = injected or next((b for b in scheme.blocks if b.kind == "if_startup"), None)
    if start is not None:
        kept &= trace.wire(f"{start.name}.mode") >= 1.0
    error = np.degrees(trace.wire(f"{observer.name}.error")[kept])
    speed = trace.wire(f"{observer.name}.omega_m")[kept] - trace.wire("plant.omega_m")[kept]
    if error.size == 0 and injected is not None:
        # Its side never told, the injection held the torque off: no angle was in use, and
        # what it told is said alone.
        return {"observer": observer.name, "polarity": float(trace.wire(f"{injected.name}.polarity")[-1])}
    if error.size == 0:
        return None
    return {
        "observer": observer.name,
        "from": float(trace.time[kept][0]),
        "angle_error_mean": float(error.mean()),
        "angle_error_rms": float(np.sqrt(np.mean(error * error))),
        "angle_error_peak": float(np.abs(error).max()),
        "speed_error_rms": float(np.sqrt(np.mean(speed * speed))),
        **(
            {}
            if injected is None
            else {
                # 1 the angle found was the magnet's, −1 it was turned, 0 the iron could not tell.
                "polarity": float(trace.wire(f"{injected.name}.polarity")[-1]),
                "injecting": float(np.mean(trace.wire(f"{injected.name}.share")[kept] < 1.0)),
            }
        ),
    }


def motor_loss(ran: Ran) -> dict:
    """What the motor itself loses over the analysed stretch: in its copper, from the
    simulated currents with their ripple, and in its iron, by the same rule the least-loss
    reference weighs (control/references.py), at the mean currents. `system` adds the inverter's."""
    trace, c = ran.trace, ran.trace.corners
    if c.shape[0] >= 2:
        t = c[:, 0]
        square = c[:, 6] ** 2 + c[:, 7] ** 2
        mean_square = float(np.sum(0.5 * (square[1:] + square[:-1]) * np.diff(t)) / (t[-1] - t[0]))
        i_d, i_q = float(np.mean(c[:, 6])), float(np.mean(c[:, 7]))
        speed = float(trace.wire("plant.omega_m")[-1])
    else:
        kept = trace.time >= trace.gather_from - 1e-12
        i_d, i_q = float(trace.wire("plant.i_d")[kept].mean()), float(trace.wire("plant.i_q")[kept].mean())
        mean_square, speed = i_d * i_d + i_q * i_q, float(trace.wire("plant.omega_m")[-1])
    copper = 1.5 * ran.machine.rs * mean_square
    iron = total_loss(replace(ran.ctx, stage=None), i_d, i_q, speed)[1]
    inverter = float(ran.found.result.p_inverter)
    return {"copper": copper, "iron": iron, "inverter": inverter, "system": copper + iron + inverter}


@dataclass
class Ready:
    """A run made ready and not yet started: everything the kernel is given."""

    design: Design
    rest: dict
    scheme: Scheme
    kind: str
    asked: dict
    ctx: Context
    compiled: Compiled
    inverter: Inverter
    planned: scenario.Plan
    stable: dict
    machine: Machine
    first: frozenset[str]
    linear: dict | None = None
    motion: Motion | None = None  # the design's own motion, where the request gives one
    coupling: Coupling | None = None  # the shaft that twists, where the request gives one

    @property
    def instants(self) -> int:
        """Sampling instants the run would go through, at the most."""
        steps = math.ceil(self.planned.test.duration / self.ctx.ts0 - 1e-9)
        return steps if self.compiled.period is None else 4 * steps

    @property
    def seconds(self) -> float:
        return seconds(self.instants, self.scheme.actuation["kind"])


def _notched(data: dict, scheme: Scheme, taken: list[str]) -> Scheme:
    """A notch with no centre set takes the shaft's resonance, where the request gives one."""
    given = (data.get("plant") or {}).get("coupling") if isinstance(data.get("plant"), dict) else None
    hz = given.get("resonance_hz") if isinstance(given, dict) else None
    if not isinstance(hz, (int, float)) or isinstance(hz, bool) or hz <= 0:
        return scheme
    blocks = []
    for b in scheme.blocks:
        if b.kind == "torque_notch" and not b.params.get("frequency"):
            b = replace(
                b,
                params={**b.params, "frequency": float(hz)},
                sources={**b.sources, "frequency": f"the shaft's resonance as the request gives it, {hz:g} Hz"},
            )
            taken.append(f"the notch {b.name} is set at the shaft's resonance, {hz:g} Hz")
        blocks.append(b)
    return replace(scheme, blocks=blocks)


LIGHTLY_DAMPED = 0.5  # a mode damped less than this is one a move leaves swinging


def _shaped(scheme: Scheme, analysis: dict, ts: float, taken: list[str]) -> Scheme:
    """An input shaper with no mode set takes the one the speed loop rings the load at: its least
    damped closed-loop pole pair with the shaft, under a quarter of the sampling rate."""
    open_ = [b for b in scheme.blocks if b.kind == "input_shaper" and not b.params.get("frequency")]
    if not open_:
        return scheme
    poles = (analysis.get("speed") or {}).get("poles") or []
    modes = [p for p in poles if p["im"] > 1e-12 and p["hz"] and p["damping"] is not None and 0 < p["hz"] < 0.25 / ts]
    mode = min(modes, key=lambda p: p["damping"], default=None)
    if mode is None or mode["damping"] >= LIGHTLY_DAMPED:
        taken.append(
            "the move is not shaped: the speed loop has no mode damped less than "
            f"{LIGHTLY_DAMPED:g} for it to leave still (a shaft that twists gives one)"
        )
        return scheme
    hz, zeta = float(f"{mode['hz']:.4g}"), float(f"{mode['damping']:.3g}")
    blocks = []
    for b in scheme.blocks:
        if b in open_:
            b = replace(
                b,
                params={**b.params, "frequency": hz, "damping": zeta},
                sources={
                    **b.sources,
                    "frequency": f"the speed loop's least damped mode with its shaft, {hz:g} Hz",
                    "damping": f"that mode's own, {zeta:g}",
                },
            )
            taken.append(
                f"the move is shaped for the swing the speed loop leaves the load in, {hz:g} Hz damped {zeta:g} "
                f"(its least damped mode with the shaft): it arrives {1e3 * _late(b.params, hz, zeta):.3g} ms later"
            )
        blocks.append(b)
    return replace(scheme, blocks=blocks)


def _late(params: dict, hz: float, zeta: float) -> float:
    """s, how much later a shaped move arrives: half the damped period (ZV), or the whole (ZVD)."""
    period = 1.0 / (hz * math.sqrt(1.0 - zeta * zeta))
    return 0.5 * period if params.get("shape") == "zv" else period


def prepared(data: dict, workspace: Workspace) -> Ready:
    """The request read, the scheme compiled and the test planned: all that is refused by
    name is refused here, before a single instant is simulated."""
    design, rest = _designed(data, workspace)
    scheme = _scheme(data, design)
    kind, asked = _asked(data, design, scheme)
    if kind == "start":
        scheme = limited(scheme, design, asked["current_limit"] * math.sqrt(2.0), scenario.LIMIT_SHAPES[asked["shape"]])
        design = replace(design, i_limit=asked["current_limit"] * math.sqrt(2.0))
    seed = _count(data.get("seed", 0), "seed", low=0, high=2**31 - 1, field="seed")
    inverter = _inverter(data, rest, design)
    taken = rest["taken"]
    scheme = _notched(data, scheme, taken)
    machine = _mismatch(data, design, taken)
    # What a probe carries of the controller as the run goes: the first output of every block.
    # (A kind there is no block of is refused where the scheme is compiled, below.)
    known = [b for b in scheme.blocks if b.kind in BLOCKS and BLOCKS[b.kind].outputs]
    first = frozenset(f"{b.name}.{BLOCKS[b.kind].outputs[0].name}" for b in known)
    ctx = context(design, scheme, seed)
    compiled = compile_scheme(scheme, ctx)
    if scheme.timing["update"] == "multi" and inverter.fidelity == "averaged":
        taken.append(
            "updated several times a carrier period, the averaged stage gives each slice the mean voltage the "
            "carrier lets through in it, not the edges themselves: close to the switched stage at four updates a "
            "period, and at eight it overshoots further than the switched stage does. Run it switched to see the "
            "compare values reloaded mid-slope as they fall"
        )
    if data.get("seed") not in (None, "", 0) and not any(b.p.get("noise") for b in compiled.blocks):
        taken.append(
            f"the seed {seed} has nothing to seed: no block of this scheme has noise on what it samples (the "
            "`noise` of `current_sampling` is nought), and the run is the same under every seed"
        )
    shaft = scenario.Shaft(design.shaft_inertia, _load_torque(rest["load"], design, taken))
    coupling = coupling_of(data, shaft.inertia, taken)
    # The linear analysis is of the shaft simulated: a twisting one where the run has one.
    analysis = linear.loops(compiled, ctx, coupling if ctx.inertia > 0 else None)
    shaped = _shaped(scheme, analysis, ctx.ts, taken)
    if shaped is not scheme:
        # The shaper is outside the loop: the analysis stands, the scheme is compiled with its mode.
        scheme, compiled = shaped, compile_scheme(shaped, ctx)
    stable = stability(compiled, ctx, analysis, design.f_sw / design.f_out if design.f_out > 0 else None)
    motion = motion_of(data, needed=kind == "motion")
    stretch = None
    if kind == "motion" and motion is not None:
        stretch, said = window_of(motion, asked["span"], asked["pick"])
        taken += said
    planned = scenario.plan(kind, asked, design, scheme, shaft, None, stretch)
    test = planned.test
    if test.fault is not None and test.fault[1] == "open_switch" and inverter.fidelity != "switched":
        inverter = replace(inverter, fidelity="switched")
        taken.append("an open switch has edges for the diodes to take over at: the stage is run switched")
    if test.duration > scenario.MOST_DURATION:
        raise Refusal(
            f"the test would last {written(test.duration, 3)} s, and {scenario.MOST_DURATION:g} s is the most",
            "shorten the test",
            "scenario.duration" if "duration" in asked else "scenario.settle",
        )
    window = _window(data, test.duration)
    if window is not None:
        test.detail = window
    return Ready(
        design,
        rest,
        scheme,
        kind,
        asked,
        ctx,
        compiled,
        inverter,
        planned,
        stable,
        machine,
        first,
        analysis,
        motion,
        coupling,
    )


def execute(data: dict, workspace: Workspace, ready: Ready | None = None) -> Generator[dict, None, Ran]:
    """A test run under a scheme, as far as the losses: each stretch said as it finishes. A
    run that would take longer than a run may is refused before it starts, by the sampling
    instants it would go through."""
    from motionsim.service.shapes import _checks
    from motionsim.service.verdict.common import _sound

    ready = ready or prepared(data, workspace)
    design, rest, scheme, kind, asked = ready.design, ready.rest, ready.scheme, ready.kind, ready.asked
    ctx, compiled, inverter, planned = ready.ctx, ready.compiled, ready.inverter, ready.planned
    stable, machine, first, test = ready.stable, ready.machine, ready.first, ready.planned.test
    if ready.instants <= MOST_STEPS and ready.seconds > RUN_BUDGET:
        raise over(ready.seconds, RUN_BUDGET, ready.instants, "the run goes through")
    plant = Plant(machine, planned.shaft.inertia, planned.shaft.load, planned.held, inverter.r_on, ready.coupling)
    kernel = Kernel(compiled, ctx, plant, inverter, test)
    try:
        for share in kernel.steps():
            yield {
                "progress": share,
                "t": plant.time,
                "series": report.series(kernel.so_far(), 200, ("plant.", "cmd."), first),
            }
    except Unstable as ran_away:
        # A loop that runs away after its observer lost the rotor is not a matter of gains.
        why = lost(compiled, kernel.so_far())
        if not why:
            raise
        raise Refusal(
            f"{ran_away.reason}, after {why[0]['message']}",
            "keep the test above that speed, or take a scheme with an encoder for it",
            "scenario",
        ) from None
    trace = kernel.trace()
    device, op = rest["device"], rest["op"]
    found = cost(device, trace, op)
    _sound(found.result)
    # A scheme that sets its own period is read over the periods it used.
    own = trace.time[:: 2 if scheme.timing["update"] == "double" else 1] if scheme.actuation.get("period") else None
    rippled = ripple(trace, design.pole_pairs, planned.window, own)
    pulsed, held = _pulsed(device, found.op, trace, planned, design, inverter.fidelity)
    checks = _checks(guard.check(device, found.op, found.result, **held))
    if not stable["linear_stable"]:
        checks.append({"level": "caution", "topic": "stability", "message": stable["said"], "field": "scheme"})
    floor = _floor(ready, rest)
    checks += tracking(kind, design, planned, trace, rippled, compiled, floor)
    return Ran(
        design,
        rest,
        scheme,
        kind,
        asked,
        ctx,
        inverter,
        planned,
        trace,
        found,
        rippled,
        checks,
        stable,
        machine,
        float(plant.time),
        ready.linear,
        pulsed,
        floor,
        followed(planned, trace, report.ripple_window(trace, design.f_sw, inverter.fidelity)),
        ready.coupling,
    )


def _floor(ready: Ready, rest: dict) -> dict | None:
    """The floor of the scheme's observer (control/floor.py) for this run and for a real stage,
    with where the design point, the open-loop start and the design's motion sit against it.
    None for a scheme that measures its angle."""
    from motionsim.control.floor import observer_floor, stage_error, uncompensated

    design, inverter, op = ready.design, ready.inverter, rest["op"]
    stage = stage_error(
        inverter.t_dead,
        inverter.v_drop,
        op.t_dead,
        design.v_drop,
        design.f_sw,
        design.v_dc,
        uncompensated(ready.compiled),
    )
    found = observer_floor(ready.compiled, stage, ready.machine.rs - ready.ctx.rs, design.i_design)
    if found is None:
        return None
    start = next((b for b in ready.scheme.blocks if b.kind == "if_startup"), None)
    back = 0.0
    if start is not None:
        from motionsim.control.startup import HYSTERESIS

        handover = float(start.params.get("handover", 0.0))
        back = min(float(start.params.get("handback", 0.0) or 0.0), HYSTERESIS * handover)
    to_rpm = 30.0 / math.pi / design.pole_pairs
    return found | {
        "design_rpm": abs(design.rpm),
        "handover_rpm": scenario.handover_rpm(design, ready.scheme),
        "handback_rpm": back * to_rpm,
        "motion": against_floor(ready.motion, found["hardware_rpm"]),
    }


def followed(planned: scenario.Plan, trace: Trace, window: float | None) -> dict | None:
    """How a run of a motion's window followed it: the error of the wire the scheme is
    commanded by (speed or torque), its rms and its largest, read on the mean over a switching
    period, with the other one's beside it; the most current a leg carried; the window's place
    in the motion."""
    from motionsim.control.metrics import moving_mean

    follows = planned.follows
    if follows is None or trace.time.size < 3:
        return None
    t = trace.time
    smooth = (lambda y: moving_mean(t, y, window)) if window else (lambda y: y)
    speed = smooth(trace.wire("plant.omega_m")) - np.array([follows.speed(x) for x in t])
    torque = smooth(trace.wire("plant.torque")) - np.array([follows.torque(x) for x in t])
    w = follows.window
    # A mission's command steps at its instants: the error is read once the loop has had its
    # time to rise to each step (follows.rise), not while no drive could yet have made it.
    read = np.ones(t.size, dtype=bool)
    if follows.rise > 0:
        for step in w.t[(w.t > w.start) & (w.t < w.end)] - w.start:
            read &= ~((t >= step) & (t < step + follows.rise))
        if not read.any():
            read[:] = True

    def error(e: np.ndarray, scale: float) -> dict:
        e = np.where(read, e, 0.0)
        return {
            "rms": float(np.sqrt(np.sum(e * e) / np.sum(read))) * scale,
            "peak": float(np.max(np.abs(e))) * scale,
            "at": float(t[int(np.argmax(np.abs(e)))]),
        }

    return {
        "from": w.start,
        "to": w.end,
        "pick": w.pick,
        "at": w.at,
        "peak_torque": w.peak,
        "rate": w.rate,
        "top_rpm": float(np.max(np.abs(w.rpm[(w.t >= w.start) & (w.t <= w.end)]))) if w.t.size else 0.0,
        "wire": follows.wire,
        "rise": follows.rise,
        "speed_error": error(speed, 30.0 / math.pi),
        "torque_error": error(torque, 1.0),
        "i_peak": float(np.max(trace.peak)),
    }


TORQUE_STEP_RUN = "this run's torque step"


def _pulsed(device, op, trace: Trace, planned: scenario.Plan, design: Design, fidelity: str) -> tuple[dict, dict]:
    """What the pulsed rating is held to in this run, and the figures guard.check is given
    for it. After a torque step the run's own overshoot of the current takes the place of the
    fixed allowance (guard.OVERSHOOT): the current it settled to, the share it passed that by,
    and the switching ripple on top of its peak. Any other test makes no step of the current
    against a reference, so the run's peak is held with the allowance, and the answer says so."""
    from motionsim.engine.solver import hot_share

    peak = float(max(trace.peak))
    rating = device.ratings.i_pulsed
    each = hot_share(device, max(int(op.parallel), 1))
    found = current_overshoot(planned, trace, report.ripple_window(trace, design.f_sw, fidelity))
    if found is None:
        held = peak * (1.0 + guard.OVERSHOOT)
        out: dict[str, Any] = {"overshoot": guard.OVERSHOOT, "measured": False, "settled": peak, "ripple_half": 0.0}
        given: dict = {"i_peak": peak}
    else:
        half = max(peak - found["peak"], 0.0)
        held = found["peak"] + half
        out = {"overshoot": found["share"], "measured": True, "settled": found["settled"], "ripple_half": half}
        given = {
            "i_peak": found["settled"],
            "ripple_pp": 2.0 * half,
            "overshoot": found["share"],
            "overshoot_from": TORQUE_STEP_RUN,
        }
    out |= {
        "allowance": guard.OVERSHOOT,
        "held": held * each,
        "rating": rating,
        "room": None if rating is None else rating - held * each,
    }
    return out, given


def shorted_current(design: Design, omega_e: float) -> float:
    """A peak: where the shorted winding's current settles at a held speed, by the motor's figures,
    0 = Rs·id − ωe·Lq·iq and 0 = Rs·iq + ωe·(Ld·id + ψ). At speed it tends to ψ/Ld."""
    r, ld, lq, psi = design.rs, design.ld, design.lq, design.psi
    under = r * r + omega_e * omega_e * ld * lq
    return abs(omega_e) * psi * math.hypot(omega_e * lq, r) / under if under > 0 else 0.0


def _tripped(ran: Ran) -> dict | None:
    """What a trip did: the safe states the stage went to, the most current a phase carried after
    it and where the current settled, the torque that braked the shaft and what went back into the
    DC link."""
    if ran.kind != "trip":
        return None
    trace, design, at = ran.trace, ran.design, ran.planned.test.gather_from
    after = trace.time >= at
    if not after.any():
        return None
    codes = sorted({int(c) for c in trace.wire("inverter.safe")[after][1:]} - {0})
    omega = ran.asked["rpm"] * math.pi / 30.0
    w_e = design.pole_pairs * omega
    sign = 1.0 if omega >= 0 else -1.0
    brake = -sign * trace.wire("plant.torque")[after]
    tail = after & (trace.time >= at + 0.8 * (trace.time[-1] - at))
    link = trace.wire("inverter.i_link")[after]
    i_d, i_q = trace.wire("plant.i_d"), trace.wire("plant.i_q")
    corners = trace.corners
    died = None
    if corners.size:
        moving = np.abs(corners[:, 1:4]).max(axis=1)
        top = moving.max()
        quiet = np.nonzero(moving <= 0.01 * top)[0] if top > 0 else np.array([], dtype=int)
        if quiet.size and np.all(moving[quiet[0] :] <= 0.01 * top):
            died = float(corners[quiet[0], 0] - at)
    return {
        "t_trip": at,
        "rpm": ran.asked["rpm"],
        "safe": ran.asked["safe"],
        "states": [("off", "short")[c - 1] for c in codes],
        "bridge_rpm": bridge_speed(design.psi, design.v_dc, design.v_drop) / design.pole_pairs * 30.0 / math.pi,
        "i_peak": float(np.max(trace.peak)),
        "i_settled": float(math.hypot(i_d[-1], i_q[-1])),
        "i_short": shorted_current(design, w_e),
        "i_motor": design.i_limit,
        "i_design": design.i_design,
        "brake_peak": float(np.max(brake)),
        "brake_settled": float(brake[tail[after]].mean()) if tail.any() else float(brake[-1]),
        "link_peak": float(np.max(link)),
        "link_mean": float(link.mean()),
        "link_energy": float(design.v_dc * link.sum() * ran.ctx.ts0),
        "died": died,
        **_linked(ran, omega),
        **_seen(ran, at),
        **_fallen(ran, after),
    }


def _seen(ran: Ran, at: float) -> dict:
    """A frozen encoder: when the drive's check saw it (the period before the stage first stood in
    a safe state), how far the rotor had turned unseen by then, and the speed under which the
    back-EMF is too small beside the stage's own errors for the check to judge."""
    from motionsim.control.faults import FLOOR

    test, trace, design = ran.planned.test, ran.trace, ran.design
    if test.fault is None:
        return {"cause": "protection"}
    tripped = np.nonzero(trace.wire("inverter.safe") > 0)[0]
    seen = float(trace.time[tripped[0]] - ran.ctx.ts0 - at) if tripped.size else None
    w_e = design.pole_pairs * abs(ran.asked["rpm"]) * math.pi / 30.0
    if test.fault[1] == "open_switch":
        return {"cause": "open_switch", "seen": seen, "seen_turns": w_e * seen / (2.0 * math.pi) if seen else None}
    floor = FLOOR * design.v_dc / math.sqrt(3.0) / design.psi / design.pole_pairs * 30.0 / math.pi
    return {
        "cause": "encoder",
        "seen": seen,
        "seen_deg": math.degrees(w_e * seen) if seen is not None else None,
        "seen_floor_rpm": floor,
    }


def _linked(ran: Ran, omega: float) -> dict:
    """The DC link the motor charged, by the supply: a battery takes the current back as charge;
    a supply that takes nothing back leaves the capacitor to charge until the bridge stops
    conducting, where the magnet's line voltage at its peak, √3·ωe·ψ, is the link's and two
    diodes' drops."""
    design, device = ran.design, ran.rest.get("device")
    supply = ran.rest.get("supply") or "one-way"
    line = math.sqrt(3.0) * design.pole_pairs * abs(omega) * design.psi - 2.0 * design.v_drop
    settles = line if supply != "battery" and line > design.v_dc else None
    return {
        "supply": supply,
        "v_link_settles": settles,
        "v_rating": float(device.ratings.v_max) if device is not None else None,
    }


BRAKE_SETTLE = 0.02  # s after the brake bites by which a brake that holds has stopped the shaft


def _fallen(ran: Ran, after) -> dict:
    """On a free shaft, how far the shaft turned once the drive let go, at the motor and at the
    load, how fast it went, and how far it had turned when the holding brake bit."""
    test, trace, design = ran.planned.test, ran.trace, ran.design
    if ran.asked.get("shaft") != "free":
        return {}
    angle = trace.wire("plant.theta_e")[after] / design.pole_pairs
    speed = trace.wire("plant.omega_m")[after]
    time = trace.time[after]
    turned = np.abs(angle - angle[0])
    at_brake = None
    if test.brake is not None:
        bitten = time >= test.brake[0]
        at_brake = float(turned[bitten][0]) if bitten.any() else None
    fall = float(turned[-1])
    # Once the brake has held a while: how far the shaft still moved, which a brake that holds keeps at nought.
    held = time >= (test.brake[0] + BRAKE_SETTLE) if test.brake is not None else time < 0
    creep = float(turned[-1] - turned[held][0]) if held.any() else None
    return {
        "fall": fall,
        "fall_deg": math.degrees(fall) / design.gear,
        "fall_at_brake": at_brake,
        "fall_peak_rpm": float(np.max(np.abs(speed))) * 30.0 / math.pi,
        "rpm_end": float(speed[-1]) * 30.0 / math.pi,
        "creep": creep,
        "brake_delay": ran.asked.get("brake_delay") if test.brake is not None else None,
    }


def _start(ran: Ran) -> dict:
    """The point the test begins at, in the same figures as `settled`: the running drive it
    starts from, or rest."""
    test = ran.planned.test
    if test.settled is not None:
        return dict(test.settled)
    still: dict[str, Any] = dict.fromkeys(
        ("i_d", "i_q", "v_d", "v_q", "torque", "f_out", "i_rms", "modulation_index", "field_weakening"), 0.0
    )
    return still | {"omega_m": float(test.initial.get("omega_m", 0.0))}


def run_steps(data: dict, workspace: Workspace) -> Generator[dict, None, dict]:
    """A test run under a scheme: each stretch said as it finishes, and the answer returned."""
    from motionsim.service.shapes import _result, level_of

    notes = shape("run", data)
    points = _count(data.get("points", 500), "points", low=10, high=MOST_POINTS, field="points")
    ran = yield from execute(data, workspace)
    ran.rest["taken"] += notes
    design, rest, trace, found, test = ran.design, ran.rest, ran.trace, ran.found, ran.planned.test
    device, op = rest["device"], rest["op"]
    detail = test.detail or (0.0, test.duration)
    answer = {
        "scheme": ran.scheme.data(),
        "scenario": {"kind": ran.kind, **ran.asked},
        "fidelity": ran.inverter.fidelity,
        "taken": rest["taken"] + ran.planned.said,
        "timing": {
            "ts": ran.ctx.ts0,
            "f_control": 1.0 / ran.ctx.ts0,
            "steps": int(trace.time.size),
            "duration": ran.duration,
            "ended": trace.ended,
            "analysed_from": test.gather_from,
        },
        "settled": scenario.settled(design, design.rpm, design.torque),
        "start": _start(ran),
        "stability": ran.stability,
        "engine": _engine(rest, design) if ran.kind == "hold" else None,
        "wires": report.wires(ran.scheme),
        "series": report.series(trace, points),
        "switches": report.switches(found, points),
        "waveform": report.waveform(trace, detail),
        "losses": {
            **_result(found.result, device.ratings.tj_max, op.parallel),
            "p_motor": found.p_motor,
            "per_switch": report.per_switch(found, trace),
        },
        "motor_loss": motor_loss(ran),
        "thermal": report.thermal(found, points),
        "channels": report.channels(trace, found, ran.quality, steady=ran.kind == "hold"),
        "ripple": ran.quality,
        "sensing": _sensing(trace, ran.scheme),
        "step": report.tracked(
            trace, ran.planned.tracked, report.ripple_window(trace, ran.design.f_sw, ran.inverter.fidelity)
        ),
        "checks": ran.checks,
        "level": level_of(ran.checks),
        "pulsed": ran.pulsed,
        "floor": ran.floor,
        "window": ran.window,
        "trip": _tripped(ran),
    }
    answer["quality"] = quality(ran, answer)
    link = linking.linked(ran, data, workspace)
    if link is not None:
        linking.with_link(answer, link.through, report.thinned(trace.time.size, points))
        answer["link"] = answer["quality"]["link"] = link.read
    answer["verdict"] = verdict.judge(answer["quality"])
    return answer


def run(data: dict, workspace: Workspace) -> dict:
    """The answer of a run, its progress left unsaid."""
    steps = run_steps(data, workspace)
    while True:
        try:
            next(steps)
        except StopIteration as done:
            return done.value
