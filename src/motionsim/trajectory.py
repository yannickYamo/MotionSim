"""Losses and temperatures along an imported trajectory.

A trajectory is what another simulator or a drive's own log gives: phase
currents and duty cycles against time. It lets the device model be judged on
the real control behaviour (current ripple of a speed loop, a field-weakening
transient, a fault ride-through) without this tool simulating the controller.

The file is a table with a header row:

    time_s, i_a, d_a [, i_b, d_b, i_c, d_c]

- i_x: current out of leg x, in A, averaged over each PWM period;
- d_x: fraction of each PWM period for which leg x's high-side switch is on.

Any number of legs from one to four, lettered from a. Duty cycles are wanted,
not gate signals: the trace must not resolve individual switching edges.

Each leg gives two positions, high side and low side. With current flowing
out of the leg, the high-side switch carries it while on and the low-side
reverse path carries it otherwise; with current flowing in, the low-side
switch and the high-side reverse path do.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from motionsim.device.schema import Device
from motionsim.engine.modulation import Role
from motionsim.engine.solver import OperatingPoint, Result, solve_roles, thermal_network
from motionsim.text import written
from motionsim.transient import ChipState

LEGS = "abcd"
MAX_SAMPLES = 8192


class BadTrajectory(ValueError):
    pass


@dataclass(frozen=True)
class Trajectory:
    time: np.ndarray  # s, uniform, starting at zero
    current: dict[str, np.ndarray]  # A out of each leg
    duty: dict[str, np.ndarray]  # high-side on fraction of each leg

    @property
    def duration(self) -> float:
        return float(self.time[-1] + (self.time[1] - self.time[0]))

    @property
    def legs(self) -> list[str]:
        return list(self.current)


def load_trajectory(path: str | Path) -> Trajectory:
    with open(path, newline="", encoding="utf-8") as f:
        rows = [row for row in csv.reader(f) if row and not row[0].lstrip().startswith("#")]
    if len(rows) < 3:
        raise BadTrajectory("a trajectory needs a header row and at least two rows of data")
    header = [name.strip().lower() for name in rows[0]]
    if header[0] != "time_s":
        raise BadTrajectory("the first column must be time_s")
    try:
        data = np.array([[float(v) for v in row] for row in rows[1:]])
    except ValueError as exc:
        raise BadTrajectory(f"not a number: {exc}") from exc
    if data.shape[1] != len(header):
        raise BadTrajectory("every row must have as many values as the header has names")
    columns = dict(zip(header, data.T))
    legs = [leg for leg in LEGS if f"i_{leg}" in columns]
    if not legs:
        raise BadTrajectory("no current column found: expected i_a, with d_a")
    for leg in legs:
        if f"d_{leg}" not in columns:
            raise BadTrajectory(f"current i_{leg} has no duty cycle d_{leg}")
        duty = columns[f"d_{leg}"]
        if duty.min() < -1e-6 or duty.max() > 1 + 1e-6:
            raise BadTrajectory(f"d_{leg} must lie between 0 and 1: it is a fraction of the PWM period")
    time = columns["time_s"]
    if np.any(np.diff(time) <= 0):
        raise BadTrajectory("time must increase")
    # The engine works on uniform samples; a logged trace seldom is.
    n = int(np.clip(len(time), 256, MAX_SAMPLES))
    step = (time[-1] - time[0]) / (n - 1)
    grid = time[0] + step * np.arange(n)
    return Trajectory(
        time=grid - time[0],
        current={leg: np.interp(grid, time, columns[f"i_{leg}"]) for leg in legs},
        duty={leg: np.clip(np.interp(grid, time, columns[f"d_{leg}"]), 0.0, 1.0) for leg in legs},
    )


def roles(trajectory: Trajectory) -> list[Role]:
    """Two positions per leg, each with what it carries at every instant."""
    out = []
    for leg in trajectory.legs:
        i, d = trajectory.current[leg], trajectory.duty[leg]
        outward, inward = i > 0, i < 0
        switching = (d > 0) & (d < 1)
        zero = np.zeros_like(i)
        out.append(
            Role(
                f"leg {leg.upper()} high side",
                1,
                np.abs(i),
                np.where(outward, d, zero),
                np.where(inward, d, zero),
                (outward & switching).astype(float),
                (inward & switching).astype(float),
                leg=leg,
            )
        )
        out.append(
            Role(
                f"leg {leg.upper()} low side",
                1,
                np.abs(i),
                np.where(inward, 1 - d, zero),
                np.where(outward, 1 - d, zero),
                (inward & switching).astype(float),
                (outward & switching).astype(float),
                leg=leg,
            )
        )
    return out


@dataclass(frozen=True)
class Outcome:
    result: Result  # taking the trajectory to repeat without end
    time: np.ndarray
    tj_from_start: np.ndarray  # hottest junction against time, starting at the sink temperature

    @property
    def peak_from_start(self) -> float:
        return float(self.tj_from_start.max())


def run(device: Device, trajectory: Trajectory, op: OperatingPoint) -> Outcome:
    """Losses and temperatures along a trajectory.

    Two answers are given. `result` takes the trajectory to repeat without
    end, which is the settled state of a machine that does the same thing
    over and over. `tj_from_start` runs through it once with every junction
    starting at the heatsink temperature, using the same losses.
    """
    stage = roles(trajectory)
    power = sum(float(np.mean(trajectory.duty[leg] * trajectory.current[leg])) for leg in trajectory.legs) * op.v_dc
    result = solve_roles(
        device,
        stage,
        op,
        period=trajectory.duration,
        p_out=power,
        extra_notes=["trajectory: taken to repeat without end for the losses and settled temperatures"],
    )
    chips = {"switch": device.switch}
    if device.diode is not None:
        chips["diode"] = device.diode
    networks = {name: thermal_network(device, chip)[0] for name, chip in chips.items()}
    dt = trajectory.duration / trajectory.time.size
    hottest = np.full(trajectory.time.size, op.t_sink)
    for role in result.roles:
        for name, network in networks.items():
            wave = role.p_switch if name == "switch" else role.p_diode
            mean = role.switch.total if name == "switch" else role.diode.total
            settled = role.tj_switch if name == "switch" else role.tj_diode
            static = settled - network.rth * mean - op.t_sink
            chip = ChipState(network)
            for k, p in enumerate(wave):
                chip.advance(float(p), dt)
                hottest[k] = max(hottest[k], op.t_sink + static + chip.rise)
    return Outcome(result, trajectory.time + dt, hottest)


def example(f_out: float = 50.0, i_rms: float = 10.0, m: float = 0.8, pf: float = 0.85, n: int = 200) -> str:
    """A made-up trajectory: one cycle of a three-phase sine drive, as CSV text."""
    theta = 2 * np.pi * (np.arange(n) + 0.5) / n
    lines = [
        "# One output cycle of a made-up three-phase drive. Replace with your own trace:",
        "# currents out of each leg in A, and each leg's high-side duty cycle (0 to 1).",
        "time_s,i_a,d_a,i_b,d_b,i_c,d_c",
    ]
    lag = np.arccos(pf)
    for k in range(n):
        row = [f"{written((k + 0.5) / (n * f_out), 6)}"]
        for shift in (0.0, -2 * np.pi / 3, 2 * np.pi / 3):
            row.append(f"{written(np.sqrt(2) * i_rms * np.sin(theta[k] + shift - lag), 5)}")
            row.append(f"{written(0.5 * (1 + m * np.sin(theta[k] + shift)), 5)}")
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"
