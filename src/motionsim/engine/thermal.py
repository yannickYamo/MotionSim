"""Junction-to-case thermal behaviour from a Foster network."""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import FosterNetwork


def zth(network: FosterNetwork, t: np.ndarray | float) -> np.ndarray:
    """Thermal impedance at time t after a power step, in K/W."""
    if network.tau is None:
        raise ValueError("this thermal model has no time constants; only steady state is known")
    t = np.asarray(t, dtype=float)
    r = np.asarray(network.r)
    tau = np.asarray(network.tau)
    return (r * (1 - np.exp(-t[..., None] / tau))).sum(axis=-1)


def steady_state_rise(network: FosterNetwork, power: float) -> float:
    """Junction temperature rise over case for a constant power, in K."""
    return network.rth * power


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
    spectrum = np.fft.rfft(power)
    omega = 2 * np.pi * np.fft.rfftfreq(power.size, d=period / power.size)
    r = np.asarray(network.r)
    tau = np.asarray(network.tau)
    impedance = (r / (1 + 1j * omega[:, None] * tau)).sum(axis=1)
    return np.fft.irfft(spectrum * impedance, n=power.size)
