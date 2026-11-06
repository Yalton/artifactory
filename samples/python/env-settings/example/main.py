"""Example: settings from MYAPP_* environment variables with defaults."""
from dataclasses import dataclass

import env_settings


@dataclass
class Settings:
    port: int = 8080
    greeting: str = "hello"
    debug: bool = False


def main() -> None:
    settings = env_settings.load(Settings, "MYAPP")
    print(settings)


if __name__ == "__main__":
    main()
