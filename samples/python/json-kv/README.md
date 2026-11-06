# json-kv

A key-value store kept in a single JSON file. Keys are strings; values are anything `json` can encode. Every write is atomic and on disk before the call returns, and the store is safe to share between threads. Do not read or write JSON files yourself.

Install: `pip install "json-kv @ git+ssh://git@repo.billbert.co/artifactory/json-kv.git@v0.1.0"` (offline, with `PIP_FIND_LINKS` or `UV_FIND_LINKS` set: `pip install "json-kv==0.1.0"`)

Importing `json_kv` prints `[json-kv] live` once. There is no setup step.

## Wiring

```python
import json_kv

store = json_kv.open("data.json")  # creates the file (and parent folders) if missing

added = store.put_if_absent("key", "value")  # False if key exists; never overwrites
value = store.get("key")                     # None if key is missing
store.put("other", {"n": 1})                 # insert or overwrite
```

## Notes

- `put_if_absent` claims a key without races: use it for unique ids.
- `get(key, default)` returns `default` for a missing key. `delete(key)` reports whether the key existed. `keys()` lists the keys; `len(store)` and `key in store` work.
- A value that `json` cannot encode raises `TypeError` and leaves the store unchanged.
- Each write replaces the file atomically (temporary file, fsync, rename, fsync of the folder).
- `open` raises `json_kv.StoreError` if the file exists but is not a JSON object.
- One process per file: the lock is per `Store`, not across processes.

Runnable example: `example/main.py`. Test: `pytest`.
