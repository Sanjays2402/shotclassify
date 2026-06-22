"""Cross-category error-fingerprint extractor.

Modern error-monitoring vendors print a short hash / trace identifier
next to every captured exception so engineers can paste it into the
vendor's dashboard and pull up the full event. Sentry, Datadog, Rollbar,
New Relic, Bugsnag, Honeybadger, and Airbrake all use distinctive
shapes:

    Sentry: ``[abc123]`` short event-id (7..16 hex), full event-id
            (32 hex), DSN-style ``[SHA-...]`` short fingerprint, or
            ``Sentry Event ID: deadbeef12345678`` plain-text label.
    Datadog: ``dd.trace_id=1234567890`` / ``dd.span_id=987654321`` pair,
             also ``trace_id: 6f4...`` long-hex form when the agent
             injects W3C trace context.
    Rollbar: ``rollbar event #12345`` numeric event ID label.
    New Relic: ``traceId: <128-hex>`` (W3C trace-context shape).
    Bugsnag: ``BugsnagError-XYZW1234`` typed event id.
    Honeybadger: ``honeybadger fault #12345``.
    Airbrake: ``[Airbrake] [tag] error #67890``.

Each surfaced entry is a ``{"vendor": str, "kind": str, "id": str}``
dict where:
  * ``vendor`` is the lowercase vendor tag (``sentry`` / ``datadog`` /
    ``rollbar`` / ``newrelic`` / ``bugsnag`` / ``honeybadger`` /
    ``airbrake``).
  * ``kind`` is the role of the ID inside the vendor's model
    (``event_id`` / ``trace_id`` / ``span_id`` / ``fingerprint`` /
    ``fault_id``).
  * ``id`` is the captured identifier, normalised to lowercase for
    hex IDs (so the same trace_id printed mixed-case collapses to one
    entry) and preserved-case for typed IDs.

Distinct from ``raw["uuids"]`` (which catches every UUID in the text)
because error fingerprints are vendor-tagged so a dashboard can route
them to the right deep-link template. Pairs with ``ErrorFields`` --
the fingerprint extractor runs cross-category because a chat capture
of an on-call thread, a doc capture of a runbook, and a code-snippet
capture of an error log all carry these IDs and dashboards want to
catch them everywhere.
"""
from __future__ import annotations

import re

# Sentry event IDs. Two shapes:
#
#   1. The full 32-hex event ID Sentry shows on each event page
#      (``Event ID: a1b2c3d4...``).
#   2. The short 7..16-hex "fingerprint" Sentry shows in the breadcrumb
#      and toast notifications (``[abc1234]`` square-bracket form, or
#      the inline ``id: abc1234`` form).
#
# Both forms REQUIRE the word "sentry" / "event id" / "fingerprint" on
# the same line OR the previous line as an anchor. The bare 7-hex
# ``[abc1234]`` form would otherwise false-positive on every git short
# SHA in a build log.
_SENTRY_FULL_RE = re.compile(
    r"(?:sentry[\s_]*event[\s_]*id|event[\s_]*id|sentry[\s_]*id)\s*[:=#]?\s*"
    r"(?P<id>[0-9a-f]{32})\b",
    re.IGNORECASE,
)
_SENTRY_SHORT_RE = re.compile(
    r"(?:sentry|event)\s*[:=#]?\s*\[(?P<id>[0-9a-f]{7,16})\]",
    re.IGNORECASE,
)
_SENTRY_INLINE_SHORT_RE = re.compile(
    r"sentry[\s_-]*(?:event[\s_-]*)?id\s*[:=#]\s*(?P<id>[0-9a-f]{7,16})\b",
    re.IGNORECASE,
)

# Datadog trace and span IDs. The dd-trace agent injects context as
# ``dd.trace_id=<digits>`` and ``dd.span_id=<digits>``. Some installs
# print W3C trace-context as ``trace_id: <128-hex>``; we accept both.
_DATADOG_TRACE_RE = re.compile(
    r"\bdd\.trace_id\s*[:=]\s*(?P<id>\d{1,32}|[0-9a-f]{16,32})\b",
    re.IGNORECASE,
)
_DATADOG_SPAN_RE = re.compile(
    r"\bdd\.span_id\s*[:=]\s*(?P<id>\d{1,32}|[0-9a-f]{16,32})\b",
    re.IGNORECASE,
)
# The bare ``trace_id: <hex>`` form NEEDS a Datadog / dd_ anchor on
# the same line to differentiate from arbitrary trace IDs in non-DD
# logs. We deliberately leave the bare form without an anchor as a
# raw["uuids"] / raw["git_shas"] candidate so this matcher doesn't
# steal generic trace IDs.
_DATADOG_BARE_TRACE_RE = re.compile(
    r"(?:datadog|dd_trace|dd\.|dd_agent)[^\n]{0,40}?"
    r"\btrace_id\s*[:=]\s*[\"']?(?P<id>[0-9a-f]{16,32})[\"']?\b",
    re.IGNORECASE,
)

# Rollbar uses numeric event IDs printed alongside the rollbar
# vendor name: ``rollbar event #12345`` / ``[Rollbar] occurrence 6789``.
_ROLLBAR_RE = re.compile(
    r"\brollbar\b[^\n]{0,40}?(?:event|occurrence|item)\s*[:#]?\s*"
    r"(?P<id>\d{4,12})\b",
    re.IGNORECASE,
)

# New Relic W3C trace-context shape: 128-hex trace IDs preceded by a
# New Relic-vendor anchor. Without the anchor the 128-hex blob would
# tag as a generic hex sha.
_NEWRELIC_RE = re.compile(
    r"(?:new[\s_-]*relic|newrelic|nr\.|nr-)\b[^\n]{0,40}?"
    r"\btrace[_-]?id\s*[:=]\s*[\"']?(?P<id>[0-9a-f]{32}|[0-9a-f]{16})[\"']?\b",
    re.IGNORECASE,
)

# Bugsnag typed event IDs: ``Bugsnag error #abc123XYZ`` /
# ``BugsnagError-XYZW1234``.
_BUGSNAG_RE = re.compile(
    r"\bbugsnag\b[^\n]{0,40}?(?:error|event|exception|fault)\s*[:#-]?\s*"
    r"(?P<id>[A-Za-z0-9]{6,24})\b",
    re.IGNORECASE,
)

# Honeybadger fault IDs: ``honeybadger fault #12345`` /
# ``Honeybadger Notice 67890``.
_HONEYBADGER_RE = re.compile(
    r"\bhoneybadger\b[^\n]{0,40}?(?:fault|notice|error)\s*[:#]?\s*"
    r"(?P<id>\d{4,12})\b",
    re.IGNORECASE,
)

# Airbrake error IDs: ``[Airbrake] [tag] error #67890`` /
# ``Airbrake notice #1234``.
_AIRBRAKE_RE = re.compile(
    r"\bairbrake\b[^\n]{0,40}?(?:error|notice|exception)\s*[:#]?\s*"
    r"(?P<id>\d{4,12})\b",
    re.IGNORECASE,
)


_MAX_FINGERPRINTS = 30


def extract_error_fingerprints(text: str) -> list[dict[str, str]]:
    """Return error-fingerprint entries found in ``text``.

    Each entry is a ``{"vendor", "kind", "id"}`` dict. Hex IDs are
    lowercased for stable dedupe; alphanumeric IDs are preserved as
    printed. Order preserves first-seen-in-OCR-text offset.

    De-dupes on the (vendor, kind, id) tuple so the same fingerprint
    printed twice in the same screenshot collapses to one entry.
    Capped at 30 entries.
    """
    if not text:
        return []

    candidates: list[tuple[int, dict[str, str]]] = []

    def _add(vendor: str, kind: str, m: re.Match[str], lowercase: bool = True) -> None:
        raw = m.group("id").strip()
        if not raw:
            return
        ident = raw.lower() if lowercase else raw
        candidates.append((m.start(), {"vendor": vendor, "kind": kind, "id": ident}))

    # Sentry full 32-hex event IDs.
    for m in _SENTRY_FULL_RE.finditer(text):
        _add("sentry", "event_id", m, lowercase=True)
    # Sentry square-bracket short IDs (need same/previous-line vendor
    # anchor -- the regex enforces a "sentry" / "event" leader so the
    # bracketed match is anchored at the regex level).
    for m in _SENTRY_SHORT_RE.finditer(text):
        _add("sentry", "event_id", m, lowercase=True)
    for m in _SENTRY_INLINE_SHORT_RE.finditer(text):
        _add("sentry", "event_id", m, lowercase=True)

    # Datadog trace / span IDs.
    for m in _DATADOG_TRACE_RE.finditer(text):
        _add("datadog", "trace_id", m, lowercase=True)
    for m in _DATADOG_SPAN_RE.finditer(text):
        _add("datadog", "span_id", m, lowercase=True)
    for m in _DATADOG_BARE_TRACE_RE.finditer(text):
        _add("datadog", "trace_id", m, lowercase=True)

    # Rollbar / New Relic / Bugsnag / Honeybadger / Airbrake.
    for m in _ROLLBAR_RE.finditer(text):
        _add("rollbar", "event_id", m, lowercase=False)
    for m in _NEWRELIC_RE.finditer(text):
        _add("newrelic", "trace_id", m, lowercase=True)
    for m in _BUGSNAG_RE.finditer(text):
        # Bugsnag IDs are alphanumeric so preserve case to keep
        # round-tripping intact.
        _add("bugsnag", "event_id", m, lowercase=False)
    for m in _HONEYBADGER_RE.finditer(text):
        _add("honeybadger", "fault_id", m, lowercase=False)
    for m in _AIRBRAKE_RE.finditer(text):
        _add("airbrake", "event_id", m, lowercase=False)

    candidates.sort(key=lambda x: x[0])
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for _, entry in candidates:
        key = (entry["vendor"], entry["kind"], entry["id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
        if len(out) >= _MAX_FINGERPRINTS:
            break
    return out


__all__ = ["extract_error_fingerprints"]
