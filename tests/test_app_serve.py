"""`motionsim serve`: which server it starts, what it says when it does, and that it runs
with the four core libraries alone."""

from __future__ import annotations

import socket
import subprocess
import sys

import pytest

from motionsim import app, server
from motionsim.app import home, run
from motionsim.cli import build_parser, main
from motionsim.observe import provider


@pytest.fixture(autouse=True)
def own_folder(tmp_path, monkeypatch):
    monkeypatch.setenv(home.HOME, str(tmp_path / "home"))
    monkeypatch.setattr(provider, "saved_key", provider.saved_key)
    return tmp_path / "home"


def stop_at_once(self, *args, **kwargs) -> None:
    """In place of a server's loop: the Ctrl+C that ends it, straight away."""
    raise KeyboardInterrupt


def test_serve_answers_this_machine_only_unless_told_otherwise() -> None:
    assert build_parser().parse_args(["serve"]).host == "127.0.0.1"
    assert build_parser().parse_args(["serve", "--host", "0.0.0.0"]).host == "0.0.0.0"


def test_without_the_app_extra_serve_runs_the_standard_librarys_server_and_says_so(monkeypatch, capsys) -> None:
    monkeypatch.setattr(run, "available", lambda: False)
    monkeypatch.setattr(server.Server, "serve_forever", stop_at_once)
    assert main(["serve", "--port", "0", "--no-browser"]) == 0
    line = capsys.readouterr().out.splitlines()[0]
    assert line.startswith("motionsim is at http://127.0.0.1:") and "Python's own HTTP server" in line
    assert "FastAPI" not in line


def test_with_the_app_extra_serve_runs_the_asgi_app_and_says_so(monkeypatch, capsys) -> None:
    uvicorn = pytest.importorskip("uvicorn", reason="the ASGI app needs the app extra")
    pytest.importorskip("fastapi", reason="the ASGI app needs the app extra")
    pytest.importorskip("wsproto", reason="the ASGI app needs the app extra")
    monkeypatch.setattr(uvicorn.Server, "run", stop_at_once)
    assert main(["serve", "--port", "0", "--no-browser"]) == 0
    line = capsys.readouterr().out.splitlines()[0]
    assert line.startswith("motionsim is at http://127.0.0.1:") and "FastAPI on uvicorn" in line


def test_the_device_files_are_kept_in_motionsims_folder_unless_another_is_named(
    monkeypatch, capsys, own_folder, tmp_path
) -> None:
    monkeypatch.setattr(run, "available", lambda: False)
    monkeypatch.setattr(server.Server, "serve_forever", stop_at_once)
    main(["serve", "--port", "0", "--no-browser"])
    assert f"devices in {own_folder / 'devices'};" in capsys.readouterr().out
    main(["serve", "--port", "0", "--no-browser", "--devices", str(tmp_path / "parts")])
    assert f"devices in {tmp_path / 'parts'};" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("host", "open_to_others"),
    [
        ("127.0.0.1", False),
        ("localhost", False),
        ("::1", False),
        ("0.0.0.0", True),
        ("192.168.1.20", True),
        ("::", True),
    ],
)
def test_an_address_other_machines_can_reach_is_known_as_one(host, open_to_others) -> None:
    assert run.open_to_others(host) is open_to_others


def test_serving_on_every_interface_says_who_can_then_use_the_page(monkeypatch, capsys) -> None:
    """The check on where a request comes from is a browser's word, which a program on
    another machine need not give: the one thing that keeps others out is the address."""
    monkeypatch.setattr(run, "available", lambda: False)
    monkeypatch.setattr(server.Server, "serve_forever", stop_at_once)
    main(["serve", "--port", "0", "--no-browser", "--host", "0.0.0.0"])
    said = capsys.readouterr()
    assert said.out.startswith("motionsim is at http://127.0.0.1:")
    assert "other machines can reach" in said.err and "127.0.0.1 only" in said.err
    main(["serve", "--port", "0", "--no-browser"])
    assert capsys.readouterr().err == ""


def test_a_port_that_is_taken_is_refused_in_words_by_either_server(monkeypatch, capsys) -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        port = str(taken.getsockname()[1])
        for asgi in (True, False):
            if asgi and not app.available():
                continue
            monkeypatch.setattr(run, "available", lambda asgi=asgi: asgi)
            assert main(["serve", "--port", port, "--no-browser"]) == 2
            said = capsys.readouterr().err
            assert f"port {port}" in said and "--port" in said


def test_the_browser_is_opened_at_the_page_once_the_address_is_taken(monkeypatch, capsys) -> None:
    opened = []
    monkeypatch.setattr(run, "available", lambda: False)
    monkeypatch.setattr(run, "_open", opened.append)
    monkeypatch.setattr(server.Server, "serve_forever", stop_at_once)
    main(["serve", "--port", "0"])
    assert opened == [capsys.readouterr().out.split()[3]]


def test_a_key_saved_from_the_page_is_read_with_whichever_server_answers(monkeypatch, capsys) -> None:
    monkeypatch.setattr(run, "available", lambda: False)
    monkeypatch.setattr(server.Server, "serve_forever", stop_at_once)
    main(["serve", "--port", "0", "--no-browser"])
    assert provider.saved_key.__module__ == "motionsim.app.keys"


def test_the_package_and_the_command_line_load_neither_fastapi_nor_uvicorn() -> None:
    """`pip install motionsim` with no extra has neither: nothing but the app itself may
    need them, and the command line answers without them."""
    code = (
        "import sys; import motionsim.app, motionsim.app.run, motionsim.app.keys, motionsim.app.store, motionsim.cli; "
        "from motionsim.cli import build_parser; build_parser(['serve']); "
        "print(sorted(m for m in ('fastapi', 'uvicorn', 'starlette', 'wsproto') if m in sys.modules))"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True)
    assert done.stdout.strip() == "[]"


def test_the_app_is_said_to_be_available_only_with_all_its_libraries(monkeypatch) -> None:
    monkeypatch.setattr(app, "find_spec", lambda name: None if name == "wsproto" else object())
    assert app.available() is False
    monkeypatch.setattr(app, "find_spec", lambda name: object())
    assert app.available() is True


def test_at_the_debug_level_other_libraries_say_nothing_below_a_warning() -> None:
    """What a datasheet holds passes through the PDF library and the model's, which say it at
    their own debug level: served at debug, the log has this tool's records and not theirs."""
    import io
    import logging

    out = io.StringIO()
    handler = logging.StreamHandler(out)
    root = logging.getLogger()
    root.addHandler(handler)
    level = root.level
    try:
        run.logs("debug")
        logging.getLogger("motionsim").debug("the tool's own")
        for name in ("anthropic._base_client", "httpx", "httpcore.http11", "pdfminer.psparser", "asyncio"):
            logging.getLogger(name).debug("page 3 of the datasheet says: secret figures")
            logging.getLogger(name).info("page 3 of the datasheet says: secret figures")
        logging.getLogger("httpx").warning("a library's warning")
    finally:
        root.removeHandler(handler)
        root.setLevel(level)
        for name in run.TALKATIVE:
            logging.getLogger(name).setLevel(logging.NOTSET)
    assert "the tool's own" in out.getvalue() and "a library's warning" in out.getvalue()
    assert "secret figures" not in out.getvalue()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no such modes")
@pytest.mark.parametrize("asgi", [False, True])
def test_motionsims_folder_is_made_its_owners_alone_before_anything_is_put_in_it(monkeypatch, own_folder, asgi) -> None:
    """It holds the reader's key: made open to the group, as a folder of device files made
    first would leave it, the key's own mode would be all that kept it."""
    import stat

    if asgi:
        uvicorn = pytest.importorskip("uvicorn", reason="the ASGI app needs the app extra")
        pytest.importorskip("fastapi", reason="the ASGI app needs the app extra")
        monkeypatch.setattr(uvicorn.Server, "run", stop_at_once)
    monkeypatch.setattr(run, "available", lambda: asgi)
    monkeypatch.setattr(server.Server, "serve_forever", stop_at_once)
    assert not own_folder.exists()
    assert main(["serve", "--port", "0", "--no-browser"]) == 0
    assert stat.S_IMODE(own_folder.stat().st_mode) == 0o700 and (own_folder / "devices").is_dir()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no such modes")
def test_an_app_made_for_motionsims_own_folder_makes_it_its_owners_alone(own_folder) -> None:
    import stat

    pytest.importorskip("fastapi", reason="the ASGI app needs the app extra")
    from motionsim.app.server import create_app

    create_app()
    assert stat.S_IMODE(own_folder.stat().st_mode) == 0o700


@pytest.mark.skipif(sys.platform == "win32" or not hasattr(__import__("os"), "geteuid"), reason="modes")
def test_a_folder_that_cannot_be_written_is_said_to_be_that_and_not_a_port(monkeypatch, tmp_path, capsys) -> None:
    import os

    if os.geteuid() == 0:
        pytest.skip("root writes anywhere")
    shut = tmp_path / "shut"
    shut.mkdir(mode=0o500)
    monkeypatch.setenv(home.HOME, str(shut / "motionsim"))
    monkeypatch.setattr(run, "available", lambda: False)
    monkeypatch.setattr(server.Server, "serve_forever", stop_at_once)
    try:
        assert main(["serve", "--port", "0", "--no-browser"]) == 2
    finally:
        shut.chmod(0o700)
    said = capsys.readouterr().err
    assert str(shut / "motionsim") in said and "cannot be written" in said and "MOTIONSIM_HOME" in said
    assert "port" not in said


@pytest.mark.parametrize(
    ("published", "shown", "warned"),
    [
        ("127.0.0.1:8000", "http://127.0.0.1:8000/", False),
        ("localhost:9001", "http://localhost:9001/", False),
        ("0.0.0.0:8000", "http://127.0.0.1:8000/", True),
        ("192.168.1.20:8000", "http://127.0.0.1:8000/", True),
    ],
)
def test_in_a_container_the_address_said_is_the_one_published(monkeypatch, capsys, published, shown, warned) -> None:
    """Inside, the page answers every interface of the container on its own port; what
    reaches it is the port the host publishes, which the container is told of."""
    monkeypatch.setenv("MOTIONSIM_PUBLISHED", published)
    monkeypatch.setattr(run, "available", lambda: False)
    monkeypatch.setattr(server.Server, "serve_forever", stop_at_once)
    main(["serve", "--port", "0", "--no-browser", "--host", "0.0.0.0"])
    said = capsys.readouterr()
    assert said.out.startswith(f"motionsim is at {shown} ")
    assert ("other machines can reach" in said.err) is warned


@pytest.mark.parametrize("asgi", [False, True])
def test_served_on_the_ipv6_loopback_the_page_is_answered_at_its_own_address(monkeypatch, capsys, asgi) -> None:
    import http.client
    import threading

    if asgi:
        pytest.importorskip("fastapi", reason="the ASGI app needs the app extra")
    try:
        socket.socket(socket.AF_INET6).close()
    except OSError:
        pytest.skip("no IPv6 here")

    def keep(self, *args, **kwargs) -> None:
        raise KeyboardInterrupt

    # Where the server would loop, the line has been said: it is read, and then a server of
    # the kind asked is run on the same address and asked.
    real = server.Server.serve_forever
    monkeypatch.setattr(run, "available", lambda: False)
    monkeypatch.setattr(server.Server, "serve_forever", keep)
    main(["serve", "--port", "0", "--no-browser", "--host", "::1"])
    said = capsys.readouterr()
    assert said.out.startswith("motionsim is at http://[::1]:") and said.err == ""
    if asgi:
        import uvicorn

        from motionsim.app.server import create_app

        listener = run.listening("::1", 0)
        uvi = uvicorn.Server(run.config(create_app()))
        thread = threading.Thread(target=uvi.run, kwargs={"sockets": [listener]}, daemon=True)
        port = listener.getsockname()[1]

        def stop() -> None:
            uvi.should_exit = True
            thread.join(timeout=20)
            listener.close()
    else:
        httpd = server.Server(("::1", 0), server.Workspace(home.devices()))
        thread = threading.Thread(target=real, args=(httpd,), daemon=True)
        port = httpd.server_address[1]

        def stop() -> None:
            httpd.shutdown()
            thread.join(timeout=20)
            httpd.server_close()

    thread.start()
    try:
        connection = http.client.HTTPConnection("::1", port, timeout=20)
        connection.request("GET", "/api/setup", headers={"Origin": f"http://[::1]:{port}"})
        assert connection.getresponse().status == 200
        connection.close()
    finally:
        stop()
