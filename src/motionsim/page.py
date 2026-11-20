"""The page's interface to the engine, by its old name.

Everything here lives in `motionsim.service`, one module to a concern. This module hands
the same names on, for the page's own copy of the engine (which calls `page.call`) and for
anything written against it.
"""

from __future__ import annotations

from motionsim.errors import Refusal
from motionsim.files import plain
from motionsim.service.answers import RUNAWAY, finite, log, reason_of
from motionsim.service.build import _alone_in_air, recommendations
from motionsim.service.catalogue import (
    FIELDS,
    LOADS_FOR,
    LOADS_MAINS,
    MOTOR_NAMES,
    OPTIONAL,
    OPTIONAL_FOR,
    STARTING,
)
from motionsim.service.motion import _mission, _scaled, cycle, largest
from motionsim.service.presets import load_presets, loads, resized, rewound, setup, suggest, typed_form
from motionsim.service.routes import ROUTES, call, dispatch, stream_call
from motionsim.service.shapes import _checks, _gate_out, _result, _stage
from motionsim.service.validate import _conditions, _motor, _number, asked
from motionsim.service.verdict import (
    _reach,
    capability,
    compare,
    largest_current,
    motor_fit,
    motor_point,
    proposal,
    simulate,
    speed_torque,
    stage,
    trajectory,
)
from motionsim.service.workspace import (
    EXAMPLE,
    EXAMPLES,
    Workspace,
    add_device,
    add_measurement,
    add_typed,
    bring_device,
    curves,
)

# A request that cannot work, by the name it has always had here.
Refused = Refusal

__all__ = [
    "EXAMPLE",
    "EXAMPLES",
    "FIELDS",
    "LOADS_FOR",
    "LOADS_MAINS",
    "MOTOR_NAMES",
    "OPTIONAL",
    "OPTIONAL_FOR",
    "ROUTES",
    "RUNAWAY",
    "STARTING",
    "Refusal",
    "Refused",
    "Workspace",
    "_alone_in_air",
    "_checks",
    "_conditions",
    "_gate_out",
    "_mission",
    "_motor",
    "_number",
    "_reach",
    "_result",
    "_scaled",
    "_stage",
    "add_device",
    "add_measurement",
    "add_typed",
    "asked",
    "bring_device",
    "call",
    "capability",
    "compare",
    "curves",
    "cycle",
    "dispatch",
    "finite",
    "largest",
    "largest_current",
    "load_presets",
    "loads",
    "log",
    "motor_fit",
    "motor_point",
    "plain",
    "proposal",
    "reason_of",
    "recommendations",
    "resized",
    "rewound",
    "setup",
    "simulate",
    "speed_torque",
    "stage",
    "stream_call",
    "suggest",
    "trajectory",
    "typed_form",
]
