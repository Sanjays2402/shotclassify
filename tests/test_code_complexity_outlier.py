"""Code complexity outlier flag tests.

The CodeFields.complexity slot now includes an ``outlier: bool``
flag set to True for the SINGLE highest-complexity function when:

1. Two or more functions are detected.
2. That function's complexity is >= 10 (McCabe high-complexity
   threshold).
3. That function's complexity is STRICTLY greater than the
   next-highest (no tie).
"""
from __future__ import annotations

from shotclassify_common import OCRResult
from shotclassify_extract.code import enrich_code, extract_complexity

# ---- Single function never flagged -------------------------------


def test_single_function_simple_no_outlier():
    code = "def f():\n    return 1\n"
    out = extract_complexity(code, "python")
    assert len(out) == 1
    assert out[0]["outlier"] is False


def test_single_function_high_complexity_no_outlier():
    # Even when complexity is 15, a single function alone doesn't
    # get the outlier flag because there's no baseline to compare
    # against.
    code = (
        "def f(x):\n"
        + "    if x > 0:\n        pass\n" * 15
        + "    return 0\n"
    )
    out = extract_complexity(code, "python")
    assert len(out) == 1
    assert int(out[0]["complexity"]) >= 10
    # Single function -- no outlier flag.
    assert out[0]["outlier"] is False


# ---- Two simple functions -- no outlier --------------------------


def test_two_simple_functions_no_outlier():
    code = (
        "def a():\n    return 1\n"
        "def b():\n    return 2\n"
    )
    out = extract_complexity(code, "python")
    assert len(out) == 2
    assert all(e["outlier"] is False for e in out)


def test_two_moderate_functions_no_outlier_below_threshold():
    # Both functions below the 10-complexity threshold -> no flag
    # even though one is bigger.
    code = (
        "def a():\n"
        "    if 1:\n        pass\n"
        "    return 1\n"
        "def b(x):\n"
        + "    if x:\n        pass\n" * 8
        + "    return 0\n"
    )
    out = extract_complexity(code, "python")
    assert len(out) == 2
    # b should have complexity ~9 which is < 10. No outlier.
    assert all(e["outlier"] is False for e in out)


# ---- Outlier flagged when top is >= 10 ---------------------------


def test_clear_outlier_flagged():
    # a is simple (complexity 1), b has 15 branches (complexity 16).
    # Top >= 10 AND strictly greater than baseline of 1 -> outlier.
    code = (
        "def a():\n    return 1\n"
        "def b(x):\n"
        + "    if x:\n        pass\n" * 15
        + "    return 0\n"
    )
    out = extract_complexity(code, "python")
    assert len(out) == 2
    by_name = {e["name"]: e for e in out}
    assert by_name["b"]["outlier"] is True
    assert by_name["a"]["outlier"] is False


def test_outlier_with_exactly_10_complexity():
    # Top function has complexity exactly 10 (threshold).
    code = (
        "def small():\n    return 1\n"
        "def big(x):\n"
        + "    if x:\n        pass\n" * 9
        + "    return 0\n"
    )
    out = extract_complexity(code, "python")
    by_name = {e["name"]: e for e in out}
    # big has complexity 10 (1 base + 9 ifs), small has 1.
    assert by_name["big"]["complexity"] == 10
    assert by_name["big"]["outlier"] is True


def test_outlier_at_9_not_flagged():
    # Top complexity 9 (< 10) -> NO outlier.
    code = (
        "def small():\n    return 1\n"
        "def big(x):\n"
        + "    if x:\n        pass\n" * 8
        + "    return 0\n"
    )
    out = extract_complexity(code, "python")
    by_name = {e["name"]: e for e in out}
    assert by_name["big"]["complexity"] == 9
    assert by_name["big"]["outlier"] is False
    assert by_name["small"]["outlier"] is False


# ---- Tie at top -> no outlier ------------------------------------


def test_tied_top_complexity_no_outlier():
    # Two functions BOTH with complexity 12 -> no outlier flag
    # because we don't arbitrarily pick a winner.
    code = (
        "def a(x):\n"
        + "    if x:\n        pass\n" * 11
        + "    return 0\n"
        "def b(x):\n"
        + "    if x:\n        pass\n" * 11
        + "    return 0\n"
    )
    out = extract_complexity(code, "python")
    assert len(out) == 2
    # Both should be complexity 12.
    assert all(int(e["complexity"]) == 12 for e in out)
    # But neither is the outlier.
    assert all(e["outlier"] is False for e in out)


def test_tied_top_three_functions_no_outlier():
    code = (
        "def a(x):\n"
        + "    if x:\n        pass\n" * 11
        + "    return 0\n"
        "def b(x):\n"
        + "    if x:\n        pass\n" * 11
        + "    return 0\n"
        "def c():\n    return 1\n"
    )
    out = extract_complexity(code, "python")
    # a and b are tied at 12, c is 1.
    # Top is 12, next is 12 (NOT strictly greater) -> no outlier.
    by_name = {e["name"]: e for e in out}
    assert by_name["a"]["outlier"] is False
    assert by_name["b"]["outlier"] is False
    assert by_name["c"]["outlier"] is False


# ---- Three functions with clear outlier --------------------------


def test_three_functions_clear_outlier():
    # Two simple functions and one highly complex.
    code = (
        "def a():\n    return 1\n"
        "def b(x):\n    if x:\n        return 1\n    return 0\n"
        "def huge(x):\n"
        + "    if x:\n        pass\n" * 20
        + "    return 0\n"
    )
    out = extract_complexity(code, "python")
    assert len(out) == 3
    by_name = {e["name"]: e for e in out}
    assert by_name["huge"]["outlier"] is True
    assert by_name["a"]["outlier"] is False
    assert by_name["b"]["outlier"] is False


def test_outlier_is_first_seen_when_unique():
    # The outlier flag is set on the first occurrence of the top
    # score (preserves first-seen-order for deterministic
    # placement, though here only one function has the top score).
    code = (
        "def small():\n    return 1\n"
        "def medium(x):\n    if x:\n        return 1\n    return 0\n"
        "def winner(x):\n"
        + "    if x:\n        pass\n" * 15
        + "    return 0\n"
    )
    out = extract_complexity(code, "python")
    by_name = {e["name"]: e for e in out}
    assert by_name["winner"]["outlier"] is True


# ---- JS / TS outlier detection ----------------------------------


def test_js_two_functions_outlier():
    code = (
        "function simple() { return 1; }\n"
        "function complex(x) {\n"
        + "  if (x) { }\n" * 15
        + "  return 0;\n}\n"
    )
    out = extract_complexity(code, "javascript")
    assert len(out) == 2
    by_name = {e["name"]: e for e in out}
    assert by_name["complex"]["outlier"] is True
    assert by_name["simple"]["outlier"] is False


def test_typescript_outlier():
    code = (
        "function a(x: number): number { return x; }\n"
        "function b(x: number): number {\n"
        + "  if (x > 0) { }\n" * 12
        + "  return 0;\n}\n"
    )
    out = extract_complexity(code, "typescript")
    assert len(out) == 2
    by_name = {e["name"]: e for e in out}
    assert by_name["b"]["outlier"] is True


# ---- Outlier flag in enrich_code integration ---------------------


def test_enrich_code_sets_outlier_flag():
    code = (
        "def small():\n    return 1\n"
        "def big(x):\n"
        + "    if x:\n        pass\n" * 15
        + "    return 0\n"
    )
    out = enrich_code(None, OCRResult(text=code))
    assert len(out.complexity) == 2
    by_name = {e["name"]: e for e in out.complexity}
    assert by_name["big"]["outlier"] is True
    assert by_name["small"]["outlier"] is False


def test_enrich_code_no_outlier_for_single_function():
    code = "def f(x):\n" + "    if x:\n        pass\n" * 15 + "    return 0\n"
    out = enrich_code(None, OCRResult(text=code))
    assert len(out.complexity) == 1
    assert out.complexity[0]["outlier"] is False


# ---- All complexity entries carry the outlier key ----------------


def test_all_entries_have_outlier_key():
    """Every complexity entry should have the ``outlier`` key,
    even when there's no outlier (defaults to False)."""
    code = (
        "def a():\n    return 1\n"
        "def b():\n    return 2\n"
        "def c():\n    return 3\n"
    )
    out = extract_complexity(code, "python")
    for entry in out:
        assert "outlier" in entry
        assert isinstance(entry["outlier"], bool)


# ---- Outlier value type stability --------------------------------


def test_outlier_is_bool_not_int():
    code = (
        "def a():\n    return 1\n"
        "def b(x):\n"
        + "    if x:\n        pass\n" * 15
        + "    return 0\n"
    )
    out = extract_complexity(code, "python")
    by_name = {e["name"]: e for e in out}
    assert by_name["b"]["outlier"] is True  # Strict identity check.
    assert by_name["a"]["outlier"] is False


# ---- Multiple ties resolved cleanly ------------------------------


def test_almost_tied_top_strict_greater():
    # Top has complexity 11, second has 10. 11 > 10 and both >= 10
    # so the outlier IS flagged (strict greater).
    code = (
        "def almost_top(x):\n"
        + "    if x:\n        pass\n" * 9
        + "    return 0\n"
        "def top(x):\n"
        + "    if x:\n        pass\n" * 10
        + "    return 0\n"
    )
    out = extract_complexity(code, "python")
    by_name = {e["name"]: e for e in out}
    assert by_name["almost_top"]["complexity"] == 10
    assert by_name["top"]["complexity"] == 11
    # top is strictly greater AND >= 10 -> outlier.
    assert by_name["top"]["outlier"] is True
    assert by_name["almost_top"]["outlier"] is False


# ---- Empty / no-functions cases ----------------------------------


def test_empty_code_no_outlier():
    out = extract_complexity("", "python")
    assert out == []


def test_no_functions_no_outlier():
    out = extract_complexity("x = 1\ny = 2\n", "python")
    assert out == []
