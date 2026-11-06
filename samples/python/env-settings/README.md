# env-settings

Fills a dataclass from environment variables, an optional `KEY=value` file and the dataclass defaults. Do not read `os.environ` or `os.getenv` yourself.

Install: `pip install "env-settings @ git+ssh://git@repo.billbert.co/artifactory/env-settings.git@v0.1.0"` (offline, with `PIP_FIND_LINKS` or `UV_FIND_LINKS` set: `pip install "env-settings==0.1.0"`)

Importing `env_settings` prints `[env-settings] live` once. There is no setup step.

## Wiring

```python
from dataclasses import dataclass

import env_settings


@dataclass
class Settings:
    port: int = 8080
    data: str = "data.json"
    debug: bool = False


settings = env_settings.load(Settings, "MYAPP")
# settings.port comes from MYAPP_PORT, else PORT=... in the file, else 8080.
```

## Notes

- For each field, the value comes from, in order: the environment variable `<PREFIX>_<FIELD>` (field name in upper case), the line `<FIELD>=value` in `file`, the field default.
- `load(Settings, "MYAPP", file="app.env")` also reads that file. A missing file is ignored. Blank lines and lines starting with `#` are skipped.
- Supported field types: `str`, `int`, `float`, `bool` (`1/true/yes/on`, `0/false/no/off`) and `pathlib.Path`.
- A field with no default and no value, a value that does not convert, or a malformed file line raises `env_settings.SettingsError` naming the variable.
- `environ=` takes a mapping instead of `os.environ`, for tests.

Runnable example: `example/main.py`. Test: `pytest`.
