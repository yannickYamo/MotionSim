"""Start the page: on the ASGI app where its libraries are installed, on the standard
library's server where they are not. `motionsim serve` calls `serve` and nothing else."""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import sys
import tempfile
from pathlib import Path

from motionsim.app import available, keys
from motionsim.app.home import HOME, devices, home, made
from motionsim.errors import Refusal
from motionsim.service.workspace import Workspace

BACKLOG = 128
STOPPING = 3  # seconds
ASGI = "FastAPI on uvicorn"
BUILTIN = "Python's own HTTP server"


# Set in a container to the address the user opens, as host:port: the host publishes the
# container's port there, which is the only way in, and the port inside is not the one outside.
PUBLISHED = "MOTIONSIM_PUBLISHED"


def published() -> tuple[str, str] | None:
    """The host and port the page is published at, where the environment says so."""
    given = os.environ.get(PUBLISHED, "").strip()
    name, colon, port = given.rpartition(":")
    if not (colon and name and port.isdigit()):
        return None
    return name.strip("[]"), port


def address(host: str, port: int) -> str:
    """The address the page is opened at: the published one in a container, this machine's
    own name for the address answered on otherwise."""
    outside = published()
    if outside:
        name, at = outside
        if ":" in name or name in ("0.0.0.0", ""):  # every interface: this machine's own name for it
            name = "[::1]" if ":" in name else "127.0.0.1"
        elif open_to_others(name):
            name = "127.0.0.1"  # the page answers only to this machine's names
        return f"http://{name}:{at}/"
    return f"http://[::1]:{port}/" if ":" in host else f"http://127.0.0.1:{port}/"


def said(port: int, how: str, workspace: Workspace, host: str = "127.0.0.1") -> str:
    """The line that says where the page is and what serves it. Whoever started the page
    waits for this line and reads the address from it."""
    return f"motionsim is at {address(host, port)}  ({how}; devices in {workspace.folder}; Ctrl+C to stop)"


def open_to_others(host: str) -> bool:
    """Whether an address is one other machines can reach: anything but this machine's own."""
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host != "localhost"


OPEN = (
    "answering on {host}, which other machines can reach: whoever can reach this port can use the page, "
    "what it keeps and the key it reads datasheets with. Publish the port on 127.0.0.1 only, as "
    "docker-compose.yml does, or leave --host as it is."
)


def _say(port: int, how: str, workspace: Workspace, host: str) -> None:
    # Said at once, also where the output is a pipe: whoever started this waits for the line.
    print(said(port, how, workspace, host), flush=True)
    # In a container the page answers every interface of its own, and is reached only where
    # the host publishes it: that is the address others could or could not reach.
    outside = published()
    reached = outside[0] if outside else host
    if open_to_others(reached):
        print(OPEN.format(host=reached), file=sys.stderr, flush=True)


# Libraries that log what passes through them at their lower levels: the model's library and
# the HTTP it speaks, a request body, a datasheet's text as it is read. Held to warnings
# whatever level the page is served at.
TALKATIVE = ("anthropic", "httpx", "httpcore", "pdfminer", "pdfplumber", "PIL", "asyncio", "urllib3", "multipart")


def logs(level: str) -> None:
    """The log as `motionsim serve` keeps it: this tool's own records at the level asked,
    other libraries' at warnings and above, and no key in any record a handler writes."""
    from motionsim.observe.provider import Scrubbed

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    for handler in root.handlers:
        if not any(isinstance(f, Scrubbed) for f in handler.filters):
            handler.addFilter(Scrubbed())
    for name in TALKATIVE:
        logging.getLogger(name).setLevel(max(logging.WARNING, root.level))


def writable(folder: Path | None) -> Workspace:
    """The workspace of device files, made first: in MotionSim's own folder, made its owner's
    alone before anything is put in it, unless another is named. A folder that cannot be
    made or written is refused as that, before any address is taken."""
    where = folder or home()
    try:
        if folder is None:
            made(where)
        workspace = Workspace(folder or devices())
        tempfile.TemporaryFile(dir=where).close()
    except OSError as exc:
        named = "the folder of device files" if folder else "MotionSim's folder"
        raise Refusal(
            f"{named} {where} cannot be written: {exc.strerror or exc}",
            "give a folder this user can write with --devices"
            if folder
            else f"set {HOME} to a folder this user can write, or give this one back to its owner",
            "devices" if folder else "home",
        ) from None
    return workspace


def config(app, log_level: str = "warning"):
    """How uvicorn runs the app, here and in the tests: quiet, named as the tool and nothing
    else, and with the page's own time for a connection that says nothing."""
    import uvicorn

    from motionsim.server import IDLE, MAX_JSON

    return uvicorn.Config(
        app,
        log_config=None,  # the command line has set the log up: faults, and nothing of a request
        log_level=log_level,
        access_log=False,
        server_header=False,  # the app names itself, and says nothing of what runs it
        ws="wsproto",
        # A socket's one request is a request of figures: one twice the largest of those is
        # closed as too large (1009) while it arrives, and never held whole. uvicorn holds
        # wsproto to this from 0.46.0, the floor in pyproject.toml.
        ws_max_size=2 * MAX_JSON,
        lifespan="on",  # the agent's MCP server runs for as long as the app does
        timeout_keep_alive=int(IDLE),
        # On Ctrl+C a request still under way has this long to finish, and is then let go.
        timeout_graceful_shutdown=STOPPING,
    )


def listening(host: str, port: int) -> socket.socket:
    """The address, taken and listening before anything is said: a taken port is known at
    once, and a request made the moment the line is read waits its turn and is answered."""
    listener = socket.socket(socket.AF_INET6 if ":" in host.strip("[]") else socket.AF_INET)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(BACKLOG)
    except BaseException:
        listener.close()
        raise
    return listener


def _open(address: str) -> None:
    import webbrowser

    webbrowser.open(address)


def _serve_asgi(host: str, port: int, workspace: Workspace, open_browser: bool, log_level: str) -> None:
    import uvicorn

    from motionsim.app.server import create_app

    listener = listening(host, port)
    try:
        port = listener.getsockname()[1]
        server = uvicorn.Server(config(create_app(workspace), log_level))
        _say(port, ASGI, workspace, host)
        if open_browser:
            _open(address(host, port))
        server.run(sockets=[listener])
    except KeyboardInterrupt:
        print()
    finally:
        listener.close()


def _serve_builtin(host: str, port: int, workspace: Workspace, open_browser: bool) -> None:
    from motionsim.server import Server

    httpd = Server((host, port), workspace)
    port = httpd.server_address[1]
    _say(port, BUILTIN, workspace, host)
    if open_browser:
        _open(address(host, port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        httpd.server_close()


def serve(
    host: str = "127.0.0.1",
    port: int = 4310,
    folder: str | Path | None = None,
    open_browser: bool = True,
    log_level: str = "warning",
) -> None:
    """Serve the page until stopped. Raises OSError where the address cannot be taken, and
    a Refusal where MotionSim's folder cannot be written."""
    workspace = writable(Path(folder) if folder else None)
    keys.use_saved()  # a key saved from the page is read with, whichever server answers
    if available():
        _serve_asgi(host, port, workspace, open_browser, log_level)
    else:
        _serve_builtin(host, port, workspace, open_browser)
