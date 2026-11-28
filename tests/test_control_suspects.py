"""Four places where a sign or an accounting could go wrong unseen, each held to a figure
worked out by hand: the thermal supervisor's clamp where the drive regenerates, the
commutations of a scheme that sets its own switching frequency, the predictive controller's
compensation of its delay, and a motor whose two axes differ."""

from __future__ import annotations

import math

import numpy as np
import pytest
from test_control_bench import SALIENT, design, run

from motionsim.control import Trial
from motionsim.control.blocks import Context
from motionsim.control.presets import BUILDERS
from motionsim.control.stage import StageModel
from motionsim.control.thermal import ThermalSupervisor


def stage(reverse_in_switch: bool) -> StageModel:
    """A stage of round figures: 1 V and 10 mΩ across a position, 50 µJ and 10 µJ/A a pair
    of commutations, at 20 kHz. At 10 A: 1.1 V, 11 W carried, and 150 µJ, 3 W switched."""
    return StageModel(
        v0=1.0, r=0.01, e0=50e-6, e1=10e-6, f_sw=20e3, t_sink=40.0,
        r_th=(1.0,), tau=(0.01,), tj_max=150.0, reverse_in_switch=reverse_in_switch,
    )  # fmt: skip


def supervisor(reverse_in_switch: bool) -> ThermalSupervisor:
    ctx = Context(
        ts=5e-5, f_carrier=2e4, v_dc=48.0, rs=0.03, ld=8e-5, lq=8e-5, psi=0.01, pole_pairs=7,
        stage=stage(reverse_in_switch),
    )  # fmt: skip
    block = ThermalSupervisor("thermal", {}, ctx)
    block.reset()
    return block


CURRENTS = (10.0, -5.0, -5.0)  # leg a carries the most, out of the leg


@pytest.mark.parametrize("reverse_in_switch", (True, False))
def test_motoring_the_clamp_pays_while_the_commutations_saved_outweigh_the_conduction_added(reverse_in_switch) -> None:
    block = supervisor(reverse_in_switch)
    # Leg a has the highest duty cycle: it is held high, and its upper switch, which carried
    # the 10 A for 0.8 of the period, carries it for all of it: 0.2 · 11 W = 2.2 W more, for
    # 3 W of switching saved.
    assert block._clamp_pays(CURRENTS, (0.8, 0.35, 0.35), 20e3) is True
    # From 0.6 of the period it is 0.4 · 11 W = 4.4 W more: the clamp would heat the switch.
    assert block._clamp_pays(CURRENTS, (0.6, 0.45, 0.45), 20e3) is False


def test_regenerating_the_clamp_is_judged_on_the_switch_it_really_loads() -> None:
    # Regenerating, the leg carrying the most current out has the LOWEST duty cycle: the
    # modulator can only hold it low. Its lower position then carries the 10 A for all of
    # the period where it carried it for 0.8: 0.2 · 11 W = 2.2 W more where the lower switch
    # conducts backwards itself, against 3 W of switching saved in the upper one.
    assert supervisor(True)._clamp_pays(CURRENTS, (0.2, 0.65, 0.65), 20e3) is True
    # With a diode chip beside the switch the 10 A goes through the diode: no switch is
    # loaded more at all, and the upper switch stops commutating.
    assert supervisor(False)._clamp_pays(CURRENTS, (0.2, 0.65, 0.65), 20e3) is True
    # Held low from 0.6: 0.6 · 11 W = 6.6 W more in the lower switch, for 3 W saved.
    assert supervisor(True)._clamp_pays(CURRENTS, (0.6, 0.9, 0.9), 20e3) is False
    assert supervisor(False)._clamp_pays(CURRENTS, (0.6, 0.9, 0.9), 20e3) is True


def test_the_clamp_is_judged_on_the_leg_the_modulator_would_hold() -> None:
    # The leg of the largest current has the middle duty cycle: it cannot be held. Of the
    # highest and the lowest the modulator holds the one carrying more, here leg c (−6 A,
    # lowest, held low: its lower switch carries the current forwards for 0.7 of the period
    # already). 0.3 · 6 A · 1.06 V = 1.9 W more against 20 kHz · 110 µJ = 2.2 W saved.
    assert supervisor(True)._clamp_pays((10.0, -4.0, -6.0), (0.5, 0.8, 0.3), 20e3) is True
    # At 2 A in that leg (and 3 A in the highest): the highest is held, 0.2 · 3 · 1.03 V =
    # 0.62 W more against 20 kHz · 80 µJ = 1.6 W.
    assert supervisor(True)._clamp_pays((-5.0, 3.0, 2.0), (0.5, 0.8, 0.3), 20e3) is True


# The commutations of a scheme that sets its own switching period.


@pytest.mark.parametrize("key", ("example-mosfet", "example-sic"))
def test_a_scheme_that_sets_its_own_period_is_charged_two_commutations_a_leg_for_each_period_it_asked(key) -> None:
    from test_control_bench import started, workspace

    from motionsim.service.control.running import execute

    ws = workspace()
    base = started(key, ws)
    steps = execute(
        {**base, "scheme": "vsf_torque", "fidelity": "averaged", "scenario": {"kind": "hold", "periods": 8}}, ws
    )
    while True:
        try:
            next(steps)
        except StopIteration as done:
            trace = done.value.trace
            break
    kept = np.flatnonzero(trace.time >= trace.gather_from - 1e-12)
    # With the delay, the period and the duty cycles in use from one instant are the ones
    # asked at the instant before.
    asked = trace.wire("frequency.period")[kept - 1]
    duties = np.stack([trace.wire(f"frequency.d_{x}") for x in "abc"], axis=1)[kept - 1]
    assert asked.max() > 1.2 * asked.min()  # the period really varies through the turn
    # Each bin of the loss accounting spans the period asked, and a leg off the rails rises
    # once and falls once in it, however long it is.
    assert trace.bin_seconds == pytest.approx(asked, rel=1e-12)
    switching = ((duties > 0.0) & (duties < 1.0)).sum(axis=1)
    assert np.array_equal(trace.events.sum(axis=1), 2.0 * switching)
    # So the mean switching frequency is the periods over the time they took, not the mean
    # of the frequencies asked (which counts a short period as much as a long one).
    assert switching.min() == 3
    periods_per_second = asked.size / asked.sum()
    assert float(trace.events.sum()) / 6.0 / float(trace.bin_seconds.sum()) == pytest.approx(
        periods_per_second, rel=1e-12
    )
    assert periods_per_second < 0.999 * np.mean(1.0 / asked)


# The predictive controller's compensation of its delay.

MPC_MOTOR = dict(rs=0.05, ld=1.0e-3, lq=2.4e-3, psi=0.1, pole_pairs=4)


def by_hand(i_d, i_q, legs, theta, w, ts, v_dc):
    """One sampling period on under the legs' state, by one forward step of the motor's two
    equations, the state's voltage seen from the rotor at the angle of mid-period."""
    m = MPC_MOTOR
    a, b, c = legs
    v_alpha, v_beta = v_dc * (2 * a - b - c) / 3.0, v_dc * (b - c) / math.sqrt(3.0)
    angle = theta + 0.5 * w * ts
    v_d = v_alpha * math.cos(angle) + v_beta * math.sin(angle)
    v_q = v_beta * math.cos(angle) - v_alpha * math.sin(angle)
    return (
        i_d + ts * (v_d - m["rs"] * i_d + w * m["lq"] * i_q) / m["ld"],
        i_q + ts * (v_q - m["rs"] * i_q - w * (m["ld"] * i_d + m["psi"])) / m["lq"],
    )


def test_the_predictive_controller_costs_each_state_by_the_current_two_instants_on() -> None:
    from motionsim.control.predictive import FcsMpc

    ts, v_dc, w, theta = 50e-6, 300.0, 1000.0, 0.4
    ctx = Context(ts=ts, f_carrier=1.0 / ts, v_dc=v_dc, **MPC_MOTOR)
    block = FcsMpc("predictive", {"weight": 0.3}, ctx)
    block.reset()
    block._state = 0b011  # legs a and b high through the period now beginning
    out = block.step(0.0, -6.0, 14.0, -5.0, 12.0, theta, w, v_dc)
    # First to the instant the choice takes effect, under the state that stands. Legs a and
    # b high are 100 V on α and 173.2 V on β; seen from the rotor at 0.425 rad, 162.5 V on d
    # and 116.6 V on q. On d: 50 µs · (162.5 + 0.25 + 1000 · 2.4 mH · 12 A) / 1 mH = 9.578 A.
    # On q: 50 µs · (116.6 − 0.6 − 1000 · (0.1 − 1 mH · 5 A)) / 2.4 mH = 0.437 A.
    d1, q1 = by_hand(-5.0, 12.0, (1, 1, 0), theta, w, ts, v_dc)
    assert (d1, q1) == pytest.approx((4.578, 12.437), abs=2e-3)
    # Then one period more under each of the eight, at the angle the rotor has by then.
    costs = []
    for state in range(8):
        legs = (state & 1, state >> 1 & 1, state >> 2 & 1)
        d2, q2 = by_hand(d1, q1, legs, theta + w * ts, w, ts, v_dc)
        changed = sum(x != y for x, y in zip(legs, (1, 1, 0), strict=True))
        costs.append(abs(-6.0 - d2) + abs(14.0 - q2) + 0.3 * changed)
    assert list(out[5:13]) == pytest.approx(costs, abs=1e-9)
    assert int(out[4]) == int(np.argmin(costs))
    # Without the compensation the same eight are costed from the measured currents, as if
    # the choice stood at once: other figures, and here another choice.
    plain = FcsMpc("predictive", {"weight": 0.3, "delay_compensation": False}, ctx)
    plain.reset()
    plain._state = 0b011
    late = plain.step(0.0, -6.0, 14.0, -5.0, 12.0, theta, w, v_dc)
    d2, q2 = by_hand(-5.0, 12.0, (0, 0, 0), theta, w, ts, v_dc)
    assert late[5] == pytest.approx(abs(-6.0 - d2) + abs(14.0 - q2) + 0.3 * 2, abs=1e-9)
    assert max(abs(x - y) for x, y in zip(late[5:13], costs, strict=True)) > 1.0


def test_the_current_the_predictive_controller_expects_is_the_one_the_motor_has_two_instants_on() -> None:
    # On the motor whose axes differ, against the plant itself: the cost of the state chosen
    # at instant k (no weight: the current error alone) is the error found at k + 2, and
    # not the one at k + 1 or k + 3.
    d = design(SALIENT, v_dc=320.0, rpm=3000.0, torque=12.0, i_design=20.0, i_limit=60.0)
    scheme = BUILDERS["mpc_torque"](d)
    block = next(b for b in scheme.blocks if b.kind == "fcs_mpc")
    block.params["weight"] = 0.0
    test = Trial(
        duration=20 / d.f_out, speed=lambda t: d.omega, torque=lambda t: d.torque, initial={"omega_m": d.omega}
    )
    trace = run(scheme, d, test, held=True)
    cost = trace.wire(f"{block.name}.cost")
    id_ref, iq_ref = trace.wire(block.inputs["id_ref"]), trace.wire(block.inputs["iq_ref"])
    i_d, i_q = trace.wire("plant.i_d"), trace.wire("plant.i_q")
    k = np.arange(200, cost.size - 3)
    off = {
        lag: float(np.mean(np.abs(cost[k] - np.abs(id_ref[k] - i_d[k + lag]) - np.abs(iq_ref[k] - i_q[k + lag]))))
        for lag in (1, 2, 3)
    }
    step = float(np.mean(np.abs(np.diff(i_q))))
    assert off[2] < 0.03 * step  # one forward step against the plant's own integration
    assert off[1] > 0.5 * step and off[3] > 0.5 * step


# A motor whose two axes differ, against the loss engine.


@pytest.mark.parametrize("fidelity", ("averaged", "switched"))
@pytest.mark.parametrize("key", ("example-mosfet", "example-sic"))
def test_a_motor_whose_axes_differ_settles_and_loses_what_the_engine_says(key: str, fidelity: str) -> None:
    from test_control_bench import engine_answer, posted, started, workspace

    from motionsim.service.validate import motor as motor_of

    ws = workspace()
    base = started(key, ws)
    figures = dict(base["motor"])
    one = figures.pop("l")
    figures.update(ld=one, lq=2.4 * one, magnets="interior")
    base["motor"] = figures
    got = posted("/api/control/run", {**base, "scheme": "foc_torque", "fidelity": fidelity}, ws)
    engine = engine_answer(key, base, ws)
    m = motor_of(figures)
    i_d, i_q = got["ripple"]["i_d"], got["ripple"]["i_q"]
    # The torque asked, by the motor's own equation from the currents the run holds: the
    # magnet's share and the share of the two inductances' difference, which needs i_d < 0.
    torque = 1.5 * m.pole_pairs * (m.flux_linkage * i_q + (m.ld - m.lq) * i_d * i_q)
    assert torque == pytest.approx(base["conditions"]["torque"], rel=2e-3)
    assert i_d < -0.2 * i_q
    # Less current than with the magnet alone, and the engine's own size of it.
    assert math.hypot(i_d, i_q) == pytest.approx(engine["i_peak"], rel=2e-3)
    assert engine["i_peak"] < 0.95 * base["conditions"]["torque"] / (1.5 * m.pole_pairs * m.flux_linkage)
    losses = got["losses"]
    assert losses["loss"] == pytest.approx(engine["loss"], rel=0.01)
    assert losses["conduction"] == pytest.approx(engine["conduction"], rel=0.015)
    assert losses["switching"] == pytest.approx(engine["switching"], rel=0.02)
    t_sink = engine["t_sink"]
    assert losses["tj_peak"] - t_sink == pytest.approx(engine["tj_peak"] - t_sink, rel=0.02)
