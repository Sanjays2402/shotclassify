"""Code type-annotation density detection tests.

A new CodeFields.type_annotation_density float in [0.0, 1.0]
captures the share of function-arg + return slots that carry a
type annotation.

* 0.0 -> no function defs OR no slots typed
* 1.0 -> every slot typed
* Strictly-typed languages (Java / Kotlin / Go / Rust / Scala /
  Swift / C# / Haskell / OCaml) return 1.0 when at least one
  function-def shape is detected.
* ``self`` / ``cls`` / ``this`` excluded from both numerator
  and denominator.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_type_annotation_density, enrich_code

# ---- Python: fully typed ----------------------------------------


def test_python_fully_typed_simple():
    code = "def foo(x: int, y: str) -> bool:\n    return True"
    out = detect_type_annotation_density(code, "python")
    # 2 args typed + 1 return typed = 3/3 = 1.0
    assert out == 1.0


def test_python_fully_typed_with_complex_annotations():
    code = (
        "def process(items: list[dict[str, int]], "
        "config: dict | None = None) -> bool:\n"
        "    return True"
    )
    out = detect_type_annotation_density(code, "python")
    # 2 args + 1 return all typed = 1.0
    assert out == 1.0


# ---- Python: untyped ---------------------------------------------


def test_python_fully_untyped():
    code = "def foo(x, y):\n    return x + y"
    out = detect_type_annotation_density(code, "python")
    # 2 args untyped + 1 return untyped = 0/3 = 0.0
    assert out == 0.0


def test_python_no_args_no_return_type():
    code = "def foo():\n    pass"
    out = detect_type_annotation_density(code, "python")
    # Edge case: no args. We don't count the return slot when args
    # is empty (denominator stays 0 -> returns 0.0).
    assert out == 0.0


# ---- Python: partially typed -------------------------------------


def test_python_args_typed_no_return_type():
    code = "def foo(x: int, y: str):\n    return True"
    out = detect_type_annotation_density(code, "python")
    # 2 typed args + 1 untyped return = 2/3 = 0.67
    assert out == 0.67


def test_python_one_arg_typed():
    code = "def foo(x: int, y) -> bool:\n    return True"
    out = detect_type_annotation_density(code, "python")
    # 1 typed arg + 1 untyped arg + 1 typed return = 2/3 = 0.67
    assert out == 0.67


def test_python_some_args_typed():
    code = "def f(a: int, b, c: str, d):\n    pass"
    out = detect_type_annotation_density(code, "python")
    # 2 typed + 2 untyped + 1 untyped return = 2/5 = 0.4
    assert out == 0.4


# ---- Python: self / cls exclusion --------------------------------


def test_python_self_not_counted():
    code = "def method(self, x: int, y: str) -> bool:\n    return True"
    out = detect_type_annotation_density(code, "python")
    # self excluded; 2 typed args + 1 typed return = 3/3 = 1.0
    assert out == 1.0


def test_python_cls_not_counted():
    code = "def cls_method(cls, x: int) -> str:\n    return ''"
    out = detect_type_annotation_density(code, "python")
    # cls excluded; 1 typed arg + 1 typed return = 2/2 = 1.0
    assert out == 1.0


def test_python_self_only_function():
    code = "def method(self):\n    pass"
    out = detect_type_annotation_density(code, "python")
    # self excluded; no args -> 0.0
    assert out == 0.0


# ---- Python: default values --------------------------------------


def test_python_default_value_typed_arg():
    code = "def foo(x: int = 5, y: str = '') -> bool:\n    return True"
    out = detect_type_annotation_density(code, "python")
    assert out == 1.0


def test_python_default_value_untyped_arg():
    code = "def foo(x=5, y=''):\n    pass"
    out = detect_type_annotation_density(code, "python")
    # Untyped + untyped + untyped return = 0/3 = 0.0
    assert out == 0.0


# ---- Python: *args / **kwargs ------------------------------------


def test_python_args_kwargs_typed():
    code = "def foo(*args: int, **kwargs: str) -> None:\n    pass"
    out = detect_type_annotation_density(code, "python")
    # 2 typed slots + 1 typed return = 1.0
    assert out == 1.0


def test_python_args_kwargs_untyped():
    code = "def foo(*args, **kwargs):\n    pass"
    out = detect_type_annotation_density(code, "python")
    # 2 untyped slots + 1 untyped return = 0/3 = 0.0
    assert out == 0.0


# ---- Python: async functions -------------------------------------


def test_python_async_def_typed():
    code = "async def foo(x: int) -> None:\n    pass"
    out = detect_type_annotation_density(code, "python")
    assert out == 1.0


def test_python_async_def_untyped():
    code = "async def foo(x, y):\n    pass"
    out = detect_type_annotation_density(code, "python")
    assert out == 0.0


# ---- Python: multiple functions ----------------------------------


def test_python_multiple_functions_average():
    code = (
        "def fully_typed(x: int, y: str) -> bool:\n"
        "    return True\n"
        "\n"
        "def untyped(a, b):\n"
        "    return a + b\n"
    )
    out = detect_type_annotation_density(code, "python")
    # Fully typed: 2 args + 1 return = 3/3
    # Untyped: 2 args + 1 untyped return = 0/3
    # Combined: 3/6 = 0.5
    assert out == 0.5


def test_python_three_functions_mixed():
    code = (
        "def a(x: int) -> bool:\n"
        "    return True\n"
        "def b(y: str):\n"
        "    pass\n"
        "def c(z):\n"
        "    pass\n"
    )
    out = detect_type_annotation_density(code, "python")
    # a: 1 typed arg + 1 typed return = 2/2
    # b: 1 typed arg + 1 untyped return = 1/2
    # c: 1 untyped arg + 1 untyped return = 0/2
    # Combined: 3/6 = 0.5
    assert out == 0.5


# ---- TypeScript: fully typed -------------------------------------


def test_typescript_function_typed():
    code = "function foo(x: number, y: string): boolean { return true; }"
    out = detect_type_annotation_density(code, "typescript")
    # 2 typed args + 1 typed return = 1.0
    assert out == 1.0


def test_typescript_arrow_function_typed():
    code = "const foo = (x: number, y: string): boolean => true;"
    out = detect_type_annotation_density(code, "typescript")
    assert out == 1.0


def test_typescript_arrow_no_args():
    code = "const foo = (): void => {};"
    out = detect_type_annotation_density(code, "typescript")
    # Empty args, typed return slot. We count the typed return
    # as 1/1 = 1.0 because the function-def shape was found and
    # the only counted slot (the return) is typed.
    assert out == 1.0


# ---- TypeScript: untyped -----------------------------------------


def test_typescript_function_untyped():
    code = "function foo(x, y) { return x + y; }"
    out = detect_type_annotation_density(code, "typescript")
    # 2 untyped args + 1 untyped return = 0/3 = 0.0
    assert out == 0.0


def test_javascript_arrow_function_untyped():
    code = "const foo = (x, y) => x + y;"
    out = detect_type_annotation_density(code, "javascript")
    assert out == 0.0


# ---- TypeScript: partially typed ---------------------------------


def test_typescript_partial_typing():
    code = "function foo(x: number, y): boolean { return true; }"
    out = detect_type_annotation_density(code, "typescript")
    # 1 typed + 1 untyped + 1 typed return = 2/3 = 0.67
    assert out == 0.67


# ---- TypeScript: optional args -----------------------------------


def test_typescript_optional_arg_typed():
    code = "function foo(x: number, y?: string): boolean { return true; }"
    out = detect_type_annotation_density(code, "typescript")
    assert out == 1.0


# ---- Strictly-typed languages ------------------------------------


def test_java_returns_1_when_func_present():
    code = "public boolean foo(int x, String y) { return true; }"
    out = detect_type_annotation_density(code, "java")
    assert out == 1.0


def test_kotlin_returns_1_when_func_present():
    code = "fun foo(x: Int, y: String): Boolean { return true }"
    out = detect_type_annotation_density(code, "kotlin")
    assert out == 1.0


def test_go_returns_1_when_func_present():
    code = "func foo(x int, y string) bool { return true }"
    out = detect_type_annotation_density(code, "go")
    assert out == 1.0


def test_rust_returns_1_when_func_present():
    code = "fn foo(x: i32, y: String) -> bool { true }"
    out = detect_type_annotation_density(code, "rust")
    assert out == 1.0


def test_csharp_returns_1_when_func_present():
    code = "public bool Foo(int x, string y) { return true; }"
    out = detect_type_annotation_density(code, "c#")
    assert out == 1.0


def test_swift_returns_1_when_func_present():
    code = "func foo(x: Int, y: String) -> Bool { return true }"
    out = detect_type_annotation_density(code, "swift")
    assert out == 1.0


def test_strictly_typed_no_func_returns_0():
    code = "class Foo { int x = 5; }"
    out = detect_type_annotation_density(code, "java")
    # No function-def shape detected -> 0.0
    assert out == 0.0


# ---- Empty / None inputs -----------------------------------------


def test_empty_code_returns_0():
    assert detect_type_annotation_density("", "python") == 0.0


def test_none_code_returns_0():
    assert detect_type_annotation_density(None, "python") == 0.0  # type: ignore[arg-type]


def test_non_string_code_returns_0():
    assert detect_type_annotation_density(123, "python") == 0.0  # type: ignore[arg-type]


def test_no_function_defs_returns_0():
    code = "x = 5\ny = 'hello'\nprint(x, y)"
    out = detect_type_annotation_density(code, "python")
    assert out == 0.0


# ---- Realistic snippets ------------------------------------------


def test_realistic_typed_python_class():
    code = """
class UserService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get_user(self, user_id: int) -> User | None:
        return self.db.query(user_id)

    def create_user(self, name: str, email: str) -> User:
        return User(name=name, email=email)
"""
    out = detect_type_annotation_density(code, "python")
    # All 3 methods fully typed (self excluded).
    # __init__: 1 typed arg + 1 typed return = 2/2
    # get_user: 1 typed arg + 1 typed return = 2/2
    # create_user: 2 typed args + 1 typed return = 3/3
    # Combined: 7/7 = 1.0
    assert out == 1.0


def test_realistic_untyped_python_legacy():
    code = """
class UserService:
    def __init__(self, db):
        self.db = db

    def get_user(self, user_id):
        return self.db.query(user_id)
"""
    out = detect_type_annotation_density(code, "python")
    # 0 typed across 2 methods.
    assert out == 0.0


def test_realistic_partial_python_migration():
    code = """
def old_function(x, y):
    return x + y

def new_function(x: int, y: int) -> int:
    return x + y
"""
    out = detect_type_annotation_density(code, "python")
    # old: 0/3 typed
    # new: 3/3 typed
    # Combined: 3/6 = 0.5
    assert out == 0.5


def test_realistic_typescript_react_component():
    code = """
function Button(props: ButtonProps): JSX.Element {
    return <button>{props.label}</button>;
}

const Card = (props: CardProps): JSX.Element => {
    return <div>{props.children}</div>;
};
"""
    out = detect_type_annotation_density(code, "typescript")
    # Button: 1 typed arg + 1 typed return = 2/2
    # Card: 1 typed arg + 1 typed return = 2/2
    # Combined: 4/4 = 1.0
    assert out == 1.0


# ---- Boundary values ---------------------------------------------


def test_value_rounded_to_two_decimals():
    code = (
        "def f1(a, b, c, d, e, f, g): pass\n"
        "def f2(a: int, b, c, d, e, f, g): pass\n"
    )
    # f1: 0/8 typed (7 args + 1 ret)
    # f2: 1/8 typed (1 arg + 7 untyped ret/args)
    # Combined: 1/16 = 0.0625 -> rounded to 0.06
    out = detect_type_annotation_density(code, "python")
    assert out == 0.06


def test_returns_clamped_to_max_1():
    code = "def f(x: int) -> bool: pass"
    out = detect_type_annotation_density(code, "python")
    assert out <= 1.0


def test_no_language_works_for_python():
    """Python `def` shape is detected even without a language tag."""
    code = "def foo(x: int) -> bool:\n    return True"
    out = detect_type_annotation_density(code, None)
    # Python def works without language tag (fallback).
    assert out == 1.0


# ---- enrich_code integration -------------------------------------


def test_enrich_code_populates_density():
    """enrich_code surfaces type_annotation_density."""
    ocr = OCRResult(text="def foo(x: int, y: str) -> bool:\n    return True")
    code = enrich_code(None, ocr)
    assert code.type_annotation_density == 1.0


def test_enrich_code_zero_for_untyped_python():
    ocr = OCRResult(text="def foo(x, y):\n    return x + y")
    code = enrich_code(None, ocr)
    assert code.type_annotation_density == 0.0


def test_enrich_code_preserves_caller_density():
    """Caller-supplied density is preserved; OCR pass doesn't override."""
    existing = CodeFields(
        code="def foo(x): pass",
        type_annotation_density=0.5,
    )
    ocr = OCRResult(text="")
    code = enrich_code(existing, ocr)
    assert code.type_annotation_density == 0.5


def test_enrich_code_zero_when_no_func_defs():
    """A snippet with no functions stays at 0.0."""
    ocr = OCRResult(text="print('hello world')")
    code = enrich_code(None, ocr)
    assert code.type_annotation_density == 0.0


# ---- Edge cases --------------------------------------------------


def test_complex_python_generics():
    code = "def foo(x: dict[str, list[int]]) -> tuple[int, str]:\n    pass"
    out = detect_type_annotation_density(code, "python")
    assert out == 1.0


def test_python_union_type():
    code = "def foo(x: int | str | None) -> bool:\n    return True"
    out = detect_type_annotation_density(code, "python")
    assert out == 1.0


def test_python_callable_arg():
    code = "def foo(callback: Callable[[int], bool]) -> None:\n    pass"
    out = detect_type_annotation_density(code, "python")
    assert out == 1.0


def test_split_args_respects_nesting():
    """Complex args with commas inside [] / {} shouldn't double-count."""
    code = "def foo(x: dict[str, int], y: list[tuple[int, str]]) -> None:\n    pass"
    out = detect_type_annotation_density(code, "python")
    # 2 typed args + 1 typed return = 1.0
    assert out == 1.0


def test_short_python_lambda_ignored():
    """Lambdas don't qualify as a function def for our purposes."""
    code = "f = lambda x: x + 1"
    out = detect_type_annotation_density(code, "python")
    assert out == 0.0
