"""Cross-category IP / port / network extractor.

Network endpoints show up in every category of screenshot -- error
stacktraces print the service that refused the connection, code
snippets bind to ``0.0.0.0:8080``, terminal screenshots paste ``ssh
host:22`` lines, documents quote firewall rules, chat captures share
``redis://prod-cache:6379`` URIs. Rather than teach each per-category
extractor to find network endpoints, we run :func:`extract_network`
once on the OCR text and stash the unique, order-preserving list
under ``ExtractedFields.raw["network"]`` so dashboards, routing
rules, and downstream agents have a single place to look.

Recognised shapes:

* **IPv4 with optional port**: ``1.2.3.4``, ``10.0.0.1:8080``,
  ``192.168.1.255:65535``. Octets are bounded to ``0..255`` so a
  semver like ``3.11.5`` cannot match, and a malformed ``300.1.1.1``
  is rejected too.
* **IPv6 with optional port**: ``2001:db8::1``, ``::1``,
  ``[fe80::1]:443`` (bracketed form when a port is present, which is
  the convention because raw IPv6 contains colons).
* **host:port**: ``example.com:8080``, ``redis.internal:6379``,
  ``localhost:3000``. The host must contain a letter (so a bare
  ``42:443`` is not a host:port endpoint) and ports are bounded to
  ``1..65535``.

Deliberately NOT matched:

* Bare hostnames without a port (``example.com``) -- too many false
  positives in receipts and OCR noise. The URL extractor already
  captures hostnames embedded in URLs.
* Mac / hardware addresses (``00:11:22:33:44:55``) -- different
  semantic class; would deserve its own extractor.
* URLs (``http://...``) -- already covered by the URL extractor.
  URL spans are masked out before scanning so a URL's host:port
  component does not double-count.
"""
from __future__ import annotations

import re

# IPv4 octet: 0..255 with a no-leading-zero exception for "0" itself.
_IPV4_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4 = rf"(?<![\d.])(?:{_IPV4_OCTET}\.){{3}}{_IPV4_OCTET}(?!\d)"
_IPV4_PORT = rf"(?P<ipv4>{_IPV4})(?::(?P<ipv4_port>\d{{1,5}}))?"
_IPV4_RE = re.compile(_IPV4_PORT)

# IPv6 raw form. Conservative: at least one ``::`` or eight ``:``
# separated groups. We accept the compressed form ``::1`` and the
# embedded-v4 form ``::ffff:192.0.2.1`` is matched as IPv4 (acceptable
# loss of precision). Bracketed form ``[addr]:port`` is checked first
# because the brackets make port parsing unambiguous.
_IPV6_GROUP = r"[0-9A-Fa-f]{1,4}"
_IPV6_RE = re.compile(
    r"(?<![\w:])"
    r"(?P<ipv6>"
    # Full eight-group form: a:b:c:d:e:f:g:h
    rf"(?:{_IPV6_GROUP}:){{7}}{_IPV6_GROUP}"
    # Compressed double-colon form. At least one digit/letter group on
    # one side and the ``::`` separator; matches ``::1`` and
    # ``2001:db8::1`` and ``fe80::1`` etc.
    rf"|(?:{_IPV6_GROUP}:){{1,6}}:(?:{_IPV6_GROUP})?"
    rf"|(?:{_IPV6_GROUP}:){{0,6}}::{_IPV6_GROUP}(?::{_IPV6_GROUP}){{0,6}}"
    rf"|::{_IPV6_GROUP}(?::{_IPV6_GROUP}){{0,6}}"
    rf"|::"
    r")"
    r"(?![\w:])"
)
_IPV6_BRACKETED_RE = re.compile(
    r"\[(?P<addr>[0-9A-Fa-f:]+)\]:(?P<port>\d{1,5})"
)

# host:port for DNS-style hosts. Requires the host segment to contain
# at least one letter so ``42:443`` (numeric only) doesn't match as a
# host:port pair. Disallows a leading digit on the first label to be
# extra strict with hostnames.
_HOSTPORT_RE = re.compile(
    r"(?<![\w.:-])"
    r"(?P<host>(?=[A-Za-z\-]*[A-Za-z])"
    r"[A-Za-z0-9](?:[A-Za-z0-9\-]{0,62}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,62}[A-Za-z0-9])?)*)"
    r":(?P<port>\d{1,5})"
    r"(?![\w.])"
)


_MAX_ENDPOINTS = 50


def _valid_port(s: str) -> bool:
    try:
        n = int(s)
    except ValueError:
        return False
    return 1 <= n <= 65535


def extract_network(text: str) -> list[str]:
    """Return unique network endpoints (IPv4 / IPv6 / host:port) found
    in ``text``.

    Preserves first-seen order across all matchers. Each entry is
    formatted as it appeared in the source text (modulo IPv6 bracket
    normalisation). URL spans are masked out before scanning so a
    URL's authority component does not double-count under both
    ``raw["urls"]`` and ``raw["network"]``. The output is capped at
    50 entries to bound memory.
    """
    if not text or not isinstance(text, str):
        return []
    # Mask URLs before scanning. The URL extractor already captures
    # them under raw["urls"]; we don't want the same authority to
    # appear under both keys.
    masked = re.sub(
        r"\bhttps?://\S+", lambda m: " " * len(m.group(0)), text, flags=re.IGNORECASE
    )

    seen: set[str] = set()
    out: list[str] = []

    # Track the byte spans we've already consumed so the IPv4 and the
    # host:port matchers don't double-match the same substring. The
    # host:port regex would also match ``1.2.3.4:80`` if we let it run
    # over an already-consumed IPv4 span (the rightmost octet looks
    # like a hostname segment). We mask consumed spans with spaces.
    work = masked

    def _consume(start: int, end: int) -> None:
        nonlocal work
        work = work[:start] + (" " * (end - start)) + work[end:]

    # 1) Bracketed IPv6 with port -- check FIRST because the brackets
    #    make port parsing unambiguous and we want
    #    ``[2001:db8::1]:443`` to land as a single endpoint.
    for m in list(_IPV6_BRACKETED_RE.finditer(work)):
        addr = m.group("addr")
        port = m.group("port")
        if not _valid_port(port):
            continue
        # Validate that addr looks like IPv6 (has ``:`` and only hex).
        if ":" not in addr:
            continue
        ep = f"[{addr}]:{port}"
        if ep not in seen and len(out) < _MAX_ENDPOINTS:
            seen.add(ep)
            out.append(ep)
        _consume(m.start(), m.end())

    # 2) IPv4 (with optional port).
    for m in list(_IPV4_RE.finditer(work)):
        ipv4 = m.group("ipv4")
        port = m.group("ipv4_port")
        if port is not None and not _valid_port(port):
            # Bad port -> still record the bare IPv4 (port was a noise
            # tail, e.g. a line number).
            ep = ipv4
            end = m.start() + len(ipv4)
        else:
            ep = ipv4 if port is None else f"{ipv4}:{port}"
            end = m.end()
        if ep not in seen and len(out) < _MAX_ENDPOINTS:
            seen.add(ep)
            out.append(ep)
        _consume(m.start(), end)

    # 3) Raw IPv6 (no brackets / no port). Run AFTER IPv4 so an
    #    embedded-v4 like ``::ffff:1.2.3.4`` doesn't get partly
    #    consumed as IPv4 and leave a malformed IPv6 remainder.
    for m in list(_IPV6_RE.finditer(work)):
        addr = m.group("ipv6")
        # Reject single-group spans that the relaxed regex might catch
        # (e.g. a single ``::`` with nothing around it) -- require at
        # least one hex digit somewhere.
        if not re.search(r"[0-9A-Fa-f]", addr):
            continue
        # Reject single-segment forms that are clearly not addresses
        # (we want at least two segments OR a `::`).
        if "::" not in addr and ":" not in addr:
            continue
        if addr not in seen and len(out) < _MAX_ENDPOINTS:
            seen.add(addr)
            out.append(addr)
        _consume(m.start(), m.end())

    # 4) Generic host:port (DNS hostnames + IPs that the masking above
    #    couldn't catch because they were embedded oddly).
    for m in list(_HOSTPORT_RE.finditer(work)):
        host = m.group("host")
        port = m.group("port")
        if not _valid_port(port):
            continue
        ep = f"{host}:{port}"
        if ep not in seen and len(out) < _MAX_ENDPOINTS:
            seen.add(ep)
            out.append(ep)

    return out


__all__ = ["extract_network"]
