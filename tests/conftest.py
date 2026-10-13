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


# ---------- two made-up SiC modules for comparisons, and a pytest option ----------

SIC = """\
schema_version: 1
vendor: synthetic
part_number: {name}
technology: SiC MOSFET
ratings: {{v_max: 650, i_nominal: 30, tj_max: 175}}
package: {{topology: six_pack, rth_case_sink: 0.1}}
switch:
  kind: mosfet
  conduction:
    source: {{kind: synthetic}}
    curves:
      - {{tj: 25, current: [0, 60], value: [0.0, 3.0]}}
      - {{tj: 150, current: [0, 60], value: [0.0, 4.2]}}
  reverse:
    source: {{kind: synthetic}}
    curves:
      - {{tj: 25, current: [0, 60], value: [3.0, 4.5]}}
  e_on:
    v_ref: 400
    source: {{kind: synthetic}}
    curves:
      - {{tj: 25, current: [0, 60], value: [0, 0.30e-3]}}
      - {{tj: 150, current: [0, 60], value: [0, 0.33e-3]}}
  e_off:
    v_ref: 400
    source: {{kind: synthetic}}
    curves:
      - {{tj: 25, current: [0, 60], value: [0, 0.12e-3]}}
      - {{tj: 150, current: [0, 60], value: [0, 0.13e-3]}}
  e_rr:
    v_ref: 400
    source: {{kind: synthetic}}
    curves:
      - {{tj: 25, current: [0, 60], value: [0, 0.03e-3]}}
  thermal:
    source: {{kind: synthetic}}
    r: {r}
    tau: [0.001, 0.01, 0.1]
"""


def sic_files(folder) -> None:
    """A SiC module, and the same one with a poor thermal path, as device files in a folder."""
    (folder / "sic.device.yaml").write_text(SIC.format(name="SIC-650V-30A", r="[0.15, 0.4, 0.45]"))
    (folder / "sic-hot.device.yaml").write_text(SIC.format(name="SIC-HOT", r="[0.6, 1.6, 1.8]"))


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="rewrite the golden figures from the code as it is: only where a change in results is meant",
    )
