"""The local store: documents kept by kind and name in one SQLite file, what it refuses to
keep, and that requests answered at the same moment do not lose each other's work."""

from __future__ import annotations

import sqlite3
import stat
import sys
import threading

import pytest

from motionsim.app import store as stores
from motionsim.app.store import KINDS, MAX_DOC, MAX_DOCS, NotKept, Store
from motionsim.errors import Refusal


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "kept" / "motionsim.db")


def test_a_document_put_is_the_document_got(store) -> None:
    doc = {"name": "step to 3000 rpm", "gains": {"kp": 0.4, "ki": 120.0}, "trace": [0, 1.5, None], "unit": "°C"}
    kept = store.put("control-run", "run-1", doc)
    assert kept["kind"] == "control-run" and kept["id"] == "run-1" and kept["name"] == "step to 3000 rpm"
    got = store.get("control-run", "run-1")
    assert got["doc"] == doc and got["updated"] == kept["updated"]


def test_a_second_put_under_a_name_takes_the_place_of_the_first(store) -> None:
    store.put("control-scheme", "foc", {"name": "first"})
    store.put("control-scheme", "foc", {"name": "second"})
    assert store.get("control-scheme", "foc")["doc"] == {"name": "second"}
    assert [item["id"] for item in store.list("control-scheme")] == ["foc"]


def test_a_list_names_what_is_kept_of_one_kind_and_holds_no_document(store, monkeypatch) -> None:
    clock = iter([100.0, 200.0, 300.0])
    monkeypatch.setattr(stores.time, "time", lambda: next(clock))
    store.put("exploration", "older", {"name": "a sweep", "points": [1, 2, 3]})
    store.put("exploration", "newer", {"points": []})
    store.put("control-run", "elsewhere", {})
    listed = store.list("exploration")
    # The latest first, each with its own name where the document gives one.
    assert [(item["id"], item["name"], item["updated"]) for item in listed] == [
        ("newer", "", 200.0),
        ("older", "a sweep", 100.0),
    ]
    assert listed[1]["bytes"] == len('{"name":"a sweep","points":[1,2,3]}')
    assert all("doc" not in item for item in listed)


def test_a_document_deleted_is_gone_and_one_never_kept_is_said_not_to_be(store) -> None:
    store.put("control-run", "run-1", {})
    store.delete("control-run", "run-1")
    assert store.list("control-run") == []
    with pytest.raises(NotKept):
        store.get("control-run", "run-1")
    with pytest.raises(NotKept):
        store.delete("control-run", "run-1")


@pytest.mark.parametrize("kind", ["device", "settings", "", "control-run ", "CONTROL-RUN", "../control-run"])
def test_a_kind_the_store_does_not_keep_is_refused_with_the_kinds_it_does(store, kind) -> None:
    for work in (
        lambda: store.put(kind, "a", {}),
        lambda: store.get(kind, "a"),
        lambda: store.list(kind),
        lambda: store.delete(kind, "a"),
    ):
        with pytest.raises(Refusal) as refused:
            work()
        assert refused.value.field == "kind" and all(k in refused.value.fix for k in KINDS)


@pytest.mark.parametrize("name", ["", ".hidden", "-dash", "a/b", "a b", "é", "a" * 65, "run\n", "..", "a%2Fb"])
def test_a_name_that_is_not_plain_is_refused(store, name) -> None:
    with pytest.raises(Refusal) as refused:
        store.put("control-run", name, {})
    assert refused.value.field == "id" and refused.value.fix


def test_the_longest_name_and_every_plain_sign_are_taken(store) -> None:
    for name in ("a" * 64, "Run_2.final-3", "0"):
        store.put("control-run", name, {})
    assert len(store.list("control-run")) == 3


@pytest.mark.parametrize("doc", [[1, 2], "text", 3, None, {"x": float("nan")}, {"x": float("inf")}, {"x": {1, 2}}])
def test_what_is_not_a_json_object_is_refused(store, doc) -> None:
    with pytest.raises(Refusal) as refused:
        store.put("control-run", "a", doc)
    assert refused.value.field == "doc" and refused.value.fix


def test_a_document_is_held_to_a_megabyte_as_it_is_kept(store) -> None:
    # {"t":"…"} is eight bytes around its text.
    store.put("control-run", "fits", {"t": "x" * (MAX_DOC - 8)})
    with pytest.raises(Refusal) as refused:
        store.put("control-run", "too-long", {"t": "x" * (MAX_DOC - 7)})
    assert str(MAX_DOC + 1) in refused.value.reason and "bytes" in refused.value.reason
    assert [item["id"] for item in store.list("control-run")] == ["fits"]


def test_a_kind_is_held_to_a_number_of_documents_and_one_kept_can_still_be_changed(store, monkeypatch) -> None:
    monkeypatch.setattr(stores, "MAX_DOCS", 3)
    for n in range(3):
        store.put("control-run", f"run-{n}", {})
    with pytest.raises(Refusal) as refused:
        store.put("control-run", "run-3", {})
    assert "3 documents" in refused.value.reason and "delete" in refused.value.fix
    store.put("control-run", "run-0", {"changed": True})  # in place of one that is there
    store.put("control-scheme", "another-kind", {})  # each kind has its own count
    assert MAX_DOCS == 500


def test_the_file_says_its_layout_and_a_later_layout_is_left_alone(store) -> None:
    store.put("control-run", "a", {"n": 1})
    link = sqlite3.connect(store.path)
    try:
        assert link.execute("PRAGMA user_version").fetchone() == (stores.SCHEMA,)
        link.execute(f"PRAGMA user_version = {stores.SCHEMA + 1}")
        link.commit()
    finally:
        link.close()
    with pytest.raises(Refusal) as refused:
        Store(store.path).get("control-run", "a")
    assert "later version" in refused.value.reason and refused.value.fix


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows has no such modes: the folder's own access rules hold there"
)
def test_the_file_is_its_owners_alone(store) -> None:
    store.put("control-run", "a", {})
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_what_is_kept_is_there_for_the_next_program_that_opens_the_file(store) -> None:
    store.put("exploration", "kept", {"n": 1})
    assert Store(store.path).get("exploration", "kept")["doc"] == {"n": 1}


def test_requests_answered_at_once_all_keep_their_documents(store) -> None:
    """Eight threads, as eight requests answered at the same moment, each keeping, reading
    and listing: nothing is lost, and none of them fails for the file being in use."""
    failed: list[BaseException] = []

    def work(thread: int) -> None:
        try:
            for n in range(20):
                store.put("control-run", f"t{thread}-{n}", {"thread": thread, "n": n})
                assert store.get("control-run", f"t{thread}-{n}")["doc"] == {"thread": thread, "n": n}
                store.list("control-run")
        except BaseException as exc:
            failed.append(exc)

    threads = [threading.Thread(target=work, args=(t,)) for t in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert failed == []
    assert len(store.list("control-run")) == 160
