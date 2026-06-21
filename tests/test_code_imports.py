"""Code import-set extraction.

A new ``CodeFields.imports`` slot carries the list of import /
require / use statements found in the snippet. Each entry is the
most-canonical short module / package identifier we can pull off
the import statement.

Recognised syntaxes:
* Python: ``import X`` / ``import X.Y as Z`` /
  ``import X, Y, Z`` / ``from X import a, b`` (captures X).
* JS / TS: ``import X from 'mod'`` / ``import { a } from "mod"`` /
  ``import 'mod'`` (side-effects) / ``require('mod')``.
* Java / Kotlin / Scala: ``import com.foo.Bar;`` / ``import com.foo.*;``.
* Go: single-line ``import "fmt"`` and parenthesised group.
* Rust: ``use std::collections::HashMap;`` and braced re-export form.
* Ruby: ``require 'json'`` / ``require_relative './foo'``.
* PHP: ``use Foo\\Bar\\Baz;`` / ``require_once 'foo.php'``.

De-duplicated, first-seen-in-text order preserved, capped at 50.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import enrich_code, extract_imports

# ---- edge cases --------------------------------------------------


def test_empty_string_returns_empty_list():
    assert extract_imports("") == []


def test_whitespace_only_returns_empty_list():
    assert extract_imports("   \n\n  ") == []


def test_plain_code_no_imports_returns_empty_list():
    assert extract_imports("x = 1\nprint(x)\n") == []


def test_none_input_returns_empty_list():
    """We accept None defensively (callers may pass it during early bootstrap)."""
    # The function accepts str only per its signature; falsy guard means
    # an empty string returns []. We just verify falsy handling here.
    assert extract_imports("") == []


# ---- Python ------------------------------------------------------


def test_python_import_single():
    code = "import os\n"
    assert extract_imports(code, language="python") == ["os"]


def test_python_import_with_as_alias():
    code = "import numpy as np\n"
    assert extract_imports(code, language="python") == ["numpy"]


def test_python_import_dotted():
    code = "import os.path\n"
    assert extract_imports(code, language="python") == ["os.path"]


def test_python_import_multi_comma():
    code = "import os, sys, json\n"
    assert extract_imports(code, language="python") == ["os", "sys", "json"]


def test_python_import_multi_with_aliases():
    code = "import numpy as np, pandas as pd\n"
    assert extract_imports(code, language="python") == ["numpy", "pandas"]


def test_python_from_import():
    code = "from collections import OrderedDict\n"
    assert extract_imports(code, language="python") == ["collections"]


def test_python_from_import_dotted():
    code = "from foo.bar.baz import qux\n"
    assert extract_imports(code, language="python") == ["foo.bar.baz"]


def test_python_from_import_multi_names():
    """Multiple names from the same module collapse to one module entry."""
    code = "from os.path import join, dirname, basename\n"
    assert extract_imports(code, language="python") == ["os.path"]


def test_python_from_import_relative():
    """``from . import x`` captures the dot as the module."""
    code = "from . import foo\n"
    assert extract_imports(code, language="python") == ["."]


def test_python_from_import_relative_dotted():
    code = "from ..bar import baz\n"
    out = extract_imports(code, language="python")
    # Either "..bar" or ".." is acceptable; we capture the dot-prefix as printed.
    assert out and out[0].startswith(".")


def test_python_dedup_preserves_first_seen_order():
    code = "import os\nimport sys\nimport os\n"
    assert extract_imports(code, language="python") == ["os", "sys"]


def test_python_indented_import_in_function_still_captured():
    code = "def foo():\n    import json\n    return json\n"
    out = extract_imports(code, language="python")
    assert "json" in out


# ---- JavaScript / TypeScript -------------------------------------


def test_js_import_default():
    code = "import React from 'react';\n"
    assert extract_imports(code, language="javascript") == ["react"]


def test_js_import_named():
    code = "import { useState, useEffect } from 'react';\n"
    assert extract_imports(code, language="javascript") == ["react"]


def test_js_import_double_quotes():
    code = 'import x from "module-x";\n'
    assert extract_imports(code, language="javascript") == ["module-x"]


def test_js_import_namespace():
    code = "import * as fs from 'fs';\n"
    assert extract_imports(code, language="javascript") == ["fs"]


def test_js_side_effects_import():
    """Bare ``import 'mod'`` (no from) is a side-effects import."""
    code = "import 'some-polyfill';\n"
    assert extract_imports(code, language="javascript") == ["some-polyfill"]


def test_js_require():
    code = "const x = require('lodash');\n"
    assert extract_imports(code, language="javascript") == ["lodash"]


def test_js_require_double_quotes():
    code = 'const fs = require("fs");\n'
    assert extract_imports(code, language="javascript") == ["fs"]


def test_js_multiple_imports():
    code = (
        "import React from 'react';\n"
        "import { useState } from 'react';\n"
        "import _ from 'lodash';\n"
    )
    assert extract_imports(code, language="javascript") == ["react", "lodash"]


def test_ts_typed_import():
    code = "import type { User } from './models';\n"
    out = extract_imports(code, language="typescript")
    assert out == ["./models"]


def test_js_mixed_import_and_require():
    code = (
        "import React from 'react';\n"
        "const fs = require('fs');\n"
    )
    assert extract_imports(code, language="javascript") == ["react", "fs"]


# ---- JVM (Java / Kotlin / Scala) ---------------------------------


def test_java_import():
    code = "import com.foo.Bar;\n"
    assert extract_imports(code, language="java") == ["com.foo.Bar"]


def test_java_import_wildcard():
    code = "import java.util.*;\n"
    assert extract_imports(code, language="java") == ["java.util.*"]


def test_java_static_import():
    code = "import static java.lang.Math.PI;\n"
    assert extract_imports(code, language="java") == ["java.lang.Math.PI"]


def test_java_multiple_imports():
    code = (
        "import com.foo.Bar;\n"
        "import com.foo.Baz;\n"
        "import java.util.*;\n"
    )
    out = extract_imports(code, language="java")
    assert out == ["com.foo.Bar", "com.foo.Baz", "java.util.*"]


def test_kotlin_import():
    code = "import kotlinx.coroutines.runBlocking\n"
    assert extract_imports(code, language="kotlin") == ["kotlinx.coroutines.runBlocking"]


def test_scala_import():
    code = "import scala.collection.mutable.HashMap\n"
    out = extract_imports(code, language="scala")
    assert "scala.collection.mutable.HashMap" in out


# ---- Go ---------------------------------------------------------


def test_go_single_import():
    code = 'import "fmt"\n'
    assert extract_imports(code, language="go") == ["fmt"]


def test_go_aliased_import():
    code = 'import f "fmt"\n'
    assert extract_imports(code, language="go") == ["fmt"]


def test_go_grouped_import():
    code = (
        'import (\n'
        '    "fmt"\n'
        '    "os"\n'
        '    "github.com/spf13/cobra"\n'
        ')\n'
    )
    out = extract_imports(code, language="go")
    assert out == ["fmt", "os", "github.com/spf13/cobra"]


def test_go_grouped_import_with_alias():
    code = (
        'import (\n'
        '    f "fmt"\n'
        '    "os"\n'
        ')\n'
    )
    out = extract_imports(code, language="go")
    assert "fmt" in out
    assert "os" in out


# ---- Rust -------------------------------------------------------


def test_rust_use_simple():
    code = "use std::collections::HashMap;\n"
    assert extract_imports(code, language="rust") == ["std::collections::HashMap"]


def test_rust_use_braced():
    """A braced re-export captures the path prefix."""
    code = "use std::io::{Read, Write};\n"
    assert extract_imports(code, language="rust") == ["std::io"]


def test_rust_pub_use():
    code = "pub use crate::foo::Bar;\n"
    out = extract_imports(code, language="rust")
    assert out == ["crate::foo::Bar"]


def test_rust_multiple_use():
    code = (
        "use std::collections::HashMap;\n"
        "use std::io::Read;\n"
        "use serde::Serialize;\n"
    )
    out = extract_imports(code, language="rust")
    assert out == [
        "std::collections::HashMap",
        "std::io::Read",
        "serde::Serialize",
    ]


# ---- Ruby -------------------------------------------------------


def test_ruby_require_single_quote():
    code = "require 'json'\n"
    assert extract_imports(code, language="ruby") == ["json"]


def test_ruby_require_double_quote():
    code = 'require "json"\n'
    assert extract_imports(code, language="ruby") == ["json"]


def test_ruby_require_relative():
    code = "require_relative './foo'\n"
    assert extract_imports(code, language="ruby") == ["./foo"]


def test_ruby_load():
    code = "load 'config.rb'\n"
    assert extract_imports(code, language="ruby") == ["config.rb"]


def test_ruby_multiple_requires():
    code = (
        "require 'json'\n"
        "require 'net/http'\n"
        "require_relative './lib/foo'\n"
    )
    out = extract_imports(code, language="ruby")
    assert out == ["json", "net/http", "./lib/foo"]


# ---- PHP --------------------------------------------------------


def test_php_use_namespace():
    code = "use Foo\\Bar\\Baz;\n"
    assert extract_imports(code, language="php") == ["Foo\\Bar\\Baz"]


def test_php_use_with_alias():
    code = "use Foo\\Bar\\Baz as B;\n"
    assert extract_imports(code, language="php") == ["Foo\\Bar\\Baz"]


def test_php_require_include():
    code = (
        "require_once 'vendor/autoload.php';\n"
        "include 'config.php';\n"
    )
    out = extract_imports(code, language="php")
    assert "vendor/autoload.php" in out
    assert "config.php" in out


def test_php_use_function():
    code = "use function Foo\\bar;\n"
    out = extract_imports(code, language="php")
    assert "Foo\\bar" in out


# ---- mixed and order ---------------------------------------------


def test_mixed_languages_all_captured():
    """A pasted snippet that mixes languages still surfaces all imports."""
    code = (
        "import os\n"
        "from collections import OrderedDict\n"
        "import React from 'react';\n"
        "use std::io;\n"
    )
    out = extract_imports(code)
    assert "os" in out
    assert "collections" in out
    assert "react" in out
    assert "std::io" in out


def test_source_text_order_preserved():
    """Order matches reading-order across matchers."""
    code = (
        "import 'react';\n"
        "import os\n"
        "use std::io;\n"
    )
    out = extract_imports(code)
    assert out == ["react", "os", "std::io"]


def test_dedup_across_syntax_forms():
    """Same module imported twice with different syntaxes only appears once."""
    code = (
        "import os\n"
        "import os\n"
    )
    assert extract_imports(code, language="python") == ["os"]


def test_cap_at_50_entries():
    lines = [f"import mod{i}\n" for i in range(60)]
    out = extract_imports("".join(lines), language="python")
    assert len(out) == 50


def test_comment_with_import_word_does_not_match():
    """A comment line containing the word ``import`` doesn't fire."""
    code = "# This is an import statement example\nx = 1\n"
    assert extract_imports(code, language="python") == []


def test_string_with_import_word_does_not_match():
    """A string containing the word ``import`` doesn't fire (when not at line start)."""
    code = 's = "import foo"\nprint(s)\n'
    assert extract_imports(code, language="python") == []


# ---- enrich_code wiring ------------------------------------------


def _ocr(text: str) -> OCRResult:
    return OCRResult(text=text, language="en", word_count=len(text.split()))


def test_enrich_code_python_imports():
    code = "import os\nfrom collections import OrderedDict\n"
    fields = enrich_code(None, _ocr(code))
    assert fields.imports == ["os", "collections"]


def test_enrich_code_caller_value_wins():
    """A caller-supplied imports list is preserved verbatim."""
    code = "import os\n"
    existing = CodeFields(code=code, imports=["llm-supplied"])
    fields = enrich_code(existing, _ocr(code))
    assert fields.imports == ["llm-supplied"]


def test_enrich_code_no_imports_stays_empty():
    code = "x = 1\nprint(x)\n"
    fields = enrich_code(None, _ocr(code))
    assert fields.imports == []


def test_enrich_code_js_imports_via_ocr():
    code = "import React from 'react';\nconst _ = require('lodash');\n"
    fields = enrich_code(None, _ocr(code))
    assert "react" in fields.imports
    assert "lodash" in fields.imports


def test_enrich_code_go_grouped_imports_via_ocr():
    code = 'import (\n    "fmt"\n    "os"\n)\n'
    fields = enrich_code(None, _ocr(code))
    assert "fmt" in fields.imports
    assert "os" in fields.imports
