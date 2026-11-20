"""Every loader of a file the user hands over reads it with the care of files.py: a missing
file, one far too large, one that does not parse and a few lines that stand for millions of
figures are each refused in a line, never a traceback and never read without end."""

from __future__ import annotations

import pytest

from motionsim import files
from motionsim.errors import Refusal
from motionsim.files import read_record, read_text
from motionsim.measured import load_double_pulse
from motionsim.reference import load_reference
from motionsim.trajectory import parse_trajectory


# Each as the command line reads it.
def load_load(path):
    return read_record(path, "load file", "load")


def load_profile(path):
    return read_record(path, "profile file", "profile")


def load_trajectory(path):
    return parse_trajectory(read_text(path, "trajectory", "trajectory"))


YAML_LOADERS = [load_load, load_profile, load_reference]
LOADERS = [*YAML_LOADERS, load_double_pulse, load_trajectory]

# Nine anchors, each naming the one before it ten times: 10**9 figures in a few hundred bytes.
BOMB = "a0: &a0 [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]\n" + "".join(
    f"a{n}: &a{n} [" + ", ".join([f"*a{n - 1}"] * 10) + "]\n" for n in range(1, 10)
)


@pytest.mark.parametrize("loader", LOADERS)
def test_a_file_that_is_not_there_is_refused_by_name(loader, tmp_path) -> None:
    with pytest.raises(Refusal, match=r"cannot read the .* nothing\.here"):
        loader(tmp_path / "nothing.here")


@pytest.mark.parametrize("loader", LOADERS)
def test_a_file_larger_than_any_such_file_is_refused_before_it_is_read(loader, tmp_path) -> None:
    big = tmp_path / "big"
    big.write_bytes(b"#" * (files.MOST_BYTES + 1))
    with pytest.raises(Refusal, match="larger than 5 MB"):
        loader(big)


@pytest.mark.parametrize("loader", YAML_LOADERS)
def test_yaml_that_stands_for_millions_of_figures_is_refused(loader, tmp_path) -> None:
    bomb = tmp_path / "bomb.yaml"
    bomb.write_text(BOMB, encoding="utf-8")
    assert len(BOMB) < 1000
    with pytest.raises(Refusal, match="far more figures"):
        loader(bomb)


@pytest.mark.parametrize("loader", YAML_LOADERS)
def test_yaml_that_does_not_parse_or_holds_no_names_is_refused(loader, tmp_path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("a: [1, 2\n", encoding="utf-8")
    with pytest.raises(Refusal, match="not YAML that can be read"):
        loader(broken)
    listed = tmp_path / "listed.yaml"
    listed.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(Refusal, match="does not hold names and values"):
        loader(listed)


def test_a_measurement_that_is_not_json_is_refused_with_where(tmp_path) -> None:
    broken = tmp_path / "m.json"
    broken.write_text('{"v_dc": 400,\n "points": [}', encoding="utf-8")
    with pytest.raises(Refusal, match=r"not JSON that can be read: .* at line 2"):
        load_double_pulse(broken)


def test_a_trajectory_not_in_utf8_is_refused(tmp_path) -> None:
    latin = tmp_path / "t.csv"
    latin.write_bytes("time_s,i_a,d_a\n0,1,0.5\n1,1,0.5\n# caf\xe9\n".encode("latin-1"))
    with pytest.raises(Refusal, match="not text in UTF-8"):
        load_trajectory(latin)


def test_a_trajectory_from_a_spreadsheet_still_reads_its_first_name(tmp_path) -> None:
    """A spreadsheet's export starts with a byte-order mark, which is not part of time_s."""
    marked = tmp_path / "t.csv"
    marked.write_bytes(b"\xef\xbb\xbftime_s,i_a,d_a\n0,1,0.5\n0.001,2,0.5\n0.002,1,0.5\n")
    assert load_trajectory(marked).legs == ["a"]


def test_a_design_written_as_json_reads_its_numbers_as_json_writes_them(tmp_path) -> None:
    """A program writes 0.00002 as 2e-05 in JSON. Read as YAML 1.1 that is the text '2e-05',
    and a design file written by a program was refused; JSON is read as JSON."""
    file = tmp_path / "design.json"
    file.write_text('{"load": {"motor_inertia": 2e-05, "inertia": 1E3, "name": "1e5"}}', encoding="utf-8")
    assert read_record(file) == {"load": {"motor_inertia": 2e-05, "inertia": 1000.0, "name": "1e5"}}
    # YAML keeps its own reading, where a bare 1e5 is a word such as a part number.
    yaml_file = tmp_path / "part.yaml"
    yaml_file.write_text("part_number: 1e5\nv_max: 2.0e-05\n", encoding="utf-8")
    assert read_record(yaml_file) == {"part_number": "1e5", "v_max": 2e-05}
