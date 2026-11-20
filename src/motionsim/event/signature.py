"""What sets one kind of switch apart in its switching event, read off the worked-out edges:
a silicon body diode's recovery, a silicon-carbide plateau's slope, a GaN transistor's
third-quadrant drop and gate margin, an IGBT's slow approach to saturation and its tail.

Each is measured on the traces, never assumed, and named where it is on its trace; one plain
line says the one that matters most for this kind of switch."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motionsim.event.calibrate import Edge
from motionsim.event.circuit import Circuit
from motionsim.event.measure import crossing
from motionsim.package.materials import family
from motionsim.text import written

GATE_RATING = {"gan": 7.0}  # V, the gate's absolute rating where it is close to the drive
TAIL_LEVEL = 0.25  # of the load current: below it, an IGBT's turn-off current is its tail
PEAK = 1.05  # a turn-on current this far over the load is a peak worth naming


@dataclass(frozen=True)
class Feature:
    edge: str  # "on" or "off"
    trace: str  # "i", "v_ds", "v_gs" or "p"
    t: float  # s
    value: float  # in the trace's unit
    label: str
    caution: bool = False


@dataclass(frozen=True)
class Signature:
    kind: str  # "si", "sic", "gan", "igbt" or "hybrid"
    line: str
    features: list[Feature]
    recovered: float  # C, carried over the load at turn-on, past the other switch's output charge
    plateau_slope: float  # V, how far the gate climbs on its plateau for half again the load's current
    approach: float  # how far over its settled drop the turn-on voltage still is, five fast falls on
    tail_share: float  # of the turn-off energy, lost once the current is down to its tail
    third_quadrant: float  # V, what the reverse path drops in a dead time
    gate_peak: float  # V, the most the gate reaches at turn-on
    gate_rating: float | None  # V


def kind_of(technology: str, igbt: bool, stored: bool) -> str:
    if igbt:
        return "igbt" if stored else "hybrid"
    kind = family(technology)
    return kind if kind in ("sic", "gan") else "si"


def _energy(e: Edge, after: float) -> float:
    w, r = e.wave, e.read
    a, b = r.window if r.window else (w.t[0], w.t[-1])
    a = max(a, after)
    keep = (w.t >= a) & (w.t <= b)
    return float(np.trapezoid(w.p[keep], w.t[keep])) if keep.sum() > 1 else 0.0


def _turn_on(on: Edge, c: Circuit) -> tuple[float, float, float, float, float]:
    """Charge over the load, plateau slope, the slow approach, and where the voltage falls."""
    w, v_dc, load = on.wave, c.loop.v_dc, c.loop.i_load
    # The first lobe over the load alone: the ringing after it carries nothing across.
    k = int(np.argmax(w.i))
    back = np.nonzero(w.i[k:] < load)[0]
    lobe = slice(0, k + int(back[0]) + 1 if back.size else len(w.t))
    over = np.clip(w.i[lobe] - load, 0.0, None)
    carried = float(np.trapezoid(over, w.t[lobe])) - c.reverse.c_r.charge(v_dc)
    t90 = crossing(w.t, w.v_ds, 0.9 * v_dc, False)
    t10 = crossing(w.t, w.v_ds, 0.1 * v_dc, False)
    g = c.gate
    slope = ((1.5 * load / g.k) ** (1 / g.n)) - ((load / g.k) ** (1 / g.n))
    approach = 0.0
    if t90 is not None and t10 is not None and t10 > t90:
        # Five fast falls after the voltage is down to a tenth, how far it still is above
        # where it ends, as a share of where it ends: an IGBT's drift region is still filling.
        end = max(float(w.v_ds[-1]), 1e-3)
        later = float(np.interp(t10 + 5 * (t10 - t90), w.t, w.v_ds))
        approach = max(later / end - 1.0, 0.0)
    return carried, slope, approach, t90 or 0.0, t10 or 0.0


def signature(device_technology: str, igbt: bool, on: Edge, off: Edge, c: Circuit) -> Signature:
    kind = kind_of(device_technology, igbt, c.reverse.q_rr > 0)
    v_dc, load = c.loop.v_dc, c.loop.i_load
    carried, slope, approach, t90, t10 = _turn_on(on, c)
    w_on, w_off = on.wave, off.wave
    third = float(w_on.v_ds[0] - v_dc)
    features: list[Feature] = []
    k = int(np.argmax(w_on.i))
    if w_on.i[k] > PEAK * load:
        name = "recovery peak" if kind in ("si", "igbt") else "output-charge peak"
        features.append(Feature("on", "i", float(w_on.t[k]), float(w_on.i[k]), name))
    if t10 > t90:
        mid = 0.5 * (t90 + t10)
        name = "sloped plateau" if kind == "sic" else "Miller plateau"
        features.append(Feature("on", "v_gs", mid, float(np.interp(mid, w_on.t, w_on.v_gs)), name))
    if kind in ("igbt", "hybrid") and t10:
        features.append(Feature("on", "v_ds", t10, 0.1 * v_dc, "slow approach to saturation"))
    if kind == "gan":
        features.append(Feature("on", "v_ds", float(w_on.t[0]), float(w_on.v_ds[0]), "third-quadrant level"))
    tail_share = 0.0
    if igbt:
        start = int(np.argmax(w_off.v_ds > 0.9 * v_dc)) if (w_off.v_ds > 0.9 * v_dc).any() else 0
        low = np.nonzero(w_off.i[start:] < TAIL_LEVEL * load)[0]
        if low.size:
            t_tail = float(w_off.t[start + low[0]])
            tail_share = _energy(off, t_tail) / max(off.read.energy, 1e-30)
            features.append(Feature("off", "i", t_tail, float(w_off.i[start + low[0]]), "tail"))
    rating = GATE_RATING.get(kind)
    peak_gate = float(max(w_on.v_gs.max(), w_off.v_gs.max()))
    if rating is not None and peak_gate > rating:
        k = int(np.argmax(w_on.v_gs))
        features.append(
            Feature("on", "v_gs", float(w_on.t[k]), peak_gate, f"over the gate's {written(rating, 2)} V rating", True)
        )
    line = _line(kind, carried, slope, tail_share, third, float(w_on.i.max()), peak_gate, rating)
    return Signature(kind, line, features, carried, slope, approach, tail_share, third, peak_gate, rating)


def _line(
    kind: str, carried: float, slope: float, tail: float, third: float, peak: float, gate: float, rating: float | None
) -> str:
    if kind == "igbt":
        part = "most" if tail > 0.5 else f"{written(100 * tail, 2)} %"
        return (
            f"IGBT: the current tail after turn-off carries {part} of Eoff; turn-on recovers the diode's stored charge."
        )
    if kind == "hybrid":
        return (
            "IGBT with a Schottky diode: no stored charge to recover, only capacitance; the tail after "
            f"turn-off carries {written(100 * tail, 2)} % of Eoff."
        )
    if kind == "gan":
        said = f"GaN: no reverse recovery; dead time conducts at {written(third, 2)} V."
        if rating is not None and gate > rating:
            said += f" The gate reaches {written(gate, 2)} V, over its {written(rating, 2)} V rating."
        return said
    if kind == "sic":
        return (
            "SiC MOSFET: next to no recovery, only the other switch's output charge; the plateau "
            f"climbs {written(slope, 2)} V for half again the current, its transconductance low."
        )
    return (
        f"Si MOSFET: the body diode's recovery lifts the turn-on current to {written(peak, 3)} A; "
        "turn-off overshoots and rings, with no tail."
    )


def signature_out(s: Signature) -> dict:
    return {
        "kind": s.kind,
        "line": s.line,
        "features": [
            {"edge": f.edge, "trace": f.trace, "t": f.t, "value": f.value, "label": f.label, "caution": f.caution}
            for f in s.features
        ],
        "recovered": s.recovered,
        "plateau_slope": s.plateau_slope,
        "tail_share": s.tail_share,
        "third_quadrant": s.third_quadrant,
        "gate_peak": s.gate_peak,
        "gate_rating": s.gate_rating,
    }
