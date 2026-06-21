"""Tests for the cross-category filesystem-path extractor.

Paths found in OCR text are stashed under ``ExtractedFields.raw["paths"]``
by the enrich pipeline so dashboards and routing rules have a single
place to look regardless of which category the screenshot belongs to.

Recognised shapes:
* POSIX absolute (``/usr/local/bin/foo``, ``/Users/sanjay/x.py``)
* Home-relative (``~/dotfiles/zshrc``)
* Windows drive (``C:\\Users\\Foo\\file.txt`` / ``D:/Projects/x``)
* UNC shares (``\\\\server\\share\\file``)

Deliberately NOT matched:
* Bare filenames without a directory (``foo.txt``) -- too noisy.
* Relative paths without a clear prefix (``src/foo.py``) -- ambiguous.

URL spans are masked out before scanning so a URL's path component
does not double-count under both raw["urls"] and raw["paths"].
"""
from __future__ import annotations

import pytest
from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_paths


def test_posix_absolute_path():
    assert extract_paths("see /usr/local/bin/foo for details") == [
        "/usr/local/bin/foo"
    ]


def test_posix_path_with_dot_extension():
    assert extract_paths("opened /Users/sanjay/code/x.py") == [
        "/Users/sanjay/code/x.py"
    ]


def test_home_relative_path():
    assert extract_paths("source ~/dotfiles/zshrc") == ["~/dotfiles/zshrc"]


def test_home_relative_with_user():
    assert extract_paths("ls ~bob/data/foo.csv") == ["~bob/data/foo.csv"]


def test_windows_drive_with_backslashes():
    text = "open C:\\Users\\Foo\\file.txt now"
    assert "C:\\Users\\Foo\\file.txt" in extract_paths(text)


def test_windows_drive_with_forward_slashes():
    text = "see D:/Projects/x/main.py"
    assert "D:/Projects/x/main.py" in extract_paths(text)


def test_unc_share():
    text = "share at \\\\fileserver\\public\\readme.txt please"
    assert "\\\\fileserver\\public\\readme.txt" in extract_paths(text)


def test_trims_trailing_punctuation():
    cases = [
        ("see /var/log/app.log.", "/var/log/app.log"),
        ("see /var/log/app.log,", "/var/log/app.log"),
        ("(see /var/log/app.log)", "/var/log/app.log"),
        ("ref: /var/log/app.log!", "/var/log/app.log"),
    ]
    for text, expected in cases:
        paths = extract_paths(text)
        assert expected in paths, f"failed: {text!r} -> {paths!r}"


def test_dedup_preserves_first_seen_order():
    text = (
        "first /a/b/c.txt\n"
        "later /d/e/f.txt\n"
        "again /a/b/c.txt (dup)\n"
    )
    assert extract_paths(text) == [
        "/a/b/c.txt",
        "/d/e/f.txt",
    ]


def test_bare_slash_not_matched():
    """A bare ``/`` is not a path."""
    assert extract_paths("/ is the root") == []


def test_single_segment_rejected():
    """``/etc`` alone is too short -- we require at least one ``/seg``
    grouping after the initial segment (so ``/etc/passwd`` works)."""
    assert extract_paths("see /etc only") == []


def test_url_path_does_not_leak_into_paths():
    """A URL's path component must not double-count under raw["paths"]."""
    text = "docs at https://example.com/api/users/me"
    assert extract_paths(text) == []


def test_path_alongside_url_only_records_path():
    text = (
        "see https://example.com/docs and /usr/local/bin/foo"
    )
    assert extract_paths(text) == ["/usr/local/bin/foo"]


def test_no_paths_returns_empty_list():
    assert extract_paths("just words here") == []
    assert extract_paths("") == []
    assert extract_paths(None) == []  # type: ignore[arg-type]


def test_cap_at_50():
    text = "\n".join(f"line /dir/file{i}.txt" for i in range(120))
    paths = extract_paths(text)
    assert len(paths) == 50
    assert paths[0] == "/dir/file0.txt"
    assert paths[-1] == "/dir/file49.txt"


# ---- pipeline integration --------------------------------------------------


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
def test_enrich_populates_raw_paths_for_every_category(category):
    ocr = OCRResult(
        text="opened /Users/sanjay/code/x.py and /var/log/build.log",
        word_count=6,
    )
    out = enrich(category, ExtractedFields(), ocr)
    assert out.raw.get("paths") == [
        "/Users/sanjay/code/x.py",
        "/var/log/build.log",
    ]


def test_enrich_omits_raw_paths_when_text_has_none():
    ocr = OCRResult(text="just words no paths", word_count=4)
    out = enrich(Category.code_snippet, ExtractedFields(), ocr)
    assert "paths" not in out.raw


def test_enrich_preserves_existing_raw_keys_alongside_paths():
    ocr = OCRResult(text="see /var/log/foo.log here", word_count=4)
    fields = ExtractedFields(raw={"trace_id": "abc123"})
    out = enrich(Category.error_stacktrace, fields, ocr)
    assert out.raw["trace_id"] == "abc123"
    assert out.raw["paths"] == ["/var/log/foo.log"]


def test_enrich_populates_both_urls_and_paths():
    """When OCR contains both URLs and paths, both raw keys are
    populated and they do not interfere with each other."""
    ocr = OCRResult(
        text="docs https://example.com/help and /Users/sanjay/x.py",
        word_count=5,
    )
    out = enrich(Category.error_stacktrace, ExtractedFields(), ocr)
    assert out.raw["urls"] == ["https://example.com/help"]
    assert out.raw["paths"] == ["/Users/sanjay/x.py"]


def test_python_stacktrace_paths_captured():
    """A real Python traceback has paths inside `File "..."` lines; the
    cross-category extractor should pick them up alongside whatever
    the error extractor itself stores."""
    text = (
        'Traceback (most recent call last):\n'
        '  File "/app/services/users.py", line 42, in get_user\n'
        '    return User.objects.get(id=uid)\n'
        'KeyError: 1\n'
    )
    out = enrich(Category.error_stacktrace, ExtractedFields(), OCRResult(text=text, word_count=12))
    assert out.raw["paths"] == ["/app/services/users.py"]
