"""Recommendations: dead time, gate resistors, heatsink.

Each one is a short calculation from the device model and the conditions the
user gives, shown with the numbers behind it. Where the model or the
conditions lack what the calculation needs, the recommendation says what to
supply instead of guessing. The limits used (margin on dead time, voltage
slew rate, share of the voltage rating) are common practice and are
parameters.

These are starting values for a first prototype. A gate resistor and a dead
time are settled on the bench, with a probe on the switch.

Each topic has a module of its own: turn_off (the dead time), gate (the gate resistors and
the gate drive), sink (the heatsink) and control (modulation, sensorless speed, d-axis
current). Every name is to be had from here.
"""

from motionsim.recommend.base import Recommendation
from motionsim.recommend.control import (
    EMF_OVER_ERROR,
    d_axis_current,
    least_loss_d_axis,
    modulation,
    sensorless_floor,
)
from motionsim.recommend.gate import USUAL_DRIVE, USUAL_LOOP, GateDrive, choose_gate_drive, gate_resistors
from motionsim.recommend.sink import heatsink
from motionsim.recommend.turn_off import (
    ABOVE_PLATEAU,
    COMMON_FIRMWARE,
    DEAD_FLOOR,
    DEAD_MARGIN,
    GAN_FLOOR,
    GAN_MISMATCH,
    HOT_SWITCHING,
    IGBT_DEAD_TIME,
    USUAL_MISMATCH,
    above_plateau,
    dead_time,
    open_dead_time,
    turn_off_time,
)

__all__ = [
    "ABOVE_PLATEAU",
    "COMMON_FIRMWARE",
    "DEAD_FLOOR",
    "DEAD_MARGIN",
    "EMF_OVER_ERROR",
    "GAN_FLOOR",
    "GAN_MISMATCH",
    "HOT_SWITCHING",
    "IGBT_DEAD_TIME",
    "USUAL_DRIVE",
    "USUAL_LOOP",
    "USUAL_MISMATCH",
    "GateDrive",
    "Recommendation",
    "above_plateau",
    "choose_gate_drive",
    "d_axis_current",
    "dead_time",
    "gate_resistors",
    "heatsink",
    "least_loss_d_axis",
    "modulation",
    "open_dead_time",
    "sensorless_floor",
    "turn_off_time",
]
