"""A leg the modulator holds to a rail does not switch: its duty cycle is the rail itself, the
kernel counts no commutation for it, and the commutations left are the ones arithmetic gives."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest
from test_control_bench import block_of, design, posted, started, workspace

from motionsim.control import Inverter, Kernel, Plant, Trial, compile_scheme, context
from motionsim.control.applications import traction_dpwm
from motionsim.control.blocks import Context
from motionsim.control.sensing import MIN_LOSS, Modulator
from motionsim.engine.modulation import Pwm
from motionsim.service.control.running import execute

# The made-up part on which the clamp was charged the most commutations it does not make.
KEY = "example"
CLAMPS = ("discontinuous-high", "discontinuous-low", "discontinuous", MIN_LOSS)


@pytest.fixture(scope="module")
def ws():
    return workspace()


def ran(ws, pwm: str, fidelity: str):
    """A hold of the part's design point under torque control with one modulation."""
    base = started(KEY, ws)
    scheme = copy.deepcopy(
        next(s for s in posted("/api/control/presets", base, ws)["schemes"] if s["id"] == "traction_dpwm")
    )
    block_of(scheme, "modulator")["params"].update(pwm=pwm, threshold=0.0)  # advance: 1.5, as the preset has it
    steps = execute({**base, "scheme": scheme, "fidelity": fidelity}, ws)
    while True:
        try:
            next(steps)
        except StopIteration as done:
            return done.value


def analysed_duties(trace) -> np.ndarray:
    kept = trace.time >= trace.gather_from - 1e-12
    return np.stack([trace.wire(f"modulator.d_{x}") for x in "abc"], axis=1)[kept]


@pytest.mark.parametrize("pwm", [*(p.value for p in Pwm if p.value.startswith("discontinuous")), MIN_LOSS])
def test_a_clamped_leg_s_duty_cycle_is_the_rail_itself_at_every_angle_and_size(pwm: str) -> None:
    # 0.5·(1 + u + (1 − u)) is not 1 in floating point for every u: it comes out one rounding
    # step under for about one reference in twenty. A leg held to a rail has to read 0 or 1.
    ctx = Context(ts=5e-5, f_carrier=2e4, v_dc=48.0, rs=0.03, ld=8e-5, lq=8e-5, psi=0.01, pole_pairs=7)
    block = Modulator("modulator", {"pwm": pwm}, ctx)
    for m in (0.31, 0.77, 1.013, 1.111):
        for k in range(720):
            angle = 2.0 * math.pi * (k + 0.37) / 720
            v = 0.5 * 48.0 * m
            duties = block.step(0.0, v * math.cos(angle), v * math.sin(angle), 48.0, 3.0, -1.0, -2.0, 0.0)[:3]
            held = [d for d in duties if d in (0.0, 1.0)]
            assert len(held) >= 1, f"no leg is on a rail at m = {m}, {math.degrees(angle):.2f}°: {duties}"
            assert all(d in (0.0, 1.0) or 1e-12 < d < 1.0 - 1e-12 for d in duties), duties


@pytest.mark.parametrize("pwm", CLAMPS)
def test_with_one_leg_held_the_averaged_stage_commutates_exactly_four_times_a_period(ws, pwm: str) -> None:
    # Two legs switch, each once up and once down in a carrier period: 4, with no ripple and
    # no pulse to lose. The same count whichever rail the third is held to.
    trace = ran(ws, pwm, "averaged").trace
    periods = int((trace.time >= trace.gather_from - 1e-12).sum())
    assert float(trace.events.sum()) == 4.0 * periods


def test_the_high_and_the_low_clamp_commutate_equally_often(ws) -> None:
    high, low = ran(ws, "discontinuous-high", "averaged").trace, ran(ws, "discontinuous-low", "averaged").trace
    assert float(high.events.sum()) == float(low.events.sum())


@pytest.mark.parametrize("pwm", ("discontinuous-high", "discontinuous-low"))
def test_the_switched_stage_adds_only_the_two_edges_of_each_leg_that_takes_over_the_high_rail(ws, pwm: str) -> None:
    # A carrier period runs from the carrier's peak, where every leg is low. A leg leaving
    # the high rail there falls at the peak and one arriving rises at it: two edges at each
    # hand-over of the high rail beside the four a period. The low rail is handed over at the
    # same peak, where both legs are low already: none.
    trace = ran(ws, pwm, "switched").trace
    duties = analysed_duties(trace)
    on_high = np.argmax(duties, axis=1)[duties.max(axis=1) == 1.0]
    handovers = int(np.count_nonzero(np.diff(on_high))) if pwm.endswith("high") else 0
    assert pwm.endswith("low") or handovers >= 3
    assert float(trace.events.sum()) == 4.0 * duties.shape[0] + 2.0 * handovers


def test_the_least_loss_clamp_switches_half_the_current_of_space_vector_modulation(ws) -> None:
    # Held on the leg of the largest current, the two legs left switch Σ|i| − max|i|. Over a
    # turn of three sines the mean of Σ|i| is 6/π of the peak and the mean of max|i| is 3/π:
    # one half, as long as the current's peak lies within 30° of the voltage's (Hava's
    # switching-loss function at its floor). Here it lags by 10.5°.
    clamped, continuous = ran(ws, MIN_LOSS, "averaged"), ran(ws, "space-vector", "averaged")
    start = clamped.planned.test.settled
    lag = math.atan2(start["v_q"], start["v_d"]) - math.atan2(start["i_q"], start["i_d"])
    assert abs(math.degrees(lag)) < 30.0
    share = float(clamped.trace.switched.sum() / continuous.trace.switched.sum())
    assert share == pytest.approx(0.5, abs=0.01)
    assert float(clamped.trace.events.sum() / continuous.trace.events.sum()) == pytest.approx(2.0 / 3.0, abs=1e-12)
    loss = lambda r: sum(x.switch.turn_on + x.switch.turn_off + x.switch.recovery + x.diode.recovery for x in r.roles)
    assert loss(clamped.found.result) / loss(continuous.found.result) == pytest.approx(0.5, abs=0.02)


def test_a_clamp_chosen_by_currents_a_period_and_a_half_old_changes_legs_that_much_late(ws) -> None:
    # With no advance the clamp is chosen by the sampled currents and applied a period and a
    # half later, the rotor δ = 1.5·2π/(periods a turn) further on. Either side of the instant
    # the two candidate legs carry cos(30° ∓ x) of the peak; the wrong one is held through δ,
    # which adds ∫₀^δ sin x dx = 1 − cos δ six times a turn to the 6/π a turn that space-vector
    # switches: (1 − cos δ)/2 on top of the half.
    base = started(KEY, ws)
    told = posted("/api/control/presets", base, ws)
    scheme = copy.deepcopy(next(s for s in told["schemes"] if s["id"] == "traction_dpwm"))
    block_of(scheme, "modulator")["params"].update(threshold=0.0, advance=0.0)
    steps = execute({**base, "scheme": scheme, "fidelity": "averaged"}, ws)
    late = None
    while late is None:
        try:
            next(steps)
        except StopIteration as done:
            late = done.value
    delta = 1.5 * 2.0 * math.pi / told["design"]["carrier_ratio"]
    share = float(late.trace.switched.sum() / ran(ws, "space-vector", "averaged").trace.switched.sum())
    assert share == pytest.approx(0.5 + 0.5 * (1.0 - math.cos(delta)), abs=0.004)
    assert share > 0.52


def test_the_kernel_counts_no_edge_for_a_duty_cycle_a_rounding_step_from_a_rail() -> None:
    # A scheme of one's own may hand the kernel 1 − 1e-16: a pulse of 1e-16 of a period is
    # no pulse, in either fidelity.
    d = design()
    scheme = traction_dpwm(d)
    for fidelity in ("averaged", "switched"):
        ctx = context(d, scheme)
        test = Trial(duration=20 / d.f_sw, initial={"omega_m": d.omega})
        kernel = Kernel(compile_scheme(scheme, ctx), ctx, Plant(_machine(d), 1.0, held=True), Inverter(fidelity), test)
        kernel.gather = True
        for _ in range(20):
            kernel.drive((1.0 - 1.1e-16, 0.4, 1.1e-16), ctx.ts)
        # Leg a comes up once from where every run starts, with all legs low, and stays.
        assert sum(kernel.N[0:4]) == (1.0 if fidelity == "switched" else 0.0), fidelity
        assert sum(kernel.N[8:12]) == 0.0, fidelity
        assert sum(kernel.N[4:8]) == 40.0, fidelity


def _machine(d):
    from test_control_bench import machine_of

    return machine_of(d)
