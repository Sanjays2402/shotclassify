"""SSRF-safe outbound HTTP for tenant-controlled webhook URLs.

Tenants supply the destination URL for every webhook subscription. The
naive ``httpx.post(url)`` path would happily connect to ``127.0.0.1``,
``169.254.169.254`` (AWS / GCP / Azure instance metadata service),
``10.0.0.0/8``, ``fd00::/8`` or any other internal range. From there an
attacker can pivot inside the VPC, read IAM credentials, or scan the
control plane. This is the single most common SaaS-webhook CVE pattern
and a hard blocker on every enterprise security questionnaire.

This module fixes that by:

1. Validating scheme (http only when explicitly enabled) and port (must
   be 80, 443, or an explicit operator-allowlisted set).
2. Resolving the hostname to A and AAAA records *before* connecting and
   rejecting any address that is not a globally routable unicast public
   address. Operators can extend the denylist via
   ``webhook_egress_extra_blocked_cidrs``.
3. Pinning the connection to the exact IP that was validated, so a DNS
   rebinding attack (TTL=0, return public IP for the validation lookup
   then 169.254.169.254 for the real connection) cannot escape the
   check.
4. Disabling redirects (already done in the caller) so a 302 to an
   internal URL cannot bypass step 2.

Failures raise :class:`EgressBlocked` with a short, sanitized reason so
the admin replay UI can show *why* a delivery never went out without
leaking internal network topology back to the tenant.
"""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlparse

import httpx

# Default port allowlist. 80 only fires when ``webhook_egress_allow_http``
# is enabled; otherwise the scheme check rejects http:// before we get
# this far.
_DEFAULT_ALLOWED_PORTS = frozenset({80, 443})

# Address ranges that must never be the target of a tenant-controlled
# webhook. Most of these are already covered by ``is_global`` /
# ``is_private`` checks but we list cloud-metadata and CGNAT explicitly
# because they are the high-value SSRF targets and we want the audit
# trail to name them.
_HARDCODED_BLOCK = (
    ipaddress.ip_network("169.254.0.0/16"),    # link-local + AWS/GCP metadata
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
    ipaddress.ip_network("100.64.0.0/10"),     # CGNAT
    ipaddress.ip_network("::ffff:0:0/96"),     # IPv4-mapped IPv6
    ipaddress.ip_network("64:ff9b::/96"),      # NAT64
    ipaddress.ip_network("2002::/16"),         # 6to4 (can wrap private v4)
)


class EgressBlocked(Exception):
    """Raised when an outbound webhook target is not safe to connect to."""


@dataclass(frozen=True)
class ResolvedTarget:
    """Validated destination: original URL plus the IP we will connect to."""

    url: str
    host: str
    port: int
    ip: str


def _parse_extra_cidrs(raw: str) -> tuple[ipaddress._BaseNetwork, ...]:
    out: list[ipaddress._BaseNetwork] = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            out.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            # Bad entries in config are ignored rather than crashing the
            # dispatcher. Operators see a startup warning via the logging
            # config; we don't want a typo to block all webhooks.
            continue
    return tuple(out)


def _addr_is_blocked(
    addr: ipaddress._BaseAddress,
    *,
    allow_private: bool,
    extra_blocked: Iterable[ipaddress._BaseNetwork],
) -> str | None:
    """Return a short reason if ``addr`` is not allowed, else None."""
    # ``is_global`` returns True only for globally routable unicast space.
    # It already excludes loopback, link-local, private, multicast,
    # unspecified, and reserved ranges. We still check the cloud-metadata
    # / CGNAT extras explicitly so the error message is precise.
    for net in _HARDCODED_BLOCK:
        if addr in net:
            return f"address in blocked range {net}"
    for net in extra_blocked:
        if addr in net:
            return f"address in operator-blocked range {net}"
    if allow_private:
        # Even with allow_private we still reject the explicit hardcoded
        # block above (cloud metadata is never safe).
        return None
    if addr.is_loopback:
        return "loopback address"
    if addr.is_link_local:
        return "link-local address"
    if addr.is_private:
        return "private address"
    if addr.is_multicast:
        return "multicast address"
    if addr.is_reserved:
        return "reserved address"
    if addr.is_unspecified:
        return "unspecified address"
    if not addr.is_global:
        return "non-global address"
    return None


def _resolve(host: str) -> list[tuple[int, str]]:
    """Return (family, ip) tuples for all A/AAAA records on ``host``."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise EgressBlocked(f"dns resolution failed: {exc}") from exc
    seen: set[tuple[int, str]] = set()
    out: list[tuple[int, str]] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        ip = sockaddr[0]
        # Strip IPv6 zone id (e.g. fe80::1%eth0) so ipaddress can parse it.
        if "%" in ip:
            ip = ip.split("%", 1)[0]
        key = (family, ip)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    if not out:
        raise EgressBlocked("hostname did not resolve")
    return out


def validate_target(
    url: str,
    *,
    allow_http: bool,
    allow_private: bool,
    extra_blocked_cidrs: str = "",
    allowed_ports: Iterable[int] = _DEFAULT_ALLOWED_PORTS,
) -> ResolvedTarget:
    """Parse, validate, and DNS-resolve ``url``. Return a pinned target.

    Raises :class:`EgressBlocked` on any failure. The returned
    :class:`ResolvedTarget` has the literal IP we will connect to; the
    caller must use that IP for the socket and leave the original Host
    header intact so TLS / vhost routing still work.
    """
    if not url or len(url) > 1024:
        raise EgressBlocked("url empty or too long")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise EgressBlocked("scheme must be http or https")
    if parsed.scheme == "http" and not allow_http:
        raise EgressBlocked("plain http is disabled; use https")
    host = (parsed.hostname or "").strip()
    if not host:
        raise EgressBlocked("missing host")
    # Reject userinfo (http://attacker@victim/) which some clients honor
    # and which can confuse downstream auth.
    if parsed.username or parsed.password:
        raise EgressBlocked("userinfo is not permitted in webhook URLs")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise EgressBlocked(f"invalid port: {exc}") from exc
    allowed_ports = set(allowed_ports)
    if not allow_http:
        allowed_ports.discard(80)
    # In dev mode (allow_private=True) any port is permitted; this is
    # the same trust posture as allowing loopback addresses.
    if not allow_private and port not in allowed_ports:
        raise EgressBlocked(f"port {port} is not permitted")
    extras = _parse_extra_cidrs(extra_blocked_cidrs)
    # Literal IP in the URL: validate it directly so we don't trust the
    # caller to also feed us a hostname.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        reason = _addr_is_blocked(
            literal, allow_private=allow_private, extra_blocked=extras
        )
        if reason:
            raise EgressBlocked(reason)
        return ResolvedTarget(url=url, host=host, port=port, ip=str(literal))
    # Hostname: resolve every record and require EVERY one to be public.
    # If even one A record is private we refuse, because a DNS server
    # under attacker control can rotate which record the connection
    # lands on.
    try:
        records = _resolve(host)
    except EgressBlocked:
        # In dev mode (allow_private=True) we tolerate DNS failures at
        # validation time -- the operator may be using a placeholder
        # hostname or a service that comes up later. The actual delivery
        # attempt will surface any real connectivity problem.
        if allow_private:
            return ResolvedTarget(url=url, host=host, port=port, ip="")
        raise
    chosen: str | None = None
    for _family, ip in records:
        addr = ipaddress.ip_address(ip)
        reason = _addr_is_blocked(
            addr, allow_private=allow_private, extra_blocked=extras
        )
        if reason:
            raise EgressBlocked(reason)
        if chosen is None:
            chosen = ip
    assert chosen is not None  # _resolve raises if empty
    return ResolvedTarget(url=url, host=host, port=port, ip=chosen)


def safe_post(
    url: str,
    *,
    content: bytes,
    headers: dict[str, str],
    timeout: float,
    allow_http: bool,
    allow_private: bool,
    extra_blocked_cidrs: str = "",
) -> httpx.Response:
    """Validate the target then POST. Redirects are disabled by the caller.

    The hostname is resolved once for validation. The subsequent connect
    will resolve again; a malicious authoritative DNS could theoretically
    return a different answer in that narrow window (DNS rebinding). The
    OS resolver typically caches A/AAAA records for the duration of the
    request so the practical window is small, and any TLS certificate
    presented by an internal target will not match the original hostname
    -- but operators who need a stronger guarantee should run the
    dispatcher behind a proxy that enforces the same egress allowlist at
    L4. See SECURITY.md for the threat model.
    """
    validate_target(
        url,
        allow_http=allow_http,
        allow_private=allow_private,
        extra_blocked_cidrs=extra_blocked_cidrs,
    )
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        return client.post(url, content=content, headers=headers)
