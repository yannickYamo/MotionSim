"""The control's update rate against the carrier: several times a carrier period (the compare
values reloaded mid-slope) and once every few carrier periods (a controller slower than its
stage), against what a carrier and a comparator do, worked by hand."""

from __future__ import annotations

import copy
import dataclasses
import math

import pytest
from test_control_bench import posted, started, workspace

from motionsim.control import Kernel, Plant
from motionsim.control.presets import _current_gains, retimed, timing_at
from motionsim.errors import Refusal
from motionsim.service.control.running import prepared

KEY = "example-mosfet"


@pytest.fixture(scope="module")
def ws():
    return workspace()


def _timed(ws, timing: dict, fidelity: str = "switched"):
    """A kernel of the torque scheme at a timing, ready to be stepped by hand (no dead time,
    as a run has unless asked)."""
    base = started(KEY, ws)
    offered = posted("/api/control/presets", base, ws)
    scheme = next(s for s in offered["schemes"] if s["id"] == "foc_torque")
    scheme["timing"] = {**scheme["timing"], **timing}
    request = base | {"scheme": scheme, "scenario": {"kind": "torque_step"}, "fidelity": fidelity}
    ready = prepared(request, ws)
    planned = ready.planned
    plant = Plant(ready.machine, planned.shaft.inertia, planned.shaft.load, planned.held, ready.inverter.r_on, None)
    return Kernel(ready.compiled, ready.ctx, plant, ready.inverter, planned.test), ready


class _Tally:
    """What the stage did: each leg's high time, and its edges."""

    def __init__(self, kernel: Kernel) -> None:
        self.high = [0.0, 0.0, 0.0]
        self.edges = [0, 0, 0]
        stretch, edge = kernel._stretch, kernel._edge

        def stretched(state: int, h: float) -> None:
            for leg in range(3):
                if (state >> leg) & 1:
                    self.high[leg] += h
            stretch(state, h)

        def edged(leg: int, rising: bool) -> None:
            self.edges[leg] += 1
            edge(leg, rising)

        kernel._stretch, kernel._edge = stretched, edged


def test_the_sampling_period_is_the_carrier_s_divided_by_the_updates_or_times_the_carriers(ws) -> None:
    f_sw = posted("/api/control/presets", started(KEY, ws), ws)["design"]["f_sw"]
    for timing, expected in (
        ({"update": "multi", "per_carrier": 4}, 1.0 / (4 * f_sw)),
        ({"update": "multi", "per_carrier": 8}, 1.0 / (8 * f_sw)),
        ({"update": "every", "carriers": 3}, 3.0 / f_sw),
    ):
        _, ready = _timed(ws, timing)
        assert ready.ctx.ts == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("n", [4, 6, 8])
def test_updated_mid_slope_at_one_duty_cycle_a_carrier_period_is_the_single_update_s(ws, n) -> None:
    # The same duty cycle in every slice: each leg high d·Tc in the carrier period and two edges.
    kernel, ready = _timed(ws, {"update": "multi", "per_carrier": n})
    tally = _Tally(kernel)
    ts = ready.ctx.ts
    duties = (0.7, 0.35, 0.52)
    for k in range(n):
        kernel.k = k
        kernel._sliced(duties, ts)
    for leg, d in enumerate(duties):
        assert tally.high[leg] == pytest.approx(d * n * ts, rel=1e-9)
    assert tally.edges == [2, 2, 2]


@pytest.mark.parametrize("n", [1, 4, 8])
def test_with_a_dead_time_each_leg_loses_it_whether_updated_once_or_several_times_a_period(ws, n) -> None:
    # A dead time of 1 µs each edge, a carrier period of 50 µs: a leg whose current flows out
    # of it (positive) is high 1/50 less of the period, one whose current flows in 1/50 more,
    # however many times the compare values are reloaded in it.
    timing = {"update": "single"} if n == 1 else {"update": "multi", "per_carrier": n}
    kernel, ready = _timed(ws, timing)
    kernel.inverter = dataclasses.replace(kernel.inverter, t_dead=1e-6)
    kernel.plant.start(i_d=0.0, i_q=30.0, theta=1.2)
    kernel.ia, kernel.ib, kernel.ic = kernel.plant.phase_currents()
    tally = _Tally(kernel)
    period = n * ready.ctx.ts
    assert period == pytest.approx(50e-6, rel=1e-12)
    duties = (0.5, 0.4, 0.76)
    for k in range(n):
        kernel.k = k
        kernel.drive(duties, ready.ctx.ts)
    for leg, (d, i) in enumerate(zip(duties, (kernel.ia, kernel.ib, kernel.ic), strict=True)):
        assert tally.high[leg] / period == pytest.approx(d - math.copysign(0.02, i), abs=1e-9)
    assert tally.edges == [2, 2, 2]


def test_a_duty_cycle_reloaded_below_the_carrier_mid_slope_crosses_it_again(ws) -> None:
    # Four slices; leg a at 0.9 goes high a twentieth into the carrier period (the carrier, from
    # one at the peak, falls under 0.9 there). Reloaded at 0.3 for the second quarter, where the
    # carrier stands between 0.5 and 0, the carrier is above it at the quarter's start: the leg
    # goes back low at once, and high again where the carrier falls under 0.3.
    kernel, ready = _timed(ws, {"update": "multi", "per_carrier": 4})
    tally = _Tally(kernel)
    ts = ready.ctx.ts
    th = 2.0 * ts
    kernel.k = 0
    kernel._sliced((0.9, 0.5, 0.5), ts)
    assert tally.high[0] == pytest.approx(ts - 0.1 * th, rel=1e-9)
    kernel.k = 1
    kernel._sliced((0.3, 0.5, 0.5), ts)
    # Low from the quarter's start until the carrier falls under 0.3, at 0.7 of the half.
    assert tally.high[0] == pytest.approx((ts - 0.1 * th) + (th - 0.7 * th), rel=1e-9)
    assert tally.edges[0] == 3  # up, down at the reload, up again


def test_averaged_a_slice_gets_the_share_of_it_the_carrier_stands_under_the_duty_cycle(ws) -> None:
    # Four slices, d = 0.7: the carrier falls from 1 to 0.5 in the first (under 0.7 for 0.4 of it),
    # from 0.5 to 0 in the second (all of it), and back up in the falling half: 0.4, 1, 1, 0.4.
    kernel, ready = _timed(ws, {"update": "multi", "per_carrier": 4}, fidelity="averaged")
    got: list[float] = []
    kernel._averaged = lambda duties, ts, edges=None: got.append(duties[0])  # type: ignore[method-assign]
    for k in range(4):
        kernel.k = k
        kernel._averaged_slice((0.7, 0.5, 0.5), ready.ctx.ts)
    assert got == pytest.approx([0.4, 1.0, 1.0, 0.4], abs=1e-12)
    assert sum(got) / 4 == pytest.approx(0.7, abs=1e-12)


@pytest.mark.parametrize(("n", "d"), [(4, 0.5), (8, 0.5), (8, 0.25), (8, 0.75), (4, 0.3)])
def test_averaged_a_leg_switches_once_up_and_once_down_a_period_where_its_edge_meets_a_slice_s_start(ws, n, d) -> None:
    # At 0.5 with four slices the carrier crosses the duty cycle exactly where a slice starts: the
    # slices are all on or all off, and the leg still switches on and off once each a period.
    kernel, ready = _timed(ws, {"update": "multi", "per_carrier": n}, fidelity="averaged")
    kernel.plant.start(i_d=0.0, i_q=30.0, theta=1.2)
    kernel.ia, kernel.ib, kernel.ic = kernel.plant.phase_currents()
    kernel.gather = True
    for k in range(n):
        kernel.k = k
        kernel._averaged_slice((d, d, d), ready.ctx.ts)
    for leg in range(3):
        assert sum(kernel.N[4 * leg : 4 * leg + 4]) == pytest.approx(2.0, abs=1e-12)


def test_updated_every_few_carrier_periods_each_carrier_period_is_switched_alike(ws) -> None:
    kernel, ready = _timed(ws, {"update": "every", "carriers": 3})
    tally = _Tally(kernel)
    kernel._carriers((0.6, 0.4, 0.5), ready.ctx.ts)
    assert tally.edges == [6, 6, 6]
    for leg, d in enumerate((0.6, 0.4, 0.5)):
        assert tally.high[leg] == pytest.approx(d * ready.ctx.ts, rel=1e-9)


def test_retimed_the_gains_follow_the_rule_at_the_new_sampling_period(ws) -> None:
    base = started(KEY, ws)
    ready = prepared(base | {"scheme": "foc_torque"}, ws)
    design, scheme = ready.design, ready.scheme
    for rate in (0.5, 2.0, 4.0):
        moved = retimed(scheme, design, rate)
        ts = moved.control_period(design.f_sw)
        assert ts == pytest.approx(1.0 / (rate * design.f_sw), rel=1e-12)
        # The rule by hand: a twentieth of the sampling rate, or what the delay leaves.
        wc = min(2 * math.pi / (20 * ts), (math.pi / 2 - math.radians(60)) / (1.5 * ts))
        current = next(b for b in moved.blocks if b.kind == "current_pi_dq")
        assert current.params["kp_q"] == pytest.approx(wc * design.lq, rel=1e-9)
        assert current.params == pytest.approx(_current_gains(design, ts, True)[0], rel=1e-12)
    assert timing_at(0.25) == {"update": "every", "carriers": 4}
    assert retimed(scheme, design, 1.0).timing["update"] == "single"


@pytest.mark.parametrize("scheme_id", ["sensorless_emf", "sensorless_flux", "sensorless_smo", "sensorless_hfi"])
def test_an_estimated_scheme_retimed_at_its_own_rate_is_the_preset_and_slower_its_observer_follows(
    ws, scheme_id
) -> None:
    # The preset is the reference: tuned again at the rate it was built for, nothing moves, the
    # speed loop under its estimate's lag included. Every fourth carrier, the observer's band
    # stays within an eighth of the sampling rate.
    from test_control_injection import salient

    request = salient(ws) | {"scheme": scheme_id}
    ready = prepared(request, ws)
    design, scheme = ready.design, ready.scheme
    own = retimed(scheme, design, 2.0)
    assert scheme.timing["update"] == "double"
    for before, after in zip(scheme.blocks, own.blocks, strict=True):
        assert after.params == before.params, before.name
    slow = retimed(scheme, design, 0.25)
    observer = next(b for b in slow.blocks if b.name == "observer").params
    rate = 1.0 / slow.control_period(design.f_sw)
    for key in ("bandwidth", "cutoff"):
        if key in observer:
            assert observer[key] <= rate / 8.0 * (1 + 1e-12)


def test_what_has_no_carrier_to_update_against_is_refused_by_name(ws) -> None:
    base = started(KEY, ws)
    for scheme_id, why in (("mpc_torque", "states"), ("foc_torque", None)):
        offered = posted("/api/control/presets", base, ws)
        scheme = next(s for s in offered["schemes"] if s["id"] == scheme_id)
        scheme["timing"] = {**scheme["timing"], "update": "multi", "per_carrier": 4}
        if why is None:
            continue
        with pytest.raises(Refusal) as refused:
            prepared(base | {"scheme": scheme}, ws)
        assert why in refused.value.reason and refused.value.field == "scheme.timing.update"
    shunted = base | {"scheme": "foc_servo"}
    offered = posted("/api/control/presets", shunted, ws)
    servo = next(s for s in offered["schemes"] if s["id"] == "foc_servo")
    sample = next(b for b in servo["blocks"] if b["kind"] == "current_sampling")
    sample["kind"] = "shunt_sampling"
    sample["inputs"] |= {
        n: f"inverter.{n}"
        for n in ("window_a", "window_b", "window_c", "i_dc_1", "vector_1", "span_1", "i_dc_2", "vector_2", "span_2")
    }
    sample["params"] = {}
    servo["timing"] = {**servo["timing"], "update": "every", "carriers": 2}
    with pytest.raises(Refusal) as refused:
        prepared(shunted | {"scheme": servo}, ws)
    assert "shunts" in refused.value.reason
    for timing, field in (
        ({"update": "multi", "per_carrier": 5}, "scheme.timing.per_carrier"),
        ({"update": "single", "carriers": 2}, "scheme.timing.carriers"),
    ):
        scheme = copy.deepcopy(next(s for s in offered["schemes"] if s["id"] == "foc_torque"))
        scheme["timing"] = {"update": "single", "delay": True, "f_control": None} | timing
        with pytest.raises(Refusal) as refused:
            prepared(base | {"scheme": scheme}, ws)
        assert refused.value.field == field


def test_an_averaged_run_updated_several_times_a_period_says_what_it_is(ws) -> None:
    base = started(KEY, ws)
    offered = posted("/api/control/presets", base, ws)
    scheme = next(s for s in offered["schemes"] if s["id"] == "foc_torque")
    scheme["timing"] = {**scheme["timing"], "update": "multi", "per_carrier": 4}
    answer = posted("/api/control/run", base | {"scheme": scheme, "fidelity": "averaged", "points": 200}, ws)
    assert any("switched stage" in said for said in answer["taken"])
