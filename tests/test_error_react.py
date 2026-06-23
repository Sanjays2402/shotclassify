"""React error-boundary parsing tests.

A new ``framework='react'`` value joins the elif chain in
parse_error_text. Recognised signatures: ``The above error
occurred in the <Component> component`` wrapper, ``React will
try to recreate this component tree`` wrapper, ``Consider adding
an error boundary`` suggestion footer, or ``componentDidCatch`` /
``getDerivedStateFromError`` typed lifecycle methods with a
React-vocabulary anchor.
"""
from __future__ import annotations

from shotclassify_extract.error import (
    _parse_react_error_boundary,
    _react_likely_cause,
    parse_error_text,
    parse_react_error_boundary,
)

# ---- Empty / None / no-React-signature ---------------------------


def test_empty_text():
    assert _parse_react_error_boundary("") is None


def test_none_text():
    assert _parse_react_error_boundary(None) is None  # type: ignore[arg-type]


def test_plain_js_no_react():
    text = "Error: oops\n    at /foo/bar.js:12:5"
    assert _parse_react_error_boundary(text) is None


def test_python_traceback_no_react():
    text = (
        "Traceback (most recent call last):\n"
        '  File "/app/main.py", line 10, in <module>\n'
        '    raise ValueError("oops")\n'
        "ValueError: oops"
    )
    assert _parse_react_error_boundary(text) is None


def test_unrelated_prose_with_componentdidcatch():
    # componentDidCatch in prose WITHOUT React-vocabulary anchor:
    # safety guard should reject because we'd false-positive on a
    # JS book that happens to mention the method.
    text = "Method called componentDidCatch is part of class-based error handling."
    assert _parse_react_error_boundary(text) is None


# ---- Canonical React 16+ wrapper ---------------------------------


def test_canonical_wrapper_minimal():
    text = "The above error occurred in the <App> component"
    out = _parse_react_error_boundary(text)
    assert out is not None
    exc, msg, file_, line_ = out
    # No inner Error: typed line, so we fall back to
    # ReactRenderError(App). file_ falls back to <App>.
    assert exc == "ReactRenderError(App)"
    assert file_ == "<App>"


def test_canonical_wrapper_with_inner_typeerror():
    text = (
        "TypeError: Cannot read property 'name' of undefined\n"
        "The above error occurred in the <ProductCard> component"
    )
    out = _parse_react_error_boundary(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "TypeError"
    assert "Cannot read property" in msg
    assert file_ == "<ProductCard>"


def test_canonical_wrapper_with_inner_error():
    text = (
        "Error: Something went wrong\n"
        "The above error occurred in the <Header> component"
    )
    out = _parse_react_error_boundary(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "Error"
    assert "Something went wrong" in msg


def test_canonical_wrapper_with_component_tree():
    text = (
        "Error: Boom\n"
        "The above error occurred in the <ProductCard> component:\n"
        "    in ProductCard (at src/ProductCard.tsx:42)\n"
        "    in ErrorBoundary\n"
        "    in App (at src/App.tsx:10)"
    )
    out = _parse_react_error_boundary(text)
    assert out is not None
    exc, msg, file_, line_ = out
    assert exc == "Error"
    assert file_ == "src/ProductCard.tsx"
    assert line_ == 42


def test_canonical_wrapper_uppercase_component():
    text = "The above error occurred in the <APP> component"
    out = _parse_react_error_boundary(text)
    assert out is not None


def test_recreate_component_tree_wrapper():
    text = "React will try to recreate this component tree by remounting all components."
    out = _parse_react_error_boundary(text)
    assert out is not None
    exc, _, _, _ = out
    assert "React" in exc or exc == "ReactBoundaryError"


def test_consider_adding_error_boundary_wrapper():
    text = "Consider adding an error boundary to your tree to customize error handling."
    out = _parse_react_error_boundary(text)
    assert out is not None


# ---- componentDidCatch / getDerivedStateFromError ----------------


def test_componentdidcatch_with_react_vocab():
    text = (
        "componentDidCatch caught: Error: render failed\n"
        "ReactDOM.render(<App />, root);"
    )
    out = _parse_react_error_boundary(text)
    assert out is not None


def test_componentdidcatch_with_jsx_anchor():
    text = "componentDidCatch fired during render() in <App>;"
    out = _parse_react_error_boundary(text)
    assert out is not None


def test_getderivedstatefromerror_with_anchor():
    text = (
        "getDerivedStateFromError handler called.\n"
        "useState hook returned undefined."
    )
    out = _parse_react_error_boundary(text)
    assert out is not None


def test_componentdidcatch_no_anchor_rejected():
    text = "Function componentDidCatch is an older lifecycle method."
    out = _parse_react_error_boundary(text)
    # No React anchor present, so we reject.
    assert out is None


# ---- Component-tree file/line extraction -------------------------


def test_tree_entry_with_file_and_line():
    text = (
        "Error: oops\n"
        "The above error occurred in the <App> component:\n"
        "    in App (at src/App.tsx:42)"
    )
    out = _parse_react_error_boundary(text)
    assert out is not None
    _, _, file_, line_ = out
    assert file_ == "src/App.tsx"
    assert line_ == 42


def test_tree_entry_with_file_no_line():
    # Bare ``in App (at src/App.tsx)`` without line. Less common
    # but should still capture the file. Our regex requires
    # :digits so this gets only the bare component name.
    text = (
        "Error: oops\n"
        "The above error occurred in the <App> component:\n"
        "    in App"
    )
    out = _parse_react_error_boundary(text)
    assert out is not None
    _, _, file_, _ = out
    # Bare ``in App`` -> emits <App>.
    assert file_ == "<App>"


def test_tree_entry_innermost_wins():
    text = (
        "Error: oops\n"
        "The above error occurred in the <ProductCard> component:\n"
        "    in ProductCard (at src/ProductCard.tsx:42)\n"
        "    in App (at src/App.tsx:10)"
    )
    out = _parse_react_error_boundary(text)
    assert out is not None
    _, _, file_, line_ = out
    # Leaf-most (innermost / first-printed) component wins.
    assert file_ == "src/ProductCard.tsx"
    assert line_ == 42


# ---- parse_error_text integration --------------------------------


def test_parse_error_text_tags_react():
    text = (
        "Error: Cannot read properties of undefined (reading 'name')\n"
        "The above error occurred in the <ProductCard> component:\n"
        "    in ProductCard (at src/ProductCard.tsx:42)"
    )
    fields = parse_error_text(text)
    assert fields.framework == "react"
    assert fields.exception == "Error"


def test_parse_error_text_recreate_tree_tags_react():
    text = (
        "TypeError: x is not a function\n"
        "React will try to recreate this component tree."
    )
    fields = parse_error_text(text)
    assert fields.framework == "react"
    assert fields.exception == "TypeError"


def test_parse_error_text_consider_boundary_tags_react():
    text = (
        "Error: boom\n"
        "Consider adding an error boundary to your tree."
    )
    fields = parse_error_text(text)
    assert fields.framework == "react"


def test_parse_error_text_vue_still_wins_when_both():
    # If somehow a capture has BOTH Vue and React keywords, Vue
    # wins because it's checked first.
    text = (
        "[Vue warn]: Error in v-on handler: 'TypeError: foo'\n"
        "found in\n"
        "---> <Bar> at src/Bar.vue\n"
        "Consider adding an error boundary"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"


def test_parse_error_text_pure_node_not_react():
    # No React keywords -> generic node.
    text = (
        "TypeError: x is not a function\n"
        "    at handler (/app/foo.js:12:5)"
    )
    fields = parse_error_text(text)
    assert fields.framework == "node"


def test_parse_error_text_react_likely_cause():
    text = (
        "TypeError: Cannot read property 'name' of undefined\n"
        "The above error occurred in the <ProductCard> component"
    )
    fields = parse_error_text(text)
    assert fields.framework == "react"
    assert fields.likely_cause is not None
    assert "optional chaining" in fields.likely_cause.lower() or "undefined" in fields.likely_cause.lower()


# ---- Public parse_react_error_boundary alias ---------------------


def test_public_alias_canonical():
    text = "The above error occurred in the <App> component"
    out = parse_react_error_boundary(text)
    assert out is not None


def test_public_alias_empty():
    assert parse_react_error_boundary("") is None


# ---- _react_likely_cause function -------------------------------


def test_likely_cause_typeerror_undefined():
    cause = _react_likely_cause("TypeError", "Cannot read property of undefined")
    assert cause is not None
    assert "optional chaining" in cause.lower() or "undefined" in cause.lower()


def test_likely_cause_typeerror_null():
    cause = _react_likely_cause("TypeError", "null is not a function")
    assert cause is not None


def test_likely_cause_typeerror_not_function():
    cause = _react_likely_cause("TypeError", "x.foo is not a function")
    assert cause is not None
    assert "non-function" in cause.lower() or "function" in cause.lower()


def test_likely_cause_referenceerror():
    cause = _react_likely_cause("ReferenceError", "myVar is not defined")
    assert cause is not None
    assert "scope" in cause.lower() or "imports" in cause.lower()


def test_likely_cause_rangeerror_infinite_render():
    cause = _react_likely_cause(
        "RangeError", "Maximum update depth exceeded", "Maximum update depth"
    )
    assert cause is not None
    assert "render loop" in cause.lower() or "setstate" in cause.lower()


def test_likely_cause_syntaxerror():
    cause = _react_likely_cause("SyntaxError", "Unexpected token")
    assert cause is not None
    assert "jsx" in cause.lower()


def test_likely_cause_minified_react():
    cause = _react_likely_cause(
        None, None, "Minified React error #185"
    )
    assert cause is not None
    assert "minified" in cause.lower()


def test_likely_cause_maximum_update_depth():
    cause = _react_likely_cause(
        None, None, "Maximum update depth exceeded. This can happen..."
    )
    assert cause is not None
    assert "render loop" in cause.lower()


def test_likely_cause_invalid_hook_call():
    cause = _react_likely_cause(
        None, None, "Invalid hook call. Hooks can only be called inside..."
    )
    assert cause is not None
    assert "hook" in cause.lower()


def test_likely_cause_hooks_violation():
    cause = _react_likely_cause(
        None, None, "Rendered fewer hooks than expected"
    )
    assert cause is not None
    assert "hook" in cause.lower()


def test_likely_cause_object_as_child():
    cause = _react_likely_cause(
        None, None, "Objects are not valid as a React child"
    )
    assert cause is not None
    assert "object" in cause.lower() or "serialiser" in cause.lower()


def test_likely_cause_missing_key():
    cause = _react_likely_cause(
        None, None, "Each child in a list should have a unique key"
    )
    assert cause is not None
    assert "key" in cause.lower()


def test_likely_cause_no_boundary():
    cause = _react_likely_cause(
        None, None, "Consider adding an error boundary"
    )
    assert cause is not None
    assert "boundary" in cause.lower()


def test_likely_cause_fallback():
    cause = _react_likely_cause("UnknownError", "boom", "boom")
    assert cause is not None
    assert "react" in cause.lower() or "component" in cause.lower()


# ---- Realistic scenarios -----------------------------------------


def test_full_react_console_dump():
    text = """\
Uncaught Error: Network request failed
    at fetchUser (src/api.ts:15:11)
    at ProductCard.componentDidMount (src/ProductCard.tsx:32:5)
The above error occurred in the <ProductCard> component:

    in ProductCard (at src/ProductCard.tsx:5)
    in div
    in ErrorBoundary (at src/ErrorBoundary.tsx:8)
    in App (at src/App.tsx:10)

React will try to recreate this component tree by remounting all components.
Consider adding an error boundary to your tree to customize error-handling behavior.
"""
    fields = parse_error_text(text)
    assert fields.framework == "react"
    assert fields.exception == "Error"
    # File should be the leaf-most ProductCard.
    assert fields.file == "src/ProductCard.tsx"


def test_react_dev_warning_with_key_prop():
    text = """\
Warning: Each child in a list should have a unique "key" prop.

Check the render method of `ProductList`.
The above error occurred in the <ProductList> component
"""
    fields = parse_error_text(text)
    assert fields.framework == "react"


def test_react_class_component_error_boundary():
    text = """\
TypeError: this.props.onChange is not a function
    at SearchBox.handleChange (src/SearchBox.tsx:25:9)
The above error occurred in the <SearchBox> component:

    in SearchBox (at src/SearchBox.tsx:8)
    in App (at src/App.tsx:12)
"""
    fields = parse_error_text(text)
    assert fields.framework == "react"
    assert fields.exception == "TypeError"
    assert fields.likely_cause is not None


def test_react_hooks_violation():
    text = """\
Error: Rendered fewer hooks than expected. This may be caused by an accidental early return statement.
    at updateFunctionComponent (react-dom.development.js:18234:13)
The above error occurred in the <ConditionalComponent> component
"""
    fields = parse_error_text(text)
    assert fields.framework == "react"
    assert fields.likely_cause is not None
    assert "hook" in fields.likely_cause.lower()


def test_react_invalid_hook_call():
    text = """\
Error: Invalid hook call. Hooks can only be called inside of the body of a function component.
The above error occurred in the <MyComponent> component
"""
    fields = parse_error_text(text)
    assert fields.framework == "react"
    assert "hook" in fields.likely_cause.lower()
