"""The switching event held to datasheet times, on the made-up parts the reader's labelled
set is written from (evals/reader/sheets.py): each part built as a perfect reading builds it.

The made-up IGBT sheets give a turn-off delay and fall time at 10 ohm; the event worked out
in that test, made to lose the sheet's turn-off energy, is set beside them. The sheets give
the same 180 ns and 45 ns for every rating from 20 to 75 A, which no family of real parts
does, so only the sheet whose rating sits in the middle (40 A) is held closely; the others
are held to the order. The made-up field-effect transistors give no times: their current
rise is held to the closed form of a gate charged through its resistor, from the sheet's
own charges.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from evals.reader import score, sheets
from motionsim.engine import OperatingPoint
from motionsim.engine.mosfet import charge_energies
from motionsim.event import Detail, switching_event
from motionsim.event.check import against_datasheet
from motionsim.event.defaults import CHANNEL_POWER
from motionsim.fit import build_device
from motionsim.package.materials import family

SHEETS = {s.name: s for s in sheets.labelled_set()}
IGBTS = [name for name, s in SHEETS.items() if s.technology == "Si IGBT"]
FETS = ["si_mosfet", "sic_mosfet", "gan_hemt"]
TEST_RG = 10.0  # ohm: what the made-up IGBT sheets say their switching test used


def part(name: str):
    sheet = SHEETS[name]
    return build_device(score.true_observations(sheet, sheets.lay_out(sheet)))


def compared(name: str) -> dict:
    device = part(name)
    assert device.timing is not None
    device = device.model_copy(update={"timing": device.timing.model_copy(update={"rg_test": TEST_RG})})
    out = against_datasheet(device, Detail())
    assert out is not None
    return {r["what"]: r for r in out["rows"]}


def test_the_middle_igbt_is_close_to_its_sheets_times() -> None:
    rows = compared("igbt_copack")
    assert rows["td(off)"]["model"] == pytest.approx(rows["td(off)"]["datasheet"], rel=0.25)
    assert rows["tf"]["model"] == pytest.approx(rows["tf"]["datasheet"], rel=0.5)


@pytest.mark.parametrize("name", IGBTS)
def test_every_igbt_is_within_the_order_of_its_sheets_times(name) -> None:
    rows = compared(name)
    assert set(rows) == {"td(off)", "tf"}
    for what, most in (("td(off)", 3.0), ("tf", 5.0)):
        ratio = rows[what]["model"] / rows[what]["datasheet"]
        assert 1 / most < ratio < most, (what, rows[what])


@pytest.mark.parametrize("name", FETS)
def test_a_field_effect_transistors_current_rises_as_its_gate_charge_says(name) -> None:
    """Current rise at turn-on, 10 % to 90 %: the gate climbs from where the channel carries
    a tenth of the load to where it carries nine tenths, charged through the resistor from
    the driver, in a loop too small for its inductance to matter. The input capacitance is the sheet's gate-source charge over its plateau;
    the threshold its charge at threshold over that capacitance."""
    sheet, device = SHEETS[name], part(name)
    c = device.switch.charge
    v_dc, current, rg, drive = sheet.reference["vdc"], device.ratings.i_nominal / 2, 5.0, 10.0
    op = OperatingPoint(
        v_dc=v_dc,
        i_rms=1,
        modulation_index=0.5,
        power_factor=0.9,
        f_sw=2e4,
        t_sink=25,
        v_drive=drive,
        rg_on=rg,
        rg_off=rg,
    )
    e_on, e_off = (float(e[0]) for e in charge_energies(device.switch, np.array([current]), op, 25.0, sheet.technology))
    given = Detail(l_loop=0.3e-9, l_cs=0.0, rg_on=rg, rg_off=rg, v_on=drive, v_off=0.0)
    ev = switching_event(device, v_dc=v_dc, current=current, tj=25.0, e_on=e_on, e_off=e_off, given=given)
    c_in = c.q_gs / c.v_plateau
    v_th = c.q_g_th / c_in
    n = CHANNEL_POWER[family(sheet.technology)]  # how the channel's current rises above threshold
    level = lambda share: v_th + (c.v_plateau - v_th) * share ** (1 / n)
    expected = rg * c_in * math.log((drive - level(0.1)) / (drive - level(0.9)))
    assert ev.on.read.t_rise == pytest.approx(expected, rel=0.3)
