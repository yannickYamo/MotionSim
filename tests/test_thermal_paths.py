"""How heat gets from a junction to the heatsink through time: the response assumed for a
part with no transient curve, the case of a package of its own through a slow turn, and the
loss of a chip read at its own temperature at each instant. Each against a closed form, hand
arithmetic, or a simulation stepped through time here."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from conftest import SRC, V_REF, energy, line, zth

from motionsim import guard
from motionsim.device import Chip, ConductionModel, Device, FosterNetwork, Package, Ratings, SwitchingEnergy, Topology
from motionsim.device.io import load_device
from motionsim.engine import OperatingPoint, Role, solve, solve_roles
from motionsim.engine.point import BeyondData, PeakBasis, ThermalRunaway
from motionsim.engine.solver import shared_time, thermal_network
from motionsim.package.column import Column, Layer, sized
from motionsim.package.materials import current_density, family

EXAMPLES = Path(__file__).parent.parent / "examples"
V0_SW, R_SW = 0.9, 0.03
V0_D, R_D = 1.0, 0.025
K_ON, K_OFF, K_RR = 20e-6, 15e-6, 5e-6
F_SW, I_RMS, M, PF = 8000.0, 20.0, 0.8, 0.9

SILICON = Layer(100.0, 1.66e6, 150e-6, slices=12)
SOLDER = Layer(50.0, 1.7e6, 50e-6, slices=3)
TAB = Layer(390.0, 3.45e6, 1.27e-3, spreads=True, slices=10)


def discrete(
    *,
    tau: bool = True,
    rth_sw: float = 0.8,
    rth_d: float = 1.5,
    sw=None,
    e_on=None,
    e_off=None,
    d=None,
    e_rr=None,
    **package,
) -> Device:
    """A switch and a diode in a package of their own, with drops that are straight lines."""
    return Device(
        vendor="synthetic",
        part_number="LINEAR",
        technology="Si IGBT",
        ratings=Ratings(v_max=600, i_nominal=30, tj_max=150),
        package=Package(topology=Topology.discrete, **package),
        switch=Chip(
            kind="igbt",
            conduction=ConductionModel(curves=sw or [line(25.0, V0_SW, R_SW)], source=SRC),
            e_on=e_on or energy(K_ON),
            e_off=e_off or energy(K_OFF),
            thermal=FosterNetwork(r=[rth_sw], tau=[0.01] if tau else None, source=SRC),
        ),
        diode=Chip(
            kind="diode",
            conduction=ConductionModel(curves=d or [line(25.0, V0_D, R_D)], source=SRC),
            e_rr=e_rr or energy(K_RR),
            thermal=FosterNetwork(r=[rth_d], tau=[0.01] if tau else None, source=SRC),
        ),
    )


def point(**kw) -> OperatingPoint:
    base = dict(v_dc=V_REF, i_rms=I_RMS, modulation_index=M, power_factor=PF, f_sw=F_SW, t_sink=40.0)
    return OperatingPoint(**{**base, **kw})


def waves(n: int = 20000) -> tuple[np.ndarray, np.ndarray]:
    """Loss of the straight-line switch and diode at each position of the output period, W:
    the high side carries a positive current in its switch for the duty cycle and a negative
    one in its diode for the duty cycle, and switches it once a PWM period."""
    theta = 2 * math.pi * (np.arange(n) + 0.5) / n
    duty = 0.5 * (1 + M * np.sin(theta))
    i = math.sqrt(2) * I_RMS * np.sin(theta - math.acos(PF))
    out, back = np.maximum(i, 0.0), np.maximum(-i, 0.0)
    p_sw = duty * out * (V0_SW + R_SW * out) + F_SW * (K_ON + K_OFF) * out
    p_d = duty * back * (V0_D + R_D * back) * (back > 0) + F_SW * K_RR * back
    return p_sw, p_d


# ---------- the column under a die ----------


def test_at_first_a_die_heats_as_a_body_without_end_would() -> None:
    """Before the heat has crossed the die, the junction rises as 2·sqrt(t/π) / (e·A), with e
    the die's effusivity sqrt(k·c). A 150 µm silicon die is crossed in about 0.4 ms."""
    side = 3.0e-3
    r, tau = Column(side, (SILICON, SOLDER, TAB)).stages()
    effusivity = math.sqrt(100.0 * 1.66e6)
    for t in (3e-6, 1e-5, 3e-5):
        expected = 2 * math.sqrt(t / math.pi) / (effusivity * side**2)
        assert float((r * (1 - np.exp(-t / tau))).sum()) == pytest.approx(expected, rel=0.02)


def test_each_layer_is_cut_into_its_slices_and_the_first_follows_the_first_microseconds() -> None:
    """A layer cut into n slices gives the ladder n stages: the die, the solder and the copper
    here, 12, 3 and 10, are 25. A 150 µm silicon die alone, in the 8 slices a layer has unless
    told, growing from its top, follows the body without end, 2·sqrt(t/π) / (e·A), to within
    3% from 3 µs on."""
    side = 3.0e-3
    assert Column(side, (SILICON, SOLDER, TAB)).stages()[0].size == 25
    die = Layer(100.0, 1.66e6, 150e-6)
    r, tau = Column(side, (die,)).stages()
    assert r.size == 8
    effusivity = math.sqrt(100.0 * 1.66e6)
    for t in (3e-6, 1e-5, 3e-5):
        expected = 2 * math.sqrt(t / math.pi) / (effusivity * side**2)
        assert float((r * (1 - np.exp(-t / tau))).sum()) == pytest.approx(expected, rel=0.03)


@pytest.mark.parametrize(("outline", "longer"), [("TO-247", 17.0e-3), ("TO-220", 12.5e-3), ("TOLL", 9.7e-3)])
def test_the_slowest_stage_of_a_large_die_on_its_tab_is_heat_crossing_the_tab_lengthwise(outline, longer) -> None:
    """A die as large as its rating allows leaves part of the datasheet's resistance to the
    tab: one more stage, as slow as heat crossing half the tab's longer side of copper with
    one end held, 4·L²/(π²·α), α = 390 / 3.45e6 m²/s."""
    from motionsim.package.templates import column_response

    stages = column_response(outline, 0.6, "low", area=(6e-3) ** 2)
    crossing = 4 * (longer / 2) ** 2 * 3.45e6 / (math.pi**2 * 390.0)
    assert max(tau for _, tau in stages) == pytest.approx(crossing, rel=1e-9)


def test_a_slab_held_at_its_far_face_heats_as_its_series_solution_says() -> None:
    """One layer, no spreading, heat in at one face and the other held: the rise at the
    heated face is (L/kA)·(1 − Σ 8/(n²π²)·exp(−n²π²αt/4L²)) over the odd n."""
    k, c, length, side = 390.0, 3.45e6, 1.0e-3, 3.0e-3
    r, tau = Column(side, (Layer(k, c, length, slices=14),)).stages()
    alpha, steady = k / c, length / (k * side**2)
    odd = np.arange(1, 400, 2)
    for t in (2e-4, 1e-3, 3e-3, 1e-2):
        series = steady * (
            1 - (8 / (odd * math.pi) ** 2 * np.exp(-((odd * math.pi) ** 2) * alpha * t / (4 * length**2))).sum()
        )
        assert float((r * (1 - np.exp(-t / tau))).sum()) == pytest.approx(series, rel=0.015)
    assert float(r.sum()) == pytest.approx(steady, rel=1e-9)


def test_the_steady_resistance_of_a_column_is_its_layers_in_series_with_the_copper_widening() -> None:
    """A 3 mm die: 150 µm of silicon and 50 µm of solder under its own area, then 1.27 mm of
    copper widening at 45°, from 3 mm to 5.54 mm a side: t / (k·a·b) between the two squares."""
    a = 3.0e-3
    b = a + 2 * 1.27e-3
    by_hand = 150e-6 / (100.0 * a * a) + 50e-6 / (50.0 * a * a) + 1.27e-3 / (390.0 * a * b)
    assert by_hand == pytest.approx(0.4737, rel=1e-3)
    assert Column(a, (SILICON, SOLDER, TAB)).resistance == pytest.approx(by_hand, rel=1e-9)
    # The copper is no wider than the tab: held to 4 mm, it stops widening there.
    held = 150e-6 / (100.0 * a * a) + 50e-6 / (50.0 * a * a) + 0.5e-3 / (390.0 * a * 4e-3) + 0.77e-3 / (390.0 * 16e-6)
    # The slice in which the copper reaches that width is taken as widening all through it.
    assert Column(a, (SILICON, SOLDER, TAB), widest=4e-3).resistance == pytest.approx(held, rel=2e-3)


def test_a_die_is_sized_so_that_its_column_has_the_datasheets_resistance() -> None:
    column = sized(0.6, (SILICON, SOLDER, TAB), 45.0, 10e-3)
    assert column.resistance == pytest.approx(0.6, rel=1e-9)
    a = column.side
    assert 2.5e-6 / a**2 + 1.27e-3 / (390.0 * a * (a + 2.54e-3)) == pytest.approx(0.6, rel=1e-6)
    # No die that fits the copper is large enough for a resistance this low: as wide as the copper.
    assert sized(0.01, (SILICON, SOLDER, TAB), 45.0, 10e-3).side == pytest.approx(10e-3)


# ---------- the response assumed for a part with no curve ----------


def without_curve(device: Device) -> Device:
    data = device.model_dump()
    for chip in ("switch", "diode"):
        if data.get(chip):
            data[chip]["thermal"] = {
                "r": [sum(data[chip]["thermal"]["r"])],
                "tau": None,
                "source": data[chip]["thermal"]["source"],
            }
    return Device.model_validate(data)


@pytest.mark.parametrize("package", [{"outline": "TO-220"}, {"outline": "TOLL"}, {}])
def test_an_assumed_response_ends_at_the_datasheets_resistance_exactly(package) -> None:
    device = discrete(tau=False, **package)
    for chip in (device.switch, device.diode):
        for variant in ("low", "typical", "high"):
            network, basis = thermal_network(device, chip, variant)
            assert basis is PeakBasis.assumed
            assert network.rth == pytest.approx(chip.thermal.rth, rel=1e-12)
            assert float(zth(network, 100.0)) == pytest.approx(chip.thermal.rth, rel=1e-9)


@pytest.mark.parametrize("construction", ["leadframe", "substrate", "unknown"])
def test_a_modules_assumed_response_ends_at_the_datasheets_resistance_too(construction) -> None:
    module = without_curve(load_device(EXAMPLES / "synthetic_igbt_600v_30a.yaml"))
    module.package.construction = construction
    for chip in (module.switch, module.diode):
        network, _ = thermal_network(module, chip)
        assert network.rth == pytest.approx(chip.thermal.rth, rel=1e-12)


def test_a_discrete_parts_assumed_response_is_that_of_the_column_sized_to_its_resistance() -> None:
    """A TO-220 with 0.6 K/W: the die that gives it is 2.63 mm a side, and at 10 µs, long
    before the heat leaves the die, the junction has risen as that die's area says."""
    device = discrete(tau=False, rth_sw=0.6, outline="TO-220")
    network, _ = thermal_network(device, device.switch)
    side = sized(0.6, (SILICON, SOLDER, TAB), 45.0, 10e-3).side
    assert side == pytest.approx(2.632e-3, rel=1e-3)
    early = 2 * math.sqrt(1e-5 / math.pi) / (math.sqrt(100.0 * 1.66e6) * side**2)
    assert float(zth(network, 1e-5)) == pytest.approx(early, rel=0.03)
    # Its time constants are those of the layers: the copper's slowest, 4·L²/(π²·α) for a
    # slab of 1.27 mm, is 5.8 ms, a little less where the heat widens.
    assert 3e-3 < max(network.tau) < 5.8e-3
    # Nothing of it waits on the layer under the tab, which has its own place in the result.
    assert float(zth(network, 0.05)) > 0.999 * 0.6


def test_the_low_end_of_an_assumed_response_is_slower_and_ends_at_the_same_resistance() -> None:
    device = discrete(tau=False, rth_sw=0.6, outline="TO-220")
    low, _ = thermal_network(device, device.switch, "low")
    typical, _ = thermal_network(device, device.switch, "typical")
    for t in (1e-4, 1e-3, 1e-2, 1e-1):
        assert float(zth(low, t)) < float(zth(typical, t))
    assert low.rth == pytest.approx(typical.rth)


def test_an_assumed_response_is_never_slower_than_the_example_modules_own_curve() -> None:
    """The one transient curve among the examples, a module's: with it taken away, the response
    assumed in its place heats at least as fast at every time, so the swing it gives is not low."""
    module = load_device(EXAMPLES / "synthetic_igbt_600v_30a.yaml")
    bare = without_curve(module)
    for chip, stripped in ((module.switch, bare.switch), (module.diode, bare.diode)):
        assumed, _ = thermal_network(bare, stripped)
        for t in np.geomspace(1e-4, 1.0, 13):
            assert float(zth(assumed, t)) >= float(zth(chip.thermal, t))


def test_the_top_of_the_range_of_an_assumed_response_is_the_peak_loss_through_the_whole_resistance() -> None:
    """No response can lift a junction above its loss at its worst instant times its
    resistance. With nothing else assumed, that is the top of the range, and the estimate
    lies under it and above the mean."""
    device = discrete(tau=False, rth_case_sink=0.0)
    r = solve(device, point())
    p_sw, p_d = waves()
    bound = 40.0 + max(0.8 * float(p_sw.max()), 1.5 * float(p_d.max()))
    assert r.peak_basis is PeakBasis.assumed
    assert r.tj_peak_range[1] == pytest.approx(bound, abs=0.02)
    mean = 40.0 + 0.8 * float(p_sw.mean())
    assert r.tj_switch == pytest.approx(mean, abs=0.02)
    assert mean + 1.0 < r.tj_switch_peak < bound - 1.0
    assert any("follow the loss at once" in a for a in r.assumptions)


def test_a_range_that_crosses_the_rating_is_undecided_not_passed() -> None:
    device = discrete(tau=False, rth_case_sink=0.0)
    op = point()
    r = solve(device, op)
    device.ratings.tj_max = 0.5 * (max(r.tj_switch_peak, r.tj_diode_peak) + r.tj_peak_range[1])
    found = next(c for c in guard.check(device, op, r, 30.0, junction_margin=0.0) if c.topic == "temperature")
    assert found.level is guard.Level.undecided and "range crosses" in found.message
    device.ratings.tj_max = r.tj_peak_range[1] + 40.0
    found = next(c for c in guard.check(device, op, r, 30.0, junction_margin=0.0) if c.topic == "temperature")
    assert found.level is guard.Level.ok


# ---------- a package of its own through a slow turn ----------

RTH_CS = 0.5
TAB_CAPACITY = 3.45e6 * 15.9e-3 * 17.0e-3 * 2.0e-3  # J/K: the copper tab of a TO-247


def stepped(f_out: float, turns: int = 6, n: int = 20000) -> tuple[float, float]:
    """The switch's junction and its case followed through time until they repeat: the
    junction's own path is one resistance and one time constant, the case is the tab's heat
    capacity charged through the layer under it by all the package loses. Each step is exact
    for the loss held through it. Returns the highest junction and the highest case, °C."""
    p_sw, p_d = waves(n)
    dt = 1.0 / (f_out * n)
    keep_own, keep_case = math.exp(-dt / 0.01), math.exp(-dt / (TAB_CAPACITY * RTH_CS))
    # Begun where the mean loss would settle them, so that a few turns are enough.
    own, case = 0.8 * float(p_sw.mean()), RTH_CS * float((p_sw + p_d).mean())
    top_junction = top_case = 0.0
    for turn in range(turns):
        for k in range(n):
            own = 0.8 * p_sw[k] + (own - 0.8 * p_sw[k]) * keep_own
            target = RTH_CS * (p_sw[k] + p_d[k])
            case = target + (case - target) * keep_case
            if turn == turns - 1:
                top_junction, top_case = max(top_junction, own + case), max(top_case, case)
    return 40.0 + top_junction, 40.0 + top_case


@pytest.mark.parametrize("f_out", [0.3, 2.0])
def test_through_a_slow_turn_the_case_follows_the_loss_as_a_simulation_through_time_says(f_out) -> None:
    device = discrete(rth_case_sink=RTH_CS, outline="TO-247")
    assert shared_time(device, point()) == pytest.approx(TAB_CAPACITY * RTH_CS)
    r = solve(device, point(f_out=f_out))
    junction, case = stepped(f_out)
    assert r.tj_switch_peak == pytest.approx(junction, abs=0.03)
    assert r.t_case == pytest.approx(case, abs=0.03)


def test_held_still_a_junction_stands_where_the_worst_position_puts_it_and_a_crawl_agrees() -> None:
    device = discrete(rth_case_sink=RTH_CS, outline="TO-247")
    p_sw, p_d = waves()
    # Where the switch loses most its diode carries nothing: the case has the switch's loss alone.
    worst = 40.0 + (RTH_CS + 0.8) * float(p_sw.max())
    still = solve(device, point(f_out=0.0))
    assert still.tj_switch_peak == pytest.approx(worst, abs=0.01)
    assert still.t_case == pytest.approx(40.0 + RTH_CS * float((p_sw + p_d).max()), abs=0.01)
    crawl = solve(device, point(f_out=1e-4))
    assert crawl.tj_switch_peak == pytest.approx(still.tj_switch_peak, abs=0.01)
    assert crawl.t_case == pytest.approx(still.t_case, abs=0.01)


def test_turning_fast_the_case_stands_at_the_mean_loss() -> None:
    device = discrete(rth_case_sink=RTH_CS, outline="TO-247")
    p_sw, p_d = waves()
    r = solve(device, point(f_out=2000.0))
    mean_case = 40.0 + RTH_CS * float((p_sw + p_d).mean())
    assert r.t_case == pytest.approx(mean_case, abs=0.01)
    assert r.tj_switch_peak == pytest.approx(mean_case + 0.8 * float(p_sw.mean()), abs=0.3)


def test_from_standstill_to_speed_the_peak_falls_without_a_step() -> None:
    """Each path is a lag, whose answer to a loss at frequency f falls no faster than 0.385 of
    its whole swing for each e-fold of f. Two paths, the junction's and the case's: between
    neighbouring frequencies the peak may fall by that share of the whole fall and no more."""
    device = discrete(rth_case_sink=RTH_CS, outline="TO-247")
    frequencies = np.geomspace(0.02, 500.0, 60)
    peaks = [solve(device, point(f_out=float(f)), spread=False).tj_switch_peak for f in frequencies]
    still = solve(device, point(f_out=0.0), spread=False).tj_switch_peak
    fast = solve(device, point(f_out=20000.0), spread=False).tj_switch_peak
    whole = still - fast
    assert whole > 10.0
    assert peaks[0] == pytest.approx(still, abs=0.02 * whole)
    step = math.log(frequencies[1] / frequencies[0])
    falls = -np.diff([still, *peaks])
    assert (falls > -1e-6).all()
    assert falls[1:].max() < 0.385 * step * whole * 1.3


def test_a_part_in_still_air_keeps_its_case_at_the_mean_while_it_turns_and_at_the_worst_when_held() -> None:
    """With no heatsink the way to the air is long: even 2 K/W under a tab of 1.87 J/K is 3.7 s."""
    device = discrete(rth_case_sink=0.0)
    p_sw, p_d = waves()
    to_air = 2.0
    assert shared_time(device, point(rth_free=to_air)) == pytest.approx(TAB_CAPACITY * to_air)
    turning = solve(device, point(f_out=50.0, rth_free=to_air, i_rms=I_RMS))
    assert turning.t_case == pytest.approx(40.0 + to_air * float((p_sw + p_d).mean()), abs=0.5)
    held = solve(device, point(f_out=0.0, rth_free=to_air))
    assert held.t_case == pytest.approx(40.0 + to_air * float((p_sw + p_d).max()), abs=0.05)


# ---------- each chip's loss at its own temperature ----------


def hot(curve, per_kelvin: float):
    """The same line 100 K hotter, risen by per_kelvin for each kelvin."""
    return curve.model_copy(
        update={"tj": curve.tj + 100.0, "value": [v * (1 + 100.0 * per_kelvin) for v in curve.value]}
    )


def two_temperatures(curve, per_kelvin: float) -> list:
    return [curve, hot(curve, per_kelvin)]


def test_each_term_is_read_at_the_temperature_of_the_chip_that_loses_it() -> None:
    """A switch and a diode held at a steady current, every table with its own rise with
    temperature and the two chips on unequal paths. Each chip's loss is then a straight
    line in its own temperature, P = S0 + S1·(T − 25), and settles where T = Ts + Rth·P."""
    a_v, a_on, a_off, a_d, a_rr = 0.002, 0.004, 0.003, -0.001, 0.006
    rth_sw, rth_d, t_sink = 0.8, 2.5, 40.0
    on, back = 0.6, 0.3
    # The current runs along a triangle from 12 A at turn-on to 18 A at turn-off, about a mean of
    # 15 A: a knee loses with the mean, a resistance with the mean square, 15² + 6²/12.
    i_on, i_off, mean_amps, square = 12.0, 18.0, 15.0, 15.0**2 + 6.0**2 / 12
    amps = math.sqrt(square)

    def table(slope: float, a: float) -> SwitchingEnergy:
        return SwitchingEnergy(curves=two_temperatures(line(25.0, 0.0, slope), a), v_ref=V_REF, source=SRC)

    device = discrete(
        sw=two_temperatures(line(25.0, V0_SW, R_SW), a_v),
        d=two_temperatures(line(25.0, V0_D, R_D), a_d),
        e_on=table(K_ON, a_on),
        e_off=table(K_OFF, a_off),
        e_rr=table(K_RR, a_rr),
        rth_sw=rth_sw,
        rth_d=rth_d,
        rth_case_sink=0.0,
    )
    n = 64
    flat = np.ones(n)
    role = Role(
        "held", 1, amps * flat, on * flat, back * flat, flat, flat, current_on=i_on * flat, current_off=i_off * flat
    )
    r = solve_roles(device, [role], point(t_sink=t_sink), period=0.02, p_out=0.0, tolerance=1e-7)

    cond, turn_on, turn_off = on * (V0_SW * mean_amps + R_SW * square), F_SW * K_ON * i_on, F_SW * K_OFF * i_off
    s0, s1 = cond + turn_on + turn_off, cond * a_v + turn_on * a_on + turn_off * a_off
    t_sw = (t_sink + rth_sw * (s0 - 25.0 * s1)) / (1 - rth_sw * s1)
    # The diode recovers when the switch of its leg turns on: at the bottom of the ripple.
    cond_d, recovery = back * (V0_D * mean_amps + R_D * square), F_SW * K_RR * i_on
    d0, d1 = cond_d + recovery, cond_d * a_d + recovery * a_rr
    t_d = (t_sink + rth_d * (d0 - 25.0 * d1)) / (1 - rth_d * d1)
    assert abs(t_sw - t_d) > 2.0

    assert r.tj_switch == pytest.approx(t_sw, abs=1e-4)
    assert r.tj_diode == pytest.approx(t_d, abs=1e-4)
    assert r.switch.conduction == pytest.approx(cond * (1 + a_v * (t_sw - 25.0)), rel=1e-6)
    assert r.switch.turn_on == pytest.approx(turn_on * (1 + a_on * (t_sw - 25.0)), rel=1e-6)
    assert r.switch.turn_off == pytest.approx(turn_off * (1 + a_off * (t_sw - 25.0)), rel=1e-6)
    assert r.diode.conduction == pytest.approx(cond_d * (1 + a_d * (t_d - 25.0)), rel=1e-6)
    assert r.diode.recovery == pytest.approx(recovery * (1 + a_rr * (t_d - 25.0)), rel=1e-6)


def rising(r0: float, a: float, rth: float) -> Device:
    """A switch that is a resistance rising by the share a for each kelvin, and nothing else."""
    nothing = [line(25.0, 0.0, 0.0)]
    device = discrete(
        sw=two_temperatures(line(25.0, 0.0, r0), a),
        d=nothing,
        e_on=energy(0.0),
        e_off=energy(0.0),
        e_rr=energy(0.0),
        rth_sw=rth,
        rth_case_sink=0.0,
    )
    device.ratings.tj_max = 200.0
    return device


def test_held_still_a_chips_loss_is_read_at_the_temperature_of_the_position_it_is_held_at() -> None:
    """At a position the switch loses g·(1 + a·(T − 25)) with g = duty·i²·R0, and stands at
    T = Ts + Rth·that: T − Ts = Rth·g·(1 + a·(Ts − 25)) / (1 − Rth·g·a). The hottest position
    is the one with the most g."""
    r0, a, rth, t_sink = 0.02, 0.004, 1.0, 60.0
    theta = 2 * math.pi * (np.arange(20000) + 0.5) / 20000
    i = np.maximum(math.sqrt(2) * I_RMS * np.sin(theta - math.acos(PF)), 0.0)
    g = float((0.5 * (1 + M * np.sin(theta)) * i**2 * r0).max())
    rise = rth * g * (1 + a * (t_sink - 25.0)) / (1 - rth * g * a)
    r = solve(rising(r0, a, rth), point(t_sink=t_sink, f_out=0.0), tolerance=1e-6)
    assert r.tj_switch_peak == pytest.approx(t_sink + rise, abs=0.01)
    # Read at the mean over positions instead, it would stand lower.
    k = 2 * (1 / 8 + M * PF / (3 * math.pi)) * r0 * I_RMS**2
    mean = rth * k * (1 + a * (t_sink - 25.0)) / (1 - rth * k * a)
    assert rise - rth * g * (1 + a * (t_sink + mean - 25.0)) > 0.4


def test_turning_fast_a_chips_loss_is_read_at_its_mean_temperature() -> None:
    r0, a, rth, t_sink = 0.02, 0.004, 1.0, 60.0
    k = 2 * (1 / 8 + M * PF / (3 * math.pi)) * r0 * I_RMS**2
    mean = rth * k * (1 + a * (t_sink - 25.0)) / (1 - rth * k * a)
    r = solve(rising(r0, a, rth), point(t_sink=t_sink, f_out=20000.0), tolerance=1e-6)
    assert r.tj_switch == pytest.approx(t_sink + mean, abs=0.01)
    assert r.switch.conduction == pytest.approx(mean / rth, rel=1e-4)


def test_a_temperature_that_settles_far_above_the_data_is_said_to_and_one_that_never_settles_runs_away() -> None:
    """T − Ts = g·(1 + a·(Ts − 25)) / (1 − g·a) for a steady current, with g = Rth·duty·I²·R0.
    At g·a = 0.9 it settles ten times higher than a part that did not rise, far over the
    rating; at g·a above 1 it has nowhere to settle."""
    r0, a, rth, t_sink = 0.02, 0.01, 1.0, 25.0
    device = rising(r0, a, rth)
    flat = np.ones(16)

    def held(amps: float) -> Role:
        return Role("held", 1, amps * flat, flat, 0 * flat, 0 * flat, 0 * flat)

    amps = math.sqrt(0.9 / (a * rth * r0))
    settles_at = t_sink + (0.9 / a) / (1 - 0.9)
    assert settles_at > device.ratings.tj_max + 500.0
    with pytest.raises(BeyondData, match=f"{settles_at:.0f} °C"):
        solve_roles(device, [held(amps)], point(t_sink=t_sink), period=0.02, p_out=0.0, max_iterations=2000)
    with pytest.raises(ThermalRunaway, match="without settling") as caught:
        solve_roles(device, [held(1.2 * amps)], point(t_sink=t_sink), period=0.02, p_out=0.0)
    assert not isinstance(caught.value, BeyondData)


# ---------- the size of a chip, by technology ----------


def test_a_chip_is_sized_by_what_its_technology_carries_on_a_unit_of_area() -> None:
    assert [family(t) for t in ("Si IGBT", "Si MOSFET", "SiC MOSFET", "GaN HEMT", "silicon carbide FET")] == [
        "igbt",
        "si",
        "sic",
        "gan",
        "sic",
    ]
    assert current_density("Si IGBT", 600) == pytest.approx(1.6e6)
    assert current_density("Si MOSFET", 100) == pytest.approx(5.0e6)
    assert current_density("Si MOSFET", 600) == pytest.approx(5.0e6 / 6)
    assert current_density("Si MOSFET", 30) == pytest.approx(10.0e6)  # the package decides, not the chip
    assert current_density("SiC MOSFET", 1200) == pytest.approx(3.5e6)
    assert current_density("SiC MOSFET", 650) == pytest.approx(3.5e6 * math.sqrt(1200 / 650))
    assert current_density("GaN HEMT", 650) == pytest.approx(3.0e6)
    assert current_density("GaN HEMT", 100) == pytest.approx(3.0e6 * 6.5**0.4)
