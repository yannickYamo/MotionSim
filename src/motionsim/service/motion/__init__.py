"""A motion followed through time: a motor, its load and how it moves, or a mission profile
of instants, with the junction traced through it, the checks over the whole of it, and how
much heavier the load could be before something gives.

The work is shared out: inputs.py has the motion as asked for, start.py how the motor is
started, follow.py the motion followed and judged, heavier.py how much more it could carry.
Every name is to be had from here.
"""

from motionsim.service.motion.follow import cycle, cycle_summary, follow_cycle, motion_checks, worst_instant
from motionsim.service.motion.heavier import GROWS, _scaled, largest
from motionsim.service.motion.inputs import MOST_INSTANTS, MOST_POINTS, MOST_SEGMENTS, Motion, _mission, motion_inputs
from motionsim.service.motion.start import SENSORLESS

__all__ = [
    "GROWS",
    "MOST_INSTANTS",
    "MOST_POINTS",
    "MOST_SEGMENTS",
    "SENSORLESS",
    "Motion",
    "_mission",
    "_scaled",
    "cycle",
    "cycle_summary",
    "follow_cycle",
    "largest",
    "motion_checks",
    "motion_inputs",
    "worst_instant",
]
