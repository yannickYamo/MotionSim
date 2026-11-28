"""The control law exported as C: generated for every covered scheme, refused by name for what
is not covered, and replayed, on the host's compiler, through every made-up part's default
test, every wire beside the simulation's."""

from __future__ import annotations

import base64
import io
import json
import re
import zipfile
from functools import cache

import pytest
import yaml
from test_control_bench import posted, started, workspace

from motionsim import cli
from motionsim.control.codegen import SCHEMES, check, generate, replay
from motionsim.control.presets import BUILDERS
from motionsim.design import starting_setup
from motionsim.errors import Refusal
from motionsim.service.control.export_c import bundle, export_c
from motionsim.service.control.running import prepared
from motionsim.service.routes import dispatch

PARTS = (
    "example",
    "example-mosfet",
    "example-mosfet-40v",
    "example-mosfet-80v",
    "example-gan",
    "example-sic",
    "example-sic-module",
)
# The least-loss scheme is exported where the motor has no iron loss to weigh: it is then the
# plain current reference, and so is its C.
# Injection is not offered on these parts (alike axes); its refusal is in test_control_injection.py.
REFUSED = sorted(set(BUILDERS) - set(SCHEMES) - {"least_loss_torque", "sensorless_hfi"})
# Words a maker's name or a real part number would show as.
MAKERS = re.compile(
    r"infineon|wolfspeed|cree|onsemi|stmicro|texas instruments|\bti\b|nexperia|rohm|vishay|toshiba|epc\b|"
    r"\bgan systems|navitas|transphorm|mitsubishi|semikron|fuji|littelfuse|\bixys|microchip|renesas|nxp",
    re.IGNORECASE,
)
INNER_LOOP_SCHEMES = {"torque_fw_feedback", "compressor_smooth"}
needs_compiler = pytest.mark.skipif(replay.compiler() is None, reason="no C compiler on this machine")


@cache
def made(key: str, scheme: str) -> dict:
    ws = workspace()
    return bundle(started(key, ws) | {"scheme": scheme}, ws)


def unzipped(raw: bytes) -> dict[str, str]:
    z = zipfile.ZipFile(io.BytesIO(raw))
    return {name.removeprefix("motionsim_ctrl/"): z.read(name).decode() for name in z.namelist()}


@pytest.mark.parametrize("scheme", [*SCHEMES, "least_loss_torque"])
def test_every_covered_scheme_is_generated_with_its_constants_said(scheme) -> None:
    ws = workspace()
    ready = prepared(started("example-mosfet", ws) | {"scheme": scheme}, ws)
    check(ready.compiled)
    g = generate(ready.compiled, ready.ctx, ["a made-up design"])
    for api in ("void motionsim_ctrl_init(", "void motionsim_ctrl_warm(", "void motionsim_ctrl_step("):
        assert api in g.header and api in g.source
    assert "MOTIONSIM_CTRL_DOUBLE" in g.header and "#ifdef __cplusplus" in g.header
    for name in ("d_a", "d_b", "d_c"):
        assert f"ms_real {name};" in g.header
    # Every tuned constant is named, with its unit and where it came from.
    constants = [line for line in g.source.splitlines() if line.startswith("static const ms_real")]
    assert constants and all(re.search(r"/\* .+ \*/$", c) for c in constants), constants[:3]
    assert "CTX_TS" in g.source
    # Every block's every output is a wire, each written once in the step.
    for w in g.wires:
        assert g.source.count(f"s->wires.{w.member} = ") == 1, w.name


@pytest.mark.parametrize("scheme", REFUSED)
def test_what_is_not_covered_is_refused_by_name_with_what_is(scheme) -> None:
    ws = workspace()
    ready = prepared(started("example-mosfet", ws) | {"scheme": scheme}, ws)
    with pytest.raises(Refusal) as refused:
        check(ready.compiled)
    said = str(refused.value.reason)
    assert "not exported yet" in said or "least total loss" in said
    assert all(s in said for s in SCHEMES)


def test_a_refusal_answers_the_route_in_words() -> None:
    ws = workspace()
    status, body = dispatch("/api/control/export_c", started("example-mosfet", ws) | {"scheme": "mpc_torque"}, ws)
    assert status == 422 and "predictive control (MPC)" in body["refused"]
    assert body["field"] == "scheme"


def test_a_noisy_sensor_is_refused_at_its_field() -> None:
    ws = workspace()
    data = started("example-mosfet", ws) | {"scheme": "foc_torque"}
    scheme = posted("/api/control/presets", data, ws)["schemes"]
    tuned = next(s for s in scheme if s["id"] == "foc_torque")
    for block in tuned["blocks"]:
        if block["kind"] == "current_sampling":
            block["params"]["noise"] = 0.05
            name = block["name"]
    status, body = dispatch("/api/control/export_c", data | {"scheme": tuned}, ws)
    assert status == 422 and body["field"] == f"scheme.blocks.{name}.noise"


@needs_compiler
@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("key", PARTS)
def test_the_c_steps_as_the_simulation_does_on_every_made_up_part(key, scheme) -> None:
    out = made(key, scheme)
    r = out["replay"]
    assert r["ran"] and r["passed"], r["said"]
    for precision, tolerance in (("float", 1e-4), ("double", 1e-9)):
        found = r["precisions"][precision]
        assert found["compiled"] and found["warnings"] == "", found.get("warnings")
        assert found["samples"] == out["samples"] > 200
        assert found["worst"]["max_rel"] <= tolerance
        # Anchored in single precision always; in double only where the scheme closes a loop
        # inside the controller, which a free replay with no motor would amplify.
        assert found["anchored"] is (precision == "float" or scheme in INNER_LOOP_SCHEMES)
        assert {o["wire"] for o in found["outputs"]} >= {"modulator.d_a", "modulator.d_b", "modulator.d_c"}
    if r["cpp"]["checked"]:
        assert r["cpp"]["compiles"], r["cpp"]["said"]


@needs_compiler
def test_the_bundle_holds_the_law_its_replay_and_a_readme_that_says_what_was_shown() -> None:
    out = made("example-mosfet", "foc_servo")
    files = unzipped(out["zip"])
    assert (
        sorted(files)
        == sorted(out["files"])
        == [
            "README.md",
            "core/motionsim_ctrl.c",
            "core/motionsim_ctrl.h",
            "design.json",
            "scheme.json",
            "test/CMakeLists.txt",
            "test/Makefile",
            "test/replay.c",
            "test/replay_data.txt",
            "test/replay_data_float.txt",
        ]
    )
    readme = files["README.md"]
    for said in ("## What was verified", "## What was not verified", "No hardware", "## Conventions", "ADC", "PWM"):
        assert said in readme
    assert "passed" in readme and "Free-running against the run itself" in readme
    assert json.loads(files["scheme.json"])["id"] == "foc_servo"
    assert "device" not in json.loads(files["design.json"])
    for name, text in files.items():
        assert not MAKERS.search(text), (name, MAKERS.search(text))
    assert files["test/replay_data_float.txt"].splitlines()[4] == "anchored"


@needs_compiler
def test_a_salient_motor_takes_the_solver_and_still_steps_as_the_simulation() -> None:
    ws = workspace()
    data = started("example-sic-module", ws)
    motor = dict(data["motor"])
    inductance = motor.pop("l")
    motor |= {"magnets": "interior", "ld": inductance, "lq": 2.5 * inductance}
    out = bundle(data | {"motor": motor, "scheme": "foc_high_speed"}, ws)
    assert "ms_fminbound" in unzipped(out["zip"])["core/motionsim_ctrl.c"]
    assert out["replay"]["passed"], out["replay"]["said"]


def test_with_no_compiler_the_bundle_is_made_and_says_it_was_not_checked(monkeypatch) -> None:
    monkeypatch.setattr(replay, "compiler", lambda: None)
    ws = workspace()
    out = bundle(started("example-gan", ws) | {"scheme": "foc_torque"}, ws)
    assert out["replay"] == {
        "ran": False,
        "passed": None,
        "said": "no C compiler on this machine (cc, gcc or clang, or $CC): the replay was not run. "
        "Run `make check` in test/ where there is one.",
    }
    assert "**Not run here.**" in unzipped(out["zip"])["README.md"]


@needs_compiler
def test_the_route_answers_the_bundle_in_base64_beside_the_replay() -> None:
    ws = workspace()
    body = posted("/api/control/export_c", started("example-mosfet-40v", ws) | {"scheme": "foc_torque"}, ws)
    raw = base64.b64decode(body["bundle"]["base64"])
    assert body["bundle"]["size"] == len(raw) and body["bundle"]["name"] == "motionsim_ctrl_foc_torque.zip"
    assert "core/motionsim_ctrl.h" in unzipped(raw)
    assert body["replay"]["passed"] and body["covered"] == list(SCHEMES)


def test_the_python_function_gives_bytes_or_a_path(tmp_path) -> None:
    ws = workspace()
    request = started("example-sic", ws)
    raw = export_c(request, "discrete_torque", workspace=ws, replay=False)
    assert raw["bytes"][:2] == b"PK" and raw["replay"]["ran"] is False
    design = tmp_path / "design.yaml"
    design.write_text(yaml.safe_dump(starting_setup("example-sic", ws)), encoding="utf-8")
    written = export_c(design, "discrete_torque", out=tmp_path / "law.zip", replay=False)
    assert written["path"] == str(tmp_path / "law.zip") and (tmp_path / "law.zip").read_bytes()[:2] == b"PK"


@pytest.fixture
def setup_file(tmp_path) -> str:
    file = tmp_path / "design.yaml"
    file.write_text(yaml.safe_dump(starting_setup("example-mosfet", workspace())), encoding="utf-8")
    return str(file)


@needs_compiler
def test_the_terminal_writes_the_zip_and_says_the_replay(capsys, setup_file, tmp_path) -> None:
    out = tmp_path / "out.zip"
    capsys.readouterr()
    status = cli.main(["control", "export-c", "--design", setup_file, "--scheme", "foc_servo", "-o", str(out)])
    text = capsys.readouterr().out
    assert status == 0, text
    assert f"(foc_servo): {out}, 10 files" in text and "float: passed" in text
    assert zipfile.ZipFile(out).namelist()


def test_the_terminal_answers_json_and_refuses_in_words(capsys, setup_file, tmp_path) -> None:
    out = tmp_path / "out.zip"
    capsys.readouterr()
    status = cli.main(["control", "export-c", setup_file, "--scheme", "foc_torque", "--no-replay", "-o", str(out)])
    assert status == 0
    capsys.readouterr()
    status = cli.main(["control", "export-c", setup_file, "--no-replay", "-o", str(out), "--json"])
    answer = json.loads(capsys.readouterr().out)
    assert status == 0 and answer["path"] == str(out) and answer["replay"]["ran"] is False
    status = cli.main(["control", "export-c", setup_file, "--scheme", "dtc_torque", "-o", str(out)])
    assert status != 0 and "direct torque control" in capsys.readouterr().err
    status = cli.main(["control", "export-c", "-o", str(out)])
    assert status != 0 and "no design file was given" in capsys.readouterr().err


def test_only_a_scheme_that_closes_a_loop_inside_the_controller_is_anchored_in_double() -> None:
    from motionsim.control.codegen.replay import closes_inner_loop

    ws = workspace()
    data = started("example-mosfet", ws)
    found = {s for s in SCHEMES if closes_inner_loop(prepared(data | {"scheme": s}, ws).scheme)}
    assert found == INNER_LOOP_SCHEMES


@needs_compiler
@pytest.mark.parametrize("shunts", ["three", "two", "single"])
@pytest.mark.parametrize("key", ["example-mosfet", "example-gan"])
def test_currents_read_through_shunts_are_exported_and_step_as_the_simulation(key, shunts) -> None:
    ws = workspace()
    base = started(key, ws)
    scheme = next(s for s in posted("/api/control/presets", base, ws)["schemes"] if s["id"] == "foc_servo")
    sample = next(b for b in scheme["blocks"] if b["name"] == "sample")
    sample["kind"] = "shunt_sampling"
    for k in ("window_a", "window_b", "window_c", "i_dc_1", "vector_1", "span_1", "i_dc_2", "vector_2", "span_2"):
        sample["inputs"][k] = f"inverter.{k}"
    sample["params"] = {"shunts": shunts, "bits": 12, "full_scale": 200.0}
    out = bundle(base | {"scheme": scheme}, ws)
    r = out["replay"]
    assert r["ran"] and r["passed"], r["said"]
    assert {o["wire"] for o in r["precisions"]["double"]["outputs"]} >= {"sample.held", "sample.i_a"}
    assert "shunts = " + shunts in unzipped(out["zip"])["core/motionsim_ctrl.c"]


@pytest.mark.parametrize(
    ("timing", "said"),
    [
        ({"update": "single"}, "sampled at the carrier's peak."),
        ({"update": "multi", "per_carrier": 4}, "4 times each carrier period, evenly from its peak"),
        ({"update": "every", "carriers": 3}, "once every 3 carrier periods"),
    ],
)
def test_the_readme_says_when_the_currents_are_sampled_for_every_update(timing, said) -> None:
    from motionsim.control.codegen.bundle import sampled_words

    assert said.rstrip(".").split("sampled ")[-1] in sampled_words(timing)
    ws = workspace()
    base = started("example-mosfet", ws)
    scheme = next(s for s in posted("/api/control/presets", base, ws)["schemes"] if s["id"] == "foc_torque")
    scheme["timing"] = {**scheme["timing"], **timing}
    out = bundle(base | {"scheme": scheme}, ws)
    assert said in unzipped(out["zip"])["README.md"]
