"""The command line and the page read a datasheet through the one entry point, say what
it says, and turn each way it can stop into one plain line."""

from __future__ import annotations

import sys

import pytest

from evals.reader import recordings, replay, sheets
from motionsim import server
from motionsim.cli import main
from motionsim.errors import Refusal
from motionsim.observe import provider, run
from motionsim.service.workspace import Workspace

KEYS = (
    "MOTIONSIM_LLM_URL",
    "MOTIONSIM_LLM_KEY",
    "MOTIONSIM_LLM_MODEL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
)


@pytest.fixture
def clean_env(monkeypatch):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def sheet(tmp_path_factory):
    """A made-up datasheet as a PDF on disk, and the recording that stands for the model."""
    one = sheets.labelled_set()[0]
    path = tmp_path_factory.mktemp("wiring") / "igbt.pdf"
    path.write_bytes(sheets.build(one)[0])
    return path, recordings.load(one.name)["faithful"]


@pytest.fixture
def recorded(sheet, monkeypatch):
    """read_datasheet answered from the recording, with what it was asked kept."""
    path, recording = sheet
    asked: list[dict] = []
    real = run.read_datasheet

    def read(pdf, output=None, **kwargs):
        kwargs.pop("say", None)  # where the plan is said is the caller's own business
        asked.append(kwargs)
        with replay.as_if_anthropic():
            return real(pdf, output, client=replay.ReplayClient(path, recording), say=lambda line: None, **kwargs)

    monkeypatch.setattr(run, "read_datasheet", read)
    return path, asked


def test_extract_reads_through_the_entry_point_and_prints_its_summary(recorded, tmp_path, capsys) -> None:
    path, asked = recorded
    out = tmp_path / "read.yaml"
    assert main(["extract", str(path), "-o", str(out)]) == 0
    assert asked == [{"max_calls": provider.MAX_CALLS, "max_pages": None, "curves": True}]
    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == "Made Up Devices MU-G-650-40 (Si IGBT, discrete)"
    # The summary of the reading, line for line: what was read, and what it cost.
    assert printed[1] == "  18 table values read, 0 flagged"
    assert any(line.startswith("  3 model calls, ") for line in printed)
    assert any(line.startswith("  7 curves digitised") for line in printed)
    assert printed[-1] == f"  written to {out}" and out.is_file()


def test_extract_passes_its_limits_on_and_can_leave_the_figures(recorded, tmp_path, capsys) -> None:
    path, asked = recorded
    argv = ["extract", str(path), "-o", str(tmp_path / "read.yaml"), "--max-calls", "7", "--max-pages", "30"]
    assert main([*argv, "--no-curves"]) == 0
    assert asked == [{"max_calls": 7, "max_pages": 30, "curves": False}]
    assert "  0 curves digitised" in capsys.readouterr().out


def test_a_file_with_more_pages_than_allowed_is_refused_before_anything_is_spent(recorded, tmp_path, capsys) -> None:
    path, _ = recorded
    assert main(["extract", str(path), "-o", str(tmp_path / "read.yaml"), "--max-pages", "1"]) == 2
    said = capsys.readouterr().err
    assert said.startswith("cannot read: ") and "pages" in said and not (tmp_path / "read.yaml").exists()


def test_without_the_reader_libraries_extract_says_what_to_install(clean_env, monkeypatch, capsys) -> None:
    # None in sys.modules is how Python records a module that cannot be imported.
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    # Said whether or not the file is there: what is missing is the reader, not the datasheet.
    assert main(["extract", "x.pdf", "-o", "y.yaml"]) == 2
    said = capsys.readouterr().err
    # The package is not on PyPI: the form given must install from where it is, and a bare
    # name there could be anyone's.
    assert said.startswith("cannot read: ")
    assert 'pip install "motionsim[reader] @ git+https://github.com/yannickYamo/MotionSim"' in said
    assert 'pip install ".[reader]"' in said
    assert "Traceback" not in said


@pytest.fixture
def read_once(sheet, tmp_path):
    """Observations on disk, read from the PDF beside them."""
    path, recording = sheet
    saved = tmp_path / "read.yaml"
    with replay.as_if_anthropic():
        run.read_datasheet(path, saved, client=replay.ReplayClient(path, recording), say=lambda line: None)
    return saved, path


@pytest.mark.parametrize(
    "stopped", [provider.NoReader("no model is set up"), provider.ReaderFailed("the service said 500")]
)
def test_curves_says_a_reader_that_stops_in_one_line(read_once, monkeypatch, capsys, stopped) -> None:
    from motionsim.observe import digitise

    def stop(*args, **kwargs):
        raise stopped

    monkeypatch.setattr(digitise, "digitise_curves", stop)
    saved, path = read_once
    assert main(["curves", str(saved), str(path)]) == 2
    assert capsys.readouterr().err.strip() == f"cannot read: {stopped}"


@pytest.mark.parametrize(
    "stopped", [provider.NoReader("no model is set up"), provider.ReaderFailed("the service said 500")]
)
def test_check_says_a_reader_that_stops_in_one_line(read_once, monkeypatch, capsys, stopped) -> None:
    from motionsim.observe import ingest

    def stop(*args, **kwargs):
        raise stopped

    monkeypatch.setattr(ingest, "with_transcripts", stop)
    saved, path = read_once
    assert main(["check", str(saved), str(path)]) == 2
    assert capsys.readouterr().err.strip() == f"cannot read: {stopped}"


def test_a_key_about_to_cross_plain_http_is_said_before_the_reading(
    recorded, clean_env, monkeypatch, tmp_path, capsys
) -> None:
    path, _ = recorded
    monkeypatch.setenv("MOTIONSIM_LLM_URL", "http://models.example/v1")
    monkeypatch.setenv("MOTIONSIM_LLM_KEY", "sk-not-a-real-key")
    monkeypatch.setenv("MOTIONSIM_LLM_MODEL", "stub")
    assert main(["extract", str(path), "-o", str(tmp_path / "read.yaml")]) == 0
    said = capsys.readouterr().err.splitlines()
    assert len([line for line in said if line.startswith("warning: ") and "not encrypted" in line]) == 1
    assert "sk-not-a-real-key" not in "\n".join(said)


def test_a_service_on_this_machine_is_not_warned_of(recorded, clean_env, monkeypatch, tmp_path, capsys) -> None:
    path, _ = recorded
    monkeypatch.setenv("MOTIONSIM_LLM_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setenv("MOTIONSIM_LLM_KEY", "sk-not-a-real-key")
    monkeypatch.setenv("MOTIONSIM_LLM_MODEL", "stub")
    assert main(["extract", str(path), "-o", str(tmp_path / "read.yaml")]) == 0
    assert "warning" not in capsys.readouterr().err


# ---------- the page's server ----------


def test_the_server_reads_through_the_entry_point_and_returns_its_summary(
    recorded, clean_env, monkeypatch, tmp_path
) -> None:
    path, asked = recorded
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")
    answer = server.read_datasheet("igbt.pdf", path.read_bytes(), Workspace(tmp_path))
    assert asked == [{}]
    assert answer["read"]["summary"][0] == "18 table values read, 0 flagged"
    assert answer["read"]["values"] == 18 and answer["read"]["warnings"] == []
    assert answer["device"]["id"] == "igbt"


def _stopping(monkeypatch, exc: Exception) -> None:
    def stop(*args, **kwargs):
        raise exc

    monkeypatch.setattr(run, "read_datasheet", stop)


@pytest.mark.parametrize(
    ("stopped", "fix"),
    [
        (provider.ReaderRefused("the model declined to read this"), "try another datasheet"),
        (provider.ReaderFailed("the service said 500"), "check the key and the file, then try again"),
        (
            provider.NoReader("no model is set up"),
            "set it in the shell that runs `motionsim serve`, then start it again",
        ),
    ],
)
def test_the_server_refuses_in_the_readers_own_words(sheet, clean_env, monkeypatch, tmp_path, stopped, fix) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")
    _stopping(monkeypatch, stopped)
    with pytest.raises(Refusal) as caught:
        server.read_datasheet("igbt.pdf", sheet[0].read_bytes(), Workspace(tmp_path))
    assert str(stopped) in caught.value.reason and caught.value.fix == fix


def test_a_slip_in_the_reader_is_a_fault_and_not_the_users_mistake(sheet, clean_env, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")
    _stopping(monkeypatch, KeyError("page"))
    with pytest.raises(KeyError):
        server.read_datasheet("igbt.pdf", sheet[0].read_bytes(), Workspace(tmp_path))


def test_the_server_passes_on_the_warning_of_a_key_in_the_clear(recorded, clean_env, monkeypatch, tmp_path) -> None:
    path, _ = recorded
    monkeypatch.setenv("MOTIONSIM_LLM_URL", "http://models.example/v1")
    monkeypatch.setenv("MOTIONSIM_LLM_KEY", "sk-not-a-real-key")
    monkeypatch.setenv("MOTIONSIM_LLM_MODEL", "stub")
    answer = server.read_datasheet("igbt.pdf", path.read_bytes(), Workspace(tmp_path))
    (warning,) = answer["read"]["warnings"]
    assert "not encrypted" in warning and "sk-not-a-real-key" not in warning
