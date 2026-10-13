"""How a drive gets a motor going, and what that costs the power stage.

A drive that knows where the rotor is (an encoder, Hall sensors, or a
sensorless method that injects a test signal at standstill) applies just the
current the torque needs, from the first instant. A sensorless drive that
reads the rotor position from the back-EMF cannot do that at standstill,
where there is none. It starts in three steps, and the first two cost
current:

1. Alignment: a fixed current is held in one direction so the rotor swings to
   a known position. The stage carries DC, as at a stall.
2. Open-loop ramp: the current vector is turned at a rising frequency and the
   rotor follows. The current is fixed at the start value whatever the load
   asks for, because the drive cannot yet see the rotor to do better.
3. Handover: once the back-EMF is large enough to read, normal control takes
   over and the current drops to what the torque needs.

A motor already turning when the drive starts (a fan in a draught) is caught
at its speed, and needs no alignment.

An induction motor has no magnets: its flux has to be built first, by holding
the magnetising current for a few rotor time constants before torque is asked
for.

Charging the DC link at power-up is the supply's affair, not the inverter's,
but it is where a first prototype most often loses a part, so it is worked
out too.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from motionsim.load import Sample

Method = Literal["sensor", "injection", "open_loop"]


@dataclass(frozen=True)
class Start:
    method: Method = "sensor"
    current: float = 0.0  # A peak, held through alignment and the open-loop ramp
    align_time: float = 0.0  # s
    handover_rpm: float = 0.0  # motor speed below which the drive runs open loop
    flux_time: float = 0.0  # s; induction motors: flux build-up before torque

    def floor(self, rpm: float) -> float | None:
        """The least current the stage carries at this speed, or None when the drive
        applies what the torque needs."""
        if self.method == "open_loop" and self.current > 0 and abs(rpm) < self.handover_rpm:
            return self.current
        return None


def with_start(samples: list[Sample], start: Start) -> list[Sample]:
    """The motion with its start-up in front: flux build-up, then alignment."""
    first = samples[0]
    before = []
    if start.flux_time > 0:
        before.append(
            replace(
                first,
                duration=start.flux_time,
                load_speed=0.0,
                load_acceleration=0.0,
                motor_rpm=0.0,
                motor_torque=0.0,
            )
        )
    # A motor that is already turning is caught at its speed: there is nothing to align.
    caught = first.motor_rpm != 0 and abs(first.motor_rpm) >= start.handover_rpm
    if start.method == "open_loop" and start.align_time > 0 and start.current > 0 and not caught:
        before.append(
            replace(
                first,
                duration=start.align_time,
                load_speed=0.0,
                load_acceleration=0.0,
                motor_rpm=0.0,
                motor_torque=0.0,
            )
        )
    return before + samples


@dataclass(frozen=True)
class Inrush:
    energy: float  # J stored in the link, and lost in whatever limits the current
    peak: float | None  # A, with the precharge resistance given
    time: float | None  # s to within 5% of the supply voltage


def inrush(v_dc: float, capacitance: float, resistance: float | None) -> Inrush:
    """Charging the DC link from empty. Whatever resistance limits the current, it
    absorbs as much energy as ends up stored: half C V squared."""
    energy = 0.5 * capacitance * v_dc**2
    if not resistance:
        return Inrush(energy, None, None)
    return Inrush(energy, v_dc / resistance, 3.0 * resistance * capacitance)
