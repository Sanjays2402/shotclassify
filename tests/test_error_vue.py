"""Vue.js component error parsing tests.

Vue's warnHandler / errorHandler (and the default console output in
dev mode) emit messages with a distinctive ``[Vue warn]:`` prefix
followed by an ``Error in <lifecycle slot>:`` body (or, in Vue 3,
``Unhandled error during execution of ...`` / ``Hydration <kind>
mismatch``).

Recognised shapes:
* ``[Vue warn]: Error in v-on handler: "TypeError: ..."``
* ``[Vue warn]: Error in render: "ReferenceError: ..."``
* ``[Vue warn]: Error in mounted hook: "..."``
* ``[Vue warn]: Error in callback for watcher "name": "..."``
* ``[Vue warn]: Unhandled error during execution of mounted hook``
* ``[Vue warn]: Hydration node mismatch: ...``

The branch sits BEFORE the generic Node branch in parse_error_text
because Vue runs on the JS runtime and the bare _JS_AT pattern would
otherwise steal a Vue capture's JS stack tail.
"""
from __future__ import annotations

from shotclassify_extract import parse_error_text, parse_vue_error
from shotclassify_extract.error import _parse_vue_error, _vue_likely_cause

# ---- v-on handler (most common in real-world captures) ----------


def test_vue_v_on_handler_with_typeerror():
    text = (
        '[Vue warn]: Error in v-on handler: "TypeError: Cannot read '
        "properties of undefined (reading 'x')\"\n"
        "  at <Button onClick=fn> at <HelloWorld>\n"
        "  found in\n"
        "    ---> <HelloWorld> at src/components/HelloWorld.vue\n"
        "           <App>"
    )
    result = parse_vue_error(text)
    assert result is not None
    exc, msg, file_, line_ = result
    assert exc == "TypeError"
    assert "Error in v-on handler" in msg
    assert "Cannot read properties of undefined" in msg
    assert file_ == "src/components/HelloWorld.vue"
    assert line_ is None


def test_vue_v_on_handler_via_parse_error_text():
    text = (
        '[Vue warn]: Error in v-on handler: "TypeError: foo"\n'
        "  found in\n"
        "    ---> <Button> at src/Button.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert fields.exception == "TypeError"
    assert "v-on handler" in (fields.message or "")
    assert fields.file == "src/Button.vue"
    assert fields.line is None
    assert "handler" in (fields.likely_cause or "").lower()


# ---- render function -------------------------------------------


def test_vue_render_with_referenceerror():
    text = (
        '[Vue warn]: Error in render: "ReferenceError: foo is not defined"\n'
        "  found in\n"
        "    ---> <HelloWorld> at src/components/HelloWorld.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert fields.exception == "ReferenceError"
    assert "render" in (fields.message or "").lower()
    assert fields.file == "src/components/HelloWorld.vue"


def test_vue_render_function_form():
    text = (
        '[Vue warn]: Error in render function: "TypeError: undefined is '
        'not a function"\n'
        "  found in\n"
        "    ---> <Counter> at src/Counter.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert fields.exception == "TypeError"
    assert "render" in (fields.message or "").lower()


# ---- mounted / created / updated hooks --------------------------


def test_vue_mounted_hook():
    text = (
        '[Vue warn]: Error in mounted hook: "TypeError: Cannot read '
        "properties of null (reading 'focus')\"\n"
        "  found in\n"
        "    ---> <Login> at src/views/Login.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert fields.exception == "TypeError"
    assert "mounted hook" in (fields.message or "")
    assert fields.file == "src/views/Login.vue"
    # Either the typed-hint (optional chaining for null access) OR the
    # slot-specific mounted-hook hint is acceptable.
    cause_l = (fields.likely_cause or "").lower()
    assert "nexttick" in cause_l or "optional chaining" in cause_l or "null" in cause_l


def test_vue_created_hook():
    text = (
        '[Vue warn]: Error in created hook: "Error: Network request failed"\n'
        "  found in\n"
        "    ---> <App> at src/App.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert "created hook" in (fields.message or "")
    assert fields.file == "src/App.vue"


def test_vue_updated_hook():
    text = (
        '[Vue warn]: Error in updated hook: "TypeError: x.y is undefined"\n'
        "  found in\n"
        "    ---> <Chart> at src/Chart.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert "updated hook" in (fields.message or "")


def test_vue_beforeunmount_hook():
    text = (
        '[Vue warn]: Error in beforeUnmount hook: "Error: timer cleanup failed"\n'
        "  found in\n"
        "    ---> <Timer> at src/Timer.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert "beforeUnmount" in (fields.message or "")
    assert "cleanup" in (fields.likely_cause or "").lower()


# ---- callback for watcher --------------------------------------


def test_vue_watcher_callback():
    text = (
        '[Vue warn]: Error in callback for watcher "count": '
        '"TypeError: x is not a function"\n'
        "  found in\n"
        "    ---> <Counter> at src/Counter.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert fields.exception == "TypeError"
    assert "watcher" in (fields.message or "").lower()
    assert "watcher" in (fields.likely_cause or "").lower()


def test_vue_watcher_callback_unquoted_name():
    text = (
        '[Vue warn]: Error in callback for watcher: "ReferenceError: foo"\n'
        "  found in\n"
        "    ---> <Profile> at src/Profile.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert fields.exception == "ReferenceError"


# ---- Vue 3 Unhandled error during execution --------------------


def test_vue3_unhandled_error_mounted_hook():
    text = (
        "[Vue warn]: Unhandled error during execution of mounted hook\n"
        "  at <App>"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert "VueUnhandledError" in (fields.exception or "")
    assert "mounted hook" in (fields.exception or "").lower()
    assert fields.file == "<App>"
    assert "errorhandler" in (fields.likely_cause or "").lower()


def test_vue3_unhandled_error_handler():
    text = (
        "[Vue warn]: Unhandled error during execution of native event handler\n"
        "  at <Form>"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert "VueUnhandledError" in (fields.exception or "")
    assert fields.file == "<Form>"


# ---- Vue 3 Hydration mismatch ---------------------------------


def test_vue3_hydration_node_mismatch():
    text = (
        "[Vue warn]: Hydration node mismatch:\n"
        "- rendered on server: <div>foo</div>\n"
        "- expected on client: <div>bar</div>"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert "HydrationNodeMismatch" in (fields.exception or "")
    assert "ssr" in (fields.likely_cause or "").lower()


def test_vue3_hydration_text_mismatch():
    text = (
        "[Vue warn]: Hydration text mismatch in <p>:\n"
        "- rendered on server: foo\n"
        "- expected on client: bar"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert "HydrationTextMismatch" in (fields.exception or "")


def test_vue3_hydration_class_mismatch():
    text = "[Vue warn]: Hydration class mismatch: server / client differ"
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert "HydrationClassMismatch" in (fields.exception or "")


def test_vue3_hydration_attribute_mismatch():
    text = "[Vue warn]: Hydration attribute mismatch: data-v-foo not on client"
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert "HydrationAttributeMismatch" in (fields.exception or "")


# ---- File / component path extraction --------------------------


def test_vue_component_file_innermost_wins():
    """When the found-in tree shows multiple components, the leaf wins."""
    text = (
        '[Vue warn]: Error in mounted hook: "TypeError: x"\n'
        "  found in\n"
        "    ---> <Child> at src/Child.vue\n"
        "           <Parent> at src/Parent.vue\n"
        "             <App> at src/App.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    # First `--->` is the innermost (leaf) -- Child wins.
    assert fields.file == "src/Child.vue"


def test_vue_component_tag_fallback_no_file_path():
    text = (
        '[Vue warn]: Error in render: "TypeError: x"\n'
        "  found in\n"
        "    ---> <Counter>"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert fields.file == "<Counter>"


def test_vue_no_component_tree():
    """No `found in` block at all -- file slot is None."""
    text = '[Vue warn]: Error in mounted hook: "TypeError: bad"'
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert fields.file is None


def test_vue_nested_vue_paths():
    """Nested .vue file path like ``src/views/admin/Settings.vue`` works."""
    text = (
        '[Vue warn]: Error in render: "TypeError: bad"\n'
        "  found in\n"
        "    ---> <Settings> at src/views/admin/Settings.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert fields.file == "src/views/admin/Settings.vue"


# ---- Negative: NOT Vue ------------------------------------------


def test_vue_plain_node_error_rejects():
    """A plain Node TypeError without ``[Vue warn]:`` prefix is NOT Vue."""
    text = (
        "TypeError: Cannot read properties of undefined (reading 'x')\n"
        "    at Object.<anonymous> (file.js:10:15)"
    )
    fields = parse_error_text(text)
    assert fields.framework != "vue"
    # Should tag as node.
    assert fields.framework == "node"


def test_vue_prelude_without_slot_rejects():
    """``[Vue warn]:`` prefix WITHOUT a recognised slot returns None."""
    text = "[Vue warn]: Some deprecated API used"
    assert _parse_vue_error(text) is None


def test_vue_empty_text_rejects():
    assert _parse_vue_error("") is None
    assert _parse_vue_error(None) is None  # type: ignore[arg-type]


def test_vue_prose_with_vue_word_rejects():
    """Prose mentioning Vue without the prelude doesn't fire."""
    text = "We had an error in our Vue render function yesterday."
    assert _parse_vue_error(text) is None


def test_vue_does_not_steal_react_error():
    """A React error without [Vue warn]: doesn't tag as Vue."""
    text = (
        "Error: Cannot read property of undefined\n"
        "    at HelloWorld (file.js:5:10)\n"
        "    at div\n"
        "    at App"
    )
    fields = parse_error_text(text)
    assert fields.framework != "vue"


# ---- Likely cause hints -----------------------------------------


def test_vue_likely_cause_typeerror_with_undefined():
    cause = _vue_likely_cause("TypeError", "Error in v-on handler: Cannot read property of undefined")
    assert cause is not None
    assert "optional chaining" in cause.lower() or "null" in cause.lower()


def test_vue_likely_cause_referenceerror():
    cause = _vue_likely_cause("ReferenceError", "Error in render: foo is not defined")
    assert cause is not None
    # The slot-specific render cause may win; both are valid -- check
    # we get one of the meaningful Vue-specific hints (render OR
    # template-scope hint).
    assert cause is not None and any(
        kw in cause.lower()
        for kw in ("render", "template", "scope", "computed", "props")
    )


def test_vue_likely_cause_hydration():
    cause = _vue_likely_cause("HydrationNodeMismatch", None)
    assert cause is not None
    assert "ssr" in cause.lower() or "non-deterministic" in cause.lower()


def test_vue_likely_cause_watcher():
    cause = _vue_likely_cause("TypeError", "Error in callback for watcher: x")
    assert cause is not None
    assert "watcher" in cause.lower() or "watch" in cause.lower()


def test_vue_likely_cause_mounted():
    cause = _vue_likely_cause("TypeError", "Error in mounted hook: focus failed")
    assert cause is not None
    assert "mounted" in cause.lower() or "nexttick" in cause.lower()


def test_vue_likely_cause_setup():
    cause = _vue_likely_cause("Error", "Error in setup function: ref init failed")
    assert cause is not None
    assert "setup" in cause.lower() or "composition" in cause.lower()


def test_vue_likely_cause_directive():
    cause = _vue_likely_cause("Error", "Error in directive focus hook: dom missing")
    assert cause is not None
    assert "directive" in cause.lower()


def test_vue_likely_cause_unhandled_default():
    cause = _vue_likely_cause("VueUnhandledError(mounted hook)", None)
    assert cause is not None
    # Either lifecycle-specific OR generic unhandled hint is fine.
    assert "mounted" in cause.lower() or "errorhandler" in cause.lower()


def test_vue_likely_cause_returns_fallback():
    cause = _vue_likely_cause("VueError(unknown)", None)
    assert cause is not None


# ---- Real-world capture combinations ----------------------------


def test_vue_real_world_dev_console():
    """Real Vue 2 dev-console capture from a TodoList app."""
    text = (
        '[Vue warn]: Error in v-on handler: "TypeError: Cannot read '
        "properties of null (reading 'value')\"\n"
        "\n"
        "  found in\n"
        "\n"
        "  ---> <TodoInput> at src/components/TodoInput.vue\n"
        "         <TodoApp> at src/App.vue\n"
        "           <Root>\n"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert fields.exception == "TypeError"
    assert fields.file == "src/components/TodoInput.vue"


def test_vue3_setup_throws():
    text = (
        '[Vue warn]: Error in setup function: "Error: API key not set"\n'
        "  found in\n"
        "    ---> <ChartCard> at src/widgets/ChartCard.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    assert "setup" in (fields.message or "").lower()
    assert "setup" in (fields.likely_cause or "").lower()


def test_vue_handler_outranks_jsat_stealing():
    """The Vue branch should win against the Node branch when both
    could match (a Vue capture often has a JS stack tail that _JS_AT
    would otherwise steal)."""
    text = (
        '[Vue warn]: Error in mounted hook: "TypeError: foo"\n'
        "    at Foo.bar (file.vue:10:15)\n"
        "    at Object.<anonymous> (file.js:25:30)\n"
        "  found in\n"
        "    ---> <Foo> at src/Foo.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
    # The .vue file path wins from the found-in tree, not the JS frame.
    assert fields.file == "src/Foo.vue"


def test_vue_case_insensitive_prelude():
    """``[VUE WARN]:`` uppercase variant still detected."""
    text = (
        '[VUE WARN]: Error in render: "TypeError: x"\n'
        "  found in\n"
        "    ---> <Foo> at src/Foo.vue"
    )
    fields = parse_error_text(text)
    assert fields.framework == "vue"
