"""SSRF protection — validate URLs and IPs before forwarding."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Default allowed protocols
DEFAULT_ALLOWED_PROTOCOLS = ("http", "https")

# Well-known private/reserved ranges
_PRIVATE_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


class SSRFError(Exception):
    """Raised when a URL or IP is blocked by SSRF protection."""


def is_private_ip(ip_address: str) -> bool:
    """Check if an IP address falls in a private/reserved range.

    Private ranges:
    - 127.0.0.0/8, ::1
    - 10.0.0.0/8
    - 172.16.0.0/12
    - 192.168.0.0/16
    - 169.254.0.0/16 (link-local)
    - 0.0.0.0/8
    - 100.64.0.0/10 (CGNAT)
    """
    try:
        ip = ipaddress.ip_address(ip_address)
    except ValueError:
        return False
    for net in _PRIVATE_RANGES:
        if ip in net:
            return True
    return False


def resolve_and_check(hostname: str) -> tuple[bool, str | None]:
    """Resolve hostname to IP(s) and check against private ranges.

    Re-resolves on every call to prevent DNS rebinding attacks.
    Returns (is_safe, reason).
    """
    try:
        addrs = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, f"Could not resolve hostname: {hostname}"

    seen = set()
    for addr in addrs:
        ip_str = addr[4][0]
        if ip_str in seen:
            continue
        seen.add(ip_str)
        if is_private_ip(ip_str):
            return False, f"Resolved to private IP: {ip_str}"

    return True, None


def validate_target_url(
    url: str,
    allow_private: bool = False,
    allowed_protocols: tuple | None = None,
) -> tuple[bool, str | None]:
    """Validate a target URL against SSRF protections.

    Returns (is_valid, reason). If valid, reason is None.
    If blocked, reason describes why.

    Checks performed:
    - Protocol must be in allowed_protocols (default: http, https)
    - Hostname resolved to IP must not be in private ranges
    - Port must not be a system port (< 1024)
    """
    if allowed_protocols is None:
        allowed_protocols = DEFAULT_ALLOWED_PROTOCOLS

    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Invalid URL: {e}"

    if not parsed.scheme:
        return False, "No protocol specified"

    if parsed.scheme not in allowed_protocols:
        return False, (
            f"Protocol '{parsed.scheme}' not allowed. "
            f"Allowed: {', '.join(allowed_protocols)}"
        )

    if parsed.port is not None and parsed.port < 1024:
        return False, f"Port {parsed.port} is a system port (< 1024)"

    hostname = parsed.hostname or ""
    if allow_private:
        return True, None

    return resolve_and_check(hostname)
