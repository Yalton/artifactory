"""Example: store and fetch a value in a JSON file."""
import tempfile
from pathlib import Path

import json_kv


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = json_kv.open(Path(tmp) / "data.json")
        added = store.put_if_absent("greeting", "hello")
        print(added, store.get("greeting"))


if __name__ == "__main__":
    main()
