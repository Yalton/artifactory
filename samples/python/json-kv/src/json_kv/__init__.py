"""A persistent key-value store kept in one JSON file."""
from __future__ import annotations

import builtins
import errno
import json
import os
import stat
import tempfile
import threading
from pathlib import Path
from typing import Any

print("[json-kv] live", flush=True)

__all__ = ["Store", "StoreError", "open"]

# Filesystems that cannot fsync a directory say so with these; any other error is real.
_DIR_FSYNC_UNSUPPORTED = {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}
_umask_lock = threading.Lock()


class StoreError(Exception):
    """The store file cannot be read, is not a JSON object, or cannot be written."""


def _copy(value: Any) -> Any:
    """A deep copy through JSON, so callers never share objects with the store. Raises TypeError if
    value does not encode."""
    return json.loads(json.dumps(value, ensure_ascii=False))


def _new_file_mode() -> int:
    with _umask_lock:  # os.umask can only be read by setting it
        mask = os.umask(0)
        os.umask(mask)
    return 0o666 & ~mask


class Store:
    """A str-keyed store of JSON values in one file. Safe to share between threads."""

    def __init__(self, path: str | os.PathLike):
        self._path = Path(path)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise StoreError(f"json_kv: {self._path}: {e}") from e
            self._replace({})
            return
        except (OSError, UnicodeDecodeError) as e:
            raise StoreError(f"json_kv: {self._path}: {e}") from e
        if text.strip():
            try:
                data = json.loads(text)
            except ValueError as e:
                raise StoreError(f"json_kv: {self._path} is not valid JSON: {e}") from e
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise StoreError(f"json_kv: {self._path} holds a JSON {type(data).__name__}, not an object")
            self._data = data

    @property
    def path(self) -> Path:
        return self._path

    def get(self, key: str, default: Any = None) -> Any:
        """A copy of the value for key, or default."""
        with self._lock:
            if key not in self._data:
                return default
            return _copy(self._data[key])

    def put_if_absent(self, key: str, value: Any) -> bool:
        """Store a copy of value under key unless key exists. True if it stored."""
        with self._lock:
            if key in self._data:
                return False
            self._replace({**self._data, _key(key): _copy(value)})
            return True

    def put(self, key: str, value: Any) -> None:
        """Store a copy of value under key, replacing any old value."""
        with self._lock:
            self._replace({**self._data, _key(key): _copy(value)})

    def delete(self, key: str) -> bool:
        """Remove key. True if it existed."""
        with self._lock:
            if key not in self._data:
                return False
            self._replace({k: v for k, v in self._data.items() if k != key})
            return True

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._data)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._data

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def close(self) -> None:
        """Nothing to release: every write is already on disk."""

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _replace(self, data: dict[str, Any]) -> None:
        """Write data to a temporary file and rename it over the store file; only then is it the
        store's state. The caller holds the lock."""
        text = json.dumps(data, ensure_ascii=False)
        folder = self._path.parent
        try:
            mode = stat.S_IMODE(os.stat(self._path).st_mode)
        except FileNotFoundError:
            mode = _new_file_mode()
        except OSError as e:
            raise StoreError(f"json_kv: {self._path}: {e}") from e
        try:
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".json-kv-", suffix=".tmp")
        except OSError as e:
            raise StoreError(f"json_kv: {self._path}: {e}") from e
        try:
            with builtins.open(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fchmod(f.fileno(), mode)
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except BaseException as e:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            if isinstance(e, OSError):
                raise StoreError(f"json_kv: {self._path}: {e}") from e
            raise
        self._data = data
        self._sync_dir(folder)

    def _sync_dir(self, folder: Path) -> None:
        try:
            dfd = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError as e:
            if e.errno not in _DIR_FSYNC_UNSUPPORTED:
                raise StoreError(f"json_kv: {folder}: {e}") from e


def _key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError(f"json_kv: keys are str, got {type(key).__name__}")
    return key


def open(path: str | os.PathLike) -> Store:  # noqa: A001 - the module's entry point
    """Open the store at path, creating the file and its parent folders if missing."""
    return Store(path)
