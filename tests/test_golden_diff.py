"""The tool that says how far the kept figures moved between two versions."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

TOOL = Path(__file__).parent.parent / "tools" / "golden_diff.py"


def _tool():
    spec = importlib.util.spec_from_file_location("golden_diff", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_group_counts_its_moved_figures_words_and_keys(capsys, tmp_path) -> None:
    """Two figures moved, by 10% and 50% of the larger of old and new: 10 to 11 is 1/11,
    1 to 2 is 1/2. One word changed, one key came and one went, and a figure that stayed
    is not counted."""
    old = {"g": {"a": 10.0, "b": [1.0, 5.0], "w": "x", "gone": 1}}
    new = {"g": {"a": 11.0, "b": [2.0, 5.0], "w": "y", "came": 2}}
    d = _tool().compare(old["g"], new["g"])
    assert d["shared"] == 4
    assert [round(m[0], 6) for m in d["moved"]] == [0.5, round(1 / 11, 6)]
    assert d["words"] == [("/w", "x", "y")]
    assert d["added"] == ["/came"] and d["removed"] == ["/gone"]

    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(old))
    b.write_text(json.dumps(new))
    assert _tool().main([str(a), str(b)]) == 0
    row = capsys.readouterr().out.splitlines()[1].split()
    # group, shared, moved, median of 1/11 and 1/2, largest, words, added, removed
    assert row == ["g", "4", "2", f"{(1 / 11 + 0.5) / 2:.3%}", "50.000%", "1", "1", "1"]
