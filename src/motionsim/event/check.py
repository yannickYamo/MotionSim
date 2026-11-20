"""The event set beside the datasheet's own switching times: worked out again in the
datasheet's test (its voltage, current and gate resistor, at 25 °C), each edge made to lose
the energy the loss model counts there, and its times read as the datasheet reads them."""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import Device
from motionsim.engine.losses import energy
from motionsim.event.calibrate import calibrated
from motionsim.event.defaults import shared_default
from motionsim.event.parts import Detail, build

TEST_TJ = 25.0  # °C: switching times are tabulated cold unless said otherwise


def _test(device: Device) -> tuple[float, float, float | None] | None:
    """The test's voltage, current and gate resistor, where they can be known."""
    t, sw = device.timing, device.switch
    if t is None or sw.e_off is None:
        return None
    v = t.v_test or sw.e_off.v_ref
    i = t.i_test or device.ratings.i_nominal
    rg = t.rg_test if t.rg_test is not None else sw.e_off.rg
    return v, i, rg


def _row(what: str, model: float | None, datasheet: float | None) -> dict | None:
    if model is None or datasheet is None:
        return None
    return {"what": what, "model": model, "datasheet": datasheet, "error": model / datasheet - 1.0}


def against_datasheet(device: Device, given: Detail) -> dict | None:
    """The model's times beside the datasheet's, at the datasheet's test; None where the
    datasheet gives no times, or no measured energy to make the event lose."""
    test = _test(device)
    if test is None:
        return None
    v, i, rg = test
    t, sw = device.timing, device.switch
    assert t is not None and sw.e_off is not None
    inside = sw.rg_internal or 0.0
    rg_total = None if rg is None else rg + inside
    # The datasheet's test is the package as it is: its own source lead is in the gate loop.
    shared = given.l_cs if given.l_cs is not None else shared_default(device)[0]
    at = Detail(rg_on=rg_total, rg_off=rg_total, l_cs=shared, l_g=given.l_g, v_on=given.v_on, v_off=given.v_off)
    built = build(device, v_dc=v, current=i, tj=TEST_TJ, given=at)
    one = np.array([i])
    off = calibrated(built.circuit, "off", built.used["rg_off"], float(energy(sw.e_off, one, TEST_TJ, v, rg)[0]))
    rows = [_row("td(off)", off.read.t_delay, t.t_d_off), _row("tf", off.read.t_fall, t.t_f)]
    if (t.t_d_on or t.t_r) and sw.e_on is not None:
        on = calibrated(built.circuit, "on", built.used["rg_on"], float(energy(sw.e_on, one, TEST_TJ, v, rg)[0]))
        rows += [_row("td(on)", on.read.t_delay, t.t_d_on), _row("tr", on.read.t_rise, t.t_r)]
    return {
        "v_test": v,
        "i_test": i,
        "rg_test": built.used["rg_off"],
        "rows": [r for r in rows if r is not None],
        "assumed": [a.text for a in built.assumed if a.field in ("rg_on", "rg_off", "l_loop")]
        + (
            []
            if given.l_cs is not None
            else [f"Common-source inductance {shared * 1e9:.2g} nH, the package's own lead"]
        ),
    }
