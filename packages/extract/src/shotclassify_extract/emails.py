"""Cross-category email-address extractor.

Email addresses show up across every category of screenshot — error
stacktraces print the contact for a failing service, receipts include
the merchant's billing email, code snippets reference test fixtures
like ``alice@example.com``, chats are mostly people emailing each
other, document captures cite authors. Rather than teach each
per-category extractor to find emails, we run :func:`extract_emails`
once on the OCR text and stash the unique, order-preserving list
under ``ExtractedFields.raw["emails"]`` so dashboards, routing rules,
and downstream agents have a single place to look.

Recognised shape: RFC-5321 ``local@domain`` with conservative local-
and domain-part character classes that match the overwhelming
majority of real-world addresses without false-positive-ing on
identifier-like substrings (``@user`` mentions, ``user@host`` SSH
fragments, ``key=value@something`` config snippets). Specifically:

* Local part: starts with a letter / digit, then 0–63 more letter /
  digit / ``.+_-`` characters. No leading dot / leading dash (rejects
  ``.foo@bar``, ``-foo@bar``).
* ``@`` separator.
* Domain: at least one label (letter/digit/dash, no leading/trailing
  dash) followed by a dot, then a TLD of 2+ letters (so a bare
  ``user@host`` SSH fragment is NOT matched as an email).
* Surrounded by word / punctuation boundaries on both sides so
  ``mailto:alice@example.com>``, ``"alice@example.com"``, and a
  bare ``alice@example.com`` line all extract cleanly.

The matcher:

* lowercases the result for storage so ``Alice@Example.COM`` and
  ``alice@example.com`` are recognised as the same address (RFC 5321
  permits case-sensitive local parts but every major provider folds
  them; lowercasing matches user expectation in dashboards).
* trims a single trailing sentence punctuation character that the
  regex consumed by accident (``.``, ``,``, ``;``, ``:``, ``!``,
  ``?``, ``)``, ``]``, ``}``, ``>``, quotes).
* strips a leading ``mailto:`` prefix that some screenshots include
  inline.
* de-dupes while preserving first-seen order.
* caps the output at 50 entries to bound memory.
"""
from __future__ import annotations

import re

# Local part: 1..64 chars from a conservative class. First char must
# be a letter or digit (rejects ``.foo`` / ``-foo``). The class
# permits the usual ``.+_-`` plus an embedded digit/letter; we keep
# it narrower than RFC 5322 because OCR noise loves to inject ``!``
# and ``%`` into unrelated tokens.
_LOCAL = r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}"

# Domain label: letter/digit, optionally followed by up to 62 more
# letter/digit/dash chars and ending in a letter/digit. Single-letter
# labels are allowed (``a.example.com``).
_DLABEL = r"[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"

# TLD: 2+ letters. We deliberately reject digit-only TLDs to keep
# random ``user@host123`` SSH fragments out of the results.
_TLD = r"[A-Za-z]{2,24}"

# Full pattern. The ``(?<![\w.+\-@])`` lookbehind prevents the regex
# from biting into an already-matched email's tail (``a@b.com c@d.com``
# becoming a single match because the dot is consumed). The
# ``(?![\w@])`` lookahead rejects ``alice@example.comextra`` from
# folding the trailing text into the TLD.
_EMAIL_RE = re.compile(
    rf"(?<![\w.+\-@])(?:mailto:)?({_LOCAL}@(?:{_DLABEL}\.)+{_TLD})(?![\w@])"
)


_TRAILING_STRIP = ".,;:!?)>]}\"'`*"
_MAX_EMAILS = 50


def extract_emails(text: str) -> list[str]:
    """Return unique lowercase email addresses found in ``text``.

    Preserves first-seen order. Trims trailing sentence punctuation.
    Strips a leading ``mailto:`` prefix. Lowercases results so
    ``Alice@Example.COM`` and ``alice@example.com`` collapse to one
    entry. Caps the output at 50 entries.
    """
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in _EMAIL_RE.findall(text):
        email = raw
        # The capture group already excludes the ``mailto:`` prefix
        # because of the non-capturing wrapper, but a stray
        # ``Mailto:`` (mixed case) outside the alternation is harmless
        # — defensive strip below covers it.
        if email.lower().startswith("mailto:"):
            email = email[len("mailto:"):]
        # Strip trailing sentence punctuation that the lookahead let
        # through (rare for emails, but a stray closing quote / paren
        # adjacent to the TLD can sneak in).
        while email and email[-1] in _TRAILING_STRIP:
            email = email[:-1]
        if not email or "@" not in email:
            continue
        norm = email.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
        if len(out) >= _MAX_EMAILS:
            break
    return out


__all__ = ["extract_emails"]
