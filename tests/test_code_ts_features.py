"""TypeScript-specific feature extraction.

A new ``CodeFields.ts_features`` slot enumerates which TypeScript-only
constructs the snippet uses. Tags surfaced:

* ``decorator``        - ``@Component`` / ``@Injectable``
* ``as_cast``          - ``foo as Bar`` type assertions (TS-only)
* ``angle_cast``       - ``<Bar>foo`` legacy type assertions
* ``generic``          - generic type params (``function<T>``, ``class<T>``)
* ``enum``             - ``enum X { ... }``
* ``readonly``         - ``readonly x:`` property/param
* ``abstract``         - ``abstract class`` / ``abstract method()``
* ``access_modifier``  - ``public`` / ``private`` / ``protected``
* ``namespace``        - ``namespace X { ... }``
* ``optional_chain``   - ``foo?.bar``
* ``non_null_assert``  - ``foo!`` / ``foo!.bar``

The detector runs only for snippets the language layer already tagged
as typescript / tsx / ts, so a plain JS snippet that happens to use
``as`` as a variable name doesn't false-positive.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_ts_features, enrich_code

# ---- detect_ts_features helper ---------------------------------------


def test_decorator_component():
    assert "decorator" in detect_ts_features("@Component\nclass Foo {}")


def test_decorator_with_args():
    assert "decorator" in detect_ts_features("@Component({ selector: 'foo' })\nclass Foo {}")


def test_decorator_lowercase_does_not_fire():
    """``@example`` (lowercase identifier) is unusual; we require a
    leading uppercase letter to avoid picking up template literals
    and other ``@`` uses.
    """
    assert "decorator" not in detect_ts_features("@example\nfoo")


def test_as_cast_basic():
    assert "as_cast" in detect_ts_features("const x = foo as Bar;")


def test_as_cast_with_generic():
    assert "as_cast" in detect_ts_features("const x = foo as Array<string>;")


def test_as_cast_to_primitive():
    assert "as_cast" in detect_ts_features("const x = value as string;")


def test_as_cast_to_unknown():
    assert "as_cast" in detect_ts_features("const x = value as unknown;")


def test_as_cast_in_english_does_not_fire():
    """``treat as constant`` is prose; we require an identifier on
    the left and a TypeName on the right.
    """
    assert "as_cast" not in detect_ts_features("// treat as constant\n")


def test_angle_cast_basic():
    assert "angle_cast" in detect_ts_features("const x = <Bar>foo;")


def test_angle_cast_generic_inner():
    assert "angle_cast" in detect_ts_features("const x = <Array<string>>foo;")


def test_angle_cast_does_not_fire_for_jsx():
    """JSX uses ``<div>`` / ``<MyComponent>`` -- those don't fire
    because they aren't followed by an identifier or call.
    """
    code = "return <div>hi</div>;"
    assert "angle_cast" not in detect_ts_features(code)


def test_generic_function_declaration():
    code = "function identity<T>(x: T): T { return x; }"
    assert "generic" in detect_ts_features(code)


def test_generic_class_declaration():
    code = "class Container<T> { constructor(public value: T) {} }"
    assert "generic" in detect_ts_features(code)


def test_generic_interface_declaration():
    code = "interface Box<T> { value: T; }"
    assert "generic" in detect_ts_features(code)


def test_generic_type_alias_declaration():
    code = "type Maybe<T> = T | undefined;"
    assert "generic" in detect_ts_features(code)


def test_generic_with_extends_constraint():
    code = "function clone<T extends object>(x: T): T { return { ...x }; }"
    assert "generic" in detect_ts_features(code)


def test_generic_multi_param():
    code = "function pair<A, B>(a: A, b: B): [A, B] { return [a, b]; }"
    assert "generic" in detect_ts_features(code)


def test_enum_declaration():
    code = "enum Color { Red, Green, Blue }"
    assert "enum" in detect_ts_features(code)


def test_enum_assignment_form():
    """``const enum X = ...`` -- the ``enum`` keyword still tags."""
    code = "enum Direction = { up: 1, down: -1 };"
    assert "enum" in detect_ts_features(code)


def test_readonly_property():
    code = "class Foo { readonly id: string; }"
    assert "readonly" in detect_ts_features(code)


def test_readonly_optional_property():
    code = "class Foo { readonly name?: string; }"
    assert "readonly" in detect_ts_features(code)


def test_readonly_in_comment_does_not_fire():
    """A bare word ``readonly`` in a comment doesn't fire because we
    require an identifier and colon after it.
    """
    assert "readonly" not in detect_ts_features("// this field is readonly\n")


def test_abstract_class():
    code = "abstract class Shape { abstract area(): number; }"
    feats = detect_ts_features(code)
    assert "abstract" in feats


def test_access_modifier_public():
    code = "class Foo { public name: string; }"
    assert "access_modifier" in detect_ts_features(code)


def test_access_modifier_private():
    code = "class Foo { private id: number; }"
    assert "access_modifier" in detect_ts_features(code)


def test_access_modifier_protected():
    code = "class Foo { protected state: any; }"
    assert "access_modifier" in detect_ts_features(code)


def test_access_modifier_with_method():
    code = "class Foo { private doStuff() {} }"
    assert "access_modifier" in detect_ts_features(code)


def test_namespace_declaration():
    code = "namespace MyNs { export const x = 1; }"
    assert "namespace" in detect_ts_features(code)


def test_optional_chain_property():
    assert "optional_chain" in detect_ts_features("const x = foo?.bar;")


def test_optional_chain_bracket():
    assert "optional_chain" in detect_ts_features("const x = foo?.['key'];")


def test_optional_chain_call():
    assert "optional_chain" in detect_ts_features("const x = foo?.();")


def test_optional_chain_after_call():
    assert "optional_chain" in detect_ts_features("const x = a()?.b;")


def test_ternary_does_not_fire_optional_chain():
    """A ternary ``a ? b : c`` must NOT trigger optional_chain."""
    assert "optional_chain" not in detect_ts_features("const x = a ? b : c;")


def test_non_null_assert_basic():
    assert "non_null_assert" in detect_ts_features("const x = foo!;")


def test_non_null_assert_with_property():
    assert "non_null_assert" in detect_ts_features("const x = foo!.bar;")


def test_non_null_assert_with_call():
    assert "non_null_assert" in detect_ts_features("const x = foo!();")


def test_logical_not_does_not_fire():
    """A logical NOT ``!foo`` must NOT trigger non_null_assert."""
    assert "non_null_assert" not in detect_ts_features("if (!foo) return;")


def test_strict_inequality_does_not_fire():
    """A strict inequality ``foo !== bar`` must NOT trigger."""
    assert "non_null_assert" not in detect_ts_features("if (foo !== bar) {}")


def test_multiple_features_in_one_snippet():
    """A realistic Angular-ish snippet should surface many tags."""
    code = """
@Component({ selector: 'app-foo' })
export class FooComponent {
    private readonly state: string;
    public items: Array<Item> = [];
    public process<T extends Item>(x: T): T {
        const y = x as Item;
        return y!;
    }
}
"""
    feats = detect_ts_features(code)
    assert "decorator" in feats
    assert "access_modifier" in feats
    assert "readonly" in feats
    assert "as_cast" in feats
    assert "non_null_assert" in feats


def test_dedup_per_snippet():
    """Two ``as`` casts in the same snippet collapse to one tag."""
    code = "const a = x as Foo; const b = y as Bar;"
    feats = detect_ts_features(code)
    assert feats.count("as_cast") == 1


def test_empty_returns_empty_list():
    assert detect_ts_features("") == []
    assert detect_ts_features("   ") == []


def test_plain_js_returns_empty_or_few():
    """A plain JS snippet without TS features returns empty / few tags."""
    code = "const x = 1; function add(a, b) { return a + b; }"
    feats = detect_ts_features(code)
    # No TS-only feature should fire here. optional_chain / non_null_assert
    # are anchored away from comparisons and ternaries.
    assert "as_cast" not in feats
    assert "decorator" not in feats
    assert "enum" not in feats
    assert "non_null_assert" not in feats
    assert "optional_chain" not in feats


# ---- enrich_code wiring ----------------------------------------------


def test_enrich_code_fires_only_when_typescript():
    """Plain JS (no ``: type`` hints) -> language="javascript" -> no
    TS extraction even if some pattern would technically match.
    """
    ocr = OCRResult(text="const x = 1; console.log(x);")
    out = enrich_code(None, ocr)
    # Language detector should tag this as javascript.
    assert out.ts_features == []


def test_enrich_code_extracts_when_typescript():
    code = "const x: string = 'hi'; const y = x as string;"
    out = enrich_code(None, OCRResult(text=code))
    # The ``: string`` hint pushes language to typescript.
    assert out.language == "typescript"
    assert "as_cast" in out.ts_features


def test_enrich_code_caller_supplied_features_preserved():
    """Caller-supplied ts_features take precedence; the heuristic
    only fills when the caller left the slot empty.
    """
    existing = CodeFields(
        language="typescript",
        code="const x: string = 'hi'; const y = x as string;",
        ts_features=["custom_tag"],
    )
    out = enrich_code(existing, OCRResult(text=existing.code))
    assert out.ts_features == ["custom_tag"]


def test_enrich_code_fills_when_caller_empty():
    existing = CodeFields(
        language="typescript",
        code="const x: string = 'hi'; enum Color { Red, Green }",
        ts_features=[],
    )
    out = enrich_code(existing, OCRResult(text=existing.code))
    assert "enum" in out.ts_features


def test_enrich_code_empty_for_python():
    """Python snippet stays without ts_features."""
    out = enrich_code(None, OCRResult(text="def add(a, b):\n    return a + b\n"))
    assert out.ts_features == []
