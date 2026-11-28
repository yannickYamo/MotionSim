"""What a simulated run costs in the switches: its currents and commutations handed to the
tool's own loss model and thermal network. No loss formula is written here.

The engine takes a power stage as roles (engine/modulation.Role): for each switch position,
through a period, the current it carries, the share of each switching period it carries it
forwards and backwards, whether it commutates, and the current at its turn-on and turn-off.
An imported trajectory is turned into six such roles (trajectory.roles), one a position;
a simulated run is turned into the same six, from what the kernel gathered:

- `current`: the root mean square of the leg's current over the time the position carried
  it, in each bin: conduction comes from the simulated i(t), ripple included;
- `d_switch`, `d_reverse`: the share of the bin it carried it forwards and backwards;
- `switch_events`, `reverse_events`: its commutations in the bin, counted (a turn-on and a
  turn-off make one) and set against the carrier frequency the engine multiplies by, so a
  scheme with no carrier is charged for the commutations it really made;
- `current_on`, `current_off`: the mean of the current at the leg's hard turn-ons and at
  its hard turn-offs in the bin.

From there on it is the engine: `solve_roles` settles losses and junction temperatures
together (conduction along the ripple, switching energy at the current switched, the
reverse path and the dead time as it splits them), and the junctions are followed from a
cold start as an imported trajectory's are (trajectory._followed).

A scheme that sets its own switching frequency gathers bins of unequal time: they are
brought back to equal stretches first (`_even`), every integral kept.

Left out: a bin holds whole sampling periods, so a loss that is not a straight line in the
current is read at the bin's mean currents; a run of more than 8192 sampling periods has
several to a bin. A turn-on and a turn-off are charged in pairs, as the engine does: where a
bin has one without the other (the current changes sign inside it), half a pair is charged.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from motionsim import trajectory
from motionsim.control.kernel import Trace
from motionsim.device.schema import Device
from motionsim.engine.modulation import Role
from motionsim.engine.notes import Code, Note
from motionsim.engine.point import OperatingPoint, Result
from motionsim.engine.solver import package_waves, shared_time, solve_roles, thermal_network
from motionsim.errors import Refusal

LEGS = "abc"


def _over(top: np.ndarray, under: np.ndarray, otherwise: np.ndarray | float = 0.0) -> np.ndarray:
    """top / under where under is above nought, `otherwise` where it is not."""
    safe = np.where(under > 0, under, 1.0)
    return np.where(under > 0, top / safe, otherwise)


def _even(trace: Trace) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """What the kernel gathered, in bins of equal time: seconds, conducting, squared, events,
    switched and energy. The loss engine reads a period as equal stretches of time. Where
    the sampling period moved through the run, a bin of so many sampling periods spans more
    or less time than its neighbours: each gathered integral is then shared out over as many
    equal stretches, taken to have built up evenly within its bin, so that every integral
    over the whole run is kept."""
    seconds = trace.bin_seconds
    gathered = (trace.conducting, trace.squared, trace.events, trace.switched, trace.energy)
    if seconds.size < 2 or float(np.ptp(seconds)) <= 1e-9 * float(seconds.max()):
        return (seconds, *gathered)
    ends = np.cumsum(seconds)
    edges = np.concatenate([[0.0], ends])
    even = np.linspace(0.0, ends[-1], seconds.size + 1)

    def shared(x: np.ndarray) -> np.ndarray:
        built = np.concatenate([np.zeros((1, *x.shape[1:])), np.cumsum(x, axis=0)])
        if x.ndim == 1:
            return np.diff(np.interp(even, edges, built))
        return np.diff(np.stack([np.interp(even, edges, built[:, j]) for j in range(x.shape[1])], axis=1), axis=0)

    conducting, squared, events, switched, energy = (shared(x) for x in gathered)
    return np.diff(even), conducting, squared, events, switched, energy


def roles(trace: Trace) -> list[Role]:
    """The six switch positions of the stage, each with what it did in every bin."""
    seconds, conducting, squared, events, switched, _ = _even(trace)
    periods = seconds * trace.f_ref
    out = []
    for k, leg in enumerate(LEGS):
        t, q = conducting[:, 4 * k : 4 * k + 4], squared[:, 4 * k : 4 * k + 4]
        n, s = events[:, 4 * k : 4 * k + 4], switched[:, 4 * k : 4 * k + 4]
        high_pairs, low_pairs = 0.5 * (n[:, 0] + n[:, 1]) / periods, 0.5 * (n[:, 2] + n[:, 3]) / periods
        for side, forwards, backwards, pairs, other in (
            ("high", 0, 1, high_pairs, low_pairs),
            ("low", 3, 2, low_pairs, high_pairs),
        ):
            carried = t[:, forwards] + t[:, backwards]
            current = np.sqrt(_over(q[:, forwards] + q[:, backwards], carried))
            out.append(
                Role(
                    f"leg {leg.upper()} {side} side",
                    1,
                    current,
                    t[:, forwards] / seconds,
                    t[:, backwards] / seconds,
                    pairs,
                    other,
                    leg=leg,
                    # A leg's hard turn-on is its high switch's or its low switch's, by the
                    # current's direction; both positions of the leg read the same.
                    current_on=_over(s[:, 0] + s[:, 2], n[:, 0] + n[:, 2], current),
                    current_off=_over(s[:, 1] + s[:, 3], n[:, 1] + n[:, 3], current),
                )
            )
    return out


@dataclass(frozen=True)
class Cost:
    """A run's losses and temperatures."""

    result: Result  # the gathered stretch taken to repeat without end
    roles: list[Role]
    op: OperatingPoint  # the conditions the engine was asked under
    time: np.ndarray  # s, the end of each bin
    tj_from_start: np.ndarray  # °C, hottest junction through the stretch from a cold start
    switch_span: tuple[float, float]  # °C, the hottest switch once the stretch has repeated: lowest, highest
    p_motor: float  # W, mean power into the motor's terminals


def cost(device: Device, trace: Trace, op: OperatingPoint) -> Cost:
    """Losses and junction temperatures of a run, from the engine. op supplies the DC
    voltage, the gate drive, the dead time the losses are charged for and the cooling."""
    bins = trace.bin_seconds.size
    if bins < 2:
        raise Refusal(
            "the run is too short to work its losses out: it holds fewer than two sampling periods",
            "lengthen the test",
            "scenario.duration",
        )
    stage = roles(trace)
    span = float(trace.bin_seconds.sum())
    dt = span / bins
    p_motor = float(trace.energy.sum() / span)
    op = replace(op, f_sw=trace.f_ref)
    result = solve_roles(
        device,
        stage,
        op,
        period=span,
        p_out=p_motor,
        extra_notes=[
            Note(
                Code.trajectory_repeats,
                "trajectory",
                "control run: the simulated stretch is taken to repeat without end for the losses and "
                "settled temperatures",
            )
        ],
    )
    chips = {"switch": device.switch} | ({"diode": device.diode} if device.diode is not None else {})
    networks = {name: thermal_network(device, chip)[0] for name, chip in chips.items()}
    tau = shared_time(device, op)
    shared = package_waves(device, stage, result, op)
    hottest = np.full(bins, op.t_sink)
    followed, spans = [], []
    for role, role_shared in zip(result.roles, shared, strict=True):
        peaks, swing = trajectory._followed(role, role_shared, networks, tau, dt, hottest)
        spans.append(swing)
        followed.append(
            replace(role, tj_switch_peak=peaks["switch"], tj_diode_peak=peaks.get("diode", peaks["switch"]))
        )
    worst = max(followed, key=lambda r: r.hottest)
    moved = worst.hottest - max(result.tj_switch_peak, result.tj_diode_peak)
    result = replace(
        result,
        roles=followed,
        switch=worst.switch,
        diode=worst.diode,
        tj_switch=worst.tj_switch,
        tj_diode=worst.tj_diode,
        tj_switch_peak=worst.tj_switch_peak,
        tj_diode_peak=worst.tj_diode_peak,
        t_case=worst.t_case,
        tj_peak_range=None
        if result.tj_peak_range is None
        else (result.tj_peak_range[0] + moved, result.tj_peak_range[1] + moved),
    )
    time = trace.gather_from + dt * np.arange(1, bins + 1)
    return Cost(result, stage, op, time, hottest, max(spans, key=lambda s: s[1]), p_motor)
