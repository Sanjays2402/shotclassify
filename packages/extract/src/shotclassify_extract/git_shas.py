"""Cross-category git SHA extractor.

Git commit SHAs show up in every category of screenshot -- error
stacktraces print the release tag, code snippets cite the commit
that introduced a regression, terminal captures paste ``git log``
output, document captures include build provenance footers, chat
captures share PR refs. Rather than teach each per-category
extractor to find SHAs, we run :func:`extract_git_shas` once on the
OCR text and stash the unique, order-preserving list under
``ExtractedFields.raw["git_shas"]`` so dashboards, routing rules,
and downstream agents have a single place to look.

Recognised shapes:

* **Full SHA-1** (40 lowercase hex chars). The unique shape; very
  rarely false-positives on anything other than a real commit.
* **Short SHA** (7..12 hex chars), but ONLY when anchored to one of
  the surrounding contexts where git SHAs actually appear:
  * After a git-vocabulary keyword (``commit``, ``revision``,
    ``rev``, ``sha``, ``hash``, ``HEAD``, ``master@{...}``).
  * Inside a ``git show`` / ``git log`` / ``git rev-parse`` /
    ``git cherry-pick`` etc. invocation.
  * In ``(commit <sha>)`` / ``[commit <sha>]`` / ``#<sha>`` style
    code-review refs.
  * After ``Fixes:`` / ``Refs:`` / ``Reverts:`` / ``See:`` /
    ``Cc:`` mail-style footers that the Linux kernel and many OSS
    projects use.

  A bare 7-12 hex blob with no surrounding context is rejected --
  too many false positives (UUIDs, base32 IDs, color codes).

Output canonical form: lowercase, no normalisation beyond case.
A short SHA is NOT extended to its full form (we don't have the
git repo to resolve against); dashboards display the short form as
captured. The full and short form of the same commit do NOT collapse
because we can't prove they refer to the same commit without the
repo.

Deliberately NOT matched:

* Any hex string that's also a valid UUID -- the UUID extractor
  already covers that case.
* Hex strings shorter than 7 chars or longer than 40 chars.
* Strings that include any non-hex character.
"""
from __future__ import annotations

import re

# Full SHA-1: exactly 40 lowercase OR uppercase hex chars, with non-
# hex / non-word boundaries on both sides so we don't bite into a
# longer hex run. Case is normalised at extraction time.
_FULL_SHA_RE = re.compile(r"(?<![0-9a-fA-F])(?P<sha>[0-9a-fA-F]{40})(?![0-9a-fA-F])")

# Short SHA shape (7..12 hex chars). We use this in conjunction with
# the context patterns below; never matched standalone.
_SHORT_SHA = r"[0-9a-fA-F]{7,12}"

# Context patterns: each captures a short SHA preceded by a
# git-vocabulary cue. Case-insensitive on the keyword but the
# captured SHA is left as printed (and lowercased at output time).
_CONTEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    # ``commit <sha>`` / ``Commit: <sha>``.
    re.compile(
        rf"\bcommit(?:\s*[:=]|\s+)\s*(?P<sha>{_SHORT_SHA})\b",
        re.IGNORECASE,
    ),
    # ``revision <sha>`` / ``rev <sha>`` / ``rev: <sha>``.
    re.compile(
        rf"\b(?:revision|rev)(?:\s*[:=]|\s+)\s*(?P<sha>{_SHORT_SHA})\b",
        re.IGNORECASE,
    ),
    # ``SHA: <sha>`` / ``Hash: <sha>``.
    re.compile(
        rf"\b(?:sha|hash)(?:\s*[:=])\s*(?P<sha>{_SHORT_SHA})\b",
        re.IGNORECASE,
    ),
    # ``git show <sha>`` / ``git log <sha>`` / ``git cherry-pick <sha>``
    # / ``git rev-parse <sha>`` / ``git checkout <sha>``. We only
    # accept the subset of git subcommands that take a SHA arg.
    # Horizontal whitespace only (``[ \t]+``) so the SHA must be on
    # the SAME LINE as the git invocation -- this prevents matching
    # ``git log --oneline\n1234567 fix...`` and picking the first
    # hex tail of the log output as the argument SHA. We accept a
    # single ``-x`` or ``--flag`` argument between the subcommand and
    # the SHA (``git log --no-merges <sha>``) but reject longer
    # flag chains because those are usually output-only filters that
    # don't pair with a SHA.
    re.compile(
        rf"\bgit[ \t]+(?:show|log|cherry-pick|rev-parse|checkout|reset|"
        rf"revert|rebase|bisect|diff|stash[ \t]+(?:apply|pop|show))"
        rf"(?:[ \t]+--?[A-Za-z][\w\-]*)?[ \t]+(?P<sha>{_SHORT_SHA})\b",
        re.IGNORECASE,
    ),
    # Mail-footer style: ``Fixes: <sha>`` / ``Refs: <sha>`` /
    # ``Reverts: <sha>`` / ``See: <sha>`` / ``Cc: <sha>``. The Linux
    # kernel and many OSS projects use these in commit messages.
    re.compile(
        rf"\b(?:fixes|refs|reverts|see|cc)(?:\s*[:=])\s*(?P<sha>{_SHORT_SHA})\b",
        re.IGNORECASE,
    ),
    # ``HEAD@{...}`` / ``master@{...}`` reflog refs commonly resolve
    # to a short SHA. No trailing ``\b`` because ``}`` is non-word
    # and ``\b`` would require a word char on the inside which we
    # already have; the rightward boundary check is unnecessary.
    re.compile(
        rf"\b[A-Za-z][\w\-/]*@\{{(?P<sha>{_SHORT_SHA})\}}",
    ),
    # ``#<sha>`` GitHub-style reference.
    re.compile(
        rf"(?<![\w])#(?P<sha>{_SHORT_SHA})\b"
    ),
)


_MAX_SHAS = 50


def extract_git_shas(text: str) -> list[str]:
    """Return unique git SHAs found in ``text``.

    Preserves first-seen order across all matchers. Output is
    lowercase. A short SHA is recorded as printed (we don't have the
    repo to resolve to full form). Full SHA-1 hashes (40 hex) match
    standalone; short SHAs (7..12 hex) match only when paired with a
    git-vocabulary context so we don't false-positive on UUIDs and
    color codes. Caps the output at 50 entries.
    """
    if not text or not isinstance(text, str):
        return []
    seen: set[str] = set()
    out: list[str] = []
    candidates: list[tuple[int, str]] = []

    # 1) Full SHA-1 first.
    for m in _FULL_SHA_RE.finditer(text):
        sha = m.group("sha").lower()
        candidates.append((m.start("sha"), sha))

    # 2) Short SHAs that appear in a git-vocabulary context.
    for pat in _CONTEXT_PATTERNS:
        for m in pat.finditer(text):
            sha = m.group("sha").lower()
            candidates.append((m.start("sha"), sha))

    # Sort by source-text offset so the order matches what a human
    # reading the screenshot top-to-bottom would see.
    candidates.sort(key=lambda x: x[0])

    for _, sha in candidates:
        if sha in seen:
            continue
        seen.add(sha)
        out.append(sha)
        if len(out) >= _MAX_SHAS:
            break
    return out


__all__ = ["extract_git_shas"]
