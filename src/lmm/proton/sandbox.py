"""Network isolation for launching a game (or a modding tool in its
prefix) with zero outbound network access.

Uses Linux network namespaces via bubblewrap rather than packet
filtering (iptables/nftables rules keyed on a UID or cgroup). A fresh
network namespace has no interfaces in it at all - not even loopback,
unless explicitly configured - so nothing spawned inside it can make any
outbound connection, no matter what the game, Proton, DXVK's shader
cache uploader, or any other child process tries. That's a kernel-level
guarantee rather than a filter that a new process could slip past.
"""
from __future__ import annotations

import shutil


class NetworkIsolationUnavailable(RuntimeError):
    pass


def bwrap_available() -> bool:
    return shutil.which("bwrap") is not None


def wrap_command(cmd: list[str]) -> list[str]:
    """Wraps ``cmd`` so it runs with no network access at all.

    Raises NetworkIsolationUnavailable if bubblewrap isn't installed.
    Deliberately does not fall back to running ``cmd`` unwrapped in that
    case - silently skipping isolation that was explicitly requested
    would defeat the entire point of asking for it.

    ``--dev-bind / /`` gives the sandbox the exact same filesystem view
    as the host (so X11/Wayland sockets, GPU device nodes, audio, and
    the game's own files all keep working normally) - the only thing
    ``--unshare-net`` changes is that there is no network.
    """
    if not bwrap_available():
        raise NetworkIsolationUnavailable(
            "bubblewrap (the 'bwrap' command, package 'bubblewrap') is not "
            "installed. Refusing to launch without it rather than silently "
            "launching with network access after isolation was requested."
        )
    return [
        "bwrap",
        "--unshare-net",
        "--die-with-parent",
        "--dev-bind", "/", "/",
        "--",
        *cmd,
    ]
