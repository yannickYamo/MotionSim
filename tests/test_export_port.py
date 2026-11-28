"""The control law ported to a microcontroller: the chip found on the curated list or profiled by
the model and marked unverified, the port held by code to what a port may be, gated by the
law's replay, compiled where a cross-compiler is at hand, and said with what was checked and
what was not. No model is ever called here: every model is a fake, and a test that reached for
a real one would fail."""

from __future__ import annotations

import base64
import contextlib
import dataclasses
import io
import json
import threading
import urllib.error
import urllib.request
import zipfile

import pytest
from test_control_bench import started, workspace

from motionsim.control.codegen import chips, firmware, port, replay
from motionsim.errors import Refusal
from motionsim.observe import provider
from motionsim.service.control import export_port
from motionsim.service.routes import dispatch

needs_compiler = pytest.mark.skipif(replay.compiler() is None, reason="no C compiler on this machine")

REGS = """#ifndef MCU_REGS_H
#define MCU_REGS_H
#include <stdint.h>
#define TIM1_CCR1 (*(volatile uint32_t *)0x40012C34u) /* TIM1 capture/compare register 1 */
#define TIM1_CCR2 (*(volatile uint32_t *)0x40012C38u) /* TIM1 capture/compare register 2 */
#define TIM1_CCR3 (*(volatile uint32_t *)0x40012C3Cu) /* TIM1 capture/compare register 3 */
#define TIM1_ARR (*(volatile uint32_t *)0x40012C2Cu)  /* TIM1 auto-reload register */
#define ADC1_JDR1 (*(volatile uint32_t *)0x50000080u) /* ADC1 injected data register 1 */
#endif
"""
PORT_H = """#ifndef PORT_H
#define PORT_H
void port_init(void);
void ADC1_2_IRQHandler(void);
#endif
"""
PORT_C = """#include <string.h>
#include "motionsim_ctrl.h"
#include "mcu_regs.h"
#include "port.h"
#define BOARD_AMPS_PER_COUNT 0.01f /* BOARD: shunt and amplifier gain */
static motionsim_ctrl_state ctrl;
void port_init(void) { TIM1_ARR = 4250u; motionsim_ctrl_init(&ctrl); }
void ADC1_2_IRQHandler(void) {
    motionsim_ctrl_in in;
    motionsim_ctrl_out out;
    memset(&in, 0, sizeof in);
    in.i_a = (ms_real)((int32_t)ADC1_JDR1 - 2048) * BOARD_AMPS_PER_COUNT;
    motionsim_ctrl_step(&ctrl, &in, &out);
    TIM1_CCR1 = (uint32_t)(out.d_a * 4250.0f);
    TIM1_CCR2 = (uint32_t)(out.d_b * 4250.0f);
    TIM1_CCR3 = (uint32_t)(out.d_c * 4250.0f);
}
"""
MAIN_C = """#include "port.h"
int main(void) { port_init(); for (;;) { } }
"""


def a_port(**extra) -> port.Port:
    files = {"port/mcu_regs.h": REGS, "port/port.h": PORT_H, "port/port.c": PORT_C, "port/main.c": MAIN_C}
    files |= extra
    return port.Port(
        files=[port.PortFile(path=p, text=t) for p, t in files.items()],
        isr="ADC1_2_IRQHandler",
        assumptions=["170 MHz from the PLL", "BOARD: 10 mA per count"],
        bench=["Check the dead time on a scope with the bridge unpowered"],
    )


class Fake:
    """A model that answers from what it is given, and counts what it was asked."""

    def __init__(self, written: port.Port | None = None, profile: port.ChipFilled | None = None) -> None:
        self.written, self.profile, self.asked = written or a_port(), profile, []

    def __call__(self, system, text, shape, max_tokens):
        self.asked.append((system, json.loads(text), shape))
        if shape is port.ChipFilled:
            assert self.profile is not None, "a curated chip is never profiled by the model"
            return self.profile
        return self.written


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    """Nothing here reaches a model: the real one fails the test where it is asked."""

    def refuse(*a, **k):
        raise AssertionError("a live model was asked")

    monkeypatch.setattr(port, "ask_model", refuse)
    monkeypatch.setattr(provider, "_post", refuse)
    monkeypatch.setenv("MOTIONSIM_FIRMWARE_URL", "off")


@pytest.fixture(scope="module")
def ws():
    return workspace()


@pytest.fixture(scope="module")
def base(ws) -> dict:
    return started("example-mosfet", ws) | {"scheme": "foc_servo"}


def unzipped(raw: bytes) -> dict[str, str]:
    z = zipfile.ZipFile(io.BytesIO(raw))
    return {name.removeprefix("motionsim_ctrl/"): z.read(name).decode() for name in z.namelist()}


# -- the chips -------------------------------------------------------------------------------


def test_the_curated_list_is_the_owner_s_twelve_each_with_a_whole_profile() -> None:
    names = [p.name for p in chips.PROFILES]
    assert names == [
        "STM32G4", "STM32F4", "C2000 F28004x", "C2000 F2837x", "MCX A", "MCX N", "i.MX RT1170", "dsPIC33CK",
        "SAM E70", "RA6T2", "ESP32-S3", "RP2350",
    ]  # fmt: skip
    for p in chips.PROFILES:
        assert p.fpu in ("single", "double", "none") and p.clock_mhz > 0 and p.adc and p.pwm and p.compiler
        assert p.fixed_point == (p.fpu == "none") and p.rate_khz[0] < p.rate_khz[1]
        assert all(chips.FLAG.match(f) for f in p.flags)
        assert (p.toolchain in firmware.TOOLCHAINS) if p.toolchain else p.source_only
    source_only = {p.name for p in chips.PROFILES if p.toolchain is None}
    assert source_only == {"C2000 F28004x", "C2000 F2837x", "dsPIC33CK"}


@pytest.mark.parametrize(
    ("typed", "found"),
    [
        ("STM32G474RE", "stm32g4"),
        ("stm32g4", "stm32g4"),
        ("TMS320F280049C", "c2000-f28004x"),
        ("F28379D", "c2000-f2837x"),
        ("MIMXRT1176", "imxrt1170"),
        ("i.MX RT1170", "imxrt1170"),
        ("esp32-s3", "esp32s3"),
        ("dsPIC33CK256MP508", "dspic33ck"),
        ("MCX N947", "mcx-n"),
        ("GD32VF103", None),
        ("", None),
    ],
)
def test_a_name_as_typed_finds_its_family(typed, found) -> None:
    p = chips.find(typed)
    assert (p.id if p else None) == found


def test_a_chip_off_the_list_is_profiled_by_the_model_and_marked_unverified() -> None:
    filled = port.ChipFilled(
        known=True, name="GD32VF103", core="RISC-V Bumblebee", fpu="none", clock_mhz=108, adc="12-bit ADC",
        pwm="advanced timer", compiler="riscv64-unknown-elf-gcc", toolchain="riscv64-unknown-elf",
        flags=["-march=rv32imac_zicsr", "-mabi=ilp32", "-fplugin=evil.so"], rate_khz_low=20, rate_khz_high=5,
    )  # fmt: skip
    fake = Fake(profile=filled)
    p = export_port.chip_of("GD32VF103", fake)
    assert not p.curated and p.notes[0].startswith("unverified profile")
    assert p.flags == ("-march=rv32imac_zicsr", "-mabi=ilp32") and p.rate_khz == (5, 20)
    assert p.fixed_point and p.toolchain == "riscv64-unknown-elf"
    assert fake.asked[0][1] == {"chip": "GD32VF103"}


def test_a_chip_the_model_does_not_know_is_refused_and_a_name_that_is_none_too() -> None:
    unknown = port.ChipFilled(
        known=False, name="", core="", fpu="none", clock_mhz=0, adc="", pwm="", compiler="", toolchain="none",
        flags=[], rate_khz_low=0, rate_khz_high=0,
    )  # fmt: skip
    with pytest.raises(Refusal, match="does not know") as refused:
        export_port.chip_of("ZX9000", Fake(profile=unknown))
    assert refused.value.field == "chip"
    for bad in ("", "   ", "a" * 80, "chip; rm -rf /", None):
        with pytest.raises(Refusal) as refused:
            export_port.chip_of(bad, Fake())
        assert refused.value.field == "chip"


# -- what a port may be ----------------------------------------------------------------------


def test_a_good_port_is_kept_whole_and_its_checks_pass() -> None:
    files, checks = port.held(a_port())
    assert sorted(files) == ["port/main.c", "port/mcu_regs.h", "port/port.c", "port/port.h"]
    assert [c["ok"] for c in checks] == [True, True]


@pytest.mark.parametrize(
    ("path", "text", "why"),
    [
        ("core/motionsim_ctrl.c", "int x;", "not a port/ C source"),
        ("port/../../etc/x.c", "int x;", "not a port/ C source"),
        ("port/run.sh", "rm -rf /", "not a port/ C source"),
        ("port/law.c", "void motionsim_ctrl_step(void *s, const void *i, void *o) { }", "defines the control law"),
        ("port/hal.c", "#include <stm32g4xx.h>\nint x;", "not the C library's"),
        ("port/leak.c", '#include "/etc/passwd"\n', "reaches outside the port"),
        ("port/macro.c", "#define F <stdio.h>\n#include F\n", "by a macro"),
        ("port/asm.c", '__asm__(".incbin \\"/etc/shadow\\"");', "assembler"),
        ("port/lost.c", '#include "nowhere.h"\n', "the port does not have"),
    ],
)
def test_what_a_port_may_not_hold_is_set_aside_and_said(path, text, why) -> None:
    files, checks = port.held(a_port(**{path: text}))
    assert path not in files and "port/port.c" in files
    assert checks[0]["ok"] is False and why in checks[0]["said"]


def test_a_port_that_does_not_call_the_law_fails_its_check() -> None:
    _, checks = port.held(a_port(**{"port/port.c": '#include "port.h"\nvoid port_init(void) { }\n'}))
    assert checks[1]["ok"] is False


def test_the_model_is_asked_with_the_profile_the_timing_and_the_law_s_header(base, ws) -> None:
    fake = Fake()
    export_port.route(base | {"chip": "STM32G4"}, ws, fake)
    assert len(fake.asked) == 1  # a curated chip is not profiled
    system, asked, shape = fake.asked[0]
    assert shape is port.Port and system == port.PORT_SYSTEM
    assert asked["chip"]["name"] == "STM32G4" and asked["chip"]["curated"] is True
    assert asked["timing"]["switching_hz"] == 20000.0 and asked["timing"]["update"] == "single"
    assert "motionsim_ctrl_step" in asked["motionsim_ctrl.h"]
    assert "example-mosfet" not in json.dumps(asked)  # no device is named to the model


# -- the gate, the compile, the answer -------------------------------------------------------


@needs_compiler
def test_the_port_is_handed_over_with_what_was_checked_and_what_was_not(base, ws) -> None:
    body = export_port.route(base | {"chip": "STM32G474RE"}, ws, Fake())
    assert body["status"] == "not compiled / not run on hardware"
    assert (
        body["chip"]["name"] == "STM32G4" and "STM32G474RE: written from the family's profile" in body["chip"]["notes"]
    )
    assert [f["path"] for f in body["files"]] == ["port/main.c", "port/mcu_regs.h", "port/port.c", "port/port.h"]
    compiled = next(c for c in body["checks"] if c["what"] == "compiles for the chip")
    assert compiled["ok"] is None and "firmware service is not up" in compiled["said"]
    assert any("Not run on hardware" in n for n in body["not_checked"])
    assert body["replay"]["passed"] is True and "Control rate 20 kHz: within" in body["rate"]
    files = unzipped(base64.b64decode(body["bundle"]["base64"]))
    assert {"core/motionsim_ctrl.c", "test/replay.c", "port/port.c", "PORT.md", "chip.json", "README.md"} <= set(files)
    assert "The port to the STM32G4 in `port/`" in files["README.md"]
    assert files["PORT.md"].startswith("# The port to the STM32G4: not compiled / not run on hardware")
    assert "ADC1_2_IRQHandler" in files["PORT.md"] and "BOARD: 10 mA per count" in files["PORT.md"]
    assert body["bundle"]["name"] == "motionsim_port_foc_servo_stm32g4.zip"


@needs_compiler
def test_a_source_only_chip_says_why_and_no_fpu_keeps_the_law_proved(base, ws) -> None:
    c2000 = export_port.route(base | {"chip": "C2000 F28004x"}, ws, Fake())
    assert "not redistributable" in c2000["compiled"]["said"] and c2000["compiled"]["compiled"] is None
    dspic = export_port.route(base | {"chip": "dsPIC33CK"}, ws, Fake())
    assert "XC16 is not redistributable" in dspic["compiled"]["said"]
    assert dspic["boundary"].startswith("No FPU: the law runs as the replay proved it")


@needs_compiler
def test_the_port_compiles_with_the_chip_s_toolchain_where_one_is_at_hand(base, ws, monkeypatch) -> None:
    # The host's own compiler stands in for the cross-compiler: what is tested is the compile
    # of core and port together, its warnings and its size, not the target.
    cc = replay.compiler()
    monkeypatch.setitem(firmware.TOOLCHAINS, "arm-none-eabi", {"cc": cc, "size": "size"})
    host = dataclasses.replace(chips.BY_ID["stm32g4"], flags=())
    monkeypatch.setattr(chips, "find", lambda name: host)
    body = export_port.route(base | {"chip": "STM32G4"}, ws, Fake())
    assert body["status"] == "compiles / not run on hardware", body["compiled"]
    assert body["compiled"]["where"] == "here" and body["compiled"]["errors"] == []
    compiled = next(c for c in body["checks"] if c["what"] == "compiles for the chip")
    assert compiled["ok"] is True and "0 warnings" in compiled["said"]
    if body["compiled"]["size"]:
        assert body["compiled"]["size"]["text"] > 0 and "B text" in compiled["said"]
    broken = a_port(**{"port/port.c": PORT_C.replace("motionsim_ctrl_step(&ctrl, &in, &out);", "nope(;")})
    failed = export_port.route(base | {"chip": "STM32G4"}, ws, Fake(broken))
    assert failed["status"] == "does not compile / not run on hardware" and failed["compiled"]["errors"]
    # A definition no reading of the text finds is found in the object: the law's check fails.
    hidden = "#define SAME(x) x\nvoid SAME(motionsim_ctrl_warm)(void) { }\n"
    assert not port.defines_law(hidden)
    defines = export_port.route(base | {"chip": "STM32G4"}, ws, Fake(a_port(**{"port/warm.c": hidden})))
    law = next(c for c in defines["checks"] if c["what"].startswith("the law is called"))
    assert law["ok"] is False and "define motionsim_ctrl_warm" in law["said"]


def test_a_law_whose_replay_did_not_pass_gets_no_port(base, ws, monkeypatch) -> None:
    fake = Fake()
    monkeypatch.setattr(
        "motionsim.service.control.export_c.replay_in",
        lambda f: {"ran": False, "passed": None, "said": "no C compiler"},
    )
    with pytest.raises(Refusal, match="replay was not run here") as refused:
        export_port.route(base | {"chip": "STM32G4"}, ws, fake)
    assert refused.value.field == "scheme"
    monkeypatch.setattr(
        "motionsim.service.control.export_c.replay_in",
        lambda f: {"ran": True, "passed": False, "said": "float: FAILED", "precisions": {}},
    )
    with pytest.raises(Refusal, match="did not pass its replay"):
        export_port.route(base | {"chip": "STM32G4"}, ws, fake)
    assert fake.asked == []  # nothing was spent on a law that was not proved


def test_with_no_model_set_up_the_port_is_refused_before_anything_runs(base, ws, monkeypatch) -> None:
    def none(env=None):
        raise provider.NoReader("none")

    monkeypatch.setattr(provider, "chosen", none)
    ran = []
    monkeypatch.setattr(export_port, "made_for", lambda *a, **k: ran.append(1))
    with pytest.raises(Refusal, match="written by a language model with your own key") as refused:
        export_port.route(base | {"chip": "STM32G4"}, ws)
    assert refused.value.field == "key" and ran == []


def test_a_model_that_fails_is_a_refusal_without_the_key(base, ws, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-0123456789")

    def fails(system, text, shape, max_tokens):
        raise provider.ReaderFailed("the key sk-ant-secret-0123456789 was rejected (401)", "check the key")

    with pytest.raises(Refusal) as refused:
        export_port.route(base | {"chip": "STM32G4"}, ws, fails)
    assert "sk-ant-secret" not in refused.value.reason and "[key]" in refused.value.reason


def test_anthropic_is_asked_with_the_reader_s_model_and_the_port_s_shape(monkeypatch) -> None:
    import types

    made: dict = {}

    class Messages:
        def create(self, **asked):
            # As the library does for a budget that may run past ten minutes: the port's does.
            raise ValueError("Streaming is required for operations that may take longer than 10 minutes")

        @contextlib.contextmanager
        def stream(self, **asked):
            made.update(asked)
            text = types.SimpleNamespace(type="text", text=a_port().model_dump_json())
            final = types.SimpleNamespace(stop_reason="end_turn", content=[text], usage=None)
            yield types.SimpleNamespace(get_final_message=lambda: final)

    class Anthropic:
        max_retries = 0

        def __init__(self, **kwargs):
            self.messages = Messages()

    sdk = types.SimpleNamespace(
        Anthropic=Anthropic, AnthropicError=Exception, APITimeoutError=TimeoutError, APIConnectionError=ConnectionError,
        APIStatusError=LookupError, transform_schema=lambda shape: shape.model_json_schema(),
    )  # fmt: skip
    monkeypatch.undo()  # the real ask_model, with a fake library under it
    monkeypatch.setattr(provider, "chosen", lambda env=None: provider.Reader("anthropic", provider.ANTHROPIC_MODEL))
    monkeypatch.setattr(provider, "needs", lambda module, what: sdk)
    got = port.ask_model(port.PORT_SYSTEM, "{}", port.Port, port.PORT_TOKENS)
    assert isinstance(got, port.Port) and got.isr == "ADC1_2_IRQHandler"
    assert made["model"] == provider.ANTHROPIC_MODEL and made["max_tokens"] == port.PORT_TOKENS
    assert made["output_config"]["format"]["type"] == "json_schema"
    assert made["output_config"]["effort"] == "medium" and port.PORT_TOKENS >= 120000


def test_a_port_cut_off_by_its_budget_is_said_as_the_port_s_not_a_datasheet_s(monkeypatch) -> None:
    import types

    class Messages:
        @contextlib.contextmanager
        def stream(self, **asked):
            final = types.SimpleNamespace(stop_reason="max_tokens", content=[], usage=None)
            yield types.SimpleNamespace(get_final_message=lambda: final)

    class Anthropic:
        max_retries = 0

        def __init__(self, **kwargs):
            self.messages = Messages()

    sdk = types.SimpleNamespace(
        Anthropic=Anthropic, AnthropicError=Exception, APITimeoutError=TimeoutError, APIConnectionError=ConnectionError,
        APIStatusError=LookupError, transform_schema=lambda shape: shape.model_json_schema(),
    )  # fmt: skip
    monkeypatch.undo()
    monkeypatch.setattr(provider, "chosen", lambda env=None: provider.Reader("anthropic", provider.ANTHROPIC_MODEL))
    monkeypatch.setattr(provider, "needs", lambda module, what: sdk)
    with pytest.raises(provider.ReaderFailed) as cut:
        port.ask_model(port.PORT_SYSTEM, "{}", port.Port, port.PORT_TOKENS)
    said = f"{cut.value} {cut.value.fix}"
    assert "port" in said and "datasheet" not in said and "--no-curves" not in said


def test_the_export_lists_the_chips_for_the_picker(base, ws) -> None:
    status, body = dispatch("/api/control/export_c", base, ws)
    assert status == 200 and [c["name"] for c in body["chips"]] == [p.name for p in chips.PROFILES]
    assert body["chips"][7]["said"].endswith("no FPU, source only")


# -- the firmware service --------------------------------------------------------------------


TOKEN = "k" * 43


def test_the_firmware_service_takes_only_what_it_may_compile() -> None:
    server = firmware.serve("127.0.0.1", 0, token=TOKEN)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=5) as answer:
            assert isinstance(json.loads(answer.read())["toolchains"], list)

        def post(body: dict) -> tuple[int, dict]:
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}
            req = urllib.request.Request(
                f"{url}/compile", data=json.dumps(body).encode(), headers=headers, method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as answer:
                    return answer.status, json.loads(answer.read())
            except urllib.error.HTTPError as refused:
                with refused:
                    return refused.code, json.loads(refused.read())

        good = {"port/a.c": "int a;"}
        assert post({"toolchain": "gcc", "flags": [], "files": good})[0] == 422
        assert post({"toolchain": "arm-none-eabi", "flags": ["-fplugin=x.so"], "files": good})[0] == 422
        assert post({"toolchain": "arm-none-eabi", "flags": [], "files": {"/etc/x.c": "int a;"}})[0] == 422
        status, said = post(
            {"toolchain": "arm-none-eabi", "flags": [], "files": {"port/a.c": '#include "/etc/passwd"'}}
        )
        assert status == 422 and "outside" in said["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_the_app_compiles_through_the_service_when_it_is_up(monkeypatch) -> None:
    server = firmware.serve("127.0.0.1", 0, token=TOKEN)
    monkeypatch.setenv(firmware.TOKEN_ENV, TOKEN)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(firmware.shutil, "which", lambda name: None)  # no cross-compiler here, nor there
    monkeypatch.setenv("MOTIONSIM_FIRMWARE_URL", f"http://127.0.0.1:{server.server_address[1]}")
    try:
        got = firmware.compile_port("arm-none-eabi", [], {"port/a.c": "int a;"})
        assert got["compiled"] is None and "refused the port (422)" in got["said"]
    finally:
        server.shutdown()
        server.server_close()
    got = firmware.compile_port("arm-none-eabi", [], {"port/a.c": "int a;"})
    assert got["compiled"] is None and "firmware service is not up" in got["said"]


# -- the app's address -----------------------------------------------------------------------


def test_the_app_ports_for_its_own_page_alone(tmp_path, monkeypatch, base) -> None:
    pytest.importorskip("fastapi", reason="the ASGI app needs the app extra")
    from test_app_http import served

    from motionsim.app import home

    monkeypatch.setenv(home.HOME, str(tmp_path / "home"))
    fake = Fake()
    monkeypatch.setattr(port, "ask_model", fake)
    monkeypatch.setattr(provider, "chosen", lambda env=None: provider.Reader("anthropic", "fake"))
    with served(tmp_path / "asgi") as app:
        other = {"Origin": "http://elsewhere.example", "Sec-Fetch-Site": "cross-site"}
        assert app.json("POST", "/api/control/export_port", base | {"chip": "STM32G4"}, other)[0] == 403
        assert fake.asked == []
        assert app.json("POST", "/api/control/export_port", {"chip": "STM32G4"})[0] == 422
        if replay.compiler() is not None:
            status, body = app.json("POST", "/api/control/export_port", base | {"chip": "RP2350"})
            assert status == 200 and body["chip"]["name"] == "RP2350" and len(fake.asked) == 1


def test_the_port_is_told_no_assembler_and_a_barrier_by_an_extern_call_is_kept():
    """A measured port wrote a barrier and a wait for interrupt in inline assembler, which the
    checks set aside, and with port.c went the call of the law. The model is told: no assembler,
    an extern function where C cannot say the instruction; and such a port is kept whole."""
    assert "Write no assembler" in port.PORT_SYSTEM and "extern function" in port.PORT_SYSTEM
    header = '#include "motionsim_ctrl.h"\n/* BOARD: supplied by the startup code */\nvoid port_barrier(void);\n'
    source = (
        '#include "port/port.h"\nvoid port_init(void) { motionsim_ctrl_init(); port_barrier(); }\n'
        "void port_isr(void) { motionsim_ctrl_step(0, 0); }\n"
    )
    written = port.Port(
        files=[port.PortFile(path="port/port.h", text=header), port.PortFile(path="port/port.c", text=source)],
        isr="port_isr",
        assumptions=[],
        bench=[],
    )
    files, checks = port.held(written)
    assert set(files) == {"port/port.h", "port/port.c"} and all(c["ok"] for c in checks)
    inline = source.replace("port_barrier();", '__asm volatile ("dsb");')
    written.files[1] = port.PortFile(path="port/port.c", text=inline)
    files, checks = port.held(written)
    assert "port/port.c" not in files and not checks[1]["ok"]
