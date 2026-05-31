"""RFC 9116 security.txt and related /.well-known endpoints.

Enterprise procurement scans (and a growing number of bug-bounty
crawlers, e.g. HackerOne, Intigriti, BugCrowd) look for
``/.well-known/security.txt`` on every target host. A missing file is
flagged as a finding on most third-party risk questionnaires
(SIG/CAIQ, Whistic, OneTrust, Vanta-driven reviews) and routinely
delays SOC2 readiness audits. This module serves the file directly
from the API tier so it is reachable on whatever host the buyer
points their scanner at.

The response is intentionally unauthenticated, exempt from the IP
allowlist and rate limiter (registered in middleware), and served
with ``Content-Type: text/plain; charset=utf-8`` as required by
RFC 9116 section 2.3. ``Expires`` is recomputed on every request from
``security_expires_days`` so operators do not have to ship a new
build to refresh the rolling expiry date.

If ``security_contact`` is not configured the endpoint returns 404,
mirroring the behaviour of a host that simply does not publish a
file, instead of returning a misleading stub.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Response
from shotclassify_common import get_settings

router = APIRouter(tags=["well-known"])


# RFC 9116 section 2.5.10: Expires MUST be in UTC, ISO 8601 with a
# trailing ``Z``. We clamp the configured horizon to a maximum of
# ~1 year because the RFC strongly recommends <= 1 year and many
# scanners flag longer expiries as a finding of their own.
_MAX_EXPIRES_DAYS = 366
_MIN_EXPIRES_DAYS = 1


def _normalize_contact(raw: str) -> str:
    """Return a value suitable for the ``Contact:`` field.

    RFC 9116 section 2.5.4 requires a URI. Bare email addresses are
    widened to ``mailto:`` so a misconfigured operator value still
    produces a spec-compliant file. Values that already look like a
    URI scheme (``mailto:``, ``https:``, ``http:``, ``tel:``) are
    returned as-is.
    """
    v = (raw or "").strip()
    if not v:
        return ""
    lowered = v.lower()
    if lowered.startswith(("mailto:", "https:", "http:", "tel:")):
        return v
    if "@" in v and " " not in v and "/" not in v:
        return f"mailto:{v}"
    return v


def _emit(lines: list[str], field: str, value: str) -> None:
    v = (value or "").strip()
    if v:
        lines.append(f"{field}: {v}")


def _languages(raw: str) -> str:
    # RFC 9116 section 2.5.8: comma-separated language tags. We accept
    # comma or whitespace separators and normalise to a single ``, ``
    # separator so the field is stable across reads.
    parts: list[str] = []
    seen: set[str] = set()
    for token in (raw or "").replace(",", " ").split():
        t = token.strip()
        if t and t.lower() not in seen:
            parts.append(t)
            seen.add(t.lower())
    return ", ".join(parts)


def _build_security_txt(now: datetime | None = None) -> str | None:
    """Render the security.txt body, or return ``None`` when unconfigured."""
    s = get_settings()
    contact = _normalize_contact(s.security_contact)
    if not contact:
        return None

    horizon_raw = int(s.security_expires_days or 0)
    horizon = max(_MIN_EXPIRES_DAYS, min(_MAX_EXPIRES_DAYS, horizon_raw or _MAX_EXPIRES_DAYS))
    expires_at = (now or datetime.now(UTC)) + timedelta(days=horizon)
    expires_at = expires_at.replace(microsecond=0)

    lines: list[str] = []
    _emit(lines, "Contact", contact)
    lines.append("Expires: " + expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"))
    langs = _languages(s.security_preferred_languages)
    if langs:
        lines.append(f"Preferred-Languages: {langs}")
    _emit(lines, "Canonical", s.security_canonical_url)
    _emit(lines, "Policy", s.security_policy_url)
    _emit(lines, "Acknowledgments", s.security_acknowledgments_url)
    _emit(lines, "Encryption", s.security_encryption_url)
    _emit(lines, "Hiring", s.security_hiring_url)
    # Trailing newline is recommended for plain-text payloads.
    return "\n".join(lines) + "\n"


@router.get("/.well-known/security.txt", include_in_schema=False)
def security_txt() -> Response:
    body = _build_security_txt()
    if body is None:
        return Response(
            content="security.txt is not configured for this deployment.\n",
            status_code=404,
            media_type="text/plain; charset=utf-8",
        )
    return Response(
        content=body,
        status_code=200,
        media_type="text/plain; charset=utf-8",
        headers={
            # security.txt MUST be cacheable but operators routinely
            # rotate the contact during an incident, so cap caching to
            # one hour. RFC 9116 does not mandate a value here.
            "Cache-Control": "public, max-age=3600",
        },
    )


# Convenience alias: some scanners still check the legacy unprefixed
# location from the original draft. RFC 9116 says the well-known path
# is canonical, but answering both costs nothing.
@router.get("/security.txt", include_in_schema=False)
def security_txt_legacy() -> Response:
    return security_txt()
