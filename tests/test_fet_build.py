"""Field-effect transistor models built from observations."""

from __future__ import annotations

import pytest
from test_observe import DOC, point

from motionsim.device import Basis, Topology
from motionsim.device.schema import ReviewStatus
from motionsim.engine import OperatingPoint, solve
from motionsim.fit import MissingData, build_device
from motionsim.observe.schema import (
    AxisClaim,
    CurveObservation,
    Quantity,
    ReadResult,
)
from motionsim.observe.verify import check

PAGE = (
    "VDS 100 V  ID 133 A  TJ 150 °C  RθJC 0.2 °C/W\n"
    "VGS(TH) ID = 14 mA 0.8 1.3 2.5 V\nRDS(on) VGS = 5 V, ID = 50 A 1.4 1.8 mΩ\n"
    "VSD IS = 0.5 A 1.5 V\nQGS 8.9 QGD 2.3 QG(TH) 6.3 nC VDS = 50 V\nQOSS 85 94 QRR 0\n"
)


def points():
    q = Quantity
    return [
        point(q.v_rated, None, "V", maximum="100"),
        point(q.i_rated, None, "A", maximum="133"),
        point(q.tj_max, None, "°C", maximum="150"),
        point(q.rth_jc_switch, "0.2", "°C/W"),
        point(q.v_th, "1.3", "V", i=0.014, tj=25, maximum="2.5"),
        point(q.rds_on, "1.4", "mΩ", i=50, tj=25, maximum="1.8"),
        point(q.v_sd, "1.5", "V", i=0.5, tj=25),
        point(q.q_gs, "8.9", "nC", i=50, v=50, tj=25),
        point(q.q_gd, "2.3", "nC", i=50, v=50, tj=25),
        point(q.q_g_th, "6.3", "nC", i=50, v=50, tj=25),
        point(q.q_oss, "85", "nC", v=50, tj=25, maximum="94"),
        point(q.q_rr, "0", "nC", tj=25),
    ]


def observations(pts=None):
    result = ReadResult(
        vendor="Example",
        part_number="FET-1",
        technology="GaN HEMT",
        topology=Topology.discrete,
        integrated_driver=False,
        points=points() if pts is None else pts,
        figures=[],
    )
    return check(result, DOC, [PAGE], reader="test")


def resistance_curve() -> CurveObservation:
    axis = AxisClaim(lo=-25, hi=175, log=False)
    return CurveObservation(
        quantity=Quantity.rds_norm_curve,
        page=4,
        label="Figure 9",
        x=[-25, 25, 75, 125, 150],
        y=[0.75, 1.0, 1.35, 1.8, 2.05],
        x_axis=axis,
        y_axis=axis,
        method="vector",
        status=ReviewStatus.unverified,
        flags=[],
    )


def test_clean_read_has_no_flags() -> None:
    assert [o.flags for o in observations().observations] == [[]] * 12


def test_fet_is_built_with_charge_and_reverse_models() -> None:
    device = build_device(observations())
    sw = device.switch
    assert device.diode is None and sw.kind.value == "mosfet"
    assert sw.conduction.curves[0].value[-1] / sw.conduction.curves[0].current[-1] == pytest.approx(1.4e-3)
    assert sw.charge.q_gs == 8.9e-9 and sw.charge.q_rr == 0.0 and sw.charge.v_ref == 50.0
    assert sw.charge.v_plateau == pytest.approx(1.3 * 8.9 / 6.3, rel=1e-3)
    assert sw.reverse.basis is Basis.point and sw.reverse.curves[0].value == [1.5, 1.5]
    assert sw.thermal.r == [0.2]


def test_resistance_follows_the_digitised_temperature_curve() -> None:
    obs = observations()
    obs.curves = [resistance_curve()]
    device = build_device(obs)
    by_temperature = {c.tj: c.value[-1] / c.current[-1] for c in device.switch.conduction.curves}
    assert by_temperature[25.0] == pytest.approx(1.4e-3)
    assert by_temperature[125.0] == pytest.approx(1.4e-3 * 1.8)
    assert max(by_temperature) == 150.0

    op = OperatingPoint(
        v_dc=48,
        i_rms=30,
        modulation_index=0.9,
        power_factor=0.85,
        f_sw=40_000,
        t_sink=125,
        v_drive=5,
        rg_on=2.5,
        rg_off=1.0,
    )
    hot = solve(device, op)
    assert hot.switch.conduction == pytest.approx(1.4e-3 * 1.8 * 30**2 / 2, rel=0.02)


def test_missing_charge_data_is_named() -> None:
    pts = [p for p in points() if p.quantity is not Quantity.q_gd]
    with pytest.raises(MissingData, match="gate-drain charge"):
        build_device(observations(pts))


SIC_PAGE = (
    "VDSS 1200 V ID 20 A TJ 175 °C RθJC 1.41 1.84 °C/W VGS(TH) ID = 5 mA 1.8 3 4.3 V\n"
    "RDS(on) VGS = 20 V, ID = 20 A 80 116 150 mΩ gFS VDS = 20 V 11 S COSS VDS = 800 V 79 pF\n"
    "QG(TH) 10 QGS 18 QGD 11 nC VDS = 600 V EON 135 EOFF 46 µJ VSD ISD = 10 A 3.9 V\n"
    "EREC 4.1 µJ QRR 61.6 nC\n"
)


def sic_points(*, energy: bool = True, threshold_charge: bool = True, gain: str | None = "11"):
    q = Quantity
    pts = [
        point(q.v_rated, "1200", "V"),
        point(q.i_rated, "20", "A"),
        point(q.tj_max, "175", "°C"),
        point(q.rth_jc_switch, "1.41", "°C/W", maximum="1.84"),
        point(q.v_th, "3", "V", i=0.005, tj=25, maximum="4.3"),
        point(q.rds_on, "80", "mΩ", i=20, tj=25, maximum="116"),
        point(q.rds_on, "150", "mΩ", i=20, tj=175),
        point(q.c_oss, "79", "pF", v=800, tj=25),
        point(q.q_gs, "18", "nC", i=20, v=600, tj=25),
        point(q.q_gd, "11", "nC", i=20, v=600, tj=25),
        point(q.v_sd, "3.9", "V", i=10, tj=25),
        point(q.q_rr, "61.6", "nC", i=20, tj=25),
    ]
    if gain is not None:
        pts.append(point(q.g_fs, gain, "S", i=20, v=20, tj=25))
    if threshold_charge:
        pts.append(point(q.q_g_th, "10", "nC", i=20, v=600, tj=25))
    if energy:
        pts += [
            point(q.e_on, "135", "µJ", i=20, v=800, tj=25),
            point(q.e_off, "46", "µJ", i=20, v=800, tj=25),
            point(q.e_rr, "4.1", "µJ", i=20, tj=25),
        ]
    return pts


def sic(**kwargs):
    result = ReadResult(
        vendor="Example",
        part_number="SIC-1",
        technology="SiC MOSFET",
        topology=Topology.h_bridge,
        integrated_driver=False,
        points=sic_points(**kwargs),
        figures=[],
    )
    return check(result, DOC, [SIC_PAGE], reader="test")


def test_tabulated_switching_energy_is_used_for_a_fet() -> None:
    device = build_device(sic())
    sw = device.switch
    assert device.package.topology.positions == 4
    assert sw.e_on.v_ref == 800 and sw.e_on.curves[0].value[-1] == pytest.approx(135e-6)
    assert sw.e_rr.v_ref == 800  # tested in the same circuit as the switch
    assert [c.tj for c in sw.conduction.curves] == [25, 175]
    assert sw.conduction.curves[1].value[-1] / sw.conduction.curves[1].current[-1] == pytest.approx(0.15)
    op = OperatingPoint(v_dc=800, i_rms=8, modulation_index=0.9, power_factor=0.9, f_sw=20e3, t_sink=60, t_dead=3e-7)
    r = solve(device, op)  # no gate drive needed: the energies are measured
    assert r.switch.turn_on > r.switch.turn_off > r.switch.recovery > 0
    # Switching: fsw * E * Ipk / pi at the test voltage, energy linear in current.
    i_pk = 8 * 2**0.5
    assert r.switch.turn_on == pytest.approx(20e3 * 135e-6 * (i_pk / 20) / 3.14159, rel=0.01)


def test_output_charge_is_estimated_from_capacitance_when_not_tabulated() -> None:
    charge = build_device(sic(energy=False)).switch.charge
    assert charge.q_oss == pytest.approx(2 * 79e-12 * 800)
    assert charge.q_oss_scaling == "sqrt" and "abrupt junction" in charge.assumption


def test_plateau_comes_from_transconductance_when_there_is_no_threshold_charge() -> None:
    charge = build_device(sic(energy=False, threshold_charge=False)).switch.charge
    assert charge.v_plateau == pytest.approx(3 + 20 / 11, rel=1e-3)
    assert charge.q_g_th == pytest.approx(18e-9 * 3 / charge.v_plateau, rel=1e-3)
    assert "transconductance" in charge.assumption


def test_no_way_to_estimate_switching_is_refused() -> None:
    with pytest.raises(MissingData, match="plateau"):
        build_device(sic(energy=False, threshold_charge=False, gain=None))


def test_a_minimum_only_transconductance_is_used_and_said() -> None:
    pts = sic_points(energy=False, threshold_charge=False, gain=None)
    pts.append(point(Quantity.g_fs, None, "S", i=20, v=20, tj=25).model_copy(update={"printed_min": "11"}))
    result = ReadResult(
        vendor="Example",
        part_number="SIC-1",
        technology="SiC MOSFET",
        topology=Topology.discrete,
        integrated_driver=False,
        points=pts,
        figures=[],
    )
    charge = build_device(check(result, DOC, [SIC_PAGE], reader="test")).switch.charge
    assert "only as a minimum" in charge.assumption
