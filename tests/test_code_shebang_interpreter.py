"""Code shebang interpreter extraction.

A new ``CodeFields.interpreter`` populates whenever the snippet
starts with a Unix shebang line (``#!/path/to/x`` or
``#!/usr/bin/env x``). The short interpreter name is stored
(``bash``, ``python3``, ``node``, ``ruby``, etc.) so dashboards
can group scripts by their runtime without parsing the full
shebang path.

Recognised shapes:

* Direct path: ``#!/bin/bash`` -> ``bash``, ``#!/usr/bin/python3.11``
  -> ``python3.11``.
* ``env`` wrapper: ``#!/usr/bin/env bash`` -> ``bash``.
* ``env -S`` split-args form: ``#!/usr/bin/env -S python3 -O``
  -> ``python3``.
* ``env --split-string=python3`` inline form -> ``python3``.

Edge cases:

* A shebang inside the body (not on line 1) is ignored.
* Leading whitespace before ``#!`` is rejected because a real
  shebang must occupy the first two bytes of the file.
* The LLM wire format accepts ``interpreter`` in the code payload
  so a vision model can populate it directly.
"""
from __future__ import annotations

import pytest
from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_interpreter, enrich_code

# ---- detect_interpreter: direct path -----------------------------------


@pytest.mark.parametrize(
    "shebang,expected",
    [
        ("#!/bin/bash", "bash"),
        ("#!/usr/bin/bash", "bash"),
        ("#!/usr/local/bin/bash", "bash"),
        ("#!/bin/sh", "sh"),
        ("#!/bin/zsh", "zsh"),
        ("#!/usr/bin/fish", "fish"),
        ("#!/usr/bin/perl", "perl"),
        ("#!/usr/local/bin/ruby", "ruby"),
        ("#!/usr/bin/python", "python"),
        ("#!/usr/bin/python3", "python3"),
        ("#!/usr/bin/python3.11", "python3.11"),
    ],
)
def test_direct_path_shebang(shebang, expected):
    code = f"{shebang}\necho hello\n"
    assert detect_interpreter(code) == expected


# ---- detect_interpreter: env wrapper -----------------------------------


@pytest.mark.parametrize(
    "shebang,expected",
    [
        ("#!/usr/bin/env bash", "bash"),
        ("#!/usr/bin/env sh", "sh"),
        ("#!/usr/bin/env python", "python"),
        ("#!/usr/bin/env python3", "python3"),
        ("#!/usr/bin/env node", "node"),
        ("#!/usr/bin/env ruby", "ruby"),
        ("#!/usr/bin/env deno", "deno"),
        ("#!/usr/bin/env perl", "perl"),
    ],
)
def test_env_wrapped_shebang(shebang, expected):
    code = f"{shebang}\necho hello\n"
    assert detect_interpreter(code) == expected


def test_env_with_s_flag_split_args():
    """``env -S python3 -O`` is the GNU coreutils >= 8.30 split-args
    form -- the interpreter is the first non-flag token."""
    code = "#!/usr/bin/env -S python3 -O\nprint('hi')\n"
    assert detect_interpreter(code) == "python3"


def test_env_with_unset_flag():
    """``env -i bash`` clears the environment then invokes bash; the
    interpreter is still bash."""
    code = "#!/usr/bin/env -i bash\necho hello\n"
    assert detect_interpreter(code) == "bash"


def test_env_with_split_string_inline_form():
    """``env --split-string=python3`` carries the interpreter inline."""
    code = "#!/usr/bin/env --split-string=python3\nprint('hi')\n"
    assert detect_interpreter(code) == "python3"


def test_env_with_split_string_inline_with_args():
    code = "#!/usr/bin/env --split-string=python3 -O\nprint('hi')\n"
    assert detect_interpreter(code) == "python3"


def test_env_only_flags_no_interpreter():
    """A degenerate ``env`` invocation with only flags returns None."""
    code = "#!/usr/bin/env -i\n"
    assert detect_interpreter(code) is None


# ---- detect_interpreter: rejection / boundary cases --------------------


def test_no_shebang_returns_none():
    code = "echo hello world\n"
    assert detect_interpreter(code) is None


def test_only_shebang_marker_returns_none():
    """A bare ``#!`` with no path is malformed."""
    assert detect_interpreter("#!\n") is None


def test_leading_whitespace_rejected():
    """The kernel requires the shebang to occupy the first two bytes."""
    cases = [
        " #!/bin/bash\n",
        "\t#!/bin/bash\n",
        "\n#!/bin/bash\necho hi\n",
    ]
    for c in cases:
        assert detect_interpreter(c) is None, f"failed: {c!r}"


def test_shebang_in_body_not_pulled():
    """A line further down the snippet is just a comment, not a shebang."""
    code = (
        "echo hello\n"
        "#!/bin/bash\n"
        "echo bye\n"
    )
    assert detect_interpreter(code) is None


def test_empty_input_returns_none():
    assert detect_interpreter("") is None
    assert detect_interpreter("\n") is None


def test_comment_with_hash_not_shebang():
    """A regular ``# comment`` line (single hash, no bang) is not
    a shebang."""
    code = "# my script\necho hi\n"
    assert detect_interpreter(code) is None


# ---- detect_interpreter: real-world shapes -----------------------------


def test_python_script_with_imports():
    code = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "import os\n"
        "print('hi')\n"
    )
    assert detect_interpreter(code) == "python3"


def test_bash_script_with_set_options():
    code = (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "echo 'starting'\n"
    )
    assert detect_interpreter(code) == "bash"


def test_node_script():
    code = (
        "#!/usr/bin/env node\n"
        "console.log('hi');\n"
    )
    assert detect_interpreter(code) == "node"


# ---- enrich_code merge behaviour ---------------------------------------


def test_enrich_populates_interpreter_when_existing_missing():
    code = "#!/usr/bin/env python3\nprint('hi')\n"
    ocr = OCRResult(text=code, word_count=2)
    enriched = enrich_code(None, ocr)
    assert enriched.interpreter == "python3"


def test_enrich_preserves_caller_supplied_interpreter():
    """If the LLM already populated interpreter, the heuristic does
    not override."""
    existing = CodeFields(
        language="python", code="#!/usr/bin/env python3\nprint('hi')\n",
        interpreter="custom-python",
    )
    ocr = OCRResult(text="anything", word_count=1)
    enriched = enrich_code(existing, ocr)
    assert enriched.interpreter == "custom-python"


def test_enrich_no_shebang_leaves_interpreter_none():
    code = "print('hi')\nprint('bye')\n"
    ocr = OCRResult(text=code, word_count=2)
    enriched = enrich_code(None, ocr)
    assert enriched.interpreter is None


def test_enrich_shebang_compatible_with_language_detection():
    """A bash shebang above a bash script should both populate
    interpreter AND let detect_language tag the language correctly."""
    code = (
        "#!/bin/bash\n"
        "echo hello\n"
        "ls /tmp\n"
    )
    ocr = OCRResult(text=code, word_count=4)
    enriched = enrich_code(None, ocr)
    assert enriched.interpreter == "bash"
    # The shell language tag is fine; existing detect_language sets
    # shell when the snippet starts with ``#!/bin/``.
    assert enriched.language == "shell"


# ---- LLM wire format ---------------------------------------------------


def test_llm_payload_round_trips_interpreter():
    from shotclassify_classify.client import _parse_llm_payload

    payload = {
        "primary": "code_snippet",
        "confidences": [],
        "rationale": "test",
        "fields": {
            "code": {
                "language": "bash",
                "code": "#!/bin/bash\necho hi\n",
                "interpreter": "bash",
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.code is not None
    assert fields.code.interpreter == "bash"


def test_llm_payload_omits_interpreter_when_not_provided():
    from shotclassify_classify.client import _parse_llm_payload

    payload = {
        "primary": "code_snippet",
        "confidences": [],
        "rationale": "test",
        "fields": {
            "code": {
                "language": "python",
                "code": "print('hi')",
            }
        },
    }
    _, fields = _parse_llm_payload(payload)
    assert fields.code is not None
    assert fields.code.interpreter is None
