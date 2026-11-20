"""One device at one point: what the motor asks of the stage, what the device then loses,
how hot it runs, and the checks on it. Also the same for several devices side by side, over
a grid of speeds and torques, and along currents read from a file.

Every function takes a request as names and values, checks it, asks the engine, and hands
back names and values. The page, a design file and the command line all come through here.

The work is shared out by what is asked: motor.py has the motor alone, design_point.py the
devices on it at its design point, reach.py what a device can drive, told.py a current told
outright, and common.py what they all read. Every name is to be had from here.
"""

from motionsim.service.verdict.common import FIXES, _distinct, _free_air, _gate, _sound, _unreachable
from motionsim.service.verdict.design_point import PROBLEM_FIX, motor_point, proposal
from motionsim.service.verdict.motor import _reach, motor_fit, stage
from motionsim.service.verdict.reach import MOST_CELLS, capability, speed_torque
from motionsim.service.verdict.told import MOST_SWEEP, compare, largest_current, simulate, trajectory

__all__ = [
    "FIXES",
    "MOST_CELLS",
    "MOST_SWEEP",
    "PROBLEM_FIX",
    "_distinct",
    "_free_air",
    "_gate",
    "_reach",
    "_sound",
    "_unreachable",
    "capability",
    "compare",
    "largest_current",
    "motor_fit",
    "motor_point",
    "proposal",
    "simulate",
    "speed_torque",
    "stage",
    "trajectory",
]
