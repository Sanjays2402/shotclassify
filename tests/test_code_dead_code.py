"""Code dead-code / linter-suppression marker detection.

The new ``CodeFields.dead_code`` slot captures per-line / next-line
/ block markers a developer drops into code to silence one specific
linter check at one specific call site:

* Python: ``# noqa`` / ``# type: ignore`` / ``# pyright: ignore`` /
  ``# pylint: disable=`` / ``# pragma: no cover``
* JS / TS: ``// eslint-disable`` family / ``// tslint:disable`` /
  ``// stylelint-disable`` / ``// prettier-ignore`` /
  ``// @ts-ignore`` / ``// @ts-expect-error`` / ``// @ts-nocheck``
* Go: ``// nolint`` / ``//nolint:errcheck``
* Rust: ``#[allow(dead_code)]`` / ``#[deny(...)]`` / ``#[warn(...)]``
* C / C++: ``// NOLINT`` family / ``// cppcheck-suppress``
* C#: ``#pragma warning disable CS0168``
* Java: ``@SuppressWarnings(...)`` / ``// CHECKSTYLE.OFF: ...``
* Kotlin: ``@Suppress(...)``
* Shell: ``# shellcheck disable=SC2086``
* Sonar: ``// NOSONAR``
* Swift: ``// swiftlint:disable line_length``

Each entry is a ``{"tool", "code", "scope"}`` dict.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import enrich_code, extract_dead_code

# ---- Python: noqa --------------------------------------------------


def test_noqa_blanket():
    out = extract_dead_code("x = eval(s)  # noqa")
    assert out == [{"tool": "noqa", "code": None, "scope": "line"}]


def test_noqa_with_single_code():
    out = extract_dead_code("x = eval(s)  # noqa: S307")
    assert out == [{"tool": "noqa", "code": "S307", "scope": "line"}]


def test_noqa_with_multi_codes_comma_separated():
    out = extract_dead_code("x = 1  # noqa: E501,F401")
    assert out == [
        {"tool": "noqa", "code": "E501", "scope": "line"},
        {"tool": "noqa", "code": "F401", "scope": "line"},
    ]


def test_noqa_with_multi_codes_space_separated():
    out = extract_dead_code("x = 1  # noqa: E501 F401")
    assert out == [
        {"tool": "noqa", "code": "E501", "scope": "line"},
        {"tool": "noqa", "code": "F401", "scope": "line"},
    ]


def test_noqa_ruff_long_code():
    """ruff uses longer plugin-prefixed codes like ``PLR1714``."""
    out = extract_dead_code("if x == 1 or x == 2:  # noqa: PLR1714")
    assert out == [{"tool": "noqa", "code": "PLR1714", "scope": "line"}]


# ---- Python: type: ignore -----------------------------------------


def test_type_ignore_blanket():
    out = extract_dead_code('x: int = "x"  # type: ignore')
    assert out == [{"tool": "mypy", "code": None, "scope": "line"}]


def test_type_ignore_with_specific_code():
    out = extract_dead_code('x: int = "x"  # type: ignore[assignment]')
    assert out == [{"tool": "mypy", "code": "assignment", "scope": "line"}]


def test_type_ignore_multi_codes():
    out = extract_dead_code("x = foo()  # type: ignore[assignment,arg-type]")
    assert out == [
        {"tool": "mypy", "code": "assignment", "scope": "line"},
        {"tool": "mypy", "code": "arg-type", "scope": "line"},
    ]


# ---- Python: pyright -----------------------------------------------


def test_pyright_blanket():
    out = extract_dead_code("import foo  # pyright: ignore")
    assert out == [{"tool": "pyright", "code": None, "scope": "line"}]


def test_pyright_with_specific_code():
    out = extract_dead_code("import foo  # pyright: ignore[reportMissingImports]")
    assert out == [
        {"tool": "pyright", "code": "reportMissingImports", "scope": "line"}
    ]


# ---- Python: pylint ------------------------------------------------


def test_pylint_disable_named_rule():
    out = extract_dead_code("def f(x): return x  # pylint: disable=missing-docstring")
    assert out == [{"tool": "pylint", "code": "missing-docstring", "scope": "block"}]


def test_pylint_disable_multi_rules():
    out = extract_dead_code(
        "# pylint: disable=missing-docstring,unused-import,too-many-arguments"
    )
    assert out == [
        {"tool": "pylint", "code": "missing-docstring", "scope": "block"},
        {"tool": "pylint", "code": "unused-import", "scope": "block"},
        {"tool": "pylint", "code": "too-many-arguments", "scope": "block"},
    ]


def test_pylint_enable():
    out = extract_dead_code("# pylint: enable=missing-docstring")
    assert out == [{"tool": "pylint", "code": "missing-docstring", "scope": "block"}]


# ---- Python: coverage.py ------------------------------------------


def test_coverage_no_cover():
    out = extract_dead_code("if False:  # pragma: no cover")
    assert out == [{"tool": "coverage", "code": None, "scope": "line"}]


def test_coverage_no_branch():
    out = extract_dead_code("if x:  # pragma: no branch")
    assert out == [{"tool": "coverage", "code": None, "scope": "line"}]


# ---- JS / TS: eslint -----------------------------------------------


def test_eslint_disable_blanket_block():
    out = extract_dead_code("// eslint-disable")
    assert out == [{"tool": "eslint", "code": None, "scope": "block"}]


def test_eslint_disable_line_named_rule():
    out = extract_dead_code(
        "const x = 1; // eslint-disable-line no-unused-vars"
    )
    assert out == [{"tool": "eslint", "code": "no-unused-vars", "scope": "line"}]


def test_eslint_disable_next_line():
    out = extract_dead_code("// eslint-disable-next-line no-unused-vars")
    assert out == [
        {"tool": "eslint", "code": "no-unused-vars", "scope": "next-line"}
    ]


def test_eslint_block_comment_disable():
    out = extract_dead_code("/* eslint-disable */")
    assert out == [{"tool": "eslint", "code": None, "scope": "block"}]


def test_eslint_scoped_plugin_rule():
    out = extract_dead_code(
        "const x: any = 1; // eslint-disable-line @typescript-eslint/no-explicit-any"
    )
    assert out == [
        {
            "tool": "eslint",
            "code": "@typescript-eslint/no-explicit-any",
            "scope": "line",
        }
    ]


def test_eslint_enable_block_end():
    out = extract_dead_code("// eslint-enable")
    assert out == [{"tool": "eslint", "code": None, "scope": "block"}]


# ---- JS / TS: tslint -----------------------------------------------


def test_tslint_disable_with_code():
    out = extract_dead_code("// tslint:disable:no-any")
    assert out == [{"tool": "tslint", "code": "no-any", "scope": "block"}]


def test_tslint_enable():
    out = extract_dead_code("// tslint:enable")
    assert out == [{"tool": "tslint", "code": None, "scope": "block"}]


# ---- CSS: stylelint ------------------------------------------------


def test_stylelint_disable_with_rule():
    out = extract_dead_code("/* stylelint-disable color-no-hex */")
    assert out == [{"tool": "stylelint", "code": "color-no-hex", "scope": "block"}]


def test_stylelint_disable_next_line():
    out = extract_dead_code("/* stylelint-disable-next-line color-no-hex */")
    assert out == [
        {"tool": "stylelint", "code": "color-no-hex", "scope": "next-line"}
    ]


# ---- prettier (formatter) -----------------------------------------


def test_prettier_ignore_line_comment():
    out = extract_dead_code("// prettier-ignore")
    assert out == [{"tool": "prettier", "code": None, "scope": "line"}]


def test_prettier_ignore_block_comment():
    out = extract_dead_code("/* prettier-ignore */")
    assert out == [{"tool": "prettier", "code": None, "scope": "line"}]


# ---- TypeScript compiler ------------------------------------------


def test_ts_ignore_is_next_line():
    out = extract_dead_code("// @ts-ignore")
    assert out == [{"tool": "typescript", "code": None, "scope": "next-line"}]


def test_ts_expect_error_is_next_line():
    out = extract_dead_code("// @ts-expect-error")
    assert out == [
        {"tool": "typescript", "code": None, "scope": "next-line"}
    ]


def test_ts_nocheck_is_file_scope():
    """``// @ts-nocheck`` disables type-checking for the whole file."""
    out = extract_dead_code("// @ts-nocheck")
    assert out == [{"tool": "typescript", "code": None, "scope": "file"}]


# ---- Go: nolint ----------------------------------------------------


def test_nolint_blanket():
    out = extract_dead_code("if cond { return }  // nolint")
    assert out == [{"tool": "nolint", "code": None, "scope": "line"}]


def test_nolint_with_single_code():
    out = extract_dead_code("if cond { return }  // nolint:errcheck")
    assert out == [{"tool": "nolint", "code": "errcheck", "scope": "line"}]


def test_nolint_multi_codes():
    out = extract_dead_code("//nolint:errcheck,gosec")
    assert out == [
        {"tool": "nolint", "code": "errcheck", "scope": "line"},
        {"tool": "nolint", "code": "gosec", "scope": "line"},
    ]


def test_nolint_zero_space_form_per_golangci_convention():
    """golangci-lint requires ``//nolint`` with NO space for some forms."""
    out = extract_dead_code("//nolint:errcheck")
    assert out == [{"tool": "nolint", "code": "errcheck", "scope": "line"}]


# ---- Rust: #[allow(...)] / #[deny(...)] / #[warn(...)] -------------


def test_rust_allow_dead_code():
    out = extract_dead_code("#[allow(dead_code)]")
    assert out == [{"tool": "rustc", "code": "dead_code", "scope": "block"}]


def test_rust_allow_clippy_namespaced():
    """Clippy rules use ``clippy::`` namespace prefix."""
    out = extract_dead_code("#[allow(clippy::needless_return)]")
    assert out == [
        {"tool": "rustc", "code": "clippy::needless_return", "scope": "block"}
    ]


def test_rust_deny_warnings():
    out = extract_dead_code("#[deny(warnings)]")
    assert out == [{"tool": "rustc", "code": "warnings", "scope": "block"}]


def test_rust_warn_attribute():
    out = extract_dead_code("#[warn(unused_imports)]")
    assert out == [{"tool": "rustc", "code": "unused_imports", "scope": "block"}]


def test_rust_outer_attribute_is_file_scope():
    """``#![allow(...)]`` (with `!`) suppresses at module / crate level."""
    out = extract_dead_code("#![allow(non_snake_case)]")
    assert out == [{"tool": "rustc", "code": "non_snake_case", "scope": "file"}]


def test_rust_multi_lints_in_one_attribute():
    out = extract_dead_code("#[allow(dead_code, unused_variables)]")
    assert out == [
        {"tool": "rustc", "code": "dead_code", "scope": "block"},
        {"tool": "rustc", "code": "unused_variables", "scope": "block"},
    ]


# ---- C / C++: clang-tidy ------------------------------------------


def test_clang_tidy_nolint_per_line():
    out = extract_dead_code("auto* p = ptr; // NOLINT")
    assert out == [{"tool": "clang-tidy", "code": None, "scope": "line"}]


def test_clang_tidy_nolint_with_specific_check():
    out = extract_dead_code("auto* p = ptr; // NOLINT(misc-x)")
    assert out == [{"tool": "clang-tidy", "code": "misc-x", "scope": "line"}]


def test_clang_tidy_nolintnextline():
    out = extract_dead_code("// NOLINTNEXTLINE(misc-x)")
    assert out == [{"tool": "clang-tidy", "code": "misc-x", "scope": "next-line"}]


def test_clang_tidy_nolintbegin_nolintend_block():
    out = extract_dead_code("// NOLINTBEGIN\n// NOLINTEND")
    assert out == [{"tool": "clang-tidy", "code": None, "scope": "block"}]


def test_cppcheck_suppress():
    out = extract_dead_code("// cppcheck-suppress unusedFunction")
    assert out == [{"tool": "cppcheck", "code": "unusedFunction", "scope": "line"}]


# ---- C#: #pragma warning ------------------------------------------


def test_csharp_pragma_disable_specific_warning():
    out = extract_dead_code("#pragma warning disable CS0168")
    assert out == [{"tool": "csharp", "code": "CS0168", "scope": "block"}]


def test_csharp_pragma_disable_multiple_warnings():
    out = extract_dead_code("#pragma warning disable CS0168, CS0219")
    assert out == [
        {"tool": "csharp", "code": "CS0168", "scope": "block"},
        {"tool": "csharp", "code": "CS0219", "scope": "block"},
    ]


def test_csharp_pragma_restore():
    out = extract_dead_code("#pragma warning restore CS0168")
    assert out == [{"tool": "csharp", "code": "CS0168", "scope": "block"}]


# ---- Java: @SuppressWarnings / Checkstyle -------------------------


def test_java_suppresswarnings_single():
    out = extract_dead_code('@SuppressWarnings("unchecked")')
    assert out == [{"tool": "suppresswarnings", "code": "unchecked", "scope": "block"}]


def test_java_suppresswarnings_multi():
    out = extract_dead_code('@SuppressWarnings({"unchecked", "rawtypes"})')
    assert out == [
        {"tool": "suppresswarnings", "code": "unchecked", "scope": "block"},
        {"tool": "suppresswarnings", "code": "rawtypes", "scope": "block"},
    ]


def test_checkstyle_off_specific_rule():
    out = extract_dead_code("// CHECKSTYLE.OFF: LineLength")
    assert out == [{"tool": "checkstyle", "code": "LineLength", "scope": "block"}]


def test_checkstyle_off_blanket():
    out = extract_dead_code("// CHECKSTYLE:OFF")
    assert out == [{"tool": "checkstyle", "code": None, "scope": "block"}]


def test_checkstyle_on_blanket():
    out = extract_dead_code("// CHECKSTYLE:ON")
    assert out == [{"tool": "checkstyle", "code": None, "scope": "block"}]


# ---- Kotlin: @Suppress --------------------------------------------


def test_kotlin_suppress_single():
    out = extract_dead_code('@Suppress("UNUSED_PARAMETER")')
    assert out == [
        {"tool": "kotlin-suppress", "code": "UNUSED_PARAMETER", "scope": "block"}
    ]


def test_kotlin_suppress_multi():
    out = extract_dead_code('@Suppress("UNUSED_PARAMETER", "UNCHECKED_CAST")')
    assert out == [
        {"tool": "kotlin-suppress", "code": "UNUSED_PARAMETER", "scope": "block"},
        {"tool": "kotlin-suppress", "code": "UNCHECKED_CAST", "scope": "block"},
    ]


# ---- Shell: shellcheck --------------------------------------------


def test_shellcheck_disable_single_code():
    out = extract_dead_code("# shellcheck disable=SC2086")
    assert out == [{"tool": "shellcheck", "code": "SC2086", "scope": "line"}]


def test_shellcheck_disable_multi_codes():
    out = extract_dead_code("# shellcheck disable=SC2086,SC2034")
    assert out == [
        {"tool": "shellcheck", "code": "SC2086", "scope": "line"},
        {"tool": "shellcheck", "code": "SC2034", "scope": "line"},
    ]


# ---- SonarQube ----------------------------------------------------


def test_nosonar_blanket():
    out = extract_dead_code("foo();  // NOSONAR")
    assert out == [{"tool": "sonarqube", "code": None, "scope": "line"}]


# ---- Swift: swiftlint ---------------------------------------------


def test_swiftlint_disable_with_rule():
    out = extract_dead_code("// swiftlint:disable line_length")
    assert out == [{"tool": "swiftlint", "code": "line_length", "scope": "block"}]


def test_swiftlint_disable_next_line_modifier():
    out = extract_dead_code("// swiftlint:disable:next line_length")
    assert out == [
        {"tool": "swiftlint", "code": "line_length", "scope": "next-line"}
    ]


def test_swiftlint_enable():
    out = extract_dead_code("// swiftlint:enable line_length")
    assert out == [{"tool": "swiftlint", "code": "line_length", "scope": "block"}]


# ---- Multi-tool snippet -------------------------------------------


def test_multiple_tools_in_one_snippet():
    """A code captures often mix Python and JS markers in the same screenshot."""
    src = """\
def f(x):  # type: ignore
    return eval(x)  # noqa: S307

// eslint-disable-next-line no-unused-vars
const y = 1;
"""
    out = extract_dead_code(src)
    # Order: noqa pass first, then mypy, then eslint
    kinds = [(e["tool"], e["code"], e["scope"]) for e in out]
    assert ("noqa", "S307", "line") in kinds
    assert ("mypy", None, "line") in kinds
    assert ("eslint", "no-unused-vars", "next-line") in kinds


# ---- Dedupe --------------------------------------------------------


def test_dedupe_same_tool_code_scope():
    """The same (tool, code, scope) tuple doesn't repeat."""
    src = """\
# noqa: E501
# noqa: E501
"""
    out = extract_dead_code(src)
    assert out == [{"tool": "noqa", "code": "E501", "scope": "line"}]


def test_same_code_different_scope_keeps_both():
    """``# noqa: E501`` on one line vs as a separate marker on
    another line keeps the same single entry (same tool+code+scope)."""
    src = """\
# pylint: disable=missing-docstring
# pylint: enable=missing-docstring
"""
    out = extract_dead_code(src)
    # Both are scope=block + same code so should dedupe to 1.
    assert out == [{"tool": "pylint", "code": "missing-docstring", "scope": "block"}]


# ---- Negatives ----------------------------------------------------


def test_empty_input():
    assert extract_dead_code("") == []


def test_no_markers_returns_empty():
    out = extract_dead_code("def foo(x):\n    return x + 1\n")
    assert out == []


def test_word_noqa_inside_prose_not_misfire():
    """The word ``noqa`` inside a string literal / docstring is matched only
    after a ``#`` comment leader; bare prose with ``noqa`` does not fire."""
    out = extract_dead_code("x = 'this has noqa in it'")
    assert out == []


def test_word_nolint_inside_prose_not_misfire():
    """``nolint`` requires a ``//`` comment leader."""
    out = extract_dead_code("var name = 'nolint';")
    assert out == []


# ---- Cap enforcement ----------------------------------------------


def test_cap_at_50_entries():
    """Output is capped at 50 entries even when more markers are present."""
    lines = [f"x = {i}  # noqa: E5{i:02d}" for i in range(60)]
    src = "\n".join(lines)
    out = extract_dead_code(src)
    assert len(out) == 50


# ---- enrich_code wiring -------------------------------------------


def test_enrich_code_populates_dead_code_from_ocr():
    """enrich_code runs extract_dead_code on the snippet body."""
    src = "def f(x): return eval(x)  # noqa: S307"
    out = enrich_code(None, OCRResult(text=src))
    assert out.dead_code == [{"tool": "noqa", "code": "S307", "scope": "line"}]


def test_enrich_code_caller_dead_code_wins():
    """When the LLM supplies a dead_code list, the OCR pass does not overwrite it."""
    existing = CodeFields(
        code="x = 1  # noqa",
        dead_code=[{"tool": "custom", "code": "FOO", "scope": "line"}],
    )
    out = enrich_code(existing, OCRResult(text="x = 1  # noqa"))
    assert out.dead_code == [{"tool": "custom", "code": "FOO", "scope": "line"}]


def test_enrich_code_empty_caller_list_runs_detector():
    """A caller-supplied empty list does NOT block the OCR detector."""
    existing = CodeFields(code="x = 1  # noqa: E501", dead_code=[])
    out = enrich_code(existing, OCRResult(text="x = 1  # noqa: E501"))
    assert out.dead_code == [{"tool": "noqa", "code": "E501", "scope": "line"}]


def test_enrich_code_no_markers_no_dead_code():
    """A clean snippet returns an empty dead_code list."""
    src = "def foo(x): return x * 2\n"
    out = enrich_code(None, OCRResult(text=src))
    assert out.dead_code == []
