"""Markdown code-fence language detection.

A new ``CodeFields.fence_language`` slot carries the lowercased
language tag declared at the opening fence of a markdown code
block. Markdown wraps code in triple-backtick fences (or triple-
tilde fences) with an optional language tag after the opening
fence:

  ```python
  def foo(): ...
  ```

  ~~~rust
  fn main() {}
  ~~~

When the OCR capture includes the fence markers (a doc / blog /
README screenshot, or a chat capture of a code message), the
fence tag is a HIGH-CONFIDENCE language signal because the
author explicitly declared it.

The tag is lowercased before storage. We do NOT canonicalise
short forms (``js`` stays ``js``, ``py`` stays ``py``) because
the original tag carries author intent.

``None`` when no fence is present, the fence has no language
tag, or only bare fences appear.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_fence_language, enrich_code

# ---- edge cases --------------------------------------------------


def test_empty_string_returns_none():
    assert detect_fence_language("") is None


def test_whitespace_only_returns_none():
    assert detect_fence_language("    \n  \n") is None


def test_plain_code_no_fence_returns_none():
    assert detect_fence_language("def foo():\n    return 1\n") is None


def test_bare_fence_no_lang_returns_none():
    """A fence opener with no language tag yields None."""
    code = "```\ndef foo(): ...\n```\n"
    assert detect_fence_language(code) is None


# ---- Canonical CommonMark fence forms ----------------------------


def test_python_backtick_fence():
    code = "```python\ndef foo(): return 1\n```\n"
    assert detect_fence_language(code) == "python"


def test_javascript_backtick_fence():
    code = "```javascript\nconst x = 1;\n```\n"
    assert detect_fence_language(code) == "javascript"


def test_go_backtick_fence():
    code = "```go\nfunc main() {}\n```\n"
    assert detect_fence_language(code) == "go"


def test_rust_backtick_fence():
    code = "```rust\nfn main() {}\n```\n"
    assert detect_fence_language(code) == "rust"


def test_typescript_backtick_fence():
    code = "```typescript\nconst x: number = 1;\n```\n"
    assert detect_fence_language(code) == "typescript"


def test_bash_backtick_fence():
    code = "```bash\necho hello\n```\n"
    assert detect_fence_language(code) == "bash"


def test_short_form_js_preserved():
    """We don't canonicalise short forms -- ``js`` stays ``js``."""
    code = "```js\nconst x = 1;\n```\n"
    assert detect_fence_language(code) == "js"


def test_short_form_py_preserved():
    code = "```py\ndef foo(): ...\n```\n"
    assert detect_fence_language(code) == "py"


def test_short_form_ts_preserved():
    code = "```ts\nconst x: number = 1;\n```\n"
    assert detect_fence_language(code) == "ts"


# ---- Tilde fences ------------------------------------------------


def test_tilde_fence_python():
    code = "~~~python\ndef foo(): pass\n~~~\n"
    assert detect_fence_language(code) == "python"


def test_tilde_fence_rust():
    code = "~~~rust\nfn main() {}\n~~~\n"
    assert detect_fence_language(code) == "rust"


def test_tilde_fence_bare_no_lang_returns_none():
    code = "~~~\nplain text\n~~~\n"
    assert detect_fence_language(code) is None


# ---- 4+ backticks ------------------------------------------------


def test_four_backtick_fence():
    """CommonMark allows 4+ backticks so the fence can wrap nested code."""
    code = "````python\ndef foo(): ...\n```\nnested\n```\n````\n"
    assert detect_fence_language(code) == "python"


def test_five_backtick_fence():
    code = "`````go\nfunc main() {}\n`````\n"
    assert detect_fence_language(code) == "go"


# ---- Case insensitivity ------------------------------------------


def test_uppercase_lang_lowercased():
    code = "```Python\ndef foo(): ...\n```\n"
    assert detect_fence_language(code) == "python"


def test_mixed_case_lang_lowercased():
    code = "```JavaScript\nconst x = 1;\n```\n"
    assert detect_fence_language(code) == "javascript"


def test_all_caps_lang_lowercased():
    code = "```SQL\nSELECT 1\n```\n"
    assert detect_fence_language(code) == "sql"


# ---- Info-string handling ----------------------------------------


def test_lang_with_title_info_string():
    """GFM allows ``` ```LANG title="file.py" `` -- we capture only LANG."""
    code = '```python title="example.py"\ndef foo(): ...\n```\n'
    assert detect_fence_language(code) == "python"


def test_lang_with_hl_lines_info_string():
    """mkdocs-style ``` ```LANG hl_lines="1 2 3" `` info string."""
    code = '```python hl_lines="1 2"\ndef foo(): ...\n```\n'
    assert detect_fence_language(code) == "python"


def test_lang_with_trailing_attrs():
    code = '```js linenums="5"\nconst x = 1;\n```\n'
    assert detect_fence_language(code) == "js"


# ---- Language tag character set ----------------------------------


def test_lang_with_hyphen_preserved():
    code = "```c-sharp\nint x = 1;\n```\n"
    assert detect_fence_language(code) == "c-sharp"


def test_lang_with_plus_preserved():
    code = "```c++\nint main() {}\n```\n"
    assert detect_fence_language(code) == "c++"


def test_lang_with_hash_preserved():
    code = "```c#\nclass Foo {}\n```\n"
    assert detect_fence_language(code) == "c#"


def test_lang_with_dot_preserved():
    code = "```objective-c.cpp\nint x;\n```\n"
    assert detect_fence_language(code) == "objective-c.cpp"


def test_lang_with_digits_preserved():
    code = "```python3\ndef foo(): ...\n```\n"
    assert detect_fence_language(code) == "python3"


# ---- Indented fences ---------------------------------------------


def test_one_space_indented_fence_accepted():
    """CommonMark allows up to 3 spaces of indent before the fence."""
    code = " ```python\ndef foo(): ...\n```\n"
    assert detect_fence_language(code) == "python"


def test_two_space_indented_fence_accepted():
    code = "  ```python\ndef foo(): ...\n```\n"
    assert detect_fence_language(code) == "python"


def test_three_space_indented_fence_accepted():
    code = "   ```python\ndef foo(): ...\n```\n"
    assert detect_fence_language(code) == "python"


def test_four_space_indent_treated_as_code_block_not_fence():
    """CommonMark: 4-space indent makes it an indented code block, not a fence."""
    code = "    ```python\n    def foo(): ...\n    ```\n"
    assert detect_fence_language(code) is None


# ---- Multi-fence behaviour ---------------------------------------


def test_first_lang_wins_with_multiple_fences():
    """When multiple fences have different tags, first one wins."""
    code = (
        "```python\nfoo()\n```\n"
        "Some prose.\n"
        "```rust\nfn main() {}\n```\n"
    )
    assert detect_fence_language(code) == "python"


def test_first_tagged_fence_wins_over_bare_fence_below():
    code = (
        "```rust\nfn main() {}\n```\n"
        "```\nplain block\n```\n"
    )
    assert detect_fence_language(code) == "rust"


def test_bare_fence_above_tagged_fence_falls_through():
    """A bare fence above a tagged one -- we keep scanning to the tagged one."""
    code = (
        "```\nplain text\n```\n"
        "```python\ndef foo(): ...\n```\n"
    )
    assert detect_fence_language(code) == "python"


# ---- Fence in middle of prose ------------------------------------


def test_fence_preceded_by_markdown_prose():
    code = (
        "# Example\n"
        "Here's the code:\n"
        "\n"
        "```python\n"
        "def foo(): ...\n"
        "```\n"
    )
    assert detect_fence_language(code) == "python"


def test_fence_followed_by_more_prose():
    code = (
        "```javascript\nconst x = 1;\n```\n"
        "\n"
        "Above is JavaScript.\n"
    )
    assert detect_fence_language(code) == "javascript"


# ---- Negative cases ----------------------------------------------


def test_inline_backticks_not_fence():
    """Single-backtick inline code is NOT a fence."""
    code = "Use `print()` to log values.\n"
    assert detect_fence_language(code) is None


def test_double_backticks_not_fence():
    """Double-backtick inline code is NOT a fence either."""
    code = "Use ``foo()`` here.\n"
    assert detect_fence_language(code) is None


def test_lang_starting_with_digit_rejected():
    """Lang token must start with a letter."""
    code = "```3d\nfoo\n```\n"
    # Three-digit tag isn't a valid language tag in our regex.
    assert detect_fence_language(code) is None


def test_lang_starting_with_dash_rejected():
    code = "```-bash\necho hi\n```\n"
    assert detect_fence_language(code) is None


def test_lang_starting_with_underscore_rejected():
    code = "```_python\nfoo\n```\n"
    assert detect_fence_language(code) is None


# ---- Unclosed fences ---------------------------------------------


def test_unclosed_fence_still_surfaces_lang():
    """A snippet that opens but never closes a fence still surfaces
    the lang (the author's intent was clear)."""
    code = "```python\ndef foo():\n    return 1\n"
    assert detect_fence_language(code) == "python"


# ---- enrich_code integration -------------------------------------


def test_enrich_code_populates_fence_language():
    """enrich_code wires fence_language onto CodeFields."""
    code = "```python\ndef foo(): return 1\n```\n"
    fields = enrich_code(None, OCRResult(text=code))
    assert fields.fence_language == "python"


def test_enrich_code_fence_language_none_for_plain_code():
    """No fence -> field is None."""
    code = "def foo():\n    return 1\n"
    fields = enrich_code(None, OCRResult(text=code))
    assert fields.fence_language is None


def test_enrich_code_caller_supplied_fence_language_wins():
    """A caller-supplied fence_language is preserved verbatim."""
    code = "```python\ndef foo(): ...\n```\n"
    existing = CodeFields(code=code, fence_language="custom-tag")
    fields = enrich_code(existing, OCRResult(text=code))
    assert fields.fence_language == "custom-tag"


def test_enrich_code_fence_language_independent_of_language_detection():
    """fence_language and language can disagree -- both are surfaced."""
    code = (
        "```typescript\n"
        "const x: number = 1;\n"
        "```\n"
    )
    fields = enrich_code(None, OCRResult(text=code))
    assert fields.fence_language == "typescript"
    # Language detection runs on the body separately; the result may
    # match or not -- we don't care here.


def test_enrich_code_preserves_fence_language_with_other_fields():
    """Pairs cleanly with imports/docstring/license detection."""
    code = (
        "```python\n"
        '"""module docstring."""\n'
        "import os\n"
        "def foo(): ...\n"
        "```\n"
    )
    fields = enrich_code(None, OCRResult(text=code))
    assert fields.fence_language == "python"
    # The docstring / imports detectors operate on the body too;
    # the fence wrapper doesn't break them.
    # (We don't assert specific docstring/imports values here -- the
    # other test files cover those.)


def test_default_field_value_is_none():
    """A fresh CodeFields has fence_language = None by default."""
    fields = CodeFields()
    assert fields.fence_language is None
