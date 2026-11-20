"""A setup saved from the page carries each part it brought: the model of a device comes with
its device file, which opens again as the same part."""

from __future__ import annotations

from pathlib import Path

from motionsim import page, server

EXAMPLE = Path(__file__).resolve().parents[1] / "src" / "motionsim" / "example_device.yaml"


def test_a_device_model_comes_with_its_file_and_the_file_brings_the_same_part_back(tmp_path: Path) -> None:
    first = server.Workspace(tmp_path / "first")
    added = page.add_device("My Part.device.yaml", EXAMPLE.read_text(encoding="utf-8"), first)
    key = added["device"]["id"]
    carried = page.curves(key, first)["file"]
    assert carried["name"] == f"{key}.device.yaml"
    assert carried["text"] == EXAMPLE.read_text(encoding="utf-8")

    elsewhere = server.Workspace(tmp_path / "elsewhere")
    again = page.add_device(carried["name"], carried["text"], elsewhere)
    assert again["device"] == added["device"]


def test_a_made_up_part_comes_with_its_file_too(tmp_path: Path) -> None:
    workspace = server.Workspace(tmp_path)
    carried = page.curves("example", workspace)["file"]
    assert carried["name"] == "example.device.yaml" and "part_number" in carried["text"]
