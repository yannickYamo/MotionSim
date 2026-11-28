"""The ripple current the DC-link capacitor carries (channels "link_ripple_rms").

The stage draws its current from the link in pulses; the supply is taken to give their average
and the capacitor the rest. The expected values do not come from the engine: for sinusoidal
currents under a carrier far above the output frequency the capacitor's current has a closed form
(Kolar and Round 2006), I_C = I·sqrt(2M(√3/(4π) + cos²φ(√3/π − 9M/16))), with I the phase current
rms, M the phase voltage's amplitude over half the link's, φ the angle between them. The paper's
record was confirmed (IEE Proc. Electric Power Applications 153, 535-543), its text not read: the
form is not taken on its word but held here to a count of the pulses, gate by gate.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from test_control_bench import SURFACE, design, run

from motionsim.control import Trial, metrics
from motionsim.control.presets import foc_torque


def closed_form(i_rms: float, m: float, phi: float) -> float:
    return i_rms * math.sqrt(
        2.0 * m * (math.sqrt(3.0) / (4.0 * math.pi) + math.cos(phi) ** 2 * (math.sqrt(3.0) / math.pi - 9.0 * m / 16.0))
    )


def counted(i_peak: float, m: float, phi: float, periods: int = 600, fine: int = 400) -> float:
    """The same by counting: one electrical turn of `periods` carrier periods, each cut in `fine`
    pieces, the three legs gated against a triangle, space-vector (the middle one of the three
    references, halved, added to each)."""
    total = square = 0.0
    carrier = (np.arange(fine) + 0.5) / fine
    triangle = 1.0 - np.abs(2.0 * carrier - 1.0)
    for k in range(periods):
        theta = 2.0 * math.pi * (k + 0.5) / periods
        angles = [theta - 2.0 * math.pi * n / 3.0 for n in range(3)]
        refs = np.array([m * math.cos(a) for a in angles])
        refs = refs - 0.5 * (refs.max() + refs.min())
        currents = [i_peak * math.cos(a - phi) for a in angles]
        link = np.zeros(fine)
        for ref, current in zip(refs, currents, strict=True):
            link += (triangle < 0.5 * (1.0 + ref)) * current
        total += link.sum()
        square += (link * link).sum()
    n = periods * fine
    return math.sqrt(square / n - (total / n) ** 2)


@pytest.mark.parametrize(("m", "phi"), [(0.3, 0.2), (0.7, 0.5), (1.0, 0.0), (0.9, 1.2)])
def test_the_closed_form_is_what_counting_the_pulses_gives(m: float, phi: float) -> None:
    assert closed_form(10.0 / math.sqrt(2.0), m, phi) == pytest.approx(counted(10.0, m, phi), rel=0.01)


@pytest.mark.parametrize("fidelity", ["switched", "averaged"])
def test_a_hold_gives_the_capacitor_the_current_the_closed_form_says(fidelity: str) -> None:
    d = design()
    w = d.omega
    asked = Trial(duration=0.2, speed=lambda t: w, torque=lambda t: 2.0, initial={"omega_m": w}, gather_from=0.1)
    trace = run(foc_torque(d), d, asked, fidelity=fidelity)
    kept = trace.time >= 0.1
    i_d, i_q = float(trace.wire("plant.i_d")[kept].mean()), float(trace.wire("plant.i_q")[kept].mean())
    w_e = SURFACE.pole_pairs * w
    v_d = SURFACE.rs * i_d - w_e * SURFACE.lq * i_q
    v_q = SURFACE.rs * i_q + w_e * (SURFACE.ld * i_d + SURFACE.psi)
    m = math.hypot(v_d, v_q) / (0.5 * d.v_dc)
    phi = math.atan2(v_q, v_d) - math.atan2(i_q, i_d)
    expected = closed_form(math.hypot(i_d, i_q) / math.sqrt(2.0), m, phi)
    assert expected > 1.0
    assert metrics.link_ripple(trace) == pytest.approx(expected, rel=0.05)


def test_a_drive_that_draws_nothing_gives_the_capacitor_nothing() -> None:
    d = design()
    asked = Trial(duration=0.02, speed=lambda t: 0.0, torque=lambda t: 0.0)
    assert metrics.link_ripple(run(foc_torque(d), d, asked, fidelity="averaged")) == pytest.approx(0.0, abs=1e-6)
