"""PII redaction for OCR text and extracted fields.

This module is the single source of truth for what counts as PII inside
shotclassify. The :func:`redact_text` helper takes a string and a set of
mode names (``email``, ``phone``, ``ssn``, ``credit_card``, ``ip``,
``iban``, ``jwt``, ``aws_access_key``, ``github_token``,
``slack_token``, ``address``, ``passport``) and returns a copy with
each match replaced by a typed placeholder such as ``[REDACTED:email]``
or ``[REDACTED:aws_access_key]``. The :func:`redact_fields` helper
walks an arbitrary JSON-shaped value (dict / list / str) and applies
the same rules to every string leaf, which lets the pipeline sanitize
OCR results and extracted structured fields with one call before any
of it is persisted or shipped to an outbound webhook.

The developer-secret modes (``jwt``, ``aws_access_key``,
``github_token``, ``slack_token``) cover the obvious leaked-secret
cases that show up in screenshots of terminals, .env editors, and CI
logs without requiring a heavier downstream scanner. The regexes are
deliberately tight: they key off the canonical format published by
each vendor (AWS's ``AKIA``/``ASIA`` prefix + 16 base32 chars,
GitHub's ``ghp_``/``gho_``/``ghu_``/``ghs_``/``ghr_``/``github_pat_``
prefixes, Slack's ``xox{a-z}-`` family, and the ``eyJ`` JWT header
opener) so a random alphanumeric string in unrelated text is never
mistakenly redacted.

The base regexes are intentionally conservative: they aim for very
low false positives at the cost of missing exotic formats. A buyer's
procurement review wants to see redaction working on the obvious
cases (email, phone, credit card, SSN, leaked vendor tokens) without
garbling unrelated text in their screenshots. Specialist DLP belongs
in a dedicated downstream service.

Adding a new mode is two edits: append it to ``_PATTERNS`` here and to
``PII_REDACT_MODES`` in ``shotclassify_store.tenant_settings`` so the
admin UI and the storage allow-list stay in lockstep.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

# Order matters: longer / more specific patterns first so that, for
# example, a credit-card-shaped number is not partially consumed by the
# phone matcher. Developer-secret patterns are matched BEFORE generic
# email so that a JWT (which embeds three dot-separated base64 chunks)
# can never be partially eaten by another rule.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        # AWS access key id: literal AKIA or ASIA followed by 16 base32
        # uppercase chars. Strictly 20 chars total. Distinct enough that
        # a single 20-char run prefixed by AKIA/ASIA in a screenshot is
        # almost always a real AWS credential.
        "aws_access_key",
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ),
    (
        # GitHub personal-access tokens, fine-grained tokens, OAuth
        # tokens, server-to-server tokens, refresh tokens. GitHub
        # publishes the prefixes (ghp_, gho_, ghu_, ghs_, ghr_,
        # github_pat_) and a fixed length is enforced by their format.
        "github_token",
        re.compile(
            r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b"
            r"|\bgithub_pat_[A-Za-z0-9_]{82}\b"
        ),
    ),
    (
        # Slack tokens: classic bots, user, app, refresh, and the modern
        # xoxe-/xoxd- variants. All begin with xox{a-z} and a dash, then
        # numeric workspace + token segments.
        "slack_token",
        re.compile(r"\bxox[abeoprs]-(?:\d+-)+[A-Za-z0-9-]{16,}\b"),
    ),
    (
        # JWT: three base64url-encoded segments separated by dots. We
        # require the header segment to start with one of the common
        # alg-typed prefixes (eyJ = base64url for `{"`), and each
        # segment to be at least 8 chars so we do not eat random
        # dot-separated identifiers. Trailing padding is optional.
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_=-]{8,}\.[A-Za-z0-9_=-]{8,}\.[A-Za-z0-9_=-]{8,}\b"
        ),
    ),
    (
        "email",
        re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    ),
    (
        # US SSN: 3-2-4. Reject the obvious invalids (000, 666, 9xx area).
        "ssn",
        re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
    ),
    (
        # 13-19 digit runs allowing single spaces or dashes as separators.
        # Followed by a Luhn check below to keep false positives in check.
        "credit_card",
        re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
    ),
    (
        # IBAN: 2 letters, 2 digits, then 11-30 alphanumerics. Allows a
        # single space every four chars to match how humans paste them.
        "iban",
        re.compile(
            r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}[ ]?[A-Z0-9]{1,4}\b"
        ),
    ),
    (
        # NANP-ish phone: optional +country, then 10 digits separated by
        # space / dash / dot / parens. Requires at least one separator so
        # we do not eat plain integer sequences.
        "phone",
        re.compile(
            r"(?:\+?\d{1,3}[ .-]?)?(?:\(\d{3}\)[ .-]?|\d{3}[ .-])\d{3}[ .-]\d{4}\b"
        ),
    ),
    (
        # IPv4 dotted quad. IPv6 is intentionally omitted: most screenshots
        # do not contain it and the regex bloat is not worth the recall.
        "ip",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
        ),
    ),
    (
        # Postal address (one-line US / UK street + city + zip). The
        # ``address`` mode targets the contact-line shape that appears
        # on receipts ("123 Main St, Springfield, IL 62704"),
        # signatures, document captures of shipping labels, and chat
        # captures of contact cards. We deliberately do NOT try to be
        # exhaustive -- a serious address parser belongs in a
        # downstream service. This regex catches the common one-line
        # forms with high precision and accepts the occasional miss
        # on multi-line addresses.
        #
        # Accepted shapes:
        # * US: "[apt-prefix? ]NUMBER STREET[, CITY[, STATE ZIP]]"
        #   street tail uses the common suffix vocabulary (St / Street
        #   / Ave / Avenue / Blvd / Boulevard / Rd / Road / Dr / Drive
        #   / Ln / Lane / Way / Ct / Court / Plaza / Pkwy / Parkway /
        #   Hwy / Highway / Sq / Square / Ter / Terrace / Pl / Place /
        #   Trail / Cir / Circle / Loop / Row).
        # * Optional unit suffix (Apt 4B / Suite 200 / #12 / Unit C).
        # * Optional ", CITY", optional ", STATE ZIP" tail (US 5- or
        #   5+4-digit ZIP; UK postcode shape with one or two leading
        #   letters, then digits and a final letter pair).
        "address",
        re.compile(
            r"\b\d{1,6}(?:[-/]\d{1,6})?\s+"  # house number
            r"(?:[NSEW]\.?\s+)?"  # optional cardinal direction
            r"[A-Z][A-Za-z0-9.'-]*"  # street name first token
            r"(?:\s+[A-Z][A-Za-z0-9.'-]*){0,4}"  # additional street tokens
            r"\s+(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive"
            r"|Ln|Lane|Way|Ct|Court|Plaza|Pkwy|Parkway|Hwy|Highway"
            r"|Sq|Square|Ter|Terrace|Pl|Place|Trail|Cir|Circle|Loop|Row"
            r")\.?"
            r"(?:\s*,?\s*(?:Apt|Suite|Ste|Unit|#)\.?\s*[A-Z0-9-]+)?"
            r"(?:\s*,\s*[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)*"
            r"(?:\s*,\s*(?:[A-Z]{2}\s+\d{5}(?:-\d{4})?"
            r"|[A-Z]{1,2}\d[A-Z\d]?\s+\d[A-Z]{2}))?"
            r")?"
        ),
    ),
    (
        # Passport number. Passport numbers vary wildly by country (US
        # / UK use 9 digits; Canada uses 2 letters + 6 digits;
        # Germany uses 1 letter + 8 alphanumerics; Australia uses 1-2
        # letters + 7 digits; many EU countries use 9 alphanumeric
        # mixes). Surfacing a bare 9-digit run as a passport would
        # false-positive on every receipt order number, every UPS
        # tracking suffix, every phone number, and every credit card
        # last-9-digits in a screenshot.
        #
        # We require the word ``passport`` (case-insensitive) to
        # appear immediately before the candidate so the matcher
        # fires ONLY on labelled passport numbers. Accepted label
        # forms:
        #
        #   Passport: A12345678
        #   Passport No: 123456789
        #   Passport No. 123456789
        #   Passport Number: A1234567
        #   Passport # 12345678
        #   Passport ID: 12345678
        #   Passport #: 12345678
        #   Passport: 123456789
        #
        # Accepted candidate shapes (after the label):
        #
        #   * 9 digits (US, UK, Russia, ...)
        #   * 1 letter + 7-8 digits (Australia, Germany, NZ, ...)
        #   * 2 letters + 6-7 digits (Canada, ...)
        #   * 1 letter + 8 alphanumerics (Germany legacy)
        #   * 8-9 mixed alphanumerics
        #
        # Letter portions captured case-insensitively but real passport
        # numbers are uppercase by convention. The matcher accepts
        # mixed-case but downstream redaction strips the whole match
        # regardless.
        #
        # When the label appears with a colon / hash / period / space
        # separator we tolerate up to 5 separator chars between the
        # label and the number so ``Passport No. 12345678`` works as
        # well as ``Passport#12345678``.
        "passport",
        re.compile(
            r"\bpassport\s*(?:no\.?|number|id|#)?\s*[:#.\s]{0,5}"
            r"(?P<num>[A-Z]{0,2}[A-Z0-9]{6,9})\b",
            re.IGNORECASE,
        ),
    ),
)


def _luhn_ok(digits: str) -> bool:
    """Return True if ``digits`` passes the Luhn checksum."""
    s = 0
    alt = False
    for ch in reversed(digits):
        if not ch.isdigit():
            continue
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        alt = not alt
    return s > 0 and s % 10 == 0


def _placeholder(mode: str) -> str:
    return f"[REDACTED:{mode}]"


def _normalize_modes(modes: Iterable[str] | None) -> set[str]:
    if not modes:
        return set()
    return {m.strip().lower() for m in modes if isinstance(m, str) and m.strip()}


def redact_text(text: str, modes: Iterable[str] | None) -> str:
    """Return ``text`` with every PII match for the requested modes redacted.

    Unknown modes are silently ignored so a future caller cannot break the
    pipeline by asking for a mode this build does not yet ship.
    """
    if not text or not isinstance(text, str):
        return text
    active = _normalize_modes(modes)
    if not active:
        return text
    out = text
    for mode, pattern in _PATTERNS:
        if mode not in active:
            continue
        if mode == "credit_card":
            def _sub_cc(m: re.Match[str]) -> str:
                digits = "".join(ch for ch in m.group(0) if ch.isdigit())
                if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                    return _placeholder("credit_card")
                return m.group(0)
            out = pattern.sub(_sub_cc, out)
        elif mode == "passport":
            # Passport mode replaces only the captured ``num`` group
            # (the actual number) so the surrounding label
            # ``Passport No: `` stays visible to the reader -- they
            # know the field WAS a passport without leaking the
            # number itself. The placeholder slots into the
            # number's original position.
            def _sub_passport(m: re.Match[str]) -> str:
                start, end = m.span("num")
                whole_start, whole_end = m.span()
                # Preserve the prefix before the number, then placeholder,
                # then any tail after the number within the match.
                return (
                    m.string[whole_start:start]
                    + _placeholder("passport")
                    + m.string[end:whole_end]
                )
            out = pattern.sub(_sub_passport, out)
        else:
            out = pattern.sub(_placeholder(mode), out)
    return out


def redact_fields(value: Any, modes: Iterable[str] | None) -> Any:
    """Recursively redact every string leaf inside ``value``.

    Dicts and lists are walked in place semantics (a new container of the
    same shape is returned). Non-string, non-container leaves are
    returned unchanged so numeric extracted fields like totals or
    confidences are preserved exactly.
    """
    active = _normalize_modes(modes)
    if not active:
        return value
    if isinstance(value, str):
        return redact_text(value, active)
    if isinstance(value, dict):
        return {k: redact_fields(v, active) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_fields(v, active) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_fields(v, active) for v in value)
    return value


__all__ = ["redact_text", "redact_fields"]
