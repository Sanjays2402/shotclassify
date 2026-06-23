"""Code dead-import detection tests.

A new CodeFields.unused_imports slot lists modules / symbols that
are imported but never referenced anywhere in the rest of the
snippet body. The detector is lexical: it scans the body for any
whitespace-/punctuation-bounded occurrence of the imported name.
"""
from __future__ import annotations

from shotclassify_common import OCRResult
from shotclassify_extract.code import enrich_code, extract_unused_imports

# ---- Python: bare ``import X`` ----------------------------------


def test_unused_plain_import():
    code = "import os\nprint('hello')"
    assert extract_unused_imports(code) == ["os"]


def test_used_plain_import_returns_empty():
    code = "import os\nprint(os.getcwd())"
    assert extract_unused_imports(code) == []


def test_multiple_imports_one_used():
    code = "import os\nimport sys\nprint(sys.argv)"
    assert extract_unused_imports(code) == ["os"]


def test_dotted_module_top_level_check():
    """``import os.path`` -- check top-level ``os``."""
    code = "import os.path\nprint(os.path.exists('/'))"
    assert extract_unused_imports(code) == []


def test_dotted_module_unused():
    code = "import os.path\nprint('hello')"
    assert extract_unused_imports(code) == ["os.path"]


# ---- Python: ``import X as Y`` ----------------------------------


def test_aliased_unused():
    code = "import numpy as np\nprint('hello')"
    assert extract_unused_imports(code) == ["numpy"]


def test_aliased_used():
    code = "import numpy as np\narr = np.array([1, 2, 3])"
    assert extract_unused_imports(code) == []


def test_aliased_using_full_name_still_unused():
    """``import numpy as np`` then using ``numpy`` doesn't count
    as usage of the alias; we check ALIAS not module."""
    code = "import numpy as np\narr = numpy.array([1, 2, 3])"
    # The alias ``np`` is unused; display is ``numpy``.
    assert extract_unused_imports(code) == ["numpy"]


# ---- Python: ``import X, Y, Z`` ---------------------------------


def test_multi_import_one_used():
    code = "import os, sys, json\nprint(json.dumps({}))"
    assert sorted(extract_unused_imports(code)) == ["os", "sys"]


def test_multi_import_all_used():
    code = "import os, sys, json\nprint(os.name, sys.argv, json.dumps({}))"
    assert extract_unused_imports(code) == []


def test_multi_import_all_unused():
    code = "import os, sys, json\nprint('hello')"
    assert sorted(extract_unused_imports(code)) == ["json", "os", "sys"]


# ---- Python: ``from X import a, b`` -----------------------------


def test_from_import_unused():
    code = "from os import path\nprint('hello')"
    assert extract_unused_imports(code) == ["path"]


def test_from_import_used():
    code = "from os import path\nif path.exists('/'):\n    pass"
    assert extract_unused_imports(code) == []


def test_from_import_multi_one_used():
    code = "from os import path, getcwd, sep\nprint(getcwd())"
    out = extract_unused_imports(code)
    assert sorted(out) == ["path", "sep"]


def test_from_import_with_alias_used():
    """``from foo import bar as baz`` -- check ``baz`` not ``bar``."""
    code = "from foo import bar as baz\nbaz()"
    assert extract_unused_imports(code) == []


def test_from_import_with_alias_unused():
    code = "from foo import bar as baz\nbar()"
    # baz alias unused; display = bar
    assert extract_unused_imports(code) == ["bar"]


def test_from_import_star_skipped():
    """``from foo import *`` cannot be safely tagged unused."""
    code = "from foo import *\nprint('hello')"
    assert extract_unused_imports(code) == []


# ---- JS / TS: ``import X from 'mod'`` ---------------------------


def test_js_default_import_unused():
    code = "import React from 'react';\nconsole.log('hi');"
    assert extract_unused_imports(code, language="javascript") == ["React"]


def test_js_default_import_used():
    code = "import React from 'react';\nconst el = React.createElement('div');"
    assert extract_unused_imports(code, language="javascript") == []


def test_js_braced_import_unused():
    code = "import { foo, bar } from 'lib';\nconsole.log('hi');"
    out = extract_unused_imports(code, language="javascript")
    assert sorted(out) == ["bar", "foo"]


def test_js_braced_import_mixed():
    code = "import { foo, bar, baz } from 'lib';\nfoo();"
    out = extract_unused_imports(code, language="javascript")
    assert sorted(out) == ["bar", "baz"]


def test_js_namespace_import_used():
    code = "import * as utils from 'lib';\nutils.helper();"
    assert extract_unused_imports(code, language="javascript") == []


def test_js_namespace_import_unused():
    code = "import * as utils from 'lib';\nconsole.log('hi');"
    assert extract_unused_imports(code, language="javascript") == ["utils"]


def test_ts_braced_with_alias_used():
    code = "import { foo as bar } from 'lib';\nbar();"
    assert extract_unused_imports(code, language="typescript") == []


def test_ts_braced_with_alias_unused():
    code = "import { foo as bar } from 'lib';\nfoo();"
    assert extract_unused_imports(code, language="typescript") == ["foo"]


# ---- JVM: ``import com.foo.Bar;`` -------------------------------


def test_jvm_class_import_unused():
    code = "import com.example.Foo;\npublic class A { void run() {} }"
    assert extract_unused_imports(code, language="java") == ["com.example.Foo"]


def test_jvm_class_import_used():
    code = "import com.example.Foo;\npublic class A { Foo f; }"
    assert extract_unused_imports(code, language="java") == []


def test_jvm_wildcard_skipped():
    """``import com.foo.*;`` cannot be safely tagged unused."""
    code = "import com.example.*;\npublic class A {}"
    assert extract_unused_imports(code, language="java") == []


# ---- Data / shell languages return [] ---------------------------


def test_json_returns_empty():
    code = '{"name": "foo", "import": "bar"}'
    assert extract_unused_imports(code, language="json") == []


def test_yaml_returns_empty():
    code = "name: foo\nimport: bar"
    assert extract_unused_imports(code, language="yaml") == []


def test_shell_returns_empty():
    code = "import foo\nrun"  # shell snippet with a misleading line
    assert extract_unused_imports(code, language="bash") == []


def test_sql_returns_empty():
    code = "SELECT * FROM foo;\n-- import comment"
    assert extract_unused_imports(code, language="sql") == []


def test_markdown_returns_empty():
    code = "import foo\nMarkdown body"
    assert extract_unused_imports(code, language="markdown") == []


# ---- Word-boundary defence --------------------------------------


def test_partial_substring_doesnt_count_as_usage():
    """An import of ``foo`` should NOT be considered used when only
    ``foobar`` appears in the body."""
    code = "import foo\nfoobar = 1"
    assert extract_unused_imports(code) == ["foo"]


def test_prefix_match_doesnt_count_as_usage():
    """``barfoo`` is not a usage of ``foo``."""
    code = "import foo\nbarfoo = 1"
    assert extract_unused_imports(code) == ["foo"]


def test_usage_in_function_call():
    code = "import os\ncwd = os.getcwd()"
    assert extract_unused_imports(code) == []


def test_usage_in_attribute_access():
    code = "import sys\nprint(sys.version)"
    assert extract_unused_imports(code) == []


def test_usage_in_decorator():
    code = "from functools import wraps\n@wraps\ndef f(): pass"
    assert extract_unused_imports(code) == []


def test_usage_in_type_annotation():
    code = "from typing import List\ndef f() -> List[int]: pass"
    assert extract_unused_imports(code) == []


# ---- Edge cases -------------------------------------------------


def test_empty_code():
    assert extract_unused_imports("") == []


def test_whitespace_only_code():
    assert extract_unused_imports("    \n\t  \n") == []


def test_no_imports():
    code = "print('hello')\nx = 1"
    assert extract_unused_imports(code) == []


def test_only_imports_all_unused():
    code = "import os\nimport sys\nimport json\n"
    assert sorted(extract_unused_imports(code)) == ["json", "os", "sys"]


def test_import_used_in_comment_still_unused():
    """A reference inside a comment is technically a body match;
    this lexical detector does NOT special-case comments. We
    document the trade-off here -- it's a known false negative."""
    code = "import foo\n# foo is great"
    # The lexical matcher will tag it as used (a known limitation).
    # We don't assert specifically; verify behaviour is consistent.
    out = extract_unused_imports(code)
    assert out == []  # lexical detector counts the comment occurrence


def test_dedupe_repeated_unused():
    code = "import os\nimport os\nprint('hi')"
    # De-duplicated even if multiple matchers find it twice.
    assert extract_unused_imports(code) == ["os"]


def test_imports_self_reference_doesnt_count():
    """An import statement should not be considered its own usage."""
    code = "import requests\nimport flask\nrequests.get('/')"
    out = extract_unused_imports(code)
    # flask appears only in its own import line -> unused.
    assert "flask" in out
    # requests is used.
    assert "requests" not in out


# ---- Real-world snippets ----------------------------------------


def test_real_python_module_one_unused():
    code = '''\
import json
import os
import sys
from typing import List

def main() -> List[int]:
    data = json.loads(sys.argv[1])
    return data

if __name__ == "__main__":
    main()
'''
    out = extract_unused_imports(code)
    # os is unused; json, sys, List are used.
    assert out == ["os"]


def test_real_python_all_used():
    code = '''\
import json
from typing import Dict

def parse(s: str) -> Dict[str, int]:
    return json.loads(s)
'''
    assert extract_unused_imports(code) == []


def test_real_react_component_unused_import():
    code = '''\
import React from 'react';
import { useState } from 'react';
import lodash from 'lodash';

function Counter() {
  const [count, setCount] = useState(0);
  return React.createElement('button', null, count);
}
'''
    out = extract_unused_imports(code, language="javascript")
    # lodash never used.
    assert out == ["lodash"]


def test_real_java_class_two_unused():
    code = '''\
import java.util.List;
import java.util.Map;
import java.io.File;

public class App {
    public static void main(String[] args) {
        File f = new File("/tmp/x");
        System.out.println(f);
    }
}
'''
    out = extract_unused_imports(code, language="java")
    assert sorted(out) == ["java.util.List", "java.util.Map"]


# ---- enrich_code integration ------------------------------------


def test_enrich_backfills_unused_imports():
    code = "import os\nprint('hi')"
    ocr = OCRResult(text=code, word_count=3, mean_confidence=0.9)
    out = enrich_code(None, ocr)
    assert out.unused_imports == ["os"]


def test_enrich_preserves_caller_unused_imports():
    """When caller has already supplied unused_imports list, enrich
    preserves it verbatim."""
    from shotclassify_common import CodeFields
    caller = CodeFields(
        language="python",
        code="import os\nos.getcwd()",
        unused_imports=["llm_provided"],
    )
    ocr = OCRResult(text="import os\nos.getcwd()", word_count=3, mean_confidence=0.9)
    out = enrich_code(caller, ocr)
    assert out.unused_imports == ["llm_provided"]


def test_enrich_no_imports_returns_empty():
    code = "print('hello world')"
    ocr = OCRResult(text=code, word_count=2, mean_confidence=0.9)
    out = enrich_code(None, ocr)
    assert out.unused_imports == []


def test_enrich_data_language_returns_empty():
    """A JSON snippet has no concept of imports."""
    code = '{"name": "foo", "import": "bar"}'
    ocr = OCRResult(text=code, word_count=4, mean_confidence=0.9)
    out = enrich_code(None, ocr)
    assert out.unused_imports == []


# ---- Cap enforcement --------------------------------------------


def test_cap_50_unused_imports():
    """The detector caps output at 50 entries."""
    # Generate 60 unique unused imports.
    code_lines = [f"import mod_{i}" for i in range(60)]
    code = "\n".join(code_lines) + "\nprint('hi')"
    out = extract_unused_imports(code)
    assert len(out) == 50
