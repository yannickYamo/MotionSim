"""A switching event zoomed in: one turn-on and one turn-off of the switch the loss chart
draws, worked out as a small circuit through time (see circuit.py), each edge's energy made
the loss model's own (see calibrate.py), and read as a double-pulse test is read.

The first figures come from the datasheet alone, with every figure it lacks named as an
assumption; what the user adds (loop inductances, gate resistors, driver levels, a layout
file) replaces them one by one. Decision D164 says what it rests on and how far it holds.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motionsim.device.schema import ChipKind, Device
from motionsim.event.calibrate import Edge, calibrated
from motionsim.event.parts import Assumed, Detail, build
from motionsim.event.signature import Signature, signature, signature_out
from motionsim.text import written

__all__ = ["Detail", "Event", "switching_event"]


@dataclass(frozen=True)
class Event:
    device: Device
    v_dc: float
    current: float
    tj: float
    on: Edge
    off: Edge
    assumed: list[Assumed]
    used: dict[str, float]
    notes: list[str]
    signature: Signature


def _notes(device: Device, on: Edge, off: Edge, used: dict[str, float]) -> list[str]:
    """What the event says of itself where its energy and the loss model's part."""
    notes = []
    stored = 0.5 * used["l_loop"] * used["current"] ** 2
    for name, e in (("turn-on", on), ("turn-off", off)):
        if not e.met:
            said = (
                f"The {name} loses {written(e.read.energy * 1e6, 3)} µJ here, and the loss model counts "
                f"{written(e.target * 1e6, 3)} µJ: no setting of the free factor meets it"
            )
            if name == "turn-off" and stored > 0.5 * e.target:
                said += (
                    f". The loop's inductance holds {written(stored * 1e6, 3)} µJ at this current, which a turn-off "
                    "has to spend: the datasheet's energy was measured in a tighter loop. Give your loop inductance"
                )
            notes.append(said + ".")
        elif e.corrected:
            moved = [
                f"{written(x, 2)} times the {what}"
                for x, what in ((e.factor, "gate-drain charge"), (e.recovery, "recovery charge"))
                if x != 1.0
            ]
            notes.append(
                f"The {name} meets the datasheet's energy only with a large correction ({' and '.join(moved)} "
                "the datasheet gives): its shape is indicative. The loss model does not see the loop "
                "inductance, which here changes how the voltage and current cross."
            )
    return notes


def switching_event(
    device: Device, *, v_dc: float, current: float, tj: float, e_on: float, e_off: float, given: Detail
) -> Event:
    """Both edges of one switching event at this voltage, current (of one device) and
    junction temperature, each made to lose the energy the loss model counts there."""
    built = build(device, v_dc=v_dc, current=current, tj=tj, given=given)
    off = calibrated(built.circuit, "off", built.used["rg_off"], e_off)
    c = built.circuit
    if device.switch.kind is ChipKind.igbt:
        # The tail time the turn-off found is the IGBT's: the turn-on fills the same charge.
        from dataclasses import replace

        c = replace(c, switch=replace(c.switch, tau_tail=off.tail or c.switch.tau_tail))
    on = calibrated(c, "on", built.used["rg_on"], e_on)
    sig = signature(device.technology, device.switch.kind is ChipKind.igbt, on, off, c)
    notes = _notes(device, on, off, built.used)
    return Event(device, v_dc, current, tj, on, off, built.assumed, built.used, notes, sig)


def _trace(x: np.ndarray, digits: int = 5) -> list[float]:
    return [float(f"{v:.{digits}g}") for v in x]


def edge_out(e: Edge) -> dict:
    """One edge as the page and the command line read it: SI units throughout. Instants
    closer than the figures kept can tell apart are kept once."""
    r, w = e.read, e.wave
    t = np.array(_trace(w.t, 7))
    keep = np.concatenate([[True], np.diff(t) > 0])
    return {
        "t": t[keep].tolist(),
        "v_gs": _trace(w.v_gs[keep], 4),
        "v_ds": _trace(w.v_ds[keep]),
        "i": _trace(w.i[keep]),
        "p": _trace(w.p[keep], 4),
        "energy": r.energy,
        "target": e.target,
        "met": e.met,
        "factor": e.factor,
        "recovery": e.recovery,
        "corrected": e.corrected,
        "tail": e.tail or None,
        "di_dt": r.di_dt,
        "dv_dt": r.dv_dt,
        "t_rise": r.t_rise,
        "t_fall": r.t_fall,
        "t_delay": r.t_delay,
        "i_peak": r.i_peak,
        "v_peak": r.v_peak,
        "ring": r.ring,
        "window": list(r.window) if r.window else None,
    }


def event_out(ev: Event) -> dict:
    return {
        "kind": ev.device.switch.kind.value,
        "technology": ev.device.technology,
        "v_dc": ev.v_dc,
        "current": ev.current,
        "tj": ev.tj,
        "v_max": ev.device.ratings.v_max,
        "turn_on": edge_out(ev.on),
        "turn_off": edge_out(ev.off),
        "assumed": [{"field": a.field, "text": a.text} for a in ev.assumed],
        "used": ev.used,
        "notes": ev.notes,
        "signature": signature_out(ev.signature),
    }
