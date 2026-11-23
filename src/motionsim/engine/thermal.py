"""Junction-to-case thermal behaviour from a Foster network."""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import FosterNetwork


def harmonics(r, tau, samples: int, period: float) -> np.ndarray:
    """Thermal impedance of a set of stages at each harmonic of a waveform of this many
    samples that repeats every period, K/W. A period without end is a waveform that is
    held still at each of its samples: every harmonic then sees the whole resistance.
    A stage with no time constant follows at once."""
    r = np.asarray(r, dtype=float)
    tau = np.asarray(tau, dtype=float)
    if not np.isfinite(period):
        return np.full(samples // 2 + 1, r.sum(), dtype=complex)
    omega = 2 * np.pi * np.fft.rfftfreq(samples, d=period / samples)
    return (r / (1 + 1j * omega[:, None] * tau)).sum(axis=1)


def through(impedance: np.ndarray, power: np.ndarray) -> np.ndarray:
    """The rise a repeating power waveform settles to through an impedance given at each of
    its harmonics (see harmonics), at the same instants, K."""
    power = np.asarray(power, dtype=float)
    return np.fft.irfft(np.fft.rfft(power) * impedance, n=power.size)


def periodic_rise(network: FosterNetwork, power: np.ndarray, period: float) -> np.ndarray | None:
    """Junction temperature rise over case for a power waveform that repeats.

    power holds uniform samples over one period, in W. The result is the
    steady-state rise at the same instants, in K: each harmonic of the power
    is multiplied by the thermal impedance at its frequency. Returns None
    when the network has no time constants.
    """
    if network.tau is None:
        return None
    power = np.asarray(power, dtype=float)
    return through(harmonics(network.r, network.tau, power.size, period), power)


def repeating_rise(r, tau, power: np.ndarray, dt: float) -> np.ndarray:
    """Rise at the end of each sample for a power held constant over each sample of dt, once
    the samples have repeated for ever, in K. Exact stage by stage, so a step in the power
    neither rings nor overshoots."""
    from scipy.signal import lfilter

    power = np.asarray(power, dtype=float)
    ends = np.arange(1, power.size + 1)
    out = np.zeros_like(power)
    for stage_r, stage_tau in zip(r, tau, strict=True):
        if stage_tau <= 0:
            out += stage_r * power
            continue
        keep = float(np.exp(-dt / stage_tau))
        # What a stage gains over a step, and loses over a whole round, is taken as it is and
        # not as one less what it keeps: for a step far below the time constant that
        # difference rounds to nothing, and the round's share to nought over nought.
        gained = -float(np.expm1(-dt / stage_tau))
        from_rest = lfilter([stage_r * gained], [1.0, -keep], power)
        # Where it starts each time round is where the last round left it.
        carried = from_rest[-1] / -float(np.expm1(-power.size * dt / stage_tau))
        out += from_rest + carried * keep**ends
    return out
