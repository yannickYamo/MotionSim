"""What a port's sources may reach, and who may ask the firmware service to compile them.

A port is written by a language model, so its text is held to its own files, the law's and the
C library's headers twice over: by reading the text, which refuses whatever could hide an
include from that reading (a line joined by a backslash, a trigraph, a comment inside the
directive, a digraph, assembler), and by asking the preprocessor what it read, which is the
only reading the compiler shares. A file from elsewhere is never compiled, and its text never
comes back in the compiler's words. The service answers this machine alone, a JSON body
alone, the shared token alone, one compile at a time or two, in one deadline a request."""

from __future__ import annotations

import json
import os
import re
import stat
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from motionsim.control.codegen import firmware, port, replay

needs_compiler = pytest.mark.skipif(replay.compiler() is None, reason="no C compiler on this machine")

SECRET = "SECRETTOKEN_abc123"

# Each way round a reading of the include lines that the preprocessor does not share, with an
# absolute path the test fills in. Every one of them, given to gcc -std=c99 as it was before the
# sandbox, read the file named.
BYPASSES = {
    "splice": '#\\\ninclude "{p}"\n',
    "comment": '#/**/include "{p}"\n',
    "trigraph": '??=include "{p}"\n',
    "digraph": '%:include "{p}"\n',
    "asm include": 'void f(void) {{ __asm__(".include \\"{p}\\""); }}\n',
    "asm incbin concatenated": 'void f(void) {{ __asm__(".inc" "bin \\"{p}\\""); }}\n',
    "asm keyword": 'void f(void) {{ asm(".include \\"{p}\\""); }}\n',
    "up a folder": '#include "../../../../../../../..{p}"\n',
}


@pytest.fixture
def secret(tmp_path: Path) -> Path:
    kept = tmp_path / "secret.txt"
    kept.write_text(f"{SECRET}\n")
    return kept


@pytest.mark.parametrize("form", sorted(BYPASSES))
def test_the_text_check_refuses_every_way_round_an_include(form, secret) -> None:
    text = BYPASSES[form].format(p=secret)
    assert firmware.outside(text) is not None, form
    files, checks = port.held(_port_with("port/leak.c", text))
    assert "port/leak.c" not in files and checks[0]["ok"] is False


@pytest.mark.parametrize(
    "text",
    [
        '#include "../x.h"\n',
        "#include <../x.h>\n",
        '#include "/etc/x.h"\n',
        '#include "C:x.h"\n',
        "#define F <stdio.h>\n#include F\n",
        '#embed "x.bin"\n',
        '#include_next "x.h"\n',
        '#pragma GCC dependency "/etc/passwd"\n',
        '_Pragma("GCC dependency \\"/etc/passwd\\"")\n',
    ],
)
def test_the_text_check_still_refuses_what_it_refused(text) -> None:
    assert firmware.outside(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        '#include <stdint.h>\n#include "port.h"\n/* a comment ?? not a trigraph: refused all the same */\n',
        '#include "port.h" // the port\nint x; /* #include "/etc/passwd" in a comment reads nothing */\n',
        'const char *s = "#include \\"/etc/x\\"";\n',
    ],
)
def test_a_source_that_reaches_nothing_passes_except_a_double_question_mark(text) -> None:
    said = firmware.outside(text)
    assert (said is not None) == ("??" in text)


def _port_with(path: str, text: str) -> port.Port:
    from test_export_port import a_port

    return a_port(**{path: text})


@needs_compiler
@pytest.mark.parametrize("form", ["splice", "comment", "trigraph", "digraph", "up a folder"])
def test_the_compile_checks_what_the_preprocessor_read(form, secret, monkeypatch) -> None:
    # The text check taken away: the preprocessor's own list of what it read refuses the file,
    # nothing is compiled, and the secret never comes back.
    monkeypatch.setattr(firmware, "outside", lambda text: None)
    monkeypatch.setitem(firmware.TOOLCHAINS, "arm-none-eabi", {"cc": replay.compiler(), "size": "size"})
    got = firmware.compile_here("arm-none-eabi", [], {"port/leak.c": BYPASSES[form].format(p=secret)})
    assert got["compiled"] is False, got
    assert any("outside the port" in e for e in got["errors"]), got
    assert SECRET not in json.dumps(got) and str(secret.parent) not in json.dumps(got)


@needs_compiler
@pytest.mark.parametrize("form", ["asm include", "asm incbin concatenated", "pasted"])
def test_the_compile_refuses_assembler_the_preprocessor_makes(form, secret, monkeypatch) -> None:
    monkeypatch.setattr(firmware, "outside", lambda text: None)
    monkeypatch.setitem(firmware.TOOLCHAINS, "arm-none-eabi", {"cc": replay.compiler(), "size": "size"})
    text = (
        f'#define P(a, b) a##b\nvoid f(void) {{ P(__as, m__)(".inc" "lude \\"{secret}\\""); }}\n'
        if form == "pasted"
        else BYPASSES[form].format(p=secret)
    )
    if form == "pasted":
        monkeypatch.undo()  # the text check is whole, and passes this one: only the preprocessor sees it
        monkeypatch.setitem(firmware.TOOLCHAINS, "arm-none-eabi", {"cc": replay.compiler(), "size": "size"})
        assert firmware.outside(text) is None
    got = firmware.compile_here("arm-none-eabi", [], {"port/leak.c": text})
    assert got["compiled"] is False and any("assembler" in e for e in got["errors"]), got
    assert SECRET not in json.dumps(got)


def test_the_compiler_s_words_are_said_only_of_the_port_s_own_files(tmp_path) -> None:
    root = tmp_path / "motionsim-port-x"
    said = [
        f"{root}/port/a.c:3:5: warning: unused variable 'x' [-Wunused-variable]",
        f"{tmp_path}/secret.txt:1:1: warning: type defaults to 'int' in declaration of '{SECRET}'",
        f"/etc/passwd:1:1: error: expected ';' before '{SECRET}'",
        f"In file included from {root}/port/a.c:1:",
        f"    1 | {SECRET}",
        "cc1: warning: command-line option is valid for C++",
        f"{root}/core/motionsim_ctrl.c:10:1: error: expected identifier",
    ]
    kept = firmware.ours(said, root)
    assert kept == [
        "port/a.c:3:5: warning: unused variable 'x' [-Wunused-variable]",
        "core/motionsim_ctrl.c:10:1: error: expected identifier",
    ]


@needs_compiler
def test_a_clean_port_still_compiles_with_the_c_library_s_headers(monkeypatch) -> None:
    monkeypatch.setitem(firmware.TOOLCHAINS, "arm-none-eabi", {"cc": replay.compiler(), "size": "size"})
    files = {
        "core/law.h": "#include <stdint.h>\nint32_t law(int32_t x);\n",
        "core/law.c": '#include <math.h>\n#include "law.h"\nint32_t law(int32_t x) { return (int32_t)sqrtf((float)x); }\n',
        "port/port.c": '#include <string.h>\n#include "law.h"\nint32_t p(void) { return law(4); }\n',
    }
    got = firmware.compile_here("arm-none-eabi", [], files)
    assert got["compiled"] is True and got["errors"] == [], got
    assert "-nostdinc" in got["flags"]


@needs_compiler
def test_a_port_that_defines_the_law_however_it_is_written_is_found_in_its_object(monkeypatch) -> None:
    # A definition the text check cannot read (a comment between the parameters and the body,
    # K&R style, or a name made by a macro) defines a symbol all the same.
    monkeypatch.setitem(firmware.TOOLCHAINS, "arm-none-eabi", {"cc": replay.compiler(), "size": "size"})
    for text, names in [
        ("void motionsim_ctrl_step(void *s) /* the law */ { (void)s; }\n", ["motionsim_ctrl_step"]),
        ("int motionsim_ctrl_init(s)\n    int s;\n{ return s; }\n", ["motionsim_ctrl_init"]),
        ("#define LAW(x) motionsim_ctrl_##x\nvoid LAW(warm)(void) { }\n", ["motionsim_ctrl_warm"]),
    ]:
        got = firmware.compile_here("arm-none-eabi", [], {"port/law.c": text})
        assert got["defined"] == names, (text, got)
        found = port.law_defined(got)
        assert found is not None and found["ok"] is False and "defines the control law" in found["said"]
    calls = "void motionsim_ctrl_step(void);\nvoid p(void) { motionsim_ctrl_step(); }\n"
    clean = firmware.compile_here("arm-none-eabi", [], {"port/p.c": calls})
    assert clean["defined"] == [] and port.law_defined(clean) is None


def test_the_text_check_reads_a_definition_past_comments_and_lines() -> None:
    for text in [
        "void motionsim_ctrl_step(void *s) /* the law */ { }\n",
        "void motionsim_ctrl_step(void *s)\n// mine\n{ }\n",
        "int motionsim_ctrl_init(s)\n    int s;\n{ return s; }\n",
        "#define LAW(x) motionsim_ctrl_##x\nvoid LAW(warm)(void) { }\n",
        "#define MINE motionsim_ctrl_step\nvoid MINE(void) { }\n",
    ]:
        files, checks = port.held(_port_with("port/law.c", text))
        assert "port/law.c" not in files and "defines the control law" in checks[0]["said"], text
    files, _ = port.held(_port_with("port/call.c", "void g(void *s) { motionsim_ctrl_init(s); }\n"))
    assert "port/call.c" in files


# -- the includes of a kept file (m1) ---------------------------------------------------------


def test_a_kept_file_may_not_include_a_file_set_aside_and_may_name_the_port_folder() -> None:
    from test_export_port import a_port

    files, checks = port.held(
        a_port(
            **{
                "port/bad.h": '#include "/etc/passwd"\n',
                "port/uses.c": '#include "bad.h"\nint u;\n',
                "port/prefixed.c": '#include "port/port.h"\nint v;\n',
            }
        )
    )
    assert "port/bad.h" not in files and "port/uses.c" not in files
    assert "port/prefixed.c" in files
    assert 'port/uses.c: includes "bad.h", which the port does not have' in checks[0]["said"]


# -- the service (M1) -------------------------------------------------------------------------

TOKEN = "t" * 43


@pytest.fixture
def service():
    server = firmware.serve(port=0, token=TOKEN)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _post(server, body: bytes, headers: dict[str, str]) -> tuple[int, dict]:
    url = f"http://127.0.0.1:{server.server_address[1]}/compile"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as refused:
        with refused:
            return refused.code, json.loads(refused.read())


GOOD = json.dumps({"toolchain": "arm-none-eabi", "flags": [], "files": {"port/a.c": "int a;"}}).encode()
JSON = {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"}


def test_the_service_listens_on_this_machine_alone_by_default(service) -> None:
    assert service.server_address[0] == "127.0.0.1"
    with pytest.raises(firmware.Unusable, match="token"):
        firmware.serve(port=0, token="")


def test_the_service_answers_its_token_a_json_body_and_a_local_name_alone(service, monkeypatch) -> None:
    compiled = []
    monkeypatch.setattr(firmware, "compile_here", lambda *a: compiled.append(a) or {"compiled": True})
    assert _post(service, GOOD, JSON)[0] == 200 and len(compiled) == 1
    assert _post(service, GOOD, {**JSON, "Content-Type": "text/plain"})[0] == 415
    assert _post(service, GOOD, {"Content-Type": "application/json"})[0] == 401
    assert _post(service, GOOD, {**JSON, "Authorization": "Bearer " + "u" * 43})[0] == 401
    assert _post(service, GOOD, {**JSON, "Host": "evil.example"})[0] == 421
    assert _post(service, GOOD, {**JSON, "Host": "firmware:8090"})[0] == 200
    assert len(compiled) == 2  # nothing refused reached the compiler


def test_the_service_refuses_every_bypass(service, secret) -> None:
    for form, text in BYPASSES.items():
        body = json.dumps(
            {"toolchain": "arm-none-eabi", "flags": [], "files": {"port/a.c": text.format(p=secret)}}
        ).encode()
        status, said = _post(service, body, JSON)
        assert status == 422 and SECRET not in json.dumps(said), form


def test_the_service_compiles_two_ports_at_a_time_and_says_it_is_busy(service, monkeypatch) -> None:
    go = threading.Event()
    started = threading.Semaphore(0)

    def slow(*a):
        started.release()
        go.wait(10)
        return {"compiled": True}

    monkeypatch.setattr(firmware, "compile_here", slow)
    monkeypatch.setattr(firmware, "WAIT", 0.2)
    answers: list[int] = []
    runs = [threading.Thread(target=lambda: answers.append(_post(service, GOOD, JSON)[0])) for _ in range(2)]
    for r in runs:
        r.start()
    assert started.acquire(timeout=10) and started.acquire(timeout=10)
    assert _post(service, GOOD, JSON)[0] == 503
    go.set()
    for r in runs:
        r.join(10)
    assert answers == [200, 200]


def test_one_deadline_holds_every_source_together(monkeypatch) -> None:
    clock = [0.0]
    given: list[float] = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def run(command, **kw):
        if "-c" not in command:
            return Done()
        given.append(kw["timeout"])
        clock[0] += 50.0  # each source takes 50 s
        return Done()

    monkeypatch.setattr(firmware.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(firmware.subprocess, "run", run)
    monkeypatch.setattr(firmware, "_reaches", lambda *a: None)
    monkeypatch.setattr(firmware.shutil, "which", lambda name: "/usr/bin/" + name)
    files = {f"port/f{i}.c": "int a;" for i in range(6)}
    got = firmware.compile_here("arm-none-eabi", [], files)
    assert given == [120.0, 70.0, 20.0]  # each compile is given what is left of the one deadline
    assert got["compiled"] is False and any(f"more than {firmware.SECONDS} s" in e for e in got["errors"])


def test_the_client_sends_the_token(service, monkeypatch) -> None:
    monkeypatch.setattr(firmware.shutil, "which", lambda name: None)
    monkeypatch.setenv("MOTIONSIM_FIRMWARE_URL", f"http://127.0.0.1:{service.server_address[1]}")
    monkeypatch.setattr(firmware, "compile_here", lambda *a: {"compiled": True, "warnings": []})
    monkeypatch.setenv(firmware.TOKEN_ENV, TOKEN)
    assert firmware.compile_port("arm-none-eabi", [], {"port/a.c": "int a;"})["compiled"] is True
    monkeypatch.setenv(firmware.TOKEN_ENV, "wrong" * 9)
    got = firmware.compile_port("arm-none-eabi", [], {"port/a.c": "int a;"})
    assert got["compiled"] is None and "(401)" in got["said"]


def test_the_container_is_preferred_to_the_host(service, monkeypatch) -> None:
    monkeypatch.setenv("MOTIONSIM_FIRMWARE_URL", f"http://127.0.0.1:{service.server_address[1]}")
    monkeypatch.setenv(firmware.TOKEN_ENV, TOKEN)
    monkeypatch.setattr(firmware.shutil, "which", lambda name: "/usr/bin/" + name)
    served = []
    monkeypatch.setattr(firmware, "compile_here", lambda *a: served.append(a) or {"compiled": True})
    got = firmware.compile_port("arm-none-eabi", [], {"port/a.c": "int a;"})
    assert got["where"] == "the firmware service" and len(served) == 1


def test_the_shared_token_is_made_once_and_kept_for_its_owner(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text("MOTIONSIM_PORT=4310\n")
    first = firmware.kept_token(env)
    assert len(first) >= 43 and first.replace("-", "").replace("_", "").isalnum()
    assert firmware.kept_token(env) == first
    lines = env.read_text().splitlines()
    assert lines == ["MOTIONSIM_PORT=4310", f"{firmware.TOKEN_ENV}={first}"]
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o600


# -- the containers (M1, M3) ------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]


def test_the_page_s_image_carries_a_c_compiler_for_the_replay_and_a_tmp_it_may_run() -> None:
    import yaml

    runtime = (ROOT / "Dockerfile").read_text().split("AS build", 1)[1].split("\nFROM ", 1)[1]
    assert re.search(r"apt-get install[^\n]*\bgcc\b[^\n]*\blibc6-dev\b", runtime)
    composed = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    tmp = next(t for t in composed["motionsim"]["tmpfs"] if t.split(":")[0] == "/tmp")
    assert "exec" in tmp.split(":", 1)[1].split(",") and "noexec" not in tmp


def test_the_firmware_service_is_published_here_alone_and_both_services_share_the_token() -> None:
    import yaml

    composed = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    assert all(p.startswith("127.0.0.1:") for p in composed["firmware"]["ports"])
    for name in ("motionsim", "firmware"):
        assert f"{firmware.TOKEN_ENV}=${{{firmware.TOKEN_ENV}:-}}" in composed[name]["environment"], name
    image = (ROOT / "tools/firmware/Dockerfile").read_text()
    assert '"--serve", "8090", "--host", "0.0.0.0"' in image


def test_what_stays_on_this_machine_is_ignored_by_every_clone() -> None:
    # Private notes, agents' worktrees and runs are ignored by the repository's own .gitignore,
    # not only by one checkout's .git/info/exclude.
    ignored = {line.strip() for line in (ROOT / ".gitignore").read_text().splitlines()}
    assert {"private/", ".claude/", "runs/", ".env"} <= ignored


def test_the_public_tests_speak_of_their_figures_not_of_how_they_were_found() -> None:
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        if path.name == "test_port_sandbox.py":
            continue
        assert "The figures of the audit" not in path.read_text(encoding="utf-8"), path.name


def test_validation_counts_each_group_of_tests_as_its_functions() -> None:
    text = (ROOT / "docs/VALIDATION.md").read_text(encoding="utf-8")
    for group in ("control", "board", "app"):
        said = re.search(rf"`tests/test_{group}_\*\.py`, (\d+) tests", text)
        assert said, group
        functions = sum(
            len(re.findall(r"^(?:async )?def test_", p.read_text(encoding="utf-8"), re.MULTILINE))
            for p in (ROOT / "tests").glob(f"test_{group}_*.py")
        )
        assert int(said[1]) == functions, group
