"""The control lab's kernel: the closed loop of a motor, its stage and a sampled controller
simulated in time, every wire recorded, and the result handed to the tool's own loss and
thermal model.

The work is shared out: plant.py has the motor and its shaft, blocks.py what a block of a
controller is; sensing.py, regulators.py, predictive.py, direct.py, discrete.py,
observers.py, startup.py, actuation.py, references.py and thermal.py the blocks there are
(stage.py: the controller's own figures of the stage); scheme.py a scheme as a wiring of
blocks in plain data, presets.py, applications.py and sensorless.py the schemes a design starts from and
the rules their gains come from, scenario.py the tests a run can execute, kernel.py the loop
in time, losses.py the hand-off to the loss engine, metrics.py and report.py what a run is
read by, linear.py the loops as transfer functions.
"""

from motionsim.control.blocks import BLOCKS, Block, BlockSpec, Context, Param, Port, describe, register
from motionsim.control.kernel import Inverter, Kernel, Trace, Trial, Unstable
from motionsim.control.losses import Cost, cost
from motionsim.control.plant import Machine, Plant, simple_load
from motionsim.control.presets import Design, context, presets
from motionsim.control.scheme import Scheme, compile_scheme, scheme_from
from motionsim.control.stage import StageModel

# The schemes by application and by method add themselves to the presets as they are read.
from motionsim.control import applications  # noqa: F401  isort: skip

__all__ = [
    "BLOCKS",
    "Block",
    "BlockSpec",
    "Context",
    "Cost",
    "Design",
    "Inverter",
    "Kernel",
    "Machine",
    "Param",
    "Plant",
    "Port",
    "Scheme",
    "StageModel",
    "Trace",
    "Trial",
    "Unstable",
    "compile_scheme",
    "context",
    "cost",
    "describe",
    "presets",
    "register",
    "scheme_from",
    "simple_load",
]
