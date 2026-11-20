"""Each kind of switch switches as its kind does, on the made-up parts of the reader's
labelled set (evals/reader/sheets.py): a silicon body diode recovers its stored charge, a
silicon-carbide or GaN reverse path only gives back capacitance, a silicon-carbide plateau
climbs, a GaN transistor conducts in reverse at a few volts and is driven close to its gate
rating, an IGBT approaches saturation slowly and turns off into a tail. Every test sets two
kinds beside each other, so that it fails if they switched alike.

The rates are held to what parts of each kind show (IGBT 2 to 20 V/ns, silicon field-effect
transistors 5 to 50, silicon carbide 20 to 80, GaN 50 to 150) wherever the event keeps the
datasheet's figures; where it meets the loss model's energy only by moving them more than a
factor of two, it has to say so instead.
"""

from __future__ import annotations

from functools import cache

import numpy as np
import pytest

from evals.reader import score, sheets
from motionsim.engine import OperatingPoint
from motionsim.engine.losses import energy
from motionsim.engine.mosfet import charge_energies
from motionsim.event import Detail, Event, switching_event
from motionsim.event.parts import build
from motionsim.fit import build_device

SHEETS = {s.name: s for s in sheets.labelled_set()}
KINDS = {"si": "si_mosfet", "sic": "sic_mosfet", "gan": "gan_hemt", "igbt": "igbt_copack"}
RATES = {"igbt": (2.0, 20.0), "si": (5.0, 50.0), "sic": (20.0, 80.0), "gan": (50.0, 150.0)}  # V/ns
TJ = 25.0


@cache
def part(name: str):
    s = SHEETS[name]
    return build_device(score.true_observations(s, sheets.lay_out(s)))


def energies(device, v_dc: float, current: float) -> tuple[float, float]:
    """What the loss model counts for one turn-on and one turn-off here."""
    sw = device.switch
    i = np.array([current])
    if sw.e_on is not None and sw.e_off is not None:
        return float(energy(sw.e_on, i, TJ, v_dc, None)[0]), float(energy(sw.e_off, i, TJ, v_dc, None)[0])
    drive = build(device, v_dc=v_dc, current=current, tj=TJ, given=Detail()).circuit.gate.v_on
    op = OperatingPoint(
        v_dc=v_dc,
        i_rms=1,
        modulation_index=0.5,
        power_factor=0.9,
        f_sw=2e4,
        t_sink=25,
        v_drive=drive,
        rg_on=5.0,
        rg_off=5.0,
    )
    on, off = charge_energies(sw, i, op, TJ, device.technology)
    return float(on[0]), float(off[0])


@cache
def event(kind: str, v_on: float | None = None, v_off: float | None = None, schottky: bool = False) -> Event:
    device = part(KINDS[kind])
    if schottky:  # the same IGBT with a freewheel diode that stores no charge
        device = device.model_copy(update={"diode": device.diode.model_copy(update={"e_rr": None})})
    v_dc, current = SHEETS[KINDS[kind]].reference["vdc"], device.ratings.i_nominal / 2
    e_on, e_off = energies(device, v_dc, current)
    given = Detail(v_on=v_on, v_off=v_off)
    return switching_event(device, v_dc=v_dc, current=current, tj=TJ, e_on=e_on, e_off=e_off, given=given)


def reverse(kind: str):
    ev = event(kind)
    return build(ev.device, v_dc=ev.v_dc, current=ev.current, tj=TJ, given=Detail()).circuit.reverse


def stored(kind: str) -> float:
    return reverse(kind).q_rr


def test_only_a_silicon_junction_recovers_stored_charge() -> None:
    """Silicon body diodes and an IGBT's co-packed diode carry their stored charge over the
    load at turn-on; silicon carbide and GaN give back no more than the other switch's output
    charge, so their spike is the capacitance's alone."""
    for kind in ("si", "igbt"):
        assert event(kind).signature.recovered > 0.5 * stored(kind), kind
        assert event(kind).signature.features[0].label == "recovery peak"
    for kind in ("sic", "gan"):
        assert stored(kind) == 0.0
        output = reverse(kind).c_r.charge(event(kind).v_dc)
        assert abs(event(kind).signature.recovered) < 0.5 * output, kind
        assert event(kind).signature.features[0].label == "output-charge peak"


def test_a_schottky_freewheel_gives_back_capacitance_only() -> None:
    with_diode, hybrid = event("igbt"), event("igbt", schottky=True)
    assert hybrid.signature.kind == "hybrid"
    assert hybrid.signature.recovered < 0.1 * with_diode.signature.recovered
    assert hybrid.on.read.i_peak < with_diode.on.read.i_peak
    assert "Schottky" in hybrid.signature.line


def test_a_silicon_carbide_plateau_climbs_where_silicons_holds() -> None:
    """Low transconductance: the gate has to climb further on its plateau for the same rise
    in current."""
    assert event("sic").signature.plateau_slope > 1.4 * event("si").signature.plateau_slope
    assert any(f.label == "sloped plateau" for f in event("sic").signature.features)
    assert not any(f.label == "sloped plateau" for f in event("si").signature.features)


def test_only_an_igbt_turns_off_into_a_tail_that_lasts_its_class() -> None:
    igbt = event("igbt")
    low, high = 0.1e-6, 1e-6  # a 600 V class tail at 25 °C
    assert low <= igbt.off.tail <= high
    assert igbt.signature.tail_share > 0.3
    assert any(f.label == "tail" for f in igbt.signature.features)
    for kind in ("si", "sic", "gan"):
        assert event(kind).off.tail == 0.0
        assert event(kind).signature.tail_share == 0.0


def test_an_igbt_tail_lasts_longer_hot() -> None:
    from motionsim.event.defaults import tail_range

    assert tail_range(650.0, 125.0)[1] > tail_range(650.0, 25.0)[1]


def test_only_an_igbt_approaches_saturation_slowly() -> None:
    """Two stages: a fast fall, then the drift region filling, so the drop is still well
    above where it settles several fall times on; a field-effect transistor is there."""
    assert event("igbt").signature.approach > 0.1
    for kind in ("si", "sic", "gan"):
        assert event(kind).signature.approach < 0.03, kind
    assert any(f.label == "slow approach to saturation" for f in event("igbt").signature.features)


def test_a_gan_transistor_conducts_in_reverse_at_a_few_volts_more_with_a_negative_gate() -> None:
    gan, si = event("gan"), event("si")
    assert 2.0 <= gan.signature.third_quadrant <= 4.0
    assert si.signature.third_quadrant < 1.5
    assert event("gan", v_off=-3.0).signature.third_quadrant == pytest.approx(
        gan.signature.third_quadrant + 3.0, abs=0.3
    )
    assert "dead time conducts at" in gan.signature.line


def test_a_gan_gate_driven_over_its_rating_is_a_caution() -> None:
    assert not any(f.caution for f in event("gan").signature.features)
    over = event("gan", v_on=7.5).signature
    assert any(f.caution and f.trace == "v_gs" for f in over.features)
    assert "over its 7 V rating" in over.line
    # A silicon gate at the same level is nowhere near its rating.
    assert not any(f.caution for f in event("si").signature.features)


@pytest.mark.parametrize("kind", list(KINDS))
def test_energies_still_meet_the_loss_model(kind) -> None:
    ev = event(kind)
    for e in (ev.on, ev.off):
        assert e.met
        assert e.read.energy == pytest.approx(e.target, rel=0.05)


@pytest.mark.parametrize("kind", list(KINDS))
def test_rates_are_the_kinds_or_said_to_be_indicative(kind) -> None:
    ev = event(kind)
    low, high = RATES[kind]
    for name, e in (("turn-on", ev.on), ("turn-off", ev.off)):
        rate = abs(e.read.dv_dt) / 1e9
        if not e.corrected:
            assert low <= rate <= high, (name, rate)
        else:
            assert any(f"The {name} meets the datasheet's energy only with a large correction" in n for n in ev.notes)


def test_an_igbt_keeps_its_datasheet_figures() -> None:
    """The made-up IGBT's energies are met with the gate-drain charge it tabulates, the
    recovery charge within a factor of two, and the tail time inside its class."""
    ev = event("igbt")
    assert not ev.on.corrected and not ev.off.corrected
    assert ev.off.factor == 1.0


def test_the_signature_lines_differ_by_kind() -> None:
    lines = {kind: event(kind).signature.line for kind in KINDS}
    assert len(set(lines.values())) == len(lines)
    assert lines["igbt"].startswith("IGBT:") and "tail" in lines["igbt"]
    assert lines["gan"].startswith("GaN: no reverse recovery")


@pytest.mark.parametrize("kind", list(KINDS))
def test_the_load_current_is_carried_on_after_each_edge(kind) -> None:
    """After turn-on the switch carries the load; after turn-off, nothing."""
    ev = event(kind)
    assert ev.on.wave.i[-1] == pytest.approx(ev.current, rel=0.01)
    assert abs(ev.off.wave.i[-1]) < 0.01 * ev.current


@pytest.mark.parametrize("kind", ["si", "igbt"])
def test_a_given_layout_still_meets_the_loss_model(kind) -> None:
    """12 nH in the loop, 1 nH of it shared with the gate loop."""
    device = part(KINDS[kind])
    v_dc, current = SHEETS[KINDS[kind]].reference["vdc"], device.ratings.i_nominal / 2
    e_on, e_off = energies(device, v_dc, current)
    given = Detail(l_loop=12e-9, l_cs=1e-9)
    ev = switching_event(device, v_dc=v_dc, current=current, tj=TJ, e_on=e_on, e_off=e_off, given=given)
    for e in (ev.on, ev.off):
        assert e.read.energy == pytest.approx(e.target, rel=0.05)
