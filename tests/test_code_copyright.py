"""Code copyright-holder extraction.

A new ``CodeFields.copyright`` slot carries a list of
``{holder, year}`` dicts parsed from the snippet's header lines.

Recognised vocabularies (case-insensitive):

* ``Copyright (c) 2024 ACME Corp``
* ``Copyright (C) 2020-2024 Alice Author``
* ``(c) 2024 ACME, All rights reserved.``
* ``(C) 2024 ACME Corp.``
* ``© 2024 ACME Corp``        (Unicode copyright sign)
* ``Copyright 2024 ACME Corp`` (no (c) marker)
* ``COPYRIGHT 2024 ACME CORP`` (uppercase)

Year shapes captured:
* ``2024``
* ``2020-2024``      (range)
* ``2020, 2021, 2024`` (list)
* ``2020, 2022-2024`` (mixed)

Holder is trimmed of trailing ``All rights reserved`` boilerplate
and punctuation. Multiple holders on separate header lines all
surface. Capped at the same 30-line header window as
``detect_license``.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import enrich_code, extract_copyrights

# ---- edge cases --------------------------------------------------


def test_empty_string_returns_empty_list():
    assert extract_copyrights("") == []


def test_whitespace_only_returns_empty_list():
    assert extract_copyrights("   \n\n  ") == []


def test_plain_code_no_copyright_returns_empty_list():
    assert extract_copyrights("def foo():\n    return 42\n") == []


def test_word_copyright_in_prose_no_year_returns_empty_list():
    """A bare ``copyright`` word with no year doesn't fire."""
    code = "# Read the copyright before using\nimport os\n"
    assert extract_copyrights(code) == []


# ---- basic Copyright statements ----------------------------------


def test_copyright_c_marker_basic():
    code = "// Copyright (c) 2024 ACME Corp\n"
    assert extract_copyrights(code) == [
        {"holder": "ACME Corp", "year": "2024"}
    ]


def test_copyright_capital_c_marker():
    code = "// Copyright (C) 2024 ACME Corp\n"
    assert extract_copyrights(code) == [
        {"holder": "ACME Corp", "year": "2024"}
    ]


def test_copyright_no_c_marker():
    code = "# Copyright 2024 ACME Corp\n"
    assert extract_copyrights(code) == [
        {"holder": "ACME Corp", "year": "2024"}
    ]


def test_copyright_uppercase():
    code = "// COPYRIGHT 2024 ACME CORP\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME CORP", "year": "2024"}]


def test_copyright_unicode_symbol():
    code = "// © 2024 ACME Corp\n"
    assert extract_copyrights(code) == [
        {"holder": "ACME Corp", "year": "2024"}
    ]


def test_copyright_unicode_symbol_with_word():
    """``© Copyright 2024 ACME`` is recognised."""
    code = "/* Copyright © 2024 ACME Corp */\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


def test_copyright_bare_c_marker_no_word():
    """``(c) 2024 ACME`` without the ``Copyright`` word still fires."""
    code = "// (c) 2024 ACME Corp\n"
    assert extract_copyrights(code) == [
        {"holder": "ACME Corp", "year": "2024"}
    ]


def test_copyright_with_by_keyword():
    """``Copyright 2024 by Alice Author``."""
    code = "# Copyright 2024 by Alice Author\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "Alice Author", "year": "2024"}]


# ---- year shapes -------------------------------------------------


def test_copyright_year_range():
    code = "// Copyright (c) 2020-2024 ACME Corp\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2020-2024"}]


def test_copyright_year_range_with_spaces():
    """``2020 - 2024`` (with spaces around the dash) collapses to ``2020-2024``."""
    code = "// Copyright (c) 2020 - 2024 ACME Corp\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2020-2024"}]


def test_copyright_year_list():
    code = "// Copyright (c) 2020, 2021, 2024 ACME Corp\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2020, 2021, 2024"}]


def test_copyright_year_mixed_list_and_range():
    code = "// Copyright (c) 2020, 2022-2024 ACME Corp\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2020, 2022-2024"}]


# ---- trailing boilerplate stripping ------------------------------


def test_copyright_all_rights_reserved_stripped():
    code = "// Copyright (c) 2024 ACME Corp. All rights reserved.\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


def test_copyright_all_rights_reserved_no_period():
    code = "// Copyright (c) 2024 ACME Corp All Rights Reserved\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


def test_copyright_trailing_period_stripped():
    code = "// Copyright (c) 2024 ACME Corp.\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


def test_copyright_trailing_comma_stripped():
    code = "// Copyright (c) 2024 ACME Corp,\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


# ---- comment-leader stripping ------------------------------------


def test_copyright_c_style_block_comment():
    code = (
        "/*\n"
        " * Copyright (c) 2024 ACME Corp\n"
        " */\n"
    )
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


def test_copyright_hash_comment():
    code = "# Copyright (c) 2024 ACME Corp\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


def test_copyright_dash_comment():
    """SQL / Lua / Haskell ``-- Copyright (c) 2024 ACME``."""
    code = "-- Copyright (c) 2024 ACME Corp\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


def test_copyright_semicolon_comment():
    """Lisp / Scheme ``; Copyright (c) 2024 ACME``."""
    code = "; Copyright (c) 2024 ACME Corp\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


# ---- multiple copyrights -----------------------------------------


def test_multiple_holders_same_year():
    code = (
        "// Copyright (c) 2024 ACME Corp\n"
        "// Copyright (c) 2024 Beta Inc\n"
    )
    out = extract_copyrights(code)
    assert {"holder": "ACME Corp", "year": "2024"} in out
    assert {"holder": "Beta Inc", "year": "2024"} in out
    assert len(out) == 2


def test_multiple_holders_different_years():
    code = (
        "// Copyright (c) 2020 ACME Corp\n"
        "// Copyright (c) 2024 ACME Corp\n"
    )
    out = extract_copyrights(code)
    # Same holder, different years -> two distinct entries.
    assert {"holder": "ACME Corp", "year": "2020"} in out
    assert {"holder": "ACME Corp", "year": "2024"} in out
    assert len(out) == 2


def test_dedup_identical_copyright():
    code = (
        "// Copyright (c) 2024 ACME Corp\n"
        "// Copyright (c) 2024 ACME Corp\n"
    )
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


def test_dedup_case_insensitive_holder():
    code = (
        "// Copyright (c) 2024 ACME Corp\n"
        "// Copyright (c) 2024 acme corp\n"
    )
    out = extract_copyrights(code)
    # Same (holder.lower(), year) key -> one entry kept.
    assert len(out) == 1


# ---- holder name variations --------------------------------------


def test_holder_with_punctuation_in_name():
    code = "// Copyright (c) 2024 ACME, Inc.\n"
    out = extract_copyrights(code)
    # The comma inside the name is part of the printed form; we don't
    # try to be too clever about parsing corporate-form suffixes, but
    # we DO strip trailing periods.
    assert out and out[0]["year"] == "2024"
    assert "ACME" in out[0]["holder"]


def test_holder_personal_name():
    code = "// Copyright (c) 2024 Alice Author\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "Alice Author", "year": "2024"}]


def test_holder_multi_word_name():
    code = "// Copyright (c) 2024 The Open Source Foundation\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "The Open Source Foundation", "year": "2024"}]


def test_holder_with_email():
    """Email after the name is captured as part of the holder string."""
    code = "// Copyright (c) 2024 Alice Author <alice@example.com>\n"
    out = extract_copyrights(code)
    assert out and out[0]["year"] == "2024"
    assert "Alice Author" in out[0]["holder"]


# ---- window cap --------------------------------------------------


def test_copyright_beyond_header_window_ignored():
    """A copyright sitting on line 40 is not picked up."""
    pre = "\n".join(["x = 1"] * 35)
    code = f"{pre}\n// Copyright (c) 2024 ACME Corp\n"
    out = extract_copyrights(code)
    assert out == []


def test_copyright_at_window_edge_captured():
    """A copyright on line 25 (within the 30-line window) is captured."""
    pre = "\n".join(["x = 1"] * 20)
    code = f"{pre}\n// Copyright (c) 2024 ACME Corp\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


# ---- enrich_code wiring ------------------------------------------


def _ocr(text: str) -> OCRResult:
    return OCRResult(text=text, language="en", word_count=len(text.split()))


def test_enrich_code_pulls_copyright():
    code = "// Copyright (c) 2024 ACME Corp\nint main() { return 0; }\n"
    fields = enrich_code(None, _ocr(code))
    assert fields.copyright == [{"holder": "ACME Corp", "year": "2024"}]


def test_enrich_code_caller_value_wins():
    """A caller-supplied copyright list is preserved verbatim."""
    code = "// Copyright (c) 2024 ACME Corp\nint main() { return 0; }\n"
    llm_value = [{"holder": "LLM Holder", "year": "1999"}]
    existing = CodeFields(code=code, copyright=llm_value)
    fields = enrich_code(existing, _ocr(code))
    assert fields.copyright == llm_value


def test_enrich_code_no_copyright_stays_empty():
    code = "def foo():\n    return 42\n"
    fields = enrich_code(None, _ocr(code))
    assert fields.copyright == []


def test_enrich_code_with_license_and_copyright():
    """Copyright and license are both detected from the same header."""
    code = (
        "// Copyright (c) 2024 ACME Corp\n"
        "// Licensed under the MIT License\n"
        "// Permission is hereby granted, free of charge, to any person\n"
        "int main() { return 0; }\n"
    )
    fields = enrich_code(None, _ocr(code))
    assert fields.copyright == [{"holder": "ACME Corp", "year": "2024"}]
    assert fields.license == "mit"


def test_python_module_with_copyright():
    """Python ``# Copyright`` header works alongside docstring detection."""
    code = (
        "# Copyright (c) 2024 ACME Corp\n"
        '"""Module docstring."""\n'
        "import os\n"
    )
    fields = enrich_code(None, _ocr(code))
    assert fields.copyright == [{"holder": "ACME Corp", "year": "2024"}]
    assert fields.docstring == "Module docstring."


# ---- corner cases -------------------------------------------------


def test_copyright_inside_string_literal_still_matches():
    """A copyright inside a string literal also fires (we don't tokenise)."""
    # This is documented as an accepted overcount, mirroring how
    # ``detect_todo_count`` handles markers inside strings.
    code = 's = "Copyright (c) 2024 ACME Corp"\n'
    out = extract_copyrights(code)
    assert out and out[0]["holder"].startswith("ACME Corp")


def test_copyright_with_indentation():
    """A copyright line that's indented inside a block still matches."""
    code = (
        "def foo():\n"
        "    # Copyright (c) 2024 ACME Corp\n"
        "    pass\n"
    )
    out = extract_copyrights(code)
    assert out == [{"holder": "ACME Corp", "year": "2024"}]


def test_copyright_two_letters_per_word():
    """A holder name like ``X Y`` (two single-letter words) still captures."""
    code = "// Copyright (c) 2024 X Y\n"
    out = extract_copyrights(code)
    assert out and out[0]["year"] == "2024"


def test_holder_with_hyphen():
    code = "// Copyright (c) 2024 X-Tech Ltd\n"
    out = extract_copyrights(code)
    assert out == [{"holder": "X-Tech Ltd", "year": "2024"}]


def test_two_copyrights_one_line_first_wins():
    """Two copyrights on the same line: only the first surfaces.

    The MULTILINE-anchored holder regex consumes the rest of the line,
    so the second copyright on the SAME line is folded into the first
    holder. Documented trade-off: real headers print one copyright per
    line, so this only affects pathological OCR captures.
    """
    code = "// Copyright (c) 2020 ACME Corp Copyright (c) 2024 Beta Inc\n"
    out = extract_copyrights(code)
    assert out
    assert out[0]["year"] == "2020"
    # The first holder absorbs the rest of the line.
    assert "ACME Corp" in out[0]["holder"]
