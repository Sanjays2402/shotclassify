"""Cross-category MAC-address extractor.

Hardware addresses surface in every category of screenshot --
terminal captures show ``ifconfig`` / ``ip link`` output, error
logs print the offending NIC (``device en0 [b8:e8:56:11:22:33]``),
network-config screenshots quote ARP / DHCP tables, support chats
paste router console output, and document captures of asset
inventories list device MACs. Rather than teach each per-category
extractor to find them, we run :func:`extract_macs` once on the OCR
text and stash the unique, order-preserving list under
``ExtractedFields.raw["macs"]`` so dashboards, routing rules, and
downstream agents have a single place to look.

Recognised shapes (EUI-48, the 48-bit Ethernet MAC):

* **Colon-separated**: ``00:11:22:33:44:55`` (the Unix / Cisco
  convention).
* **Dash-separated**: ``00-11-22-33-44-55`` (the Windows ``ipconfig``
  convention).
* **Dot-quad** (Cisco's three-group form): ``0011.2233.4455`` --
  three groups of four hex chars separated by dots.

Output canonical form: lowercase + colon-separated regardless of
which input shape was matched. ``00-11-22-33-44-55``,
``00:11:22:33:44:55``, ``0011.2233.4455``, and
``00:11:22:33:44:55`` all collapse to one entry.

Deliberately NOT matched:

* IPv6 addresses -- they also use colons, but they're never six
  pairs of two hex chars; the IPv6 extractor (``network.py``)
  handles them.
* The all-zero MAC (``00:00:00:00:00:00``) -- it's almost always a
  placeholder / default printed by uninitialised devices.
* The all-ones broadcast MAC (``ff:ff:ff:ff:ff:ff``) -- not an
  identifier of any specific device; including it bloats the list
  with broadcast addresses that appear in every ARP table.
* EUI-64 (64-bit) addresses -- rare in practice; would deserve their
  own extractor if a customer asks.

IPv6 spans are masked before scanning so a ``2001:db8::00:11:22:33``
suffix does not get carved up into a false-positive MAC.
"""
from __future__ import annotations

import re

# Colon-separated EUI-48: 6 pairs of 2 hex chars, ``:`` separated.
# Lookarounds reject hex on either side so we don't bite into the
# middle of a longer hex string. Case-insensitive because vendors
# print MACs in both cases.
_MAC_COLON_RE = re.compile(
    r"(?<![0-9A-Fa-f:])"
    r"(?P<m>[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})"
    r"(?![0-9A-Fa-f:])"
)

# Dash-separated EUI-48: Windows ipconfig form.
_MAC_DASH_RE = re.compile(
    r"(?<![0-9A-Fa-f\-])"
    r"(?P<m>[0-9A-Fa-f]{2}(?:-[0-9A-Fa-f]{2}){5})"
    r"(?![0-9A-Fa-f\-])"
)

# Cisco dot-quad: 3 groups of 4 hex chars separated by dots.
_MAC_DOTQUAD_RE = re.compile(
    r"(?<![0-9A-Fa-f.])"
    r"(?P<m>[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4}\.[0-9A-Fa-f]{4})"
    r"(?![0-9A-Fa-f.])"
)

# IPv6 spans we mask before scanning. We use a slightly looser shape
# than ``network.py`` because we only need to identify the spans to
# blank them out -- correctness of the IPv6 extractor itself is not
# our concern here. We REQUIRE a ``::`` or 7 colons so we don't bite
# into a normal colon-separated MAC.
_IPV6_MASK_RE = re.compile(
    r"(?<![\w:])"
    r"(?:"
    # Compressed double-colon form
    r"(?:[0-9A-Fa-f]{1,4}:){0,7}::?(?:[0-9A-Fa-f]{1,4})?(?::[0-9A-Fa-f]{1,4}){0,7}"
    r"|"
    # Full 8-group form -- never a MAC because MACs are only 6 groups.
    r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"
    r")"
    r"(?![\w:])"
)


_MAX_MACS = 50

# Reserved MACs we deliberately reject as placeholders / non-device
# identifiers. Canonical lowercase + colon-separated form.
_NULL_MAC = "00:00:00:00:00:00"
_BROADCAST_MAC = "ff:ff:ff:ff:ff:ff"


def _normalise(raw: str) -> str:
    """Drop separators, lowercase, then reinsert ``:`` every 2 chars."""
    hex_only = re.sub(r"[^0-9A-Fa-f]", "", raw).lower()
    return ":".join(hex_only[i : i + 2] for i in range(0, len(hex_only), 2))


def _is_ipv6_span(span: str) -> bool:
    """Tell whether a colon-separated hex run is actually an IPv6 span.

    We use this AS WELL AS the upfront IPv6 mask because some IPv6
    shapes (a full 8-group ``aaaa:bbbb:cccc:dddd:eeee:ffff:gggg:hhhh``
    with every group exactly 4 chars) don't satisfy the MAC regex
    anyway, but the compressed-form ``::1`` doesn't either; the mask
    catches both cleanly. This helper is reserved for a defensive
    re-check the day we widen the upfront mask.
    """
    return "::" in span or span.count(":") == 7


def _is_ipv6_like_pair(span: str) -> bool:
    """A six-group colon hex run that happens to be all-zeros sits
    inside the broader IPv6 space (``::`` = all zeros). Filtering
    this out via the null-MAC reject already handles it.
    """
    return span == _NULL_MAC


def extract_macs(text: str) -> list[str]:
    """Return unique MAC addresses found in ``text``.

    Output entries are in canonical form: lowercase + colon-separated
    regardless of which input shape (colon / dash / Cisco dot-quad)
    was matched. Preserves first-seen-in-text order. Caps the output
    at 50 entries. Rejects the all-zero placeholder MAC and the
    broadcast MAC because neither identifies a specific device.
    IPv6 spans are masked before scanning so the ``2001:db8::ff:ee``
    suffix of an IPv6 address does not false-positive as a MAC.
    """
    if not text or not isinstance(text, str):
        return []
    # Mask IPv6 spans first so a compressed IPv6 like
    # ``fe80::1ff:fe23:4567:890a`` doesn't get carved up.
    work = text
    for m in _IPV6_MASK_RE.finditer(text):
        span = m.group(0)
        # An eight-group IPv6 can never match a MAC regex (6 groups),
        # so blanking it only matters when the span is ``::``-y. But
        # we blank either way to keep the loop simple.
        if "::" in span or span.count(":") == 7:
            work = work[: m.start()] + (" " * (m.end() - m.start())) + work[m.end() :]

    seen: set[str] = set()
    out: list[str] = []
    candidates: list[tuple[int, str]] = []

    # Colon-separated -- canonical form, just lowercase.
    for m in _MAC_COLON_RE.finditer(work):
        candidates.append((m.start(), m.group("m").lower()))
    # Dash-separated -- normalise to colon-separated.
    for m in _MAC_DASH_RE.finditer(work):
        candidates.append((m.start(), _normalise(m.group("m"))))
    # Cisco dot-quad -- normalise to colon-separated.
    for m in _MAC_DOTQUAD_RE.finditer(work):
        candidates.append((m.start(), _normalise(m.group("m"))))

    # Source-text order so the list matches reading order.
    candidates.sort(key=lambda x: x[0])

    for _, canonical in candidates:
        if canonical in (_NULL_MAC, _BROADCAST_MAC):
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
        if len(out) >= _MAX_MACS:
            break
    return out


__all__ = ["extract_macs"]
