"""Cross-category URL extractor.

Every category of screenshot can contain URLs — error stacktraces
point at docs, code snippets embed Stack Overflow links, receipts
sometimes print a Yelp page, chats are mostly links, document
captures cite sources. Rather than teach each per-category extractor
to find URLs, we run :func:`extract_urls` once on the OCR text and
stash the unique, order-preserving list under
``ExtractedFields.raw["urls"]`` so dashboards, routing rules, and
downstream agents have a single place to look.

The regex is deliberately conservative: it matches ``http://`` and
``https://`` scheme prefixes only (no bare ``www.`` or
``example.com`` — those have too many false positives in OCR
output), trims a single trailing punctuation character that a sentence
boundary commonly drags along (``.``, ``,``, ``;``, ``:``, ``!``,
``?``, ``)``, ``]``, ``}``, ``>``, single/double quote), and de-dupes
matches while preserving first-seen order.

The output is capped at 50 URLs to bound memory in case a long error
log floods the matcher; that's plenty for any human-readable
screenshot.
"""
from __future__ import annotations

import re

# Scheme + ``://`` + host/path chars. We allow most URL-safe chars,
# disallow whitespace, and stop at the first quote / closing bracket /
# closing paren because those almost always close a markdown link or
# a parenthetical aside in screenshots.
_URL_RE = re.compile(
    r"\bhttps?://[^\s<>\"'`(){}\[\]|]+",
    re.IGNORECASE,
)


# Trailing characters that are almost certainly NOT part of the URL
# (sentence punctuation, closing brackets the regex didn't consume).
_TRAILING_STRIP = ".,;:!?)>]}\"'`*"


_MAX_URLS = 50


def extract_urls(text: str) -> list[str]:
    """Return the unique ``http(s)://`` URLs found in ``text``.

    Preserves first-seen order, trims one trailing punctuation
    character per match, and caps the output at 50 entries so a
    pathological OCR pass cannot balloon stored metadata. Returns
    ``[]`` for empty or non-string input rather than raising.
    """
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in _URL_RE.findall(text):
        url = raw
        # Strip one trailing sentence-ish punctuation. Iteratively peel
        # so ``...)`` collapses to ``...`` rather than ``...)``.
        while url and url[-1] in _TRAILING_STRIP:
            url = url[:-1]
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= _MAX_URLS:
            break
    return out


__all__ = ["extract_urls"]
