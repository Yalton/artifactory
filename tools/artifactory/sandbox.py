"""Build bubblewrap command lines that confine a trial to its own directories.

The sandbox root is an empty tmpfs remounted read-only. On top of it go the
host system directories (read-only), any extra read-only binds, a private
/tmp, and the only two writable host paths: the trial's project and HOME.
Every path is bound at its host path, so absolute paths mean the same thing
inside and out. The environment is cleared and rebuilt from `env`.

Networking: the sandbox gets its own network namespace from pasta, with no
route back to the host: no host loopback services, no port forwarding either
way, and no abstract unix sockets (X11, D-Bus) since those are per network
namespace. Egress is an allowlist: before bwrap starts, an nftables output
chain in that namespace accepts loopback and TCP to each allowed address:port
and rejects everything else (other hosts, other ports, UDP, ICMP); outbound
IPv6 neighbor and router solicitations pass so allowed IPv6 endpoints work.
Callers pass the exact endpoints to allow. The harness passes `allowlist()` of
the llama server for the agent, which adds ARTIFACTORY_SANDBOX_ALLOW
(comma-separated IP:PORT, e.g. a local NuGet feed); it passes nothing for the
checker, which gets no network. There is no DNS: the host resolver socket is
not bound, so names do not resolve.

bwrap runs the command in a nested user namespace, so it holds no
capabilities over the network namespace (owned by pasta's user namespace) and
cannot change the rules or routes.
"""
from __future__ import annotations

import ipaddress
import os
from collections.abc import Iterable
from pathlib import Path

BWRAP = "/usr/bin/bwrap"
PASTA = "/usr/bin/pasta"
NFT = "/usr/sbin/nft"
ALLOW_ENV = "ARTIFACTORY_SANDBOX_ALLOW"
# --no-map-gw: the gateway address is not the host; -t/-u/-T/-U none: no port forwarding.
PASTA_ARGS = ["--config-net", "--no-map-gw", "--quiet", "-t", "none", "-u", "none", "-T", "none", "-U", "none"]
SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc")
SYSTEM_TRY_DIRS = ("/sys",)  # cgroup info for dotnet


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


def _endpoint(host: str, port: int | str) -> tuple[str, int]:
    addr = ipaddress.ip_address(host.strip().strip("[]"))  # an IP literal: nothing resolves names here
    if getattr(addr, "scope_id", None):
        raise ValueError(f"{host}: scoped IPv6 addresses are not allowed")
    port = int(port)
    if not 0 < port < 65536:
        raise ValueError(f"bad port {port}")
    return str(addr), port


def allowlist(allow: Iterable[tuple[str, int]] = ()) -> list[tuple[str, int]]:
    """`allow` plus the endpoints in $ARTIFACTORY_SANDBOX_ALLOW, as (ip, port)."""
    out = [_endpoint(h, p) for h, p in allow]
    for item in filter(None, (x.strip() for x in os.environ.get(ALLOW_ENV, "").split(","))):
        host, sep, port = item.rpartition(":")
        if not sep:
            raise ValueError(f"{ALLOW_ENV}: {item!r} is not IP:PORT")
        out.append(_endpoint(host, port))
    return list(dict.fromkeys(out))


def egress_ruleset(allow: Iterable[tuple[str, int]]) -> str:
    """nftables ruleset: loopback and TCP to each allowed endpoint; everything else is rejected at once."""
    rules = ['oif "lo" accept',
             "icmpv6 type { nd-neighbor-solicit, nd-router-solicit, nd-neighbor-advert } accept"]
    for host, port in allow:
        family = "ip" if ipaddress.ip_address(host).version == 4 else "ip6"
        rules.append(f"{family} daddr {host} tcp dport {port} accept")
    rules += ["meta l4proto tcp reject with tcp reset", "reject with icmpx type admin-prohibited"]
    body = "\n".join(f"    {r}" for r in rules)
    return ("table inet sandbox_egress {\n  chain out {\n    type filter hook output priority 0; policy drop;\n"
            f"{body}\n  }}\n}}\n")


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
                    rw_binds: list[Path] = (), allow: Iterable[tuple[str, int]] = ()) -> list[str]:
    """bwrap argv running `argv` in `cwd` (default: project); only project, home and rw_binds are writable.

    Network egress is limited to TCP to exactly the `allow` endpoints (ip, port); the default is none.
    """
    project, home = Path(project).resolve(), Path(home).resolve()
    for tool, why in ((PASTA, "it isolates the sandbox network from host services"),
                      (NFT, "it limits sandbox egress to the allowlist")):
        if not os.access(tool, os.X_OK):
            raise RuntimeError(f"{tool} not found; {why}")
    # Load the rules as root of pasta's namespaces, then exec bwrap; if nft fails, nothing runs.
    firewall = ["/bin/sh", "-c", f'printf "%s" "$0" | {NFT} -f - && exec "$@"', egress_ruleset([_endpoint(h, p) for h, p in allow])]
    args = [PASTA, *PASTA_ARGS, "--", *firewall, BWRAP, "--die-with-parent", "--unshare-user", "--unshare-pid",
            "--unshare-ipc", "--unshare-uts", "--new-session", "--tmpfs", "/"]
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
