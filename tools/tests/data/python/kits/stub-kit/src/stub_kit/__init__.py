"""A stand-in kit for checker tests: prints its liveness marker on import."""

print("[stub-kit] live", flush=True)


def greet(name: str) -> str:
    return f"hello, {name}"
