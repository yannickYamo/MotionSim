"""Field weakening by voltage feedback (regulators.VoltageFeedbackFw).

The expected values are worked from the steady-state voltage of the machine, R left out:
|v| = ωe·√((ψ + Ld·id)² + (Lq·iq)²), so the loop must settle where that equals the headroom's
share of the most voltage, which gives id in closed form.
"""

from __future__ import annotations

import math

import pytest
from test_control_bench import design, posted, started, workspace

from motionsim.control import context
from motionsim.control.blocks import kind_of
from motionsim.control.presets import BUILDERS


def _block(**params):
    d = design()
    ctx = context(d, BUILDERS["torque_fw_feedback"](d))
    block = kind_of("voltage_feedback_fw")("fw", {"headroom": 0.95, "bandwidth": 100.0, **params}, ctx)
    block.reset()
    return block, ctx


def _closed(block, ctx, w_e, i_d, i_q, v_dc, steps=20000):
    """The block on a machine whose voltage is the steady one of the currents it asks."""
    v_d = v_q = 0.0
    for k in range(steps):
        out_d, out_q, delta, held = block.step(k * ctx.ts, i_d, i_q, v_d, v_q, v_dc, w_e)
        v_d, v_q = -w_e * ctx.lq * out_q, w_e * (ctx.psi + ctx.ld * out_d)
    return out_d, out_q, delta, held


def test_below_the_headroom_the_loop_adds_nothing():
    block, _ = _block()
    out = block.step(0.0, -3.0, 10.0, 1.0, 2.0, 48.0, 500.0)
    assert out == (-3.0, 10.0, 0.0, 0.0)


def test_where_the_voltage_runs_out_it_settles_on_the_headroom():
    block, ctx = _block()
    v_dc, i_q = 48.0, 10.0
    v_max = ctx.pwm.max_modulation_index * 0.5 * v_dc
    # A speed at which the magnet alone asks 1.3 times the most voltage.
    w_e = 1.3 * v_max / ctx.psi
    out_d, out_q, delta, _ = _closed(block, ctx, w_e, 0.0, i_q, v_dc)
    by_hand = (math.sqrt((0.95 * v_max / w_e) ** 2 - (ctx.lq * i_q) ** 2) - ctx.psi) / ctx.ld
    assert out_d == pytest.approx(by_hand, rel=1e-4)
    assert delta == pytest.approx(by_hand, rel=1e-4) and out_q == i_q


def test_it_never_goes_past_the_characteristic_current_and_holds_the_current_limit():
    block, ctx = _block(i_limit=1e3)
    v_dc = 48.0
    v_max = ctx.pwm.max_modulation_index * 0.5 * v_dc
    # Far past what any d current can reach: the q axis's own voltage, ωe·Lq·iq, is already
    # above the most there is, so nothing on the d axis brings the voltage within it.
    w_e = 50.0 * v_max / ctx.psi
    assert w_e * ctx.lq * 10.0 > v_max
    out_d, _, _, held = _closed(block, ctx, w_e, 0.0, 10.0, v_dc)
    assert out_d == pytest.approx(-ctx.psi / ctx.ld, rel=1e-9) and held == 1.0
    block, ctx = _block(i_limit=20.0)
    out_d, out_q, _, held = _closed(block, ctx, 1.3 * v_max / ctx.psi, 0.0, 30.0, v_dc)
    assert math.hypot(out_d, out_q) == pytest.approx(20.0, rel=1e-9) and held == 1.0


@pytest.fixture(scope="module")
def ws():
    return workspace()


def test_with_the_flux_above_the_controllers_figure_the_model_alone_loses_the_torque_and_the_loop_keeps_it(ws):
    base = started("example-mosfet", ws)
    conditions = base["conditions"] | {"rpm": 1.5 * base["conditions"]["rpm"]}
    made = {}
    for scheme in ("foc_torque", "torque_fw_feedback"):
        answer = posted(
            "/api/control/run",
            base | {"conditions": conditions, "scheme": scheme, "mismatch": {"flux": 1.15}, "fidelity": "averaged"},
            ws,
        )
        made[scheme] = answer["verdict"]["findings"][0]["head"]
    asked = base["conditions"]["torque"]
    # The torque made is said first; with no torque feedback, a flux 15% high makes up to 15% more.
    torque = {k: float(v.split("made ")[1].split(" N·m")[0]) for k, v in made.items()}
    assert torque["foc_torque"] < 0.5 * asked
    assert asked < torque["torque_fw_feedback"] < 1.2 * asked


def test_with_the_motor_as_the_controller_holds_it_the_loop_changes_nothing(ws):
    base = started("example-mosfet", ws)
    runs = [
        posted("/api/control/run", base | {"scheme": s, "fidelity": "averaged"}, ws)["channels"]["i_switch_rms"]
        for s in ("foc_torque", "torque_fw_feedback")
    ]
    assert runs[1] == pytest.approx(runs[0], rel=1e-3)
