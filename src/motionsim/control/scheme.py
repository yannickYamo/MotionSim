"""A control scheme: a named wiring of blocks, as plain data a page can save, show and edit.

    {
      "id": "foc_torque", "label": "...", "about": "...",
      "timing": {"update": "single", "delay": true, "f_control": null},
      "actuation": {"kind": "duties", "wires": ["mod.d_a", "mod.d_b", "mod.d_c"]},
      "blocks": [
        {"name": "sample", "kind": "current_sampling", "params": {...},
         "inputs": {"i_a": "plant.i_a", "i_b": "plant.i_b", "i_c": "plant.i_c"}},
        ...
      ]
    }

A wire is named for the block and the output it leaves: "mod.d_a". The kernel itself drives
the wires of `SOURCES`: what the plant does, what the test asks, and the time. Blocks are
stepped in the order they are listed; a block that reads a wire driven further down the list
reads what was on it one sampling instant ago.

`actuation` is how the scheme drives the stage, and the one thing the kernel needs to know of
a scheme: three duty cycles for a carrier (`duties`), or the three legs' states themselves
(`states`), which is what a controller with no modulator gives. `actuation.period`, where
given, names a wire that carries the sampling period in seconds: the scheme then sets its
own switching frequency, instant by instant, within a quarter and four times the nominal. `timing.update` is `single`
(sampled once a carrier period, at its peak), `double` (at peak and valley), `multi` (sampled
and updated `per_carrier` times a carrier period, 4, 6 or 8: the timer's compare values are
reloaded mid-slope) or `every` (once every `carriers` carrier periods, 2 to 8: the control
slower than the switching, as a fast stage's controller often has to be); `delay` says
whether what is computed at one instant is applied from the next. A scheme of `states` is
sampled at `f_control` hertz.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

# Each kind of block registers itself as its module is read.
from motionsim.control import (  # noqa: F401
    actuation,
    direct,
    discrete,
    injection,
    observers,
    predictive,
    references,
    regulators,
    sensing,
    startup,
    thermal,
)
from motionsim.control.blocks import Block, BlockSpec, Context, kind_of
from motionsim.errors import Refusal
from motionsim.text import whole

# The wires the kernel drives, with the unit of each and what it carries.
SOURCES: dict[str, tuple[str, str]] = {
    "time.t": ("s", "time"),
    "plant.i_a": ("A", "phase a current, at the sampling instant"),
    "plant.i_b": ("A", "phase b current, at the sampling instant"),
    "plant.i_c": ("A", "phase c current, at the sampling instant"),
    "plant.i_d": ("A", "true d-axis current"),
    "plant.i_q": ("A", "true q-axis current"),
    "plant.theta_e": ("rad", "true electrical angle"),
    "plant.omega_m": ("rad/s", "true shaft speed"),
    "plant.torque": ("N·m", "torque the motor makes"),
    "plant.load_torque": ("N·m", "torque the load asks"),
    "plant.v_dc": ("V", "DC voltage"),
    "cmd.speed": ("rad/s", "speed the test asks for"),
    "cmd.torque": ("N·m", "torque the test asks for"),
    "const.zero": ("", "nought: what an optional input left open reads"),
    "plant.omega_load": ("rad/s", "the load's speed, at its own side of the shaft (the motor's, where it is rigid)"),
    # What shunts in the stage could read, worked out only for a scheme that senses through them
    # (kernel.py); nought otherwise. A low-side shunt reads its phase while that leg's low switch
    # is on about the sampling instant; one shunt in the DC link reads the current of each
    # active vector of the period before.
    "inverter.window_a": ("s", "time leg a's low switch was on about this instant, the period before"),
    "inverter.window_b": ("s", "time leg b's low switch was on about this instant, the period before"),
    "inverter.window_c": ("s", "time leg c's low switch was on about this instant, the period before"),
    "inverter.i_dc_1": ("A", "DC-link current at the end of the period's first active vector, the period before"),
    "inverter.vector_1": ("", "the legs high in that vector, as a number: a 1, b 2, c 4 (0: no vector)"),
    "inverter.span_1": ("s", "how long that vector stood"),
    "inverter.i_dc_2": ("A", "DC-link current at the end of the period's second active vector, the period before"),
    "inverter.vector_2": ("", "the legs high in that vector, as a number: a 1, b 2, c 4 (0: no vector)"),
    "inverter.span_2": ("s", "how long that vector stood"),
    "inverter.skip": (
        "",
        "1 where no shunt reading is due at this instant: updated twice a period, the shunts are read once",
    ),
    # The stage once the drive trips (safestate.py); nought before, and in any run with no trip.
    "inverter.safe": (
        "",
        "the stage's safe state once the drive has tripped: 0 switching, 1 every gate off, 2 shorted",
    ),
    "inverter.i_link": ("A", "current the stage returned to the DC link through its diodes, the period before"),
}
SHUNT_SOURCES = 15  # where the stage's shunt readings begin on the bus
SAFE_SOURCES = 25  # where the safe state and the current it returns are on the bus
RESERVED = ("time", "plant", "cmd", "const", "inverter")
UPDATES = ("single", "double", "multi", "every")
PER_CARRIER = (4, 6, 8)  # updates a carrier period, for "multi": an even count, the halves split alike
CARRIERS = (2, 3, 4, 5, 6, 7, 8)  # carrier periods an update, for "every"
ACTUATIONS = ("duties", "states")
MOST_BLOCKS = 64
MOST_CONTROL_RATE = 2e6  # Hz


def _refused(reason: str, fix: str, where: str = "scheme") -> Refusal:
    return Refusal(reason, fix, where)


@dataclass
class Scheme:
    id: str
    label: str
    about: str
    blocks: list[BlockSpec]
    actuation: dict[str, Any]
    timing: dict[str, Any] = field(default_factory=lambda: {"update": "single", "delay": True, "f_control": None})

    def data(self) -> dict:
        """The scheme as plain data."""
        return {
            "id": self.id,
            "label": self.label,
            "about": self.about,
            "timing": dict(self.timing),
            "actuation": copy.deepcopy(self.actuation),
            "blocks": [
                {
                    "name": b.name,
                    "kind": b.kind,
                    "inputs": dict(b.inputs),
                    "params": dict(b.params),
                    "sources": dict(b.sources),
                }
                for b in self.blocks
            ],
        }

    def block(self, kind: str) -> BlockSpec | None:
        """The first block of a kind, or None."""
        return next((b for b in self.blocks if b.kind == kind), None)

    @property
    def named(self) -> str:
        """The scheme as a sentence names it: its label, with its id in parentheses."""
        return f"{self.label} ({self.id})"

    def reads(self, wire: str) -> bool:
        return any(wire in b.inputs.values() for b in self.blocks)

    def control_period(self, f_sw: float) -> float:
        """Seconds between two sampling instants, on a carrier of f_sw hertz."""
        if self.actuation["kind"] == "states":
            return 1.0 / float(self.timing.get("f_control") or f_sw)
        update = self.timing["update"]
        if update == "multi":
            return 1.0 / (int(self.timing.get("per_carrier", 4)) * f_sw)
        if update == "every":
            return int(self.timing.get("carriers", 2)) / f_sw
        return 1.0 / f_sw if update == "single" else 0.5 / f_sw


def _timing(given: Any) -> dict:
    timing = {"update": "single", "delay": True, "f_control": None} | (given if isinstance(given, dict) else {})
    if timing["update"] not in UPDATES:
        raise _refused(f"scheme.timing.update is one of {', '.join(UPDATES)}", "", "scheme.timing.update")
    if not isinstance(timing["delay"], bool):
        raise _refused("scheme.timing.delay is true or false", "give true or false", "scheme.timing.delay")
    for key, update, allowed in (("per_carrier", "multi", PER_CARRIER), ("carriers", "every", CARRIERS)):
        if key not in timing:
            continue
        value = timing[key]
        if timing["update"] != update:
            raise _refused(
                f"scheme.timing.{key} is read only where the update is {update}",
                f"leave it out, or update {update}",
                f"scheme.timing.{key}",
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in allowed:
            raise _refused(
                f"scheme.timing.{key} is one of {', '.join(str(a) for a in allowed)}", "", f"scheme.timing.{key}"
            )
        timing[key] = int(value)
    rate = timing["f_control"]
    if rate is not None:
        sound = isinstance(rate, (int, float)) and not isinstance(rate, bool) and 100 <= rate <= MOST_CONTROL_RATE
        if not sound:
            raise _refused(
                f"scheme.timing.f_control lies between 100 Hz and {whole(MOST_CONTROL_RATE)} Hz",
                "give the sampling frequency in hertz",
                "scheme.timing.f_control",
            )
    return timing


def _actuation(given: Any) -> dict:
    if not isinstance(given, dict) or given.get("kind") not in ACTUATIONS:
        raise _refused(
            f"scheme.actuation.kind is one of {', '.join(ACTUATIONS)}",
            "say how the scheme drives the stage: duty cycles for a carrier, or the legs' states",
            "scheme.actuation",
        )
    wires = given.get("wires")
    if not (isinstance(wires, list) and len(wires) == 3 and all(isinstance(w, str) for w in wires)):
        raise _refused("scheme.actuation.wires names three wires, one a leg", "", "scheme.actuation.wires")
    out = {"kind": given["kind"], "wires": list(wires)}
    if given.get("period") is not None:
        if not isinstance(given["period"], str):
            raise _refused("scheme.actuation.period names a wire", "", "scheme.actuation.period")
        out["period"] = given["period"]
    return out


def _block(given: Any, k: int) -> BlockSpec:
    where = f"scheme.blocks[{k}]"
    if not isinstance(given, dict) or not isinstance(given.get("name"), str) or not isinstance(given.get("kind"), str):
        raise _refused(f"{where} needs a name and a kind", "give each block a name and a kind", where)
    name = given["name"]
    if not name or "." in name or name in RESERVED:
        raise _refused(
            f"{name!r} cannot name a block: no dot in a name, and {', '.join(RESERVED)} are the kernel's own",
            "choose another name",
            where,
        )
    inputs, params = given.get("inputs") or {}, given.get("params") or {}
    if not isinstance(inputs, dict) or not isinstance(params, dict):
        raise _refused(f"the inputs and params of {name} are sets of names and values", "", f"scheme.blocks.{name}")
    if not all(isinstance(w, str) for w in inputs.values()):
        raise _refused(f"each input of {name} names a wire", "", f"scheme.blocks.{name}")
    said = given.get("sources")
    sources = said if isinstance(said, dict) else {}
    return BlockSpec(name, given["kind"], dict(inputs), dict(params), {k: str(v) for k, v in sources.items()})


def scheme_from(data: Any) -> Scheme:
    """A scheme from plain data, its shape checked: what a page sends back after an edit.
    The wiring and the parameters are checked when it is compiled for a run."""
    if not isinstance(data, dict):
        raise _refused("the scheme is not a set of names and values", "send the scheme as the presets give it")
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise _refused("the scheme has no blocks", "give at least one block", "scheme.blocks")
    if len(blocks) > MOST_BLOCKS:
        raise _refused(
            f"the scheme has {len(blocks)} blocks, and {MOST_BLOCKS} is the most", "take blocks out", "scheme.blocks"
        )
    return Scheme(
        id=str(data.get("id") or "custom"),
        label=str(data.get("label") or "Custom scheme"),
        about=str(data.get("about") or ""),
        blocks=[_block(b, k) for k, b in enumerate(blocks)],
        actuation=_actuation(data.get("actuation")),
        timing=_timing(data.get("timing")),
    )


@dataclass
class Compiled:
    """A scheme made ready to step: its blocks, and where on the bus each reads and writes."""

    scheme: Scheme
    blocks: list[Block]
    wires: list[str]  # every wire by its place on the bus
    units: list[str]
    program: list[tuple[Any, tuple[int, ...], int, int]]  # step, places read, first place written, how many
    actuation: tuple[int, int, int]
    period: int | None  # the place of the wire that sets the sampling period, where a scheme has one

    def place(self, wire: str) -> int:
        return self.wires.index(wire)

    def block(self, name: str) -> Block:
        return next(b for b in self.blocks if b.name == name)


def _rated(scheme: Scheme) -> None:
    """A rate other than once or twice a carrier period asks for a carrier of its own: not a
    scheme that drives the legs' states, sets its own period, or reads shunts by the period."""
    update = scheme.timing["update"]
    if update not in ("multi", "every"):
        return
    why = None
    if scheme.actuation["kind"] == "states":
        why = "drives the legs' states itself, with no carrier to update"
    elif scheme.actuation.get("period"):
        why = "sets its own switching period"
    elif any(b.kind == "shunt_sampling" for b in scheme.blocks):
        why = "reads its currents through shunts, whose windows are reckoned by the carrier period"
    if why is not None:
        raise _refused(
            f"the scheme {scheme.named} {why}: it is updated once or twice a carrier period",
            "set the update to single or double",
            "scheme.timing.update",
        )


def compile_scheme(scheme: Scheme, ctx: Context) -> Compiled:
    """The blocks of a scheme built with their parameters and wired to the bus. A kind of
    block that does not exist, a parameter out of its bounds, an input left open or a wire
    nothing drives is refused by name."""
    _rated(scheme)
    wires, units = list(SOURCES), [unit for unit, _ in SOURCES.values()]
    built: list[Block] = []
    seen: set[str] = set()
    for spec in scheme.blocks:
        if spec.name in seen:
            raise _refused(f"two blocks are called {spec.name}", "give each block its own name", "scheme.blocks")
        seen.add(spec.name)
        block = kind_of(spec.kind, f"scheme.blocks.{spec.name}.kind")(spec.name, spec.params, ctx)
        built.append(block)
        for port in block.outputs:
            wires.append(f"{spec.name}.{port.name}")
            units.append(port.unit)
    place = {wire: k for k, wire in enumerate(wires)}

    def placed(wire: str, where: str) -> int:
        if wire not in place:
            raise _refused(
                f"{where} reads the wire {wire}, which nothing drives", "name a wire a block puts out", where
            )
        return place[wire]

    program = []
    for spec, block in zip(scheme.blocks, built, strict=True):
        ports = [p.name for p in block.inputs]
        for wired in spec.inputs:
            if wired not in ports:
                raise _refused(
                    f"the block {spec.name} ({spec.kind}) has no input called {wired}",
                    f"one of {', '.join(ports) or 'none'}",
                    f"scheme.blocks.{spec.name}.inputs.{wired}",
                )
        optional = {p.name for p in block.inputs if p.optional}
        for needed in ports:
            if needed not in spec.inputs and needed not in optional:
                raise _refused(
                    f"the input {needed} of the block {spec.name} is not wired",
                    "name the wire it reads",
                    f"scheme.blocks.{spec.name}.inputs.{needed}",
                )
        reads = tuple(placed(spec.inputs.get(p, "const.zero"), f"scheme.blocks.{spec.name}.inputs.{p}") for p in ports)
        program.append((block.step, reads, place[f"{spec.name}.{block.outputs[0].name}"], len(block.outputs)))
    drive = scheme.actuation
    a, b, c = (placed(w, "scheme.actuation.wires") for w in drive["wires"])
    period = placed(drive["period"], "scheme.actuation.period") if drive.get("period") else None
    return Compiled(scheme, built, wires, units, program, (a, b, c), period)
