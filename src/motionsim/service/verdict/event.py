"""One switching event of the switch the loss chart draws: its turn-on and turn-off through
time, at the same voltage, current, junction temperature and gate drive as the chart."""

from __future__ import annotations

from motionsim.errors import Refusal
from motionsim.service.validate import _conditions, _motor, _number, point
from motionsim.service.verdict.common import _gate, _unreachable
from motionsim.service.workspace import Workspace

# What the page's event fold sends, in the units its boxes are in: the factor to SI, the
# range, and the name of the figure for the event.
ASKED = {
    "l_cs_nh": (1e-9, 0.0, 100.0, "l_cs", "common-source inductance"),
    "l_g_nh": (1e-9, 0.0, 1000.0, "l_g", "gate-loop inductance"),
    "v_off": (1.0, -25.0, 0.0, "v_off", "gate driver's low level"),
}


def _detail(data: dict, op, gate):
    """What the event is given: the fold's boxes over the layout file over the conditions."""
    from motionsim.event import Detail
    from motionsim.event.layout import read_layout

    asked = data.get("event") or {}
    if not isinstance(asked, dict):
        raise Refusal("the event's figures are not names and values", "give them by name", "event")
    boxes = {}
    for key, (factor, low, high, name, words) in ASKED.items():
        if asked.get(key) not in (None, ""):
            boxes[name] = _number(asked[key], words, low=low, high=high, field=key, unit="") * factor
    layout = (
        read_layout(asked["layout"], asked.get("layout_name") or "layout.yaml") if asked.get("layout") else Detail()
    )
    stage = Detail(l_loop=op.l_loop, rg_on=gate.rg_on, rg_off=gate.rg_off, v_on=op.v_drive)
    return Detail(**boxes).over(layout).over(stage)


def _chosen_resistors(gate, used: dict, asked) -> list[dict]:
    """The gate resistors the tool chose, said as assumptions the user can replace: where the
    edge limit set one, said so, with the way to the limit."""
    if gate.kind != "chosen":
        return []
    from motionsim.engine.point import EDGE_LIMITS, EDGE_SAID

    out = []
    for key in ("rg_on", "rg_off"):
        if getattr(asked, key) is not None:
            continue  # the user's own
        ohms = f"Gate resistance {key[3:]} {used[key]:.3g} Ω"
        limit = EDGE_LIMITS[asked.edge_limit]
        if key in gate.held and limit is not None:
            why = f"chosen to hold the edges to {limit / 1e9:g} V/ns for {EDGE_SAID[asked.edge_limit]}"
            out.append({"field": "edge_limit", "text": f"{ohms}, {why}"})
        else:
            out.append({"field": key, "text": f"{ohms}, chosen by the tool for the limits: give yours"})
    return out


# Under this share of the limit, an edge is well under it: what sets its pace is not the limit.
WELL_UNDER = 0.5


def per_ns(rate: float) -> str:
    return f"{rate / 1e9:.2g} V/ns"


def _held_note(gate, device, asked, out: dict) -> str | None:
    """Where the edge limit chose a resistor: said once, above the edges, with the event's own
    plotted slopes, so the line never disagrees with the plot. Where the fastest is near the
    limit, the limit is what held it, and how much faster the part could switch within the
    gate-charge model is said; where it is well under, the gate charge and the loss model's
    energy set the pace, and that is said instead."""
    from motionsim.engine.point import EDGE_LIMITS

    limit = EDGE_LIMITS[asked.edge_limit]
    if gate.kind != "chosen" or not gate.held or limit is None:
        return None
    rates = {name: abs(out[key]["dv_dt"] or 0.0) for name, key in (("turn-on", "turn_on"), ("turn-off", "turn_off"))}
    edge, fastest = max(rates.items(), key=lambda item: item[1])
    if fastest < WELL_UNDER * limit:
        return (
            f"The edges here are {per_ns(rates['turn-on'])} at turn-on and {per_ns(rates['turn-off'])} at turn-off, "
            f"well under the {limit / 1e9:g} V/ns limit: the gate charge and the loss model's energy set their "
            "speed, not the limit"
        )
    said = (
        f"Edge speed is limited to {limit / 1e9:g} V/ns, by the gate resistance chosen for that limit. "
        f"The fastest edge here is {per_ns(fastest)}, at {edge}"
    )
    if gate.faster is not None and gate.faster >= 1.5:
        said += (
            f". Without the limit this {device.technology} could switch about {gate.faster:.0f}× faster: "
            "its driver's peak current and its channel would then set the pace"
        )
    return said


def event(data: dict, workspace: Workspace) -> dict:
    """The switching event of the device's hottest switch at the design point."""
    from motionsim.drivers import at_speed_and_torque
    from motionsim.event import event_out, switching_event
    from motionsim.event.check import against_datasheet
    from motionsim.motor import Unreachable
    from motionsim.service.verdict.design_point import hardest_period

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    rpm, torque = point(data["conditions"])
    device = workspace.device(data["device"])
    gate = _gate(device, op, motor, data["conditions"])
    try:
        design = at_speed_and_torque(device, motor, rpm, torque, gate.op)
    except Unreachable as exc:
        raise _unreachable(exc, gate.op) from None
    period, tj = hardest_period(device, design, gate.op)
    if not period["e_on"] and not period["e_off"]:
        raise Refusal("this switch does not switch at its hardest instant", "", "event")
    given = _detail(data, gate.op, gate)
    ev = switching_event(
        device,
        v_dc=gate.op.v_dc,
        current=period["current"],
        tj=tj,
        e_on=period["e_on"],
        e_off=period["e_off"],
        given=given,
    )
    out = event_out(ev)
    out["assumed"] += _chosen_resistors(gate, ev.used, op)
    out["held"] = _held_note(gate, device, op, out)
    out["position"] = period["position"]
    out["datasheet"] = against_datasheet(device, given)
    out["name"] = f"{device.vendor} {device.part_number}"
    return out
