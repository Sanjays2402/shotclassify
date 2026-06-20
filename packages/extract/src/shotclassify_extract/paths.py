"""Cross-category file-path extractor.

Every category of screenshot can contain file paths -- error
stacktraces cite source files, code snippets reference imports,
terminal screenshots paste shell paths, documents quote artefact
locations. Rather than teach each per-category extractor to find
paths, we run :func:`extract_paths` once on the OCR text and stash
the unique, order-preserving list under ``ExtractedFields.raw["paths"]``
so dashboards, routing rules, and downstream agents have a single
place to look.

Recognised shapes:

* POSIX absolute paths: ``/usr/local/bin/foo``, ``/Users/sanjay/x.py``
  (require a leading ``/`` followed by a name segment so a bare ``/``
  cannot match).
* Home-relative paths: ``~/dotfiles/zshrc``, ``~/code/proj``.
* Windows drive paths: ``C:\\Users\\Foo\\file.txt``,
  ``D:/Projects/x``.
* UNC shares: ``\\\\server\\share\\file``.

Deliberately NOT matched:

* Bare filenames without a directory component (``foo.txt``) -- too
  many false positives in receipts, chat, OCR noise.
* Relative paths without a clear prefix (``src/foo.py``) -- also
  ambiguous with phrases that contain slashes (URLs, date fragments).

The matcher:

* trims trailing sentence punctuation (``.``, ``,``, ``;``, ``:``,
  ``!``, ``?``, ``)``, ``]``, ``}``, ``>``, quotes) -- the same set
  used by the URL extractor.
* de-dupes while preserving first-seen order.
* caps the output at 50 entries.
* skips anything that looks like a URL scheme (``://``) so URLs do
  not double-count under both ``urls`` and ``paths``.
"""
from __future__ import annotations

import re

# POSIX absolute: leading slash + at least one path char + at least
# one ``/seg`` group so ``/`` alone never matches.
_POSIX_RE = re.compile(r"(?<![:\w])/[\w.\-+@]+(?:/[\w.\-+@]+)+/?")

# Home-relative: ``~/`` or ``~user/`` followed by at least one segment.
_HOME_RE = re.compile(r"~(?:[\w.\-]+)?/[\w.\-+@/]+")

# Windows drive: drive letter + colon + slash + at least one segment.
# Allows both backslash and forward slash separators. Path segments
# explicitly forbid spaces so a trailing word ("file.txt now") cannot
# be absorbed into the match.
_WINDRIVE_RE = re.compile(
    r"\b[A-Za-z]:[\\/][\w.\-+]+(?:[\\/][\w.\-+]+)*",
)

# UNC share: ``\\server\share\...``. Escaped here as ``\\\\`` in the
# pattern source. Same no-spaces rule as Windows drive.
_UNC_RE = re.compile(r"\\\\[\w.\-]+\\[\w.\-]+(?:\\[\w.\-+]+)*")


_TRAILING_STRIP = ".,;:!?)>]}\"'`*"
_MAX_PATHS = 50


def extract_paths(text: str) -> list[str]:
    """Return unique filesystem paths found in ``text``.

    Preserves first-seen order across all matchers (POSIX, home,
    Windows drive, UNC). Trims trailing sentence punctuation. Skips
    matches embedded in a URL (anything preceded by ``://`` within the
    same word). When two matchers produce overlapping spans (POSIX
    inside a home-relative path), the EARLIER match wins and the
    overlapping span is discarded. Caps the output at 50 entries.
    """
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    out: list[str] = []

    # Mask out URL substrings before scanning: any ``http(s)://...``
    # span is replaced with spaces so a URL path like
    # ``https://example.com/docs/api`` cannot leak ``/docs/api`` into
    # paths.
    masked = re.sub(r"\bhttps?://\S+", lambda m: " " * len(m.group(0)), text, flags=re.IGNORECASE)

    candidates: list[tuple[int, int, str]] = []
    for pat in (_POSIX_RE, _HOME_RE, _WINDRIVE_RE, _UNC_RE):
        for m in pat.finditer(masked):
            candidates.append((m.start(), m.end(), m.group(0)))
    # Stable first-seen order by start offset; longer match wins ties.
    candidates.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    # Drop any candidate whose span is fully covered by an earlier
    # (kept) candidate. This is how we prevent the POSIX matcher from
    # double-counting the tail of a home-relative path.
    kept: list[tuple[int, int, str]] = []
    for start, end, raw in candidates:
        covered = any(k_start <= start and end <= k_end for k_start, k_end, _ in kept)
        if covered:
            continue
        kept.append((start, end, raw))

    for _, _, raw in kept:
        path = raw
        while path and path[-1] in _TRAILING_STRIP:
            path = path[:-1]
        if not path or path in seen:
            continue
        # Reject things that are clearly not paths: require at least
        # one slash / backslash / leading ``~``.
        if "/" in path or "\\" in path or path.startswith("~"):
            seen.add(path)
            out.append(path)
            if len(out) >= _MAX_PATHS:
                break
    return out


__all__ = ["extract_paths"]
