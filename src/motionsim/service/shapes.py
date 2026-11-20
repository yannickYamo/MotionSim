"""The shape of each answer: what the engine worked out, as names and values a page or a
program reads. Nothing is worked out here, and no words are read to decide anything."""

from __future__ import annotations

import numpy as np

from motionsim import guard
from motionsim.engine import Pwm
from motionsim.engine.limits import hottest
from motionsim.engine.notes import Note

LEVEL_WORD = {
    guard.Level.ok: "ok",
    guard.Level.caution: "caution",
    guard.Level.undecided: "undecided",
    guard.Level.fail: "fail",
}


def _losses(sw, d) -> dict:
    return {
        "conduction": sw.conduction,
        "turn_on": sw.turn_on,
        "turn_off": sw.turn_off,
        "dead_time": sw.dead_time,
        "recovery": sw.recovery,
        "diode_conduction": d.conduction,
        "diode_recovery": d.recovery,
        "total": sw.total + d.total,
    }


def coded(r) -> list[dict]:
    """Every remark of a result that carries a code: the code, the figure or loss term it
    concerns, and its words. For whoever has to act on a remark: by its code, never its words."""
    return [
        {"code": n.code.value, "field": n.field, "text": str(n)}
        for n in (*r.rating_warnings, *r.notes)
        if isinstance(n, Note)
    ]


def _result(r, tj_max: float, parallel: int = 1) -> dict:
    # The roles hold one device of each position; with devices in parallel there are more.
    conduction = parallel * sum(
        x.count * (x.switch.conduction + x.switch.dead_time + x.diode.conduction) for x in r.roles
    )
    switching = parallel * sum(
        x.count * (x.switch.turn_on + x.switch.turn_off + x.switch.recovery + x.diode.recovery) for x in r.roles
    )
    return {
        "loss": r.p_inverter,
        "conduction": conduction,
        "switching": switching,
        "efficiency": r.efficiency,
        "tj_peak": hottest(r),
        # Of the hottest position: the average over the output period and the peak within it.
        "tj_switch": r.tj_switch,
        "tj_diode": r.tj_diode,
        "tj_switch_peak": r.tj_switch_peak,
        "tj_diode_peak": r.tj_diode_peak,
        "peak_basis": r.peak_basis.value,
        "tj_range": r.tj_peak_range,
        "range_lead": r.range_lead,
        "tj_max": tj_max,
        "t_case": r.t_case,
        "t_sink": r.t_sink,
        "validity": r.validity.value,
        "notes": [str(n) for n in r.notes],
        "limits": r.limits,
        "assumptions": r.assumptions,
        "warnings": [str(n) for n in r.rating_warnings],
        "codes": coded(r),
        "hottest": _losses(r.switch, r.diode),
        "positions": [
            {
                "name": x.name,
                "count": x.count,
                **_losses(x.switch, x.diode),
                "tj": x.hottest,
                "tj_switch": x.tj_switch_peak,
                "tj_diode": x.tj_diode_peak,
                # Averages over the output period, beside the peaks within it.
                "tj_switch_mean": x.tj_switch,
                "tj_diode_mean": x.tj_diode,
            }
            for x in r.roles
        ],
    }


def _checks(checks) -> list[dict]:
    """The checks as names and values. A check about one figure the user can put right
    names it as `field`; the rest carry no such name."""
    return [
        {"level": LEVEL_WORD[c.level], "topic": c.topic, "message": str(c.message)}
        | ({"field": c.field} if getattr(c, "field", None) else {})
        for c in checks
    ]


def level_of(checks: list[dict]) -> str:
    """The gravest level among checks as they are written: ok where there are none."""
    order = ("ok", "caution", "undecided", "fail")
    return max((c["level"] for c in checks), key=order.index, default="ok")


def _stage(stage, motor, pwm: Pwm) -> dict:
    return {
        "positions": sum(r.count for r in stage.roles),
        "i_peak": stage.i_peak,
        "p_shaft": stage.p_shaft,
        "p_electrical": stage.p_electrical,
        "p_motor_loss": stage.p_motor_loss,
        "scheme": motor.scheme(pwm),
        "summary": [{"label": a, "value": b, "unit": c} for a, b, c in stage.summary],
        "notes": stage.notes,
        "roles": [
            {
                "name": r.name,
                "count": r.count,
                "forward": float(np.mean(r.d_switch * (r.current > 0))),
                "reverse": float(np.mean(r.d_reverse * (r.current > 0))),
                "switching": float(np.mean(r.switch_events + r.reverse_events) > 0),
            }
            for r in stage.roles
        ],
    }


def _gate_out(gate) -> dict:
    return {
        "kind": gate.kind,
        "v_drive": gate.v_drive,
        "rg_on": gate.rg_on,
        "rg_off": gate.rg_off,
        "lines": gate.lines,
        # The dead time in use, chosen here or given.
        "t_dead": gate.t_dead if gate.t_dead is not None else (gate.op.t_dead or None),
    }
