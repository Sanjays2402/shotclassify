"""Cross-category JWT extractor.

JSON Web Tokens (JWTs) show up everywhere screenshots get captured --
.env editors, terminal output where a developer pasted a Bearer
token to call an API, error logs that include the failing
``Authorization`` header, chat captures of API debugging, browser
DevTools captures of cookies / localStorage. We surface every JWT
found in the OCR text under ``ExtractedFields.raw["jwts"]`` so
dashboards and routing rules can spot leaked tokens (and pair this
with the existing ``jwt`` redact mode that strips the raw token
from the persisted OCR text).

Output shape: a list of ``{"alg", "typ", "kid", "iss", "sub",
"aud", "exp", "iat", "header_b64"}`` dicts. The first five keys
mirror the canonical JOSE header / common payload claims; the
last is the FULL base64url-encoded header segment so callers that
need the raw header can recover it without re-scanning. The
``kid`` (key ID), ``iss`` (issuer), ``sub`` (subject), ``aud``
(audience), ``exp`` (expiration), and ``iat`` (issued-at) claims
are pulled from the payload when present.

Security guarantee: the FULL JWT token is NEVER stored in the
output. We only persist the header + a short summary of the
payload's standard claims. The signature segment is completely
discarded. This pairs with the ``jwt`` redact mode in
``shotclassify_common.redact`` (which replaces the raw token with
``[REDACTED:jwt]`` before persistence) to give a complete
defence-in-depth posture: even if a tenant somehow forgets to
enable the redact mode, the extractor still does not leak the
secret signature.

Shape rules (mirror the existing redact regex so the two stay in
lockstep):

* Three base64url-encoded segments separated by ``.``.
* Header segment must start with ``eyJ`` (the base64url prefix
  for ``{"``) so a random three-dot-separated identifier doesn't
  misfire.
* Each segment must be at least 8 chars to keep us out of
  arbitrary dot-separated identifier territory.
* Word-boundary on the leading edge so a ``Bearer eyJ...``
  prelude doesn't bleed in -- and word-boundary on the trailing
  edge for the same reason.

Payload claims surfaced:

* ``iss`` (issuer) -- the entity that issued the token
* ``sub`` (subject) -- the entity the token is about
* ``aud`` (audience) -- the entity the token is for
* ``exp`` (expiration) -- as printed (integer seconds since epoch)
* ``iat`` (issued-at) -- as printed
* ``kid`` (header) -- key ID
* ``alg`` (header) -- signing algorithm
* ``typ`` (header) -- token type

Claims that are not present in the header / payload are omitted
from the dict so the output stays compact. The expiration and
issued-at timestamps are stored as their printed values (typically
integer seconds since epoch); we do NOT convert them to ISO strings
because the LLM consumer prefers the original numeric value for
arithmetic.

If the header is not parseable as JSON (corrupted / OCR-mangled),
the entry is skipped entirely -- we'd rather miss a JWT than emit
a half-formed entry. The same applies to the payload: a missing
or unparseable payload still yields an entry (with only the header
claims) provided the header decoded cleanly.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

# Three base64url segments separated by dots. The header must start
# with ``eyJ`` (the base64url prefix for ``{"``) so a random
# three-segment identifier doesn't false-positive. Each segment must
# be at least 8 chars to keep us out of arbitrary dot-separated
# identifier territory. The trailing word-boundary is on the side of
# the signature -- if a JWT is followed immediately by punctuation
# (``.`` / ``,`` / ``)``) the boundary fires.
#
# We allow trailing ``=`` / ``+`` / ``/`` chars in segments to be
# robust against tokens that use the older base64 alphabet (some
# legacy issuers do). Standard JWT uses base64url which forbids ``+``
# / ``/`` / ``=`` but real-world OCR captures sometimes have
# legitimate tokens that were originally base64-encoded.
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_=+/-]{8,}\.[A-Za-z0-9_=+/-]{8,}\.[A-Za-z0-9_=+/-]{8,}\b"
)


# Cap on number of JWTs returned per OCR text. A real screenshot
# rarely contains more than a handful; the cap is defensive.
_MAX_JWTS = 20

# Whitelist of payload claim names we surface. We deliberately do NOT
# surface arbitrary claims because a token's custom claims may carry
# PII (email, user_id, ...) that should stay inside the token boundary.
# The canonical JWT registered claims (RFC 7519 §4.1) plus the common
# ``email`` / ``name`` / ``preferred_username`` are intentionally NOT
# included for the same reason.
_PAYLOAD_CLAIMS = ("iss", "sub", "aud", "exp", "iat", "nbf", "jti")

# Whitelist of header claims we surface. ``alg`` (signing algorithm)
# and ``typ`` (token type) are the canonical JOSE header fields; we
# also surface ``kid`` (key ID) because dashboards routing on
# key-rotation status care about it.
_HEADER_CLAIMS = ("alg", "typ", "kid")


def _base64url_decode(segment: str) -> bytes | None:
    """Decode a base64url segment, returning None on failure.

    Pads the segment to a multiple of 4 chars (base64 requires the
    length to be a multiple of 4); accepts both base64url and
    standard-base64 alphabets so legacy tokens decode cleanly.
    """
    if not segment:
        return None
    # Pad to multiple of 4.
    pad = (-len(segment)) % 4
    s = segment + ("=" * pad)
    # Try base64url first (RFC 7515 standard); fall back to
    # standard base64 if the token was issued with the older
    # alphabet.
    try:
        return base64.urlsafe_b64decode(s)
    except (binascii.Error, ValueError):
        pass
    try:
        return base64.b64decode(s)
    except (binascii.Error, ValueError):
        return None


def _stringify_claim(value: Any) -> str | int | None:
    """Coerce a JSON-decoded claim value to str / int for storage.

    JWT claims are typically strings or numeric epoch timestamps. Lists
    (e.g. ``aud`` can be a list of audiences) collapse to comma-joined
    string. Objects / nested structures are rejected to keep the output
    compact.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        # JSON true/false -- store as 1/0 to avoid downstream type
        # confusion. ``exp`` / ``iat`` are never bool in practice; this
        # is a defensive coercion.
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # Whole-number floats collapse to int (common for epoch
        # timestamps that JSON parsed as float because of trailing .0).
        if value.is_integer():
            return int(value)
        return str(value)
    if isinstance(value, str):
        # Bound the captured string -- a JWT issuer URL can be long but
        # never longer than a reasonable URL. We cap defensively.
        if len(value) > 256:
            return value[:256]
        return value
    if isinstance(value, list):
        # Coerce each entry to its string form, comma-join.
        parts: list[str] = []
        for entry in value:
            if isinstance(entry, str):
                parts.append(entry)
            elif isinstance(entry, (int, float)):
                parts.append(str(entry))
            # Skip nested objects.
        if not parts:
            return None
        joined = ",".join(parts)
        if len(joined) > 256:
            return joined[:256]
        return joined
    # Dict / other -- reject.
    return None


def extract_jwts(text: str) -> list[dict[str, Any]]:
    """Return decoded JWT summaries found in ``text``.

    Output is a list of dicts, one per unique JWT, preserving
    first-seen order. Each dict contains:

    * ``alg``, ``typ``, ``kid`` -- from the JOSE header (when present)
    * ``iss``, ``sub``, ``aud``, ``exp``, ``iat``, ``nbf``, ``jti`` --
      from the payload (when present)
    * ``header_b64`` -- the raw base64url header segment for callers
      that need to recover the original header

    The full token (header.payload.signature) is intentionally NOT
    stored in the output. The signature segment is discarded
    entirely; this is a tested security guarantee.

    A JWT whose header is not parseable as JSON is skipped --
    we'd rather miss a candidate than emit a half-formed entry.
    A JWT whose payload is missing or unparseable still emits a
    summary (with only the header fields and ``header_b64``)
    provided the header decoded cleanly.

    De-duplicates on the full token shape (header.payload.signature)
    so a JWT printed twice in the same screenshot collapses to one
    entry. Capped at 20 entries (defensive -- real screenshots
    contain at most a handful).
    """
    if not text or not isinstance(text, str):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in _JWT_RE.finditer(text):
        token = m.group(0)
        if token in seen:
            continue
        seen.add(token)
        header_b64, payload_b64, _sig_b64 = token.split(".", 2)
        header_bytes = _base64url_decode(header_b64)
        if header_bytes is None:
            continue
        try:
            header = json.loads(header_bytes)
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            # Header failed to decode -- skip this token entirely.
            continue
        if not isinstance(header, dict):
            continue
        entry: dict[str, Any] = {}
        for key in _HEADER_CLAIMS:
            if key in header:
                v = _stringify_claim(header[key])
                if v is not None:
                    entry[key] = v
        # Always preserve the original header_b64 segment so callers
        # that need the raw header (e.g. forensic analysis) can
        # recover it without re-running the matcher.
        entry["header_b64"] = header_b64
        # Payload decode is best-effort; an unparseable payload still
        # leaves the header fields populated.
        payload_bytes = _base64url_decode(payload_b64)
        if payload_bytes is not None:
            try:
                payload = json.loads(payload_bytes)
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                payload = None
            if isinstance(payload, dict):
                for key in _PAYLOAD_CLAIMS:
                    if key in payload:
                        v = _stringify_claim(payload[key])
                        if v is not None:
                            entry[key] = v
        out.append(entry)
        if len(out) >= _MAX_JWTS:
            break
    return out


__all__ = ["extract_jwts"]
