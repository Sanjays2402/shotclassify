"""Tests for code line-numbering detection.

Code snippets pasted from documentation, code-review tools, or
terminal output sometimes carry a line-number prefix column on every
line: ``1: code`` / ``1| code`` / ``  1  code`` / ``1\\tcode``. The
detector :func:`detect_numbered` decides whether the snippet was
captured with one of these prefixes, and if so returns the body
with the prefix stripped so dashboards render the actual source
without the gutter.

The boolean is exposed via ``CodeFields.numbered`` so dashboards can
surface a "looks copy-pasted from a doc with line numbers"
annotation. The :func:`enrich_code` pipeline runs line-number
detection FIRST so language / dialect / framework / comment-density
detectors all see the de-numbered code.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_numbered, enrich_code

# ---- detect_numbered: positive cases -----------------------------------


def test_colon_separator():
    code = "1: def foo():\n2:     return 1\n3: foo()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is True
    assert stripped == "def foo():\n    return 1\nfoo()"


def test_pipe_separator():
    code = "1|def foo():\n2|    return 1\n3|foo()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is True
    assert stripped == "def foo():\n    return 1\nfoo()"


def test_pipe_separator_with_space():
    code = "1| def foo():\n2|     return 1\n3| foo()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is True
    assert stripped == "def foo():\n    return 1\nfoo()"


def test_tab_separator():
    code = "1\tdef foo():\n2\t    return 1\n3\tfoo()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is True
    assert stripped == "def foo():\n    return 1\nfoo()"


def test_right_aligned_column():
    """``cat -n`` / ``pr -n`` style: 6-wide right-aligned number gutter."""
    code = (
        "     1  def foo():\n"
        "     2      return 1\n"
        "     3  foo()"
    )
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is True
    assert stripped == "def foo():\n    return 1\nfoo()"


def test_right_aligned_column_two_spaces_minimum():
    """Right-aligned column requires AT LEAST 2 spaces between number
    and code so we don't bite into a regular line of code that happens
    to start with a digit + space."""
    code = (
        "1  def foo():\n"
        "2      return 1\n"
        "3  foo()"
    )
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is True


def test_numbers_non_decreasing_allowed():
    """A code-review excerpt that pastes lines 45..47 then 78..80 is
    still numbered (numbers must be non-decreasing, but gaps are OK)."""
    code = "45: a()\n46: b()\n78: c()\n79: d()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is True
    assert stripped == "a()\nb()\nc()\nd()"


def test_starting_number_not_one():
    """Doesn't have to start at 1."""
    code = "100: a()\n101: b()\n102: c()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is True


def test_blank_lines_preserved_in_stripped_body():
    """Blank lines in the input remain blank in the output."""
    code = "1: def foo():\n\n2:     return 1\n\n3: foo()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is True
    assert stripped == "def foo():\n\n    return 1\n\nfoo()"


def test_blank_lines_dont_need_a_number():
    """The detector only requires non-blank lines to carry numbers."""
    code = "1: a\n\n2: b\n\n\n3: c"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is True


def test_long_snippet_all_numbered():
    """A 20-line numbered listing tags as numbered."""
    code = "\n".join(f"{i}: code_line_{i}()" for i in range(1, 21))
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is True
    assert stripped.startswith("code_line_1()")
    assert stripped.endswith("code_line_20()")


# ---- detect_numbered: negative cases -----------------------------------


def test_unnumbered_snippet():
    code = "def foo():\n    return 1\nfoo()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is False
    assert stripped == code


def test_mixed_separators_rejected():
    """A snippet that mixes ``1:`` and ``2|`` is not numbered."""
    code = "1: a()\n2| b()\n3: c()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is False
    assert stripped == code


def test_one_unnumbered_line_in_middle_rejected():
    """Even one missing prefix kills the detection (strict)."""
    code = "1: a()\nbare line\n3: c()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is False


def test_too_short_two_lines_rejected():
    """Below the 3-line minimum, the signal is unreliable."""
    code = "1: a()\n2: b()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is False


def test_single_line_rejected():
    """A 1-line snippet is never numbered."""
    code = "1: a()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is False


def test_numbers_decreasing_rejected():
    """Numbers that decrease (3, 2, 1) reject the detection."""
    code = "3: a()\n2: b()\n1: c()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is False


def test_empty_string():
    is_numbered, stripped = detect_numbered("")
    assert is_numbered is False
    assert stripped == ""


def test_only_whitespace():
    is_numbered, stripped = detect_numbered("   \n\n  ")
    assert is_numbered is False


def test_normal_code_with_leading_digit_call():
    """``1 + 1`` is not a numbered listing -- the digit isn't a line number."""
    code = "1 + 1\n2 + 2\n3 + 3"
    is_numbered, stripped = detect_numbered(code)
    # ``1 + 1`` matches the right-aligned column pattern (digit + at
    # least one space + rest). We use 2+ spaces as the minimum for
    # the right-aligned column to prevent exactly this false-positive.
    # ``1 + 1`` is one space, so it should reject.
    assert is_numbered is False


def test_code_with_legit_colon_lines_not_numbered():
    """Python dict initialisers with bare ``key: value`` lines should NOT
    tag as numbered when the keys are not consecutive numbers."""
    code = "a: 1\nb: 2\nc: 3"
    is_numbered, stripped = detect_numbered(code)
    # 'a' is not a digit -> colon pattern fails on line 1 -> reject.
    assert is_numbered is False


def test_csv_like_first_column_not_numbered():
    """A CSV with a numeric first column would falsely match the right-
    aligned pattern if we weren't careful. We are careful because the
    detector requires 2+ spaces between the number and the next column,
    while CSVs use a comma."""
    code = "1,foo,bar\n2,baz,qux\n3,a,b"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is False


def test_long_lines_with_digits_not_numbered():
    """A snippet whose first line happens to start with a digit, but
    the rest don't, rejects."""
    code = "1: only_first_line_is_numbered\nbut_this_isnt()\nnor_this()"
    is_numbered, stripped = detect_numbered(code)
    assert is_numbered is False


# ---- enrich_code integration -------------------------------------------


def test_enrich_code_strips_numbering_and_sets_flag():
    code = (
        "1: def foo():\n"
        "2:     return 1\n"
        "3: foo()"
    )
    fields = enrich_code(CodeFields(code=code), OCRResult(text="", confidence=1.0))
    assert fields.numbered is True
    assert fields.code == "def foo():\n    return 1\nfoo()"
    assert fields.line_count == 3


def test_enrich_code_language_detected_on_stripped_body():
    """Language detector runs on the de-numbered body -- ``def foo()``
    should be detected as python even though the input had ``1: def
    foo()``."""
    code = (
        "1: def foo():\n"
        "2:     return 1\n"
        "3:     # nothing here\n"
    )
    fields = enrich_code(CodeFields(code=code), OCRResult(text="", confidence=1.0))
    assert fields.numbered is True
    assert fields.language == "python"


def test_enrich_code_unnumbered_preserves_body():
    """An unnumbered snippet flows through unchanged."""
    code = "def foo():\n    return 1\nfoo()"
    fields = enrich_code(CodeFields(code=code), OCRResult(text="", confidence=1.0))
    assert fields.numbered is False
    assert fields.code == code


def test_enrich_code_comment_density_on_stripped_body():
    """Comment density is computed on the de-numbered body, so the
    line-number column doesn't artificially lower the density."""
    code = (
        "1: # docstring\n"
        "2: # more docs\n"
        "3: # final\n"
    )
    fields = enrich_code(CodeFields(code=code), OCRResult(text="", confidence=1.0))
    assert fields.numbered is True
    # Every non-blank line in the stripped body opens with ``#`` so
    # comment density is 1.0.
    assert fields.comment_density == 1.0


def test_enrich_code_caller_supplied_numbered_preserved():
    """A caller that already set numbered=True keeps the flag."""
    code = "1: a()\n2: b()\n3: c()"
    fields = enrich_code(
        CodeFields(code=code, numbered=True),
        OCRResult(text="", confidence=1.0),
    )
    assert fields.numbered is True
    assert fields.code == "a()\nb()\nc()"


def test_enrich_code_right_aligned_column_strips():
    """cat -n style right-aligned column also strips cleanly."""
    code = (
        "     1  def foo():\n"
        "     2      return 1\n"
        "     3  foo()"
    )
    fields = enrich_code(CodeFields(code=code), OCRResult(text="", confidence=1.0))
    assert fields.numbered is True
    assert fields.code == "def foo():\n    return 1\nfoo()"
    assert fields.language == "python"


def test_enrich_code_pipe_separator_strips():
    code = (
        "1| def foo():\n"
        "2|     return 1\n"
        "3| foo()"
    )
    fields = enrich_code(CodeFields(code=code), OCRResult(text="", confidence=1.0))
    assert fields.numbered is True
    assert fields.code == "def foo():\n    return 1\nfoo()"


# ---- LLM wire format integration ---------------------------------------


def test_classify_wire_format_round_trips_numbered_true():
    """``CodeFields.numbered`` round-trips through the LLM client."""
    from shotclassify_classify.client import _parse_llm_payload

    payload = {
        "primary": "code_snippet",
        "confidences": {"code_snippet": 0.99},
        "fields": {
            "code": {
                "language": "python",
                "code": "def foo():\n    return 1",
                "numbered": True,
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.code is not None
    assert fields.code.numbered is True


def test_classify_wire_format_round_trips_numbered_default_false():
    """When the LLM omits ``numbered``, it defaults to False."""
    from shotclassify_classify.client import _parse_llm_payload

    payload = {
        "primary": "code_snippet",
        "confidences": {"code_snippet": 0.99},
        "fields": {
            "code": {
                "language": "python",
                "code": "def foo():\n    return 1",
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.code is not None
    assert fields.code.numbered is False
