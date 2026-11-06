"""A persistent key-value store kept in one JSON file."""
from __future__ import annotations

import builtins
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

print("[json-kv] live", flush=True)

__all__ = ["Store", "StoreError", "open"]

_MISSING = object()


class StoreError(Exception):
    """The store file cannot be read, is not a JSON object, or cannot be written."""


class Store:
    """A str-keyed store of JSON values in one file. Safe to share between threads."""

    def __init__(self, path: str | os.PathLike):
        self._path = Path(path)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        try:
            text = self._path.read_text()
        except FileNotFoundError:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._flush(self._data)
            return
        except OSError as e:
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
        """The value for key, or default."""
        with self._lock:
            return self._data.get(key, default)

    def put_if_absent(self, key: str, value: Any) -> bool:
        """Store value under key unless key exists. True if it stored."""
        with self._lock:
            if key in self._data:
                return False
            self._write({**self._data, _key(key): value})
            return True

    def put(self, key: str, value: Any) -> None:
        """Store value under key, replacing any old value."""
        with self._lock:
            self._write({**self._data, _key(key): value})

    def delete(self, key: str) -> bool:
        """Remove key. True if it existed."""
        with self._lock:
            if key not in self._data:
                return False
            self._write({k: v for k, v in self._data.items() if k != key})
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

    def _write(self, data: dict[str, Any]) -> None:
        self._flush(data)  # raises before anything changes if data does not encode
        self._data = data

    def _flush(self, data: dict[str, Any]) -> None:
        text = json.dumps(data, ensure_ascii=False)
        folder = self._path.parent
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".json-kv-", suffix=".tmp")
        try:
            with builtins.open(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
        dfd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


def _key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError(f"json_kv: keys are str, got {type(key).__name__}")
    return key


def open(path: str | os.PathLike) -> Store:  # noqa: A001 - the module's entry point
    """Open the store at path, creating the file and its parent folders if missing."""
    return Store(path)
