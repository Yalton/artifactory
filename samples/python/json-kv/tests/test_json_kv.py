import json
import threading

import pytest

import json_kv
from json_kv import StoreError


def test_creates_missing_file_and_round_trips(tmp_path):
    path = tmp_path / "sub" / "data.json"
    s = json_kv.open(path)
    assert path.read_text() == "{}"
    assert s.get("a") is None and s.get("a", 7) == 7
    assert s.put_if_absent("a", "1") is True
    assert s.put_if_absent("a", "2") is False
    s.put("b", {"n": [1, 2]})
    s = json_kv.open(path)
    assert s.get("a") == "1" and s.get("b") == {"n": [1, 2]}
    assert sorted(s.keys()) == ["a", "b"] and len(s) == 2 and "a" in s


def test_put_overwrites_and_delete_removes(tmp_path):
    s = json_kv.open(tmp_path / "d.json")
    s.put("k", 1)
    s.put("k", 2)
    assert s.get("k") == 2
    assert s.delete("k") is True and s.delete("k") is False
    assert json.loads((tmp_path / "d.json").read_text()) == {}


def test_unencodable_value_leaves_store_unchanged(tmp_path):
    s = json_kv.open(tmp_path / "d.json")
    s.put("ok", 1)
    with pytest.raises(TypeError):
        s.put("bad", object())
    assert "bad" not in s
    assert json.loads((tmp_path / "d.json").read_text()) == {"ok": 1}


def test_non_str_key_raises(tmp_path):
    s = json_kv.open(tmp_path / "d.json")
    with pytest.raises(TypeError, match="keys are str"):
        s.put(1, "x")


def test_writes_leave_no_temp_files(tmp_path):
    s = json_kv.open(tmp_path / "d.json")
    for i in range(5):
        s.put(str(i), i)
    assert [p.name for p in tmp_path.iterdir()] == ["d.json"]


def test_concurrent_put_if_absent_claims_once(tmp_path):
    s = json_kv.open(tmp_path / "d.json")
    wins = []

    def claim(i):
        if s.put_if_absent("key", i):
            wins.append(i)
        s.put_if_absent(f"k{i}", "v")

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    assert len(json_kv.open(tmp_path / "d.json")) == 21


@pytest.mark.parametrize("text", ["not json", "[1, 2]"])
def test_corrupt_or_non_object_file_raises(tmp_path, text):
    (tmp_path / "d.json").write_text(text)
    with pytest.raises(StoreError):
        json_kv.open(tmp_path / "d.json")


@pytest.mark.parametrize("text", ["", "null"])
def test_empty_or_null_file_is_an_empty_store(tmp_path, text):
    (tmp_path / "d.json").write_text(text)
    s = json_kv.open(tmp_path / "d.json")
    assert s.put_if_absent("a", "1") and s.get("a") == "1"


def test_docs_travel_as_package_data():
    from importlib.resources import files
    pkg = files("json_kv")
    assert "name: json-kv" in (pkg / "module.yaml").read_text()
    assert "# json-kv" in (pkg / "README.md").read_text()


def test_put_and_get_copy_values(tmp_path):
    s = json_kv.open(tmp_path / "d.json")
    value = {"n": [1, 2]}
    s.put("k", value)
    value["n"].append(3)
    got = s.get("k")
    assert got == {"n": [1, 2]}
    got["n"].append(4)
    assert s.get("k") == {"n": [1, 2]}
    s.put("t", (1, 2))
    assert s.get("t") == [1, 2]


def test_replace_keeps_the_file_mode(tmp_path):
    import os
    import stat

    path = tmp_path / "d.json"
    json_kv.open(path)
    os.chmod(path, 0o640)
    s = json_kv.open(path)
    s.put("a", 1)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_new_file_mode_follows_the_umask(tmp_path):
    import os
    import stat

    old = os.umask(0o027)
    try:
        json_kv.open(tmp_path / "d.json").put("a", 1)
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "d.json").stat().st_mode) == 0o640


def test_failed_write_raises_store_error_and_keeps_state(tmp_path, monkeypatch):
    import os

    s = json_kv.open(tmp_path / "d.json")
    s.put("a", 1)

    def broken(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(StoreError, match="No space left"):
        s.put("b", 2)
    assert "b" not in s and s.get("a") == 1
    assert [p.name for p in tmp_path.iterdir()] == ["d.json"]
    monkeypatch.undo()
    assert json_kv.open(tmp_path / "d.json").keys() == ["a"]


@pytest.mark.parametrize("code,raises", [(22, False), (95, False), (5, True)])  # EINVAL, EOPNOTSUPP, EIO
def test_directory_fsync_errors(tmp_path, monkeypatch, code, raises):
    import os

    s = json_kv.open(tmp_path / "d.json")
    real = os.fsync
    dirs = set()
    real_open = os.open

    def tracking_open(path, flags, *a, **k):
        fd = real_open(path, flags, *a, **k)
        if os.path.isdir(path):
            dirs.add(fd)
        return fd

    def fsync(fd):
        if fd in dirs:
            raise OSError(code, os.strerror(code))
        return real(fd)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "fsync", fsync)
    if raises:
        with pytest.raises(StoreError):
            s.put("a", 1)
    else:
        s.put("a", 1)
    assert s.get("a") == 1  # the file was replaced either way; memory matches disk
    monkeypatch.undo()
    assert json_kv.open(tmp_path / "d.json").get("a") == 1


def test_unreadable_file_raises_store_error(tmp_path):
    (tmp_path / "d.json").write_bytes(b"\xff\xfe")
    with pytest.raises(StoreError):
        json_kv.open(tmp_path / "d.json")
    with pytest.raises(StoreError):
        json_kv.open(tmp_path)  # a directory
