"""
Team JB Downloader Bot — URL security helpers.

Blocks SSRF attempts (private IPs, loopback, cloud metadata endpoints) and
non-HTTP schemes before any download begins.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class UnsafeURLError(ValueError):
    """Raised when a URL fails security validation."""


_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {80, 443, 8080, 8443}


def validate_url(url: str) -> str:
    """
    Validate a user-submitted URL for safety. Returns the URL unchanged if safe.

    Raises UnsafeURLError with a user-facing reason otherwise.
    """
    if not url or not isinstance(url, str):
        raise UnsafeURLError("Empty or invalid URL.")

    url = url.strip()
    if len(url) > 2048:
        raise UnsafeURLError("URL is too long.")

    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f"Unsupported URL scheme: {parsed.scheme or 'none'}. Only http and https are allowed."
        )

    if not parsed.hostname:
        raise UnsafeURLError("URL has no hostname.")

    # Reject explicit credentials in the URL (often used for phishing).
    if parsed.username or parsed.password:
        raise UnsafeURLError("URLs with embedded credentials are not allowed.")

    # Resolve the hostname and check every returned IP.
    try:
        hostname = parsed.hostname
        # If the hostname is already an IP literal, this resolves to itself.
        addr_infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise UnsafeURLError("Could not resolve the URL hostname.")

    for info in addr_infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise UnsafeURLError("URL resolved to an invalid address.")

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            logger.warning("Blocked SSRF attempt: url=%s resolved_to=%s", url, ip_str)
            raise UnsafeURLError(
                "This URL resolves to a private or reserved address and cannot be downloaded."
            )

        # Explicitly block the AWS/GCP/Azure metadata endpoint.
        if str(ip) == "169.254.169.254":
            logger.warning("Blocked metadata endpoint: url=%s", url)
            raise UnsafeURLError("This URL points to a metadata endpoint and is blocked.")

    # Restrict ports. Allow default ports implicitly.
    port = parsed.port
    if port is not None and port not in _ALLOWED_PORTS:
        raise UnsafeURLError(
            f"Port {port} is not allowed. Allowed ports: 80, 443, 8080, 8443."
        )

    return url


def is_probably_url(text: str) -> bool:
    """Quick check whether a message text looks like a URL."""
    if not text:
        return False
    lowered = text.strip().lower()
    return lowered.startswith(("http://", "https://"))
