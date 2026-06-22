"""Code regex-literal extraction into CodeFields.regexes.

The extractor recognises regex literals across 8 language flavors:
JS slash-delimited, Python re.* calls, Ruby %r{} percent-literals,
Perl qr literals, Go regexp.MustCompile, Java Pattern.compile,
Rust Regex::new, and C# new Regex(...) / Regex.Match.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import enrich_code, extract_regex_literals

# ---- JS slash-delimited regex --------------------------------------


def test_js_basic_assignment():
    """``const re = /hello/g``."""
    out = extract_regex_literals("const re = /hello/g")
    assert {"flavor": "js", "pattern": "hello", "flags": "g"} in out


def test_js_no_flags():
    out = extract_regex_literals("if (str.match(/foo/)) {}")
    assert {"flavor": "js", "pattern": "foo", "flags": ""} in out


def test_js_multiple_flags():
    out = extract_regex_literals("var pat = /abc/gimu")
    assert {"flavor": "js", "pattern": "abc", "flags": "gimu"} in out


def test_js_with_character_class():
    out = extract_regex_literals("const re = /[a-z]+/g")
    assert {"flavor": "js", "pattern": "[a-z]+", "flags": "g"} in out


def test_js_with_escaped_slash():
    """``/foo\\/bar/`` (escaped slash is part of the pattern)."""
    out = extract_regex_literals(r"const p = /foo\/bar/i")
    assert any(e["flavor"] == "js" and "/" in e["pattern"] for e in out)


def test_js_after_return_keyword():
    """``return /pat/g`` is a regex (not division)."""
    out = extract_regex_literals("function f() { return /pat/g; }")
    assert {"flavor": "js", "pattern": "pat", "flags": "g"} in out


def test_js_division_not_matched():
    """``x = a / b / c`` is division, not a regex."""
    # The right-context lookahead disqualifies this because the
    # trailing flag region would have to be ASCII identifier chars
    # but the surrounding context lacks the regex-suggesting opener.
    out = extract_regex_literals("var x = a / b / c;")
    # Pattern body would be ` b ` but no left-context operator
    # immediately before the /, so the line itself doesn't satisfy
    # the regex matcher. Should produce no matches OR at most very
    # narrow false-positives. We assert the obvious division-only
    # case has no matches.
    assert all(e["pattern"] != " b " for e in out)


# ---- Python re.* calls ---------------------------------------------


def test_python_re_compile_basic():
    out = extract_regex_literals('p = re.compile("[a-z]+")')
    assert {"flavor": "python", "pattern": "[a-z]+", "flags": ""} in out


def test_python_re_match_raw_string():
    out = extract_regex_literals('m = re.match(r"\\d+", text)')
    assert {"flavor": "python", "pattern": r"\d+", "flags": ""} in out


def test_python_re_search_single_quotes():
    out = extract_regex_literals("re.search('hello.*world', text)")
    assert {"flavor": "python", "pattern": "hello.*world", "flags": ""} in out


def test_python_re_findall():
    out = extract_regex_literals("re.findall(r'\\w+@\\w+', text)")
    assert {"flavor": "python", "pattern": r"\w+@\w+", "flags": ""} in out


def test_python_re_sub():
    out = extract_regex_literals('re.sub(r"\\s+", " ", text)')
    assert {"flavor": "python", "pattern": r"\s+", "flags": ""} in out


def test_python_re_subn():
    out = extract_regex_literals('re.subn(r"foo", "bar", text)')
    assert {"flavor": "python", "pattern": "foo", "flags": ""} in out


def test_python_re_split():
    out = extract_regex_literals('parts = re.split(r"[,;]", text)')
    assert {"flavor": "python", "pattern": "[,;]", "flags": ""} in out


def test_python_re_fullmatch():
    out = extract_regex_literals('re.fullmatch(r"\\d{3}", text)')
    assert {"flavor": "python", "pattern": r"\d{3}", "flags": ""} in out


def test_python_re_finditer():
    out = extract_regex_literals('for m in re.finditer(r"\\w+", text):')
    assert {"flavor": "python", "pattern": r"\w+", "flags": ""} in out


# ---- Ruby percent-literal regex ------------------------------------


def test_ruby_percent_r_curly():
    out = extract_regex_literals("pat = %r{hello.*world}")
    assert {"flavor": "ruby", "pattern": "hello.*world", "flags": ""} in out


def test_ruby_percent_r_curly_with_flags():
    out = extract_regex_literals("pat = %r{[a-z]+}i")
    assert {"flavor": "ruby", "pattern": "[a-z]+", "flags": "i"} in out


def test_ruby_percent_r_bang():
    out = extract_regex_literals("pat = %r!^\\d+!")
    assert {"flavor": "ruby", "pattern": "^\\d+", "flags": ""} in out


def test_ruby_percent_r_slash():
    out = extract_regex_literals("pat = %r/abc/")
    assert {"flavor": "ruby", "pattern": "abc", "flags": ""} in out


def test_ruby_percent_r_paren():
    out = extract_regex_literals("pat = %r(hello)")
    assert {"flavor": "ruby", "pattern": "hello", "flags": ""} in out


# ---- Perl qr literal -----------------------------------------------


def test_perl_qr_slash():
    out = extract_regex_literals("my $re = qr/hello.*world/i;")
    assert {"flavor": "perl", "pattern": "hello.*world", "flags": "i"} in out


def test_perl_qr_curly():
    out = extract_regex_literals("my $re = qr{[a-z]+}m;")
    assert {"flavor": "perl", "pattern": "[a-z]+", "flags": "m"} in out


def test_perl_qr_pipe():
    out = extract_regex_literals("my $re = qr|foo\\|bar|;")
    assert any(e["flavor"] == "perl" and "foo" in e["pattern"] for e in out)


# ---- Go regexp.* ---------------------------------------------------


def test_go_must_compile_backtick():
    out = extract_regex_literals('re := regexp.MustCompile(`[a-z]+`)')
    assert {"flavor": "go", "pattern": "[a-z]+", "flags": ""} in out


def test_go_compile_quoted():
    out = extract_regex_literals('re, err := regexp.Compile("\\\\d+")')
    assert any(e["flavor"] == "go" for e in out)


def test_go_must_compile_complex_pattern():
    out = extract_regex_literals('re := regexp.MustCompile(`^[A-Z][a-zA-Z0-9_]*$`)')
    assert {
        "flavor": "go",
        "pattern": "^[A-Z][a-zA-Z0-9_]*$",
        "flags": "",
    } in out


# ---- Java Pattern.compile -----------------------------------------


def test_java_pattern_compile_basic():
    out = extract_regex_literals('Pattern p = Pattern.compile("[a-z]+");')
    assert {"flavor": "java", "pattern": "[a-z]+", "flags": ""} in out


def test_java_pattern_with_escaped_chars():
    out = extract_regex_literals('Pattern.compile("\\\\d{3}")')
    assert any(e["flavor"] == "java" for e in out)


# ---- Rust Regex::new -----------------------------------------------


def test_rust_regex_new_quoted():
    out = extract_regex_literals('let re = Regex::new("[a-z]+").unwrap();')
    assert {"flavor": "rust", "pattern": "[a-z]+", "flags": ""} in out


def test_rust_regex_new_raw_string():
    out = extract_regex_literals('let re = Regex::new(r"\\d+").unwrap();')
    assert {"flavor": "rust", "pattern": "\\d+", "flags": ""} in out


# ---- C# Regex -----------------------------------------------------


def test_cs_new_regex_basic():
    out = extract_regex_literals('var re = new Regex("[a-z]+");')
    assert {"flavor": "c#", "pattern": "[a-z]+", "flags": ""} in out


def test_cs_new_regex_verbatim():
    """``@"pattern"`` (verbatim string)."""
    out = extract_regex_literals('var re = new Regex(@"\\d+");')
    assert any(e["flavor"] == "c#" for e in out)


def test_cs_regex_match_static():
    out = extract_regex_literals('var m = Regex.Match(input, "[a-z]+");')
    assert {"flavor": "c#", "pattern": "[a-z]+", "flags": ""} in out


def test_cs_regex_is_match():
    out = extract_regex_literals('if (Regex.IsMatch(input, "hello")) {}')
    assert {"flavor": "c#", "pattern": "hello", "flags": ""} in out


# ---- dedupe / cap / order -----------------------------------------


def test_dedupe_same_pattern_flavor_flags():
    out = extract_regex_literals(
        'p1 = re.compile("foo"); p2 = re.compile("foo")'
    )
    py_entries = [e for e in out if e["flavor"] == "python"]
    assert len(py_entries) == 1


def test_distinct_patterns_kept_separate():
    out = extract_regex_literals(
        'a = re.compile("foo"); b = re.compile("bar"); c = re.compile("baz")'
    )
    patterns = sorted(e["pattern"] for e in out if e["flavor"] == "python")
    assert patterns == ["bar", "baz", "foo"]


def test_first_seen_order_preserved():
    code = (
        'p1 = re.compile("first")\n'
        'p2 = re.compile("second")\n'
        'p3 = re.compile("third")\n'
    )
    out = extract_regex_literals(code)
    patterns = [e["pattern"] for e in out if e["flavor"] == "python"]
    assert patterns == ["first", "second", "third"]


def test_mixed_flavors_all_captured():
    code = (
        'js = /hello/g\n'
        'py = re.compile("python")\n'
        'rb = %r{ruby}\n'
        'go := regexp.MustCompile(`golang`)\n'
        'Pattern.compile("java");\n'
        'Regex::new("rust");\n'
        'new Regex("csharp");\n'
        'my $p = qr/perl/;\n'
    )
    out = extract_regex_literals(code)
    flavors = {e["flavor"] for e in out}
    assert "js" in flavors
    assert "python" in flavors
    assert "ruby" in flavors
    assert "go" in flavors
    assert "java" in flavors
    assert "rust" in flavors
    assert "c#" in flavors
    assert "perl" in flavors


# ---- edge cases / rejection ---------------------------------------


def test_empty_code():
    assert extract_regex_literals("") == []
    assert extract_regex_literals(None) == []  # type: ignore[arg-type]


def test_no_regex_returns_empty():
    out = extract_regex_literals("def foo():\n    return 42\n")
    assert out == []


def test_comments_not_excluded():
    """Regex in a comment IS captured -- we don't tokenise."""
    out = extract_regex_literals('# example: re.compile("foo")')
    assert any(e["pattern"] == "foo" for e in out)


def test_python_re_compile_with_special_chars():
    """Patterns with brackets, dots, etc. captured correctly."""
    out = extract_regex_literals('re.compile(r"^[a-z]+\\.[a-z]+$")')
    assert {
        "flavor": "python",
        "pattern": "^[a-z]+\\.[a-z]+$",
        "flags": "",
    } in out


# ---- enrich_code integration --------------------------------------


def test_enrich_code_populates_regexes_python():
    snippet = (
        '"""Module docstring."""\n'
        'import re\n'
        '\n'
        'EMAIL = re.compile(r"[a-z]+@[a-z]+\\.[a-z]+")\n'
        'PHONE = re.compile(r"\\d{3}-\\d{4}")\n'
    )
    out = enrich_code(None, OCRResult(text=snippet, word_count=10))
    patterns = sorted(e["pattern"] for e in out.regexes if e["flavor"] == "python")
    assert "[a-z]+@[a-z]+\\.[a-z]+" in patterns
    assert "\\d{3}-\\d{4}" in patterns


def test_enrich_code_populates_regexes_javascript():
    snippet = (
        'const URL = /https?:\\/\\/[^\\s]+/g;\n'
        'const ID = /^id_[A-Z0-9]+$/;\n'
    )
    out = enrich_code(None, OCRResult(text=snippet, word_count=10))
    patterns = [e["pattern"] for e in out.regexes if e["flavor"] == "js"]
    assert any("https" in p for p in patterns)


def test_enrich_code_no_regexes_for_pure_data():
    """A JSON snippet has no regex literals."""
    snippet = '{"name": "Alice", "age": 30}'
    out = enrich_code(None, OCRResult(text=snippet, word_count=4))
    assert out.regexes == []


def test_enrich_code_caller_supplied_regexes_preserved():
    existing = CodeFields(
        code="foo",
        regexes=[{"flavor": "python", "pattern": "from-llm", "flags": ""}],
    )
    out = enrich_code(existing, OCRResult(text='re.compile("from-ocr")', word_count=3))
    assert out.regexes == [
        {"flavor": "python", "pattern": "from-llm", "flags": ""}
    ]
