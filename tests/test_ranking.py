"""A comparison has to put devices in the right order, say when it cannot tell them apart,
and say where they are not compared like for like."""

from __future__ import annotations

import math
import tomllib
from pathlib import Path

import numpy as np
import pytest
from conftest import V_REF, line, linear_device
from test_mosfet import fet
from test_mosfet import op as fet_op
from test_propose import BASE, MOTOR, igbt

from motionsim import __version__, cli
from motionsim.device import save_device
from motionsim.engine import OperatingPoint
from motionsim.engine.compare import compare, crossover, sweep_switching_frequency
from motionsim.engine.limits import hottest
from motionsim.propose import LEVEL, explain, level_with_best, propose, switching_footing

ROOT = Path(__file__).parent.parent
EXAMPLES = ROOT / "examples"
DV0 = 0.9  # V: how much more the fast device drops
K_SLOW, K_FAST = 70e-6, 18e-6  # J/A, turn-on and turn-off together


def pair():
    """Two devices alike but for this: one drops less and switches slower."""

    def build(name, v0, k):
        d = linear_device(
            sw_curves=[line(25.0, v0, 0.03)],
            d_curves=[line(25.0, 1.0, 0.025)],
            k_on=0.6 * k,
            k_off=0.4 * k,
            k_rr=5e-6,
            rth_sw=0.2,
            rth_d=0.2,
        )
        d.part_number = name
        return d

    return build("SLOW", 0.7, K_SLOW), build("FAST", 0.7 + DV0, K_FAST)


def test_two_devices_cross_where_the_closed_forms_say() -> None:
    m, pf, i_rms = 0.8, 0.9, 20.0
    # A switch conducts v0 * Ipk * (1/2pi + m*pf/8) more for each volt of offset, and loses
    # f * k * Ipk / pi in switching: the two differences are equal at one frequency.
    f_cross = DV0 * (1 / (2 * math.pi) + m * pf / 8) * math.pi / (K_SLOW - K_FAST)
    slow, fast = pair()

    def at(f_sw):
        return OperatingPoint(v_dc=V_REF, i_rms=i_rms, modulation_index=m, power_factor=pf, f_sw=f_sw, t_sink=25.0)

    assert [r.device.part_number for r in compare([fast, slow], at(0.8 * f_cross))] == ["SLOW", "FAST"]
    assert [r.device.part_number for r in compare([slow, fast], at(1.2 * f_cross))] == ["FAST", "SLOW"]
    frequencies = np.linspace(0.5 * f_cross, 1.5 * f_cross, 9)
    table = sweep_switching_frequency([slow, fast], at(f_cross), frequencies)
    assert crossover(frequencies, table[0], table[1]) == pytest.approx(f_cross, rel=0.01)


def test_devices_the_model_cannot_tell_apart_are_called_level() -> None:
    near = propose([igbt("ONE", 0.90), igbt("TWO", 0.92), igbt("FAR", 1.6)], MOTOR, 3000, 2.0, BASE)
    level = level_with_best(near)
    assert [c.device.part_number for c in level] == ["ONE", "TWO"]
    assert level[1].loss <= level[0].loss * (1 + LEVEL) < near[2].loss
    text = " ".join(explain(near))
    assert "synthetic ONE and synthetic TWO lose within 5% of each other" in text
    assert "has the lowest power-stage loss" not in text
    assert "synthetic FAR loses" in text and "synthetic TWO loses" not in text

    clear = propose([igbt("ONE", 0.7), igbt("FAR", 1.6)], MOTOR, 3000, 2.0, BASE)
    assert [c.device.part_number for c in level_with_best(clear)] == ["ONE"]
    assert "synthetic ONE has the lowest power-stage loss" in " ".join(explain(clear))


def test_the_margin_is_counted_from_the_top_of_the_range_and_said_when_it_differs() -> None:
    cool, hot = igbt("COOL", 0.92, rth=1.0), igbt("HOT", 0.90, rth=6.0)
    ranked = propose([cool, hot], MOTOR, 3000, 2.0, BASE)
    assert [c.device.part_number for c in ranked] == ["HOT", "COOL"]  # by loss, as before
    for c in ranked:
        assert c.design.result.tj_peak_range is None
        assert c.margin == pytest.approx(150.0 - hottest(c.design.result))
        assert c.stall_margin == pytest.approx(150.0 - hottest(c.stall.result))
    by = {c.device.part_number: c for c in ranked}
    more = by["COOL"].margin - by["HOT"].margin
    assert more > 5
    assert f"synthetic COOL has {more:.0f} °C more margin to its junction limit at the design point" in " ".join(
        explain(ranked)
    )

    alike = propose([igbt("A", 0.90), igbt("B", 0.92)], MOTOR, 3000, 2.0, BASE)
    assert "more margin" not in " ".join(explain(alike))


def test_the_switching_footing_says_what_each_figure_rests_on() -> None:
    measured = igbt("MEASURED", 0.9)
    measured.switch.e_on.rg = measured.switch.e_off.rg = 10.0
    measured.switch.e_on.gate_voltage = 15.0
    same = switching_footing(measured, BASE)
    assert (same.kind, same.text, same.stretched) == ("measured", "measured at 300 V, 10 Ω, 15 V gate", False)

    from dataclasses import replace

    higher = switching_footing(measured, replace(BASE, v_dc=360.0))
    assert higher.stretched and higher.text.endswith("brought to 360 V in proportion")
    lower = switching_footing(measured, replace(BASE, v_dc=200.0))
    assert not lower.stretched and lower.text.endswith("brought to 200 V in proportion")
    own = switching_footing(measured, replace(BASE, rg_on=22.0, rg_off=22.0))
    assert own.text.endswith("your gate resistor is not applied, for want of a figure against it")
    measured.switch.e_on.rg_values, measured.switch.e_on.rg_factor = [5.0, 50.0], [0.8, 2.0]
    followed = switching_footing(measured, replace(BASE, rg_on=22.0, rg_off=33.0))
    assert followed.text.endswith("brought to 22 Ω on, 33 Ω off along the datasheet's figure")

    charge = switching_footing(fet(), fet_op())
    assert (charge.kind, charge.text) == (
        "from charge",
        "estimated from gate and output charge, with 2 Ω on, 1 Ω off at 5 V drive",
    )


def test_devices_on_unlike_data_are_said_to_be() -> None:
    gate = fet_op(i_rms=0.0, t_dead=2e-7)
    mixed = propose(
        [igbt("MEASURED", 0.9), fet()],
        MOTOR,
        3000,
        2.0,
        BASE,
        tune=lambda d: gate if d.switch.kind == "mosfet" else BASE,
    )
    assert all(c.design is not None for c in mixed)
    text = " ".join(explain(mixed))
    assert "is measured and that of" in text and "rests on unlike data" in text
    assert "unlike data" not in " ".join(explain(propose([igbt("A", 0.7), igbt("B", 1.6)], MOTOR, 3000, 2.0, BASE)))

    from dataclasses import replace

    tested_low = igbt("TESTED-LOW", 0.9)
    tested_low.switch.e_on.v_ref = tested_low.switch.e_off.v_ref = 200.0
    text = " ".join(explain(propose([igbt("A", 0.7), tested_low], MOTOR, 3000, 2.0, replace(BASE, v_dc=300.0))))
    assert "synthetic TESTED-LOW is brought in proportion to a higher voltage" in text


def test_the_command_line_ranks_a_part_that_has_charge_data_only(tmp_path, capsys) -> None:
    part = fet()
    part.part_number = "CHARGE-ONLY"
    path = tmp_path / "fet.yaml"
    save_device(part, path)
    code = cli.main(
        [
            "propose",
            str(path),
            "--vdc",
            "48",
            "--motor",
            str(EXAMPLES / "motor_robot_joint_pmsm.yaml"),
            "--fsw",
            "20000",
            "--tsink",
            "40",
            "--tdead",
            "2e-7",
            "--rpm",
            "1000",
            "--torque",
            "1",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "gate drive chosen for the lowest loss within the limits" in out
    assert "give the gate drive voltage" not in out and "ruled out" not in out
    assert "margin" in out.splitlines()[2]


def test_the_command_line_takes_parallel_devices_and_a_motor_temperature(capsys) -> None:
    point = [
        str(EXAMPLES / "synthetic_igbt_600v_30a.yaml"),
        "--vdc",
        "300",
        "--motor",
        str(EXAMPLES / "motor_appliance_pmsm.yaml"),
        "--fsw",
        "16000",
        "--tsink",
        "70",
        "--rpm",
        "3000",
        "--torque",
        "6",
    ]
    assert cli.main(["motor", *point]) == 0
    plain = capsys.readouterr().out
    assert cli.main(["motor", *point, "--parallel", "2", "--tmotor", "120", "--tmin", "1e-6"]) == 0
    out = capsys.readouterr().out
    assert "2 devices in parallel" in out and "2 devices in parallel" not in plain
    assert "motor taken at 120 °C" in out and "motor taken at" not in plain


def test_one_version_everywhere(capsys) -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert __version__ == declared
    with pytest.raises(SystemExit) as stop:
        cli.main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == f"motionsim {declared}"
