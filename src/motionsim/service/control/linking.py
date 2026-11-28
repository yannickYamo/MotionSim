"""The DC link of a run, where the drive is fed from the mains: the front end's control run
on what the motor's control drew, with the two tied as the design ties them."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from motionsim import front_end as fe
from motionsim.control import front_end as control
from motionsim.control.codegen import front_end as codegen
from motionsim.errors import Refusal
from motionsim.service import front_end as service
from motionsim.service.validate import _number
from motionsim.service.workspace import Workspace

# The link's movement at twice the mains that a capacitor is sized for where none is given,
# peak to peak, as a share of the link's voltage; three phases draw a steady power and are
# given a quarter of that capacitance.
RIPPLE = 0.05
# Hz, the most the front end's controller is sampled at: a stage that switches faster is still
# controlled at this rate, and a run's cost stays bounded.
MOST_RATE = 100e3
LINK_WIRES = (
    ("link.v_dc", "V", "the DC link's voltage, as the front end holds it"),
    ("link.p_in", "W", "the power drawn from the mains"),
    ("link.i_line", "A", "the current in one line of the mains"),
)


def tied(data: dict) -> bool:
    """Whether the front end is told what the motor's control is about to draw. The design's
    word is kept; with none, it is told, except where the load swings within a turn (a
    compressor's): told, the stage would draw that swing from the mains and bend its current,
    and the link capacitor is left to take it."""
    given = (data.get("front_end") or {}).get("feed_forward")
    if given in (None, ""):
        swing = ((data.get("load") or {}).get("pulsation") or {}).get("torque")
        return not swing
    if given in (True, "on"):
        return True
    if given in (False, "off"):
        return False
    raise Refusal(f"the tie of the two controls is on or off, not {given}", "on or off", "front_end.feed_forward")


def drawn(ran) -> tuple[np.ndarray, np.ndarray]:
    """What the inverter drew from the link at each instant of a run, W: the shaft's power,
    what the winding lost, and the stage's own mean loss."""
    trace = ran.trace
    shaft = trace.wire("plant.torque") * trace.wire("plant.omega_m")
    copper = 1.5 * ran.machine.rs * (trace.wire("plant.i_d") ** 2 + trace.wire("plant.i_q") ** 2)
    return trace.time, shaft + copper + float(ran.found.result.p_inverter)


def sized_capacitance(line: fe.Mains, v_dc: float, power: float) -> float:
    c = power / (2.0 * math.pi * line.f * v_dc * v_dc * RIPPLE)
    return c if line.phases == 1 else c / 4.0


@dataclass
class Link:
    """The link through a run: what the verdict reads, the traces, the controller's gains (None
    for a rectifier), the mains, and the power drawn as the run begins."""

    read: dict
    through: control.Linked
    gains: control.Gains | None
    line: fe.Mains
    p_start: float


def linked(ran, data: dict, workspace: Workspace, record: int = 0) -> Link | None:
    """The link through a run; None where the drive is not fed from the mains. record: how many
    of the controller's samples to keep, for its C's replay."""
    if data.get("supply") != "mains" or ran.kind == "trip":
        return None
    try:
        answer = service.front_end(data, workspace)
    except Refusal:
        return None
    line = service.mains(data)
    kind = fe.TOPOLOGIES[answer["chosen"]]
    result = answer["result"]
    time, power = drawn(ran)
    if time.size < 2 or not np.isfinite(power).all():
        return None  # a run that broke down says nothing of the link
    # Sized and tuned for the most the drive's control can ask at the design speed (its torque
    # limit over the design torque, on the design point's power), whatever the test.
    design = ran.design
    most = max(abs(design.torque_limit) / max(abs(design.torque), 1e-9), 1.0)
    rated = max(float(result["p_link"]) * most, 1.0)
    v_dc = float(result["v_dc"])
    given = result["capacitor"]["capacitance"]
    capacitance = float(given) if given else sized_capacitance(line, v_dc, rated)
    # A sweep's share of it: a smaller or an aged capacitor under the controller tuned for the whole.
    share = _number(
        data.get("link_share") or 1.0, "the share of the link capacitance", low=0.05, high=100, field="link.capacitance"
    )
    gains = None
    if kind.shapes:
        inductor = result["inductor"]
        gains = control.tuned(
            line,
            v_dc,
            rated,
            # Cells side by side on one phase act as one of their inductance shared between them.
            float(inductor["henry"]) / (float(inductor["count"]) if line.phases == 1 else 1.0),
            capacitance,
            # The controller runs once a switching period, up to MOST_RATE.
            min(float(result["f_sw"]), MOST_RATE),
            returns=kind.returns,
            feed_forward=tied(data),
        )
    capacitance *= share
    through = control.link_through(line, kind.shapes, gains, capacitance, time, power, v_start=v_dc, record=record)
    read = {
        "stage": kind.id,
        "name": kind.name,
        "shapes": kind.shapes,
        "returns": kind.returns,
        "phases": line.phases,
        "f": line.f,
        "feed_forward": bool(gains and gains.feed_forward),
        "v_ref": through.v_ref,
        "v_min": through.v_min,
        "v_max": through.v_max,
        "ripple": through.ripple,
        "thd": through.thd,
        "i_peak": through.i_peak,
        "c": capacitance,
        "c_sized": not given or bool(result["capacitor"]["sized"]),
        "need": service._Design(data, workspace).least(v_dc),
        # How far the motor's power moves over the last period of the mains, and its mean there.
        "p_swing": float(np.ptp(power[time >= time[-1] - 1.0 / line.f])),
        "p_mean": float(np.mean(power[time >= time[-1] - 1.0 / line.f])),
        "v_rating": float(ran.rest["device"].ratings.v_max),
        "braked": bool(power.min() < 0.0),
        "collapsed": through.collapsed,
        "choke": kind.id == "six_pulse",
    }
    return Link(read, through, gains, line, float(power[0]))


def with_link(answer: dict, through: control.Linked, places: np.ndarray) -> None:
    """The link's traces among a run's wires, at the instants the others are kept at."""
    answer["wires"] += [{"name": n, "unit": u, "block": "link", "about": about} for n, u, about in LINK_WIRES]
    values = {"link.v_dc": through.v_dc, "link.p_in": through.p_in, "link.i_line": through.i_line}
    for name, column in values.items():
        answer["series"]["wires"][name] = column[places].tolist()


def c_files(link: Link, design_lines: list[str]) -> dict[str, str]:
    """The front end's controller as C with its replay, for the bundle; none for a rectifier,
    which has no control."""
    if link.gains is None:
        return {}
    read = link.read
    tie = "told the power the motor's control draws (p_ff)" if read["feed_forward"] else "not told the motor's power"
    lines = [
        f"{read['name']} on {link.line.v_rms:.6g} V, {link.line.f:.6g} Hz, "
        + ("three phases" if link.line.phases == 3 else "one phase"),
        f"the DC link held at {read['v_ref']:.6g} V on {read['c'] * 1e6:.6g} uF; {tie}",
        *design_lines,
    ]
    peak = math.sqrt(2.0) * link.line.v_phase
    return codegen.files(link.gains, peak, link.through, read["v_ref"], link.p_start, lines)


def c_readme(link: Link, replay: dict) -> list[str]:
    """The README's section on the front end's controller."""
    g, read = link.gains, link.read
    assert g is not None
    fast = (
        "`fe_fast(&s, v_in, i_l, v_dc)` returns the boost switch's duty cycle from the rectified mains voltage, the "
        "inductor's current and the link's voltage"
        if g.phases == 1
        else "`fe_fast3(&s, e, i, v_dc, duty)` gives each leg's duty cycle from the mains voltages to neutral, the "
        "line currents into the stage and the link's voltage"
    )
    return [
        "## The front end's controller",
        "",
        f"`front_end/motionsim_front_end.c` is the controller of the stage that feeds this drive from the mains "
        f"({read['name']}), tuned for this design: the DC link held at {read['v_ref']:.6g} V, its loop crossing over "
        f"at {control.LINK_LOOP * read['f']:.3g} Hz, the current's at {control.CURRENT_LOOP / g.ts:.4g} Hz.",
        "",
        f"- Every {g.ts * 1e6:.6g} µs (once a switching period, up to {MOST_RATE / 1e3:.0f} kHz): {fast}.",
        f"- Every {g.slow} of those, before the fast loop: `fe_slow(&s, v_dc, p_ff)`, the link's loop.",
        "- `p_ff` is the tie to the motor's control: the power the inverter is about to draw from the link, W. "
        "From the motor's controller it is 1.5·(v_d·i_d + v_q·i_q) with the voltages it asks for and the currents "
        "it reads; given it, the front end raises its power as the load comes on and the link does not have to "
        "fall first. In the simulation the front end is given exactly what the inverter draws, at the instant "
        "it draws it: a figure made in the controller is a little off and a sample late, and holds the link a "
        "little less well. "
        + (
            "This design uses it."
            if read["feed_forward"]
            else "This design does not use it: p_ff is read and left out."
        ),
        "- `fe_settle(&s, v_dc, p)` starts it as a stage already holding the link.",
        "",
        "Verified as the motor's controller is: the C was given the samples the simulation's controller was given "
        f"from its settled state on (the mains periods before the test, then the test as far as the samples reach) and "
        "past its limits (a feed forward beyond the most power, braking, a link far off its set point, a current "
        "that does not follow), and the power it asks for and its duty cycles held to the simulation's: to rounding in double precision, "
        "and to half a percent of full scale in single, where a float's rounding decides a sample sooner or later "
        f"whether the integrator holds as the duty cycle meets its limit at the mains' zero crossings. {replay['said']}.",
        "",
        "Not covered: the stage is simulated averaged over a switching period (no ripple of its own, no dead time), "
        "the mains is stiff and balanced, the start-up from an uncharged link and the protections are not written, "
        "and what turns a duty cycle into gate signals is outside this file. On a totem-pole `i_l` is the line "
        "current times the sign of the mains voltage, the duty cycle changes switch each half period and the "
        "line-frequency leg follows that sign. On interleaved cells `i_l` is the sum of their currents and each "
        "cell takes the duty cycle half a period apart. On a Vienna rectifier `duty` is the mean voltage asked of "
        "each leg, as a share of the link, and the three-level modulator that makes it is not written.",
        "",
    ]
