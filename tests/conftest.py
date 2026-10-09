"""Builders for linear devices, whose losses have closed-form solutions."""

from __future__ import annotations

from motionsim.device import (
    Chip,
    ConductionModel,
    Curve,
    Device,
    FosterNetwork,
    Package,
    Ratings,
    Source,
    SwitchingEnergy,
    Topology,
)

SRC = Source(kind="synthetic")
I_MAX = 200.0
V_REF = 300.0


def line(tj: float, offset: float, slope: float) -> Curve:
    return Curve(tj=tj, current=[0.0, I_MAX], value=[offset, offset + slope * I_MAX])


def energy(slope: float) -> SwitchingEnergy:
    return SwitchingEnergy(curves=[line(25.0, 0.0, slope)], v_ref=V_REF, source=SRC)


def linear_device(
    *,
    sw_curves: list[Curve],
    d_curves: list[Curve],
    k_on: float = 0.0,
    k_off: float = 0.0,
    k_rr: float = 0.0,
    rth_sw: float = 1.0,
    rth_d: float = 1.0,
    rth_cs: float = 0.0,
    topology: Topology = Topology.discrete,
) -> Device:
    return Device(
        vendor="synthetic",
        part_number="LINEAR",
        technology="Si IGBT",
        ratings=Ratings(v_max=600, i_nominal=30, tj_max=150),
        package=Package(topology=topology, rth_case_sink=rth_cs, rth_mutual=0.0),
        switch=Chip(
            kind="igbt",
            conduction=ConductionModel(curves=sw_curves, source=SRC),
            e_on=energy(k_on),
            e_off=energy(k_off),
            thermal=FosterNetwork(r=[rth_sw], tau=[0.01], source=SRC),
        ),
        diode=Chip(
            kind="diode",
            conduction=ConductionModel(curves=d_curves, source=SRC),
            e_rr=energy(k_rr),
            thermal=FosterNetwork(r=[rth_d], tau=[0.01], source=SRC),
        ),
    )
