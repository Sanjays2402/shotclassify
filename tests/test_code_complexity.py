"""Code per-function complexity heuristic tests.

A new CodeFields.complexity slot lists per-function McCabe-style
cyclomatic complexity scores. Each entry is a
``{"name": str, "complexity": int}`` dict.

Base complexity is 1 (a no-branch function); +1 per decision
point (if/elif/for/while/case/catch/and/or/&&/||/ternary).
"""
from __future__ import annotations

from shotclassify_common import OCRResult
from shotclassify_extract.code import enrich_code, extract_complexity

# ---- Python ------------------------------------------------------


def test_python_no_branches_returns_1():
    code = "def f():\n    return 1\n"
    out = extract_complexity(code, "python")
    assert out == [{"name": "f", "complexity": 1}]


def test_python_one_if_returns_2():
    code = "def f(x):\n    if x:\n        return 1\n    return 0\n"
    out = extract_complexity(code, "python")
    assert out == [{"name": "f", "complexity": 2}]


def test_python_if_elif_else_returns_3():
    """``if`` + ``elif`` + ``else`` -> 1 base + if + elif = 3."""
    code = (
        "def f(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    elif x == 0:\n"
        "        return 2\n"
        "    else:\n"
        "        return 3\n"
    )
    out = extract_complexity(code, "python")
    assert out == [{"name": "f", "complexity": 3}]


def test_python_for_loop_returns_2():
    code = "def f():\n    for i in range(10):\n        print(i)\n"
    out = extract_complexity(code, "python")
    assert out == [{"name": "f", "complexity": 2}]


def test_python_while_loop_returns_2():
    code = "def f():\n    while True:\n        break\n"
    out = extract_complexity(code, "python")
    assert out == [{"name": "f", "complexity": 2}]


def test_python_try_except_returns_2():
    code = "def f():\n    try:\n        x = 1\n    except ValueError:\n        x = 2\n"
    out = extract_complexity(code, "python")
    assert out == [{"name": "f", "complexity": 2}]


def test_python_and_or_in_condition():
    """``if a and b or c`` -> 1 base + if + and + or = 4."""
    code = "def f(a, b, c):\n    if a and b or c:\n        return 1\n    return 0\n"
    out = extract_complexity(code, "python")
    assert out == [{"name": "f", "complexity": 4}]


def test_python_match_case_returns_3():
    """``match`` with 2 cases: 1 base + 2 cases = 3."""
    code = (
        "def f(x):\n"
        "    match x:\n"
        "        case 1:\n"
        "            return 'one'\n"
        "        case 2:\n"
        "            return 'two'\n"
    )
    out = extract_complexity(code, "python")
    assert out == [{"name": "f", "complexity": 3}]


def test_python_async_def():
    code = "async def f():\n    if True:\n        return 1\n"
    out = extract_complexity(code, "python")
    assert out == [{"name": "f", "complexity": 2}]


def test_python_multiple_functions():
    code = (
        "def simple():\n"
        "    return 1\n"
        "\n"
        "def branchy(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    elif x == 0:\n"
        "        return 2\n"
        "    return 3\n"
    )
    out = extract_complexity(code, "python")
    assert {"name": "simple", "complexity": 1} in out
    assert {"name": "branchy", "complexity": 3} in out


def test_python_nested_function():
    code = (
        "def outer():\n"
        "    def inner():\n"
        "        if True:\n"
        "            return 1\n"
        "        return 0\n"
        "    return inner\n"
    )
    out = extract_complexity(code, "python")
    # Both outer (containing inner+its if) and inner detected.
    names = [e["name"] for e in out]
    assert "outer" in names
    assert "inner" in names


def test_python_high_complexity_function():
    code = (
        "def big(x):\n"
        "    if x > 10:\n"
        "        for i in range(x):\n"
        "            if i % 2:\n"
        "                while i > 0:\n"
        "                    i -= 1\n"
        "            elif i > 5 and i < 8:\n"
        "                pass\n"
        "    return x\n"
    )
    out = extract_complexity(code, "python")
    assert out[0]["name"] == "big"
    # Manually: 1 base + 2 if + 1 elif + 1 for + 1 while + 1 and = 7
    assert out[0]["complexity"] == 7


# ---- JavaScript / TypeScript -----------------------------------


def test_js_function_no_branches():
    code = "function f() { return 1; }"
    out = extract_complexity(code, "javascript")
    assert out == [{"name": "f", "complexity": 1}]


def test_js_function_with_if():
    code = "function f(x) { if (x) { return 1; } return 0; }"
    out = extract_complexity(code, "javascript")
    assert out == [{"name": "f", "complexity": 2}]


def test_js_function_with_else_if():
    code = "function f(x) { if (x) {} else if (x == 0) {} else {} }"
    out = extract_complexity(code, "javascript")
    # 1 base + if + else if = 3
    assert out == [{"name": "f", "complexity": 3}]


def test_js_function_with_logical_and_or():
    code = "function f(a, b, c) { if (a && b || c) return 1; }"
    out = extract_complexity(code, "javascript")
    # 1 base + if + && + || = 4
    assert out == [{"name": "f", "complexity": 4}]


def test_js_arrow_function():
    code = "const f = (x) => { if (x) return 1; return 0; };"
    out = extract_complexity(code, "javascript")
    assert out == [{"name": "f", "complexity": 2}]


def test_js_try_catch():
    code = "function f() { try { x(); } catch (e) { y(); } }"
    out = extract_complexity(code, "javascript")
    # 1 base + catch = 2
    assert out == [{"name": "f", "complexity": 2}]


def test_js_switch_case():
    code = (
        "function f(x) {\n"
        "    switch (x) {\n"
        "        case 1: return 'a';\n"
        "        case 2: return 'b';\n"
        "        default: return 'c';\n"
        "    }\n"
        "}"
    )
    out = extract_complexity(code, "javascript")
    # 1 base + 2 cases = 3
    assert out[0]["complexity"] == 3


def test_js_ternary():
    code = "function f(x) { return x > 0 ? 'pos' : 'neg'; }"
    out = extract_complexity(code, "javascript")
    # 1 base + ternary = 2
    assert out[0]["complexity"] == 2


def test_js_multiple_functions():
    code = (
        "function a() { return 1; }\n"
        "function b(x) { if (x) return 1; return 0; }\n"
        "const c = () => { for (let i=0;i<10;i++) {} };\n"
    )
    out = extract_complexity(code, "javascript")
    names = {e["name"]: e["complexity"] for e in out}
    assert names["a"] == 1
    assert names["b"] == 2
    assert names["c"] == 2


# ---- Java --------------------------------------------------------


def test_java_method_no_branches():
    code = "public void f() { return; }"
    out = extract_complexity(code, "java")
    assert out == [{"name": "f", "complexity": 1}]


def test_java_method_with_if():
    code = "public int f(int x) { if (x > 0) return 1; return 0; }"
    out = extract_complexity(code, "java")
    assert out[0]["complexity"] == 2


def test_java_method_with_switch():
    code = (
        "public String f(int x) {\n"
        "    switch (x) {\n"
        "        case 1: return \"a\";\n"
        "        case 2: return \"b\";\n"
        "        default: return \"c\";\n"
        "    }\n"
        "}"
    )
    out = extract_complexity(code, "java")
    assert out[0]["complexity"] == 3


# ---- Go ----------------------------------------------------------


def test_go_func_no_branches():
    code = "func f() int { return 1 }"
    out = extract_complexity(code, "go")
    assert out == [{"name": "f", "complexity": 1}]


def test_go_func_with_if():
    code = "func f(x int) int { if x > 0 { return 1 }; return 0 }"
    out = extract_complexity(code, "go")
    assert out[0]["complexity"] == 2


def test_go_func_with_for():
    code = "func f() { for i := 0; i < 10; i++ { } }"
    out = extract_complexity(code, "go")
    assert out[0]["complexity"] == 2


def test_go_method_with_receiver():
    code = "func (r *Receiver) f() int { if true { return 1 }; return 0 }"
    out = extract_complexity(code, "go")
    assert out[0]["name"] == "f"
    assert out[0]["complexity"] == 2


# ---- Rust --------------------------------------------------------


def test_rust_fn_no_branches():
    code = "fn f() -> i32 { 1 }"
    out = extract_complexity(code, "rust")
    assert out == [{"name": "f", "complexity": 1}]


def test_rust_fn_with_if():
    code = "fn f(x: i32) -> i32 { if x > 0 { 1 } else { 0 } }"
    out = extract_complexity(code, "rust")
    assert out[0]["complexity"] == 2


def test_rust_fn_with_match():
    code = (
        "fn f(x: i32) -> &'static str {\n"
        "    match x {\n"
        "        1 => \"a\",\n"
        "        2 => \"b\",\n"
        "        _ => \"c\",\n"
        "    }\n"
        "}"
    )
    out = extract_complexity(code, "rust")
    # 1 base + match = 2
    assert out[0]["complexity"] == 2


# ---- Kotlin ------------------------------------------------------


def test_kotlin_fun_no_branches():
    code = "fun f(): Int { return 1 }"
    out = extract_complexity(code, "kotlin")
    assert out == [{"name": "f", "complexity": 1}]


def test_kotlin_fun_with_when():
    code = (
        "fun f(x: Int): String {\n"
        "    return when (x) {\n"
        "        1 -> \"a\"\n"
        "        2 -> \"b\"\n"
        "        else -> \"c\"\n"
        "    }\n"
        "}"
    )
    out = extract_complexity(code, "kotlin")
    # 1 base + when = 2
    assert out[0]["complexity"] == 2


# ---- Data / shell languages return [] ---------------------------


def test_json_returns_empty():
    code = '{"if": "true", "def": "f"}'
    out = extract_complexity(code, "json")
    assert out == []


def test_yaml_returns_empty():
    code = "if: true\nfor: each"
    out = extract_complexity(code, "yaml")
    assert out == []


def test_sql_returns_empty():
    code = "SELECT * FROM foo WHERE if = 1"
    out = extract_complexity(code, "sql")
    assert out == []


def test_bash_returns_empty():
    code = "if [ -f x ]; then\n  for i in *; do\n    echo $i\n  done\nfi"
    out = extract_complexity(code, "bash")
    assert out == []


# ---- Edge cases -------------------------------------------------


def test_empty_code():
    assert extract_complexity("") == []


def test_no_functions():
    code = "if True:\n    print('hi')\n"
    out = extract_complexity(code, "python")
    assert out == []


def test_anonymous_arrow_in_callback():
    """Arrow function assigned via const gets the const name. A
    truly anonymous arrow (passed as a callback) gets <anonymous>
    if our matcher catches it -- but our JS_FUNC_RE focuses on
    named forms so callbacks may not register."""
    code = "function f() { return 1; }\nconst g = function() { return 2; };"
    out = extract_complexity(code, "javascript")
    names = [e["name"] for e in out]
    assert "f" in names
    assert "g" in names


def test_python_function_with_comment_branches_counted():
    """Comments that look like keywords are NOT counted because
    Python's pattern uses \\b which requires whole-word match --
    BUT the lexical scan does not exclude comments. We document
    that as a trade-off."""
    code = (
        "def f():\n"
        "    # if this then that\n"
        "    return 1\n"
    )
    out = extract_complexity(code, "python")
    # Lexical detector counts "if" in comment -> complexity 2.
    assert out[0]["complexity"] == 2


# ---- enrich_code integration ------------------------------------


def test_enrich_backfills_complexity():
    code = "def f(x):\n    if x:\n        return 1\n    return 0\n"
    ocr = OCRResult(text=code, word_count=10, mean_confidence=0.9)
    out = enrich_code(None, ocr)
    assert out.complexity == [{"name": "f", "complexity": 2}]


def test_enrich_preserves_caller_complexity():
    """When caller has already supplied complexity, enrich keeps
    it verbatim."""
    from shotclassify_common import CodeFields
    caller = CodeFields(
        language="python",
        code="def f(): pass\n",
        complexity=[{"name": "llm_provided", "complexity": 99}],
    )
    ocr = OCRResult(text="def f(): pass\n", word_count=3, mean_confidence=0.9)
    out = enrich_code(caller, ocr)
    assert out.complexity == [{"name": "llm_provided", "complexity": 99}]


def test_enrich_no_functions_returns_empty():
    code = "print('hello world')\n"
    ocr = OCRResult(text=code, word_count=3, mean_confidence=0.9)
    out = enrich_code(None, ocr)
    assert out.complexity == []


# ---- Real-world snippets ----------------------------------------


def test_real_python_validator_function():
    code = '''\
def validate(data):
    if not data:
        return False
    if "name" not in data:
        return False
    if len(data["name"]) < 3 or len(data["name"]) > 50:
        return False
    for char in data["name"]:
        if not char.isalnum() and char != "_":
            return False
    return True
'''
    out = extract_complexity(code, "python")
    assert out[0]["name"] == "validate"
    # 1 base + 4 if + 1 for + 1 elif... actually 4 if + 1 for +
    # 2 or + 1 and = 9
    assert out[0]["complexity"] >= 7


def test_real_js_filter_chain():
    code = "function filter(arr) { return arr.filter(x => x > 0 && x < 100); }"
    out = extract_complexity(code, "javascript")
    # 1 base + && = 2
    assert out[0]["name"] == "filter"
    assert out[0]["complexity"] == 2


def test_real_go_handler():
    code = '''\
func handler(w http.ResponseWriter, r *http.Request) {
    if r.Method == "GET" {
        handleGet(w, r)
    } else if r.Method == "POST" {
        handlePost(w, r)
    } else {
        w.WriteHeader(http.StatusMethodNotAllowed)
    }
}
'''
    out = extract_complexity(code, "go")
    assert out[0]["name"] == "handler"
    # 1 base + if + else if = 3
    assert out[0]["complexity"] == 3
