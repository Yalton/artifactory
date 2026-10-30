"""Build bubblewrap command lines that confine a trial to its own directories.

The sandbox root is an empty tmpfs remounted read-only. On top of it go the
host system directories (read-only), any extra read-only binds, a private
/tmp, and the only two writable host paths: the trial's project and HOME.
Every path is bound at its host path, so absolute paths mean the same thing
inside and out. The environment is cleared and rebuilt from `env`.

Networking: the sandbox gets its own network namespace from pasta, with
outbound connections (the LAN llama server, package feeds) but no route back
to the host: no host loopback services, no port forwarding either way, and no
abstract unix sockets (X11, D-Bus) since those are per network namespace.
"""
from __future__ import annotations

import os
from pathlib import Path

BWRAP = "/usr/bin/bwrap"
PASTA = "/usr/bin/pasta"
# --no-map-gw: the gateway address is not the host; -t/-u/-T/-U none: no port forwarding.
PASTA_ARGS = ["--config-net", "--no-map-gw", "--quiet", "-t", "none", "-u", "none", "-T", "none", "-U", "none"]
SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")
SYSTEM_TRY_DIRS = ("/run/systemd/resolve", "/sys")  # DNS stub resolver; cgroup info for dotnet


def _system_args() -> list[str]:
    args: list[str] = []
    for d in SYSTEM_DIRS:
        if os.path.islink(d):
            args += ["--symlink", os.readlink(d), d]
        elif os.path.isdir(d):
            args += ["--ro-bind", d, d]
    for d in SYSTEM_TRY_DIRS:
        args += ["--ro-bind-try", d, d]
    return args


def with_real_paths(paths: list[Path]) -> list[Path]:
    """Each path plus its resolved target, so symlinked binds work both ways."""
    out: list[Path] = []
    for p in paths:
        p = Path(os.path.abspath(p))
        for q in (p, p.resolve()):
            if q not in out:
                out.append(q)
    return out


def sandbox_command(project: Path, home: Path, ro_binds: list[Path], argv: list[str],
                    env: dict[str, str], cwd: Path | None = None,
                    rw_binds: list[Path] = ()) -> list[str]:
    """bwrap argv running `argv` in `cwd` (default: project); only project, home and rw_binds are writable."""
    project, home = Path(project).resolve(), Path(home).resolve()
    if not os.access(PASTA, os.X_OK):
        raise RuntimeError(f"{PASTA} not found; it isolates the sandbox network from host services")
    args = [PASTA, *PASTA_ARGS, "--", BWRAP, "--die-with-parent", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
            "--new-session", "--tmpfs", "/"]
    args += _system_args()
    args += ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
    # Read-only binds before writable ones: a writable path nested in a
    # read-only bind (the trial dir under the repo) must win.
    for p in with_real_paths(list(ro_binds)):
        args += ["--ro-bind", str(p), str(p)]
    for p in [project, home, *(Path(r).resolve() for r in rw_binds)]:
        args += ["--bind", str(p), str(p)]
    args += ["--remount-ro", "/", "--clearenv"]
    for k, v in env.items():
        args += ["--setenv", k, v]
    args += ["--chdir", str(cwd or project), "--", *argv]
    return args
