"""Tests for the cross-category git SHA extractor.

Git commit SHAs found in OCR text are stashed under
``ExtractedFields.raw["git_shas"]`` by the enrich pipeline so
dashboards and routing rules have a single place to look regardless
of which category the screenshot belongs to.

The matcher accepts:

* **Full SHA-1** (40 hex chars, lowercase or uppercase). Standalone
  match -- 40 hex is unique enough that we never demand context.
* **Short SHA** (7..12 hex chars) ONLY when anchored to git-vocabulary
  context (``commit`` / ``revision`` / ``rev`` / ``SHA`` / ``hash`` /
  ``git show`` / ``git log`` / ``Fixes:`` / ``Refs:`` / ``#<sha>`` /
  reflog ``HEAD@{sha}``).

Output is lowercase. Short SHAs are NOT extended to full form. The
matcher refuses to false-positive on bare 7-12 hex blobs (UUIDs,
color codes, base16 IDs).
"""
from __future__ import annotations

import pytest
from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_git_shas

# ---- extract_git_shas: full SHA-1 --------------------------------------


def test_full_sha1_standalone():
    """40 hex chars is unique enough to match without context."""
    sha = "1234567890abcdef1234567890abcdef12345678"
    assert extract_git_shas(f"see release {sha} today") == [sha]


def test_full_sha1_uppercase_normalised_to_lowercase():
    sha = "1234567890ABCDEF1234567890ABCDEF12345678"
    assert extract_git_shas(f"see {sha}") == [sha.lower()]


def test_full_sha1_inside_url_path():
    """A GitHub URL ``/commit/<sha>`` legitimately carries a SHA we
    want to extract."""
    text = "https://github.com/x/y/commit/abcdef0123456789abcdef0123456789abcdef01"
    assert extract_git_shas(text) == [
        "abcdef0123456789abcdef0123456789abcdef01"
    ]


def test_multiple_full_shas_preserves_order():
    sha1 = "1111111111111111111111111111111111111111"
    sha2 = "2222222222222222222222222222222222222222"
    text = f"start {sha1}\nend {sha2}\n"
    assert extract_git_shas(text) == [sha1, sha2]


# ---- extract_git_shas: short SHA needs context -------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        "commit abc1234",
        "Commit: abc1234",
        "Commit = abc1234",
        "revision abc1234",
        "rev abc1234",
        "rev: abc1234",
        "SHA: abc1234",
        "Hash: abc1234",
    ],
)
def test_short_sha_with_keyword(snippet):
    assert extract_git_shas(snippet) == ["abc1234"]


@pytest.mark.parametrize(
    "snippet",
    [
        "git show abc1234",
        "git log abc1234",
        "git checkout abc1234",
        "git cherry-pick abc1234",
        "git rev-parse abc1234",
        "git reset abc1234",
        "git revert abc1234",
    ],
)
def test_short_sha_in_git_invocation(snippet):
    assert extract_git_shas(snippet) == ["abc1234"]


@pytest.mark.parametrize(
    "snippet",
    [
        "Fixes: abc1234",
        "Refs: abc1234",
        "Reverts: abc1234",
        "See: abc1234",
        "Cc: abc1234",
    ],
)
def test_short_sha_in_mail_footer(snippet):
    assert extract_git_shas(snippet) == ["abc1234"]


def test_short_sha_in_pr_reference():
    """GitHub-style ``#<sha>`` references."""
    assert extract_git_shas("see #abc1234 for the fix") == ["abc1234"]


def test_short_sha_in_reflog_ref():
    """``HEAD@{abc1234}`` / ``master@{abc1234}`` reflog references."""
    text = "checkout to HEAD@{abc1234} please"
    assert extract_git_shas(text) == ["abc1234"]


# ---- extract_git_shas: rejection rules ---------------------------------


def test_bare_short_sha_without_context_rejected():
    """A 7-12 hex run with no git keyword nearby is too easy to
    false-positive on (UUIDs, color codes, etc.) -- rejected."""
    assert extract_git_shas("see abc1234 in the log") == []


def test_short_sha_too_short_rejected():
    """6 hex chars is below the 7-char minimum."""
    assert extract_git_shas("commit abc123 here") == []


def test_short_sha_too_long_rejected():
    """13 hex chars is above the 12-char maximum (and below 40, the
    full SHA-1 length) -- ambiguous, rejected."""
    assert extract_git_shas("commit abc123456789a here") == []


def test_full_sha1_with_non_hex_inside_rejected():
    """41 hex chars or 40-char string with a non-hex char is not
    a SHA."""
    cases = [
        "see 1234567890abcdef1234567890abcdef123456789",  # 39
        "see 1234567890abcdef1234567890abcdef1234567890",  # 41
        "see 1234567890abcdef1234567890abcdef1234567g",  # contains g
    ]
    for c in cases:
        assert extract_git_shas(c) == [], f"failed: {c!r}"


def test_empty_input_returns_empty():
    assert extract_git_shas("") == []
    assert extract_git_shas("no shas here") == []
    assert extract_git_shas(None) == []  # type: ignore[arg-type]


# ---- extract_git_shas: dedup and order ---------------------------------


def test_dedups_repeated_full_sha():
    sha = "abcdef0123456789abcdef0123456789abcdef01"
    text = f"start {sha}\nlater {sha}\n"
    assert extract_git_shas(text) == [sha]


def test_full_and_short_are_distinct_entries():
    """We cannot prove a short SHA refers to the same commit as a
    full one without the repo, so they stay distinct."""
    sha = "abcdef0123456789abcdef0123456789abcdef01"
    text = f"release {sha}\ncommit abcdef0\n"
    assert extract_git_shas(text) == [sha, "abcdef0"]


def test_cap_at_50_shas():
    text = "\n".join(
        f"commit {i:07x}" for i in range(120)
    )
    out = extract_git_shas(text)
    assert len(out) == 50


# ---- extract_git_shas: real-world contexts -----------------------------


def test_terminal_git_log_output():
    text = (
        "$ git log --oneline\n"
        "1234567 fix(api): add retry\n"
        "abcdef0 feat(ui): new button\n"
        "0987654 chore: bump deps\n"
    )
    # Bare hex without context -> none extracted. Only commit-keyword
    # short SHAs land.
    assert extract_git_shas(text) == []


def test_kernel_commit_message_footer():
    text = (
        "fix: avoid use-after-free in foo\n"
        "\n"
        "Fixes: deadbee123\n"
        "Refs: cafef00d456\n"
        "Signed-off-by: dev@example.com\n"
    )
    assert extract_git_shas(text) == ["deadbee123", "cafef00d456"]


def test_dashboard_release_footer():
    sha = "1234567890abcdef1234567890abcdef12345678"
    text = (
        "Release: 2026.06.20\n"
        f"Built from {sha}\n"
        "© ACME 2026\n"
    )
    assert extract_git_shas(text) == [sha]


# ---- pipeline integration ----------------------------------------------


@pytest.mark.parametrize(
    "category",
    [
        Category.receipt,
        Category.code_snippet,
        Category.error_stacktrace,
        Category.chat_screenshot,
        Category.document,
        Category.meme,
        Category.ui_mockup,
        Category.chart,
        Category.other,
    ],
)
def test_enrich_populates_raw_git_shas_for_every_category(category):
    sha = "1234567890abcdef1234567890abcdef12345678"
    ocr = OCRResult(
        text=f"release {sha}, see commit abcdef0 for the fix",
        word_count=9,
    )
    out = enrich(category, ExtractedFields(), ocr)
    assert out.raw.get("git_shas") == [sha, "abcdef0"]


def test_enrich_omits_raw_git_shas_when_text_has_none():
    ocr = OCRResult(text="just words no shas", word_count=4)
    out = enrich(Category.code_snippet, ExtractedFields(), ocr)
    assert "git_shas" not in out.raw


def test_enrich_preserves_existing_raw_keys_alongside_git_shas():
    ocr = OCRResult(text="see commit deadbee123 for ref", word_count=5)
    fields = ExtractedFields(raw={"trace_id": "abc123"})
    out = enrich(Category.error_stacktrace, fields, ocr)
    assert out.raw["trace_id"] == "abc123"
    assert out.raw["git_shas"] == ["deadbee123"]


def test_enrich_git_shas_coexist_with_other_cross_category_signals():
    """Real OCR pass with every cross-category signal we extract."""
    sha = "1234567890abcdef1234567890abcdef12345678"
    ocr = OCRResult(
        text=(
            "docs https://example.com/help "
            "log /var/log/app.log "
            f"trace {sha} "
            "page oncall@acme.io "
            "tel (415) 555-1234"
        ),
        word_count=12,
    )
    out = enrich(Category.error_stacktrace, ExtractedFields(), ocr)
    assert out.raw["urls"] == ["https://example.com/help"]
    assert out.raw["paths"] == ["/var/log/app.log"]
    assert out.raw["git_shas"] == [sha]
    assert out.raw["emails"] == ["oncall@acme.io"]
    assert out.raw["phones"] == ["4155551234"]
