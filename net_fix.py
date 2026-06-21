"""
Local environment workaround: Python's getaddrinfo fails on this machine
(resolv.conf advertises an IPv6 link-local nameserver from a phone hotspot,
which CPython's resolver can't use), even though curl/pip/system tools resolve
fine. Without this, every hydra_db SDK call dies with:
    httpx.ConnectError: [Errno 8] nodename nor servname provided, or not known

Fix: resolve the API host via the system resolver (curl) once, then pin that
hostname -> IP at the socket layer. TLS SNI and the HTTP Host header still use
the real hostname, so this is transparent and certificate validation is intact.

This is a dev-machine quirk, not part of the product. Import it before
constructing the HydraDB client:  `import net_fix; net_fix.install()`
"""

import socket
import subprocess

# All external hosts the app talks to; CPython can't resolve any of them on the
# dev machine, so each must be pinned.
DEFAULT_HOSTS = ("api.hydradb.com", "openrouter.ai")
_installed = False


def _resolve_via_system(host: str) -> str | None:
    try:
        ip = subprocess.run(
            ["curl", "-sS", "-m", "15", "-o", "/dev/null",
             "-w", "%{remote_ip}", f"https://{host}/"],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        return ip or None
    except Exception:
        return None


def install(hosts: tuple[str, ...] = DEFAULT_HOSTS) -> dict[str, str]:
    """Pin the given hostnames to their system-resolved IPs. Idempotent."""
    global _installed
    pins: dict[str, str] = {}
    for h in hosts:
        ip = _resolve_via_system(h)
        if ip:
            pins[h] = ip
    if _installed or not pins:
        return pins

    _orig = socket.getaddrinfo

    def _patched(host, *args, **kwargs):
        return _orig(pins.get(host, host), *args, **kwargs)

    socket.getaddrinfo = _patched
    _installed = True
    return pins
