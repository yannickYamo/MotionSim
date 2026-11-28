"""The current reference of least total loss: of all the pairs of d- and q-axis current that
make a torque, the one for which the motor's copper, the motor's iron and the inverter
together lose least.

The least-current pair (control/regulators.py) minimises the copper loss and, since the
inverter's loss rises with the current, nearly the inverter's too. It ignores the iron: the
loss in the iron rises with the flux through it, and a negative d-axis current lowers that
flux. Past the speed at which the iron loss saved is worth the copper loss spent, the pair of
least loss lies at more negative d-axis current than the pair of least current, and the two
part further as the speed rises and the torque falls.

    P(id, iq) = 1.5·R·(id² + iq²)                                  copper
              + P_fe(n) · ((ψ + Ld·id)² + (Lq·iq)²) / ψ²           iron
              + P_inv(√(id² + iq²))                                inverter

P_fe(n) is the motor's iron loss at the speed as the tool has it everywhere, which is its
loss at full flux: it is taken to fall and rise with the square of the stator flux, as an
iron-loss resistance across the back-EMF would have it. P_inv is the controller's own two
lines of the device (control/stage.py). The search runs along the line of constant torque,
from the least-current pair toward more negative d-axis current, within the current limit
and the voltage.

What this rests on: the iron loss is one figure and a rule for its split and its scaling
with flux, not a measured map; with no iron loss given, least loss and least current are
the same pair.
"""

from __future__ import annotations

import math

from motionsim.control.blocks import Context

GOLDEN = 0.5 * (math.sqrt(5.0) - 1.0)


def total_loss(ctx: Context, i_d: float, i_q: float, omega_m: float) -> tuple[float, float, float]:
    """W lost in the copper, in the iron and in the inverter at a pair of currents and a speed."""
    copper = 1.5 * ctx.rs * (i_d * i_d + i_q * i_q)
    iron = 0.0
    if ctx.iron is not None and ctx.psi > 0:
        full = ctx.iron(abs(omega_m) * 30.0 / math.pi)
        iron = full * ((ctx.psi + ctx.ld * i_d) ** 2 + (ctx.lq * i_q) ** 2) / ctx.psi**2
    inverter = ctx.stage.loss(math.hypot(i_d, i_q)) if ctx.stage is not None else 0.0
    return copper, iron, inverter


def least_loss(
    ctx: Context, torque: float, omega_m: float, v_max: float, i_limit: float, start: tuple[float, float]
) -> tuple[float, float]:
    """The pair of least total loss for a torque at a speed, searched from the least-current
    pair `start` toward more negative d-axis current. `start` itself where nothing is gained."""
    if ctx.iron is None or torque == 0.0:
        return start
    w = ctx.pole_pairs * omega_m
    gap = ctx.ld - ctx.lq

    def pair(i_d: float) -> tuple[float, float]:
        return i_d, torque / (1.5 * ctx.pole_pairs * (ctx.psi + gap * i_d))

    def cost(i_d: float) -> float:
        i_d, i_q = pair(i_d)
        v_d = ctx.rs * i_d - w * ctx.lq * i_q
        v_q = ctx.rs * i_q + w * (ctx.ld * i_d + ctx.psi)
        over = max(math.hypot(i_d, i_q) - i_limit, 0.0) + max(math.hypot(v_d, v_q) - v_max, 0.0)
        return sum(total_loss(ctx, i_d, i_q, omega_m)) + 1e6 * over

    # Never past the point where the magnet's flux is all opposed, nor past the current limit.
    low, high = max(-0.95 * ctx.psi / ctx.ld, -i_limit), start[0]
    if low >= high:
        return start
    a, b = low, high
    c, d = b - GOLDEN * (b - a), a + GOLDEN * (b - a)
    f_c, f_d = cost(c), cost(d)
    for _ in range(40):
        if f_c < f_d:
            b, d, f_d = d, c, f_c
            c = b - GOLDEN * (b - a)
            f_c = cost(c)
        else:
            a, c, f_c = c, d, f_d
            d = a + GOLDEN * (b - a)
            f_d = cost(d)
    best = 0.5 * (a + b)
    return pair(best) if cost(best) < cost(start[0]) else start
