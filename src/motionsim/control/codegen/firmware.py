"""The port compiled with a cross-compiler: on this machine where the toolchain is on the PATH,
or by the firmware service of `docker compose --profile firmware`, which runs this same file.

Compiling is all that is done: each source is compiled to an object (`-c`), nothing is linked
(there is no startup code or linker script for a board), and nothing is run. The answer is
whether every source compiled, the compiler's warnings and errors, and the size of the objects
(text, data, bss) as the toolchain's `size` gives it.

This file uses the standard library alone and imports nothing of MotionSim's: the firmware
image copies it by itself (tools/firmware/Dockerfile) and serves it with

    python3 firmware.py --serve 8090

    python3 firmware.py --serve 8090 --host 0.0.0.0     (in the image: reached by its port alone)

which answers GET /health with the toolchains it has, and POST /compile with
{"toolchain", "flags", "files": {path: text}}. A request names a toolchain of the table below
and flags of target selection alone; paths are relative, of .c and .h files, and a source
includes only its neighbours and the C library's headers.

The sources are a language model's, so what they may reach is held twice. Their text is
refused where it could hide an include from a reading of the text: a line joined by a
backslash, a trigraph, a digraph, a comment inside a directive, any assembler. Then the
preprocessor is asked what it read (-nostdinc, the toolchain's own include folders named,
-MD): a source that read a file outside the port and the toolchain's headers is not compiled.
The compiler's words are said only of the port's own files, so the text of a file from
elsewhere never comes back.

The service listens on 127.0.0.1 unless told otherwise, answers only a Host of this machine or
the compose service's name, a JSON body, and the token in MOTIONSIM_FIRMWARE_TOKEN (the app
sends the same one); it compiles two requests at a time, each in one deadline.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The toolchains the firmware image carries, by the name a profile gives: the compiler and its `size`.
TOOLCHAINS: dict[str, dict[str, str]] = {
    "arm-none-eabi": {"cc": "arm-none-eabi-gcc", "size": "arm-none-eabi-size"},
    "riscv64-unknown-elf": {"cc": "riscv64-unknown-elf-gcc", "size": "riscv64-unknown-elf-size"},
    "xtensa-esp32s3-elf": {"cc": "xtensa-esp32s3-elf-gcc", "size": "xtensa-esp32s3-elf-size"},
}
COMMON = ("-std=c99", "-O2", "-Wall", "-Wextra", "-c")
FLAG = re.compile(r"^-m[a-z0-9][a-z0-9=.,+_-]*$")
PATH = re.compile(r"^(?:core|port)/[A-Za-z0-9_][A-Za-z0-9_.-]*\.[ch]$")
MOST_FILES = 24
MOST_BYTES = 1_000_000
SECONDS = 120  # for every source of a request together
SERVICE = "http://127.0.0.1:4391"  # where `docker compose --profile firmware` publishes the service
WAIT = 5.0  # s to reach the service, and to wait for a compile's turn there
TOKEN_ENV = "MOTIONSIM_FIRMWARE_TOKEN"  # the token the app and the service share
TOKEN_BYTES = 32  # of randomness, as the agent's access code: 43 characters
AT_ONCE = 2  # compiles the service runs at a time
NAMES = ("firmware", "localhost", "127.0.0.1", "[::1]")  # the Host a request may name
LAW = ("motionsim_ctrl_init", "motionsim_ctrl_warm", "motionsim_ctrl_step")
# What a compiler is told by its environment, besides its flags: none of it is passed on.
ENVIRONMENT = (
    "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH", "GCC_EXEC_PREFIX",
    "COMPILER_PATH", "LIBRARY_PATH", "DEPENDENCIES_OUTPUT", "SUNPRO_DEPENDENCIES", "GCC_COMPARE_DEBUG",
)  # fmt: skip


class Unusable(ValueError):
    """A request this compiler does not take: said in words."""


def checked(toolchain: str, flags: list[str], files: dict[str, str]) -> None:
    if toolchain not in TOOLCHAINS:
        raise Unusable(f"no toolchain {toolchain!r} here: one of {', '.join(TOOLCHAINS)}")
    if not isinstance(flags, list) or not all(isinstance(f, str) and FLAG.match(f) for f in flags):
        raise Unusable("the flags are target selection alone (-m...)")
    if not isinstance(files, dict) or not files or len(files) > MOST_FILES:
        raise Unusable(f"between 1 and {MOST_FILES} files are compiled")
    if sum(len(str(t)) for t in files.values()) > MOST_BYTES:
        raise Unusable(f"the files are more than {MOST_BYTES} bytes")
    for path, text in files.items():
        if not isinstance(path, str) or not PATH.match(path) or not isinstance(text, str):
            raise Unusable(f"{path!r} is not a core/ or port/ C source or header")
        if (why := outside(text)) is not None:
            raise Unusable(f"{path}: {why}")


INCLUDE = re.compile(r"^[ \t]*(?:#|%:)[ \t]*(\w+)\b[ \t]*(.*)$", re.MULTILINE)
INCLUDES = ("include", "embed", "import", "include_next")
SPLICE = re.compile(r"\\[ \t\f\v]*(?:\r\n|\r|\n|$)")
ASM = re.compile(r"\b(?:__asm__|__asm|asm)\b")
PRAGMA = re.compile(r"\b_Pragma\b|^[ \t]*(?:#|%:)[ \t]*pragma\b.*\bdependency\b", re.MULTILINE)


def uncommented(text: str) -> str:
    """The text with each comment made one space, as the preprocessor makes it; string and
    character literals are kept as they are."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            out.append(" " + "\n" * text.count("\n", i, n if j < 0 else j))
            i = n if j < 0 else j + 2
        elif text.startswith("//", i):
            j = text.find("\n", i)
            out.append(" ")
            i = n if j < 0 else j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _hidden(text: str) -> str | None:
    """What would hide an include from a reading of the text: a trigraph, a joined line."""
    if "??" in text:
        return "?? (a trigraph) is not taken"
    if SPLICE.search(text):
        return "a line joined by a backslash is not taken"
    return None


def outside(text: str) -> str | None:
    """Why a source could reach past its own files, or None: whatever would hide an include
    from this reading (a line joined by a backslash, a trigraph), an include by a macro, by an
    absolute path or up a folder, an #embed, assembler, a pragma that names a file."""
    if (hidden := _hidden(text)) is not None:
        return hidden
    code = uncommented(text)
    for m in INCLUDE.finditer(code):
        if m[1] not in INCLUDES:
            continue
        if m[1] != "include":
            return f"#{m[1]} is not taken"
        target = re.match(r'^[<"]([^>"]+)[>"]', m[2].strip())
        if target is None:
            return "an #include by a macro is not taken"
        if target[1].startswith(("/", "\\")) or ".." in target[1] or ":" in target[1] or "\\" in target[1]:
            return f"#include {target[1]} reaches outside the port"
    for found, why in (
        (ASM.search(code), "assembler (asm) is not taken"),
        ("incbin" in text or ".include" in text, ".incbin and .include are not taken"),
        (PRAGMA.search(code), "_Pragma and #pragma ... dependency are not taken"),
    ):
        if found:
            return why
    return None


def ours(said: list[str], root: Path) -> list[str]:
    """The compiler's diagnostics about the port's own files alone, said relative to the
    port: a line about any other file, or one that quotes a source, is dropped."""
    prefix = f"{root}/"
    kept = []
    for line in said:
        line = line.removeprefix(prefix)
        m = re.match(
            r"^((?:core|port)/[A-Za-z0-9_][A-Za-z0-9_.-]*\.[ch]):\d+(?::\d+)?: (?:fatal )?(?:warning|error):", line
        )
        if m and PATH.match(m[1]):
            kept.append(line[:400])
    return kept


def _environment() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in ENVIRONMENT}


def _search(cc: str, flags: list[str]) -> list[Path]:
    """The toolchain's own include folders, as its driver lists them."""
    done = subprocess.run(
        [cc, *flags, "-xc", "-E", "-v", "-"], input="", capture_output=True, text=True, timeout=30, env=_environment()
    )
    lines = done.stderr.splitlines()
    try:
        start = lines.index("#include <...> search starts here:") + 1
        end = lines.index("End of search list.", start)
    except ValueError:
        return []
    return [Path(line.strip()).resolve() for line in lines[start:end] if line.strip()]


def _under(path: Path, folders: list[Path]) -> bool:
    return any(path == f or f in path.parents for f in folders)


def _dependencies(made: str) -> list[str]:
    """The files a make rule of `-MD` names, past its target."""
    joined = re.sub(r"\\\n", " ", made)
    _, _, after = joined.partition(": ")
    return [p.replace("\\ ", " ") for p in re.findall(r"(?:\\ |[^\s])+", after)]


def _root_text(pre: str, root: Path) -> str:
    """What the preprocessor made of the port's own files, without the headers' text."""
    mine, kept = True, []
    for line in pre.splitlines():
        marker = re.match(r'^# \d+ "(.*)"', line)
        if marker:
            name = marker[1]
            mine = not name.startswith("<") and _under((root / name).resolve(), [root.resolve()])
            continue
        if mine:
            kept.append(line)
    return "\n".join(kept)


def _reaches(cc: str, command: list[str], path: str, root: Path, system: list[Path], left: float) -> str | None:
    """Why the preprocessor's reading of `path` is not compiled, or None: it read a file
    outside the port and the toolchain's headers, or made assembler."""
    made = root / "obj" / (path.replace("/", "_") + ".d")
    pre = root / "obj" / (path.replace("/", "_") + ".i")
    done = subprocess.run(
        [*command, "-E", "-MD", "-MF", str(made), "-o", str(pre), path],
        cwd=root, capture_output=True, text=True, timeout=max(left, 0.1), env=_environment(),
    )  # fmt: skip
    if done.returncode != 0 or not made.exists():
        return "the preprocessor failed"
    folders = [root.resolve(), *system]
    for dependency in _dependencies(made.read_text(encoding="utf-8", errors="replace")):
        if not _under((root / dependency).resolve(), folders):
            return "it reads a file outside the port and the C library's headers"
    if ASM.search(_root_text(pre.read_text(encoding="utf-8", errors="replace"), root)):
        return "the preprocessor makes assembler of it, which is not taken"
    return None


def _sizes(size_tool: str, objects: list[Path], root: Path, left: float = 30) -> dict[str, int] | None:
    if not objects or shutil.which(size_tool) is None or left <= 0:
        return None
    done = subprocess.run(
        [size_tool, "-t", *(str(o) for o in objects)],
        cwd=root, capture_output=True, text=True, timeout=min(30, left), env=_environment(),
    )  # fmt: skip
    total = [line.split() for line in done.stdout.splitlines() if line.rstrip().endswith("(TOTALS)")]
    if done.returncode != 0 or not total:
        return None
    text, data, bss = (int(v) for v in total[0][:3])
    return {"text": text, "data": data, "bss": bss}


def _version(cc: str) -> str:
    try:
        done = subprocess.run([cc, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return cc
    return (done.stdout.splitlines() or [cc])[0].strip()


def _defined(nm_tool: str, objects: list[Path], root: Path, left: float) -> list[str]:
    """The law's functions a port object defines, by its symbol table."""
    if not objects or shutil.which(nm_tool) is None or left <= 0:
        return []
    done = subprocess.run(
        [nm_tool, "--defined-only", *(str(o) for o in objects)],
        cwd=root, capture_output=True, text=True, timeout=min(30, left), env=_environment(),
    )  # fmt: skip
    found = {line.split()[-1] for line in done.stdout.splitlines() if len(line.split()) >= 3}
    return [name for name in LAW if name in found]


def compile_here(toolchain: str, flags: list[str], files: dict[str, str]) -> dict:
    """Every source compiled to an object with this machine's toolchain, once the preprocessor
    has shown it reads nothing past the port and the toolchain's headers: whether all did, the
    warnings and errors about the port's own files, the objects' size, and the law's functions
    a port object defines (which it may not)."""
    deadline = time.monotonic() + SECONDS
    checked(toolchain, flags, files)
    tools = TOOLCHAINS[toolchain]
    cc = shutil.which(tools["cc"])
    if cc is None:
        raise Unusable(f"{tools['cc']} is not on this machine")
    system = _search(cc, flags)
    includes = ["-nostdinc", *(a for d in system for a in ("-isystem", str(d))), "-Icore", "-Iport"]
    with tempfile.TemporaryDirectory(prefix="motionsim-port-") as temporary:
        root = Path(temporary)
        for path, text in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text, encoding="utf-8")
        (root / "obj").mkdir()
        said: list[str] = []
        refused: list[str] = []
        objects: list[Path] = []
        compiled = True
        for path in sorted(p for p in files if p.endswith(".c")):
            obj = root / "obj" / (path.replace("/", "_")[:-2] + ".o")
            left = deadline - time.monotonic()
            try:
                if left <= 0:
                    raise subprocess.TimeoutExpired(cc, SECONDS)
                why = _reaches(cc, [cc, "-std=c99", *flags, *includes], path, root, system, left)
                if why is not None:
                    refused.append(f"{path}: error: not compiled: {why}")
                    compiled = False
                    continue
                command = [cc, *COMMON, *flags, *includes, path, "-o", str(obj)]
                done = subprocess.run(
                    command, cwd=root, capture_output=True, text=True,
                    timeout=max(deadline - time.monotonic(), 0.1), env=_environment(),
                )  # fmt: skip
            except subprocess.TimeoutExpired:
                refused.append(f"{path}: error: the compiler took more than {SECONDS} s for every source together")
                compiled = False
                continue
            said += [line for line in done.stderr.splitlines() if line.strip()]
            if done.returncode == 0:
                objects.append(obj)
            else:
                compiled = False
        said = ours(said, root)
        left = deadline - time.monotonic()
        ported = [o for o in objects if o.name.startswith("port_")]
        return {
            "compiled": compiled and bool(objects),
            "compiler": _version(cc),
            "flags": [*COMMON, *flags, "-nostdinc"],
            "warnings": [line for line in said if ": warning:" in line],
            "errors": refused + [line for line in said if ": error:" in line or ": fatal error:" in line],
            "size": _sizes(shutil.which(tools["size"]) or tools["size"], objects, root, left) if compiled else None,
            "defined": _defined(tools.get("nm", tools["size"].removesuffix("size") + "nm"), ported, root, left),
            "where": "here",
        }


def service_url() -> str | None:
    """The firmware service's address: MOTIONSIM_FIRMWARE_URL, or the one compose publishes;
    "off" for none."""
    url = os.environ.get("MOTIONSIM_FIRMWARE_URL", SERVICE).strip().rstrip("/")
    return None if url in ("", "off") else url


def token() -> str:
    """The token the app and the firmware service share, from the environment: "" for none."""
    return os.environ.get(TOKEN_ENV, "").strip()


def kept_token(env: Path) -> str:
    """The shared token kept in a compose .env file, made there (as the agent's access code is
    made) where there is none yet; the file is its owner's alone."""
    lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
    for line in lines:
        name, _, value = line.partition("=")
        if name.strip() == TOKEN_ENV and len(value.strip()) >= 32:
            os.chmod(env, 0o600)
            return value.strip()
    made = secrets.token_urlsafe(TOKEN_BYTES)
    lines = [line for line in lines if line.partition("=")[0].strip() != TOKEN_ENV] + [f"{TOKEN_ENV}={made}"]
    handle = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")
    os.chmod(env, 0o600)
    return made


def compile_port(toolchain: str, flags: list[str], files: dict[str, str]) -> dict:
    """The port compiled where it can be: by the firmware service, in its container, where it
    answers; else with the toolchain on this machine's PATH. Never raises for want of a
    compiler: {"compiled": None, "said": why}."""
    checked(toolchain, flags, files)
    url = service_url()
    absent = (
        f"not compiled: {TOOLCHAINS[toolchain]['cc']} is not on this machine and the firmware service is not up "
        "(docker compose --profile firmware up)"
    )
    here = shutil.which(TOOLCHAINS[toolchain]["cc"]) is not None
    if url is None:
        return compile_here(toolchain, flags, files) if here else {"compiled": None, "said": absent}
    request = urllib.request.Request(
        f"{url}/compile",
        data=json.dumps({"toolchain": toolchain, "flags": flags, "files": files}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token()}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=WAIT + SECONDS) as answer:
            body = json.loads(answer.read(4_000_000))
    except urllib.error.HTTPError as refused:
        with refused:
            said = refused.read(2000).decode(errors="replace")
        return {"compiled": None, "said": f"the firmware service refused the port ({refused.code}): {said[:300]}"}
    except (urllib.error.URLError, OSError, ValueError):
        return compile_here(toolchain, flags, files) if here else {"compiled": None, "said": absent}
    if not isinstance(body, dict):
        return {"compiled": None, "said": "the firmware service answered in a form not known here"}
    return body | {"where": "the firmware service"}


_TURNS = threading.BoundedSemaphore(AT_ONCE)


class _Refused(Exception):
    def __init__(self, status: int, said: str) -> None:
        super().__init__(said)
        self.status = status


class _Handler(BaseHTTPRequestHandler):
    server_version = "motionsim-firmware"
    token = ""  # set by serve()

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _local(self) -> None:
        host = (self.headers.get("Host") or "").strip().lower()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.partition("]")[0] + "]"
        if name not in NAMES:
            raise _Refused(421, "this service answers this machine and the compose service's name alone")

    def do_GET(self) -> None:
        try:
            self._local()
        except _Refused as refused:
            self._send(refused.status, {"error": str(refused)})
            return
        if self.path != "/health":
            self._send(404, {"error": "no such address"})
            return
        have = [name for name, tools in TOOLCHAINS.items() if shutil.which(tools["cc"])]
        self._send(200, {"toolchains": have})

    def do_POST(self) -> None:
        try:
            if self.path != "/compile":
                raise _Refused(404, "no such address")
            self._local()
            scheme, _, given = (self.headers.get("Authorization") or "").strip().partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(given.strip().encode(), self.token.encode()):
                raise _Refused(401, "the token is missing or wrong")
            if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
                raise _Refused(415, "the body is JSON alone (Content-Type: application/json)")
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 2 * MOST_BYTES:
                raise Unusable("the request has no body, or one too large")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise Unusable("the request is not an object")
            if not _TURNS.acquire(timeout=WAIT):
                raise _Refused(503, f"{AT_ONCE} ports are being compiled already: try again")
            try:
                answer = compile_here(data.get("toolchain", ""), data.get("flags", []), data.get("files", {}))
            finally:
                _TURNS.release()
            self._send(200, answer)
        except _Refused as refused:
            self._send(refused.status, {"error": str(refused)})
        except (Unusable, ValueError) as refused:
            self._send(422, {"error": str(refused)})

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write(f"firmware: {format % args}\n")


def serve(host: str = "127.0.0.1", port: int = 8090, token: str | None = None) -> ThreadingHTTPServer:
    """The service, made and bound (this machine alone unless `host` says otherwise), answering
    the token given or MOTIONSIM_FIRMWARE_TOKEN's; the caller runs `serve_forever`."""
    shared = (globals()["token"]() if token is None else token).strip()
    if len(shared) < 32:
        raise Unusable(f"no token of at least 32 characters in {TOKEN_ENV}: make one with `make firmware-token`")
    handler = type("Handler", (_Handler,), {"token": shared})
    return ThreadingHTTPServer((host, port), handler)


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--token-env":
        kept_token(Path(args[1]))
        print(f"{TOKEN_ENV} kept in {args[1]}")
    elif len(args) in (2, 4) and args[0] == "--serve" and (len(args) == 2 or args[2] == "--host"):
        where = args[3] if len(args) == 4 else "127.0.0.1"
        try:
            made = serve(where, int(args[1]))
        except Unusable as e:
            sys.exit(f"firmware: {e}")
        print(f"firmware service on {where}:{args[1]}", flush=True)
        made.serve_forever()
    else:
        sys.exit("usage: python3 firmware.py --serve PORT [--host HOST] | --token-env PATH")
