"""Code license-header detection.

A new ``CodeFields.license`` slot carries an SPDX-style tag for the
open-source license header detected at the top of the snippet:
``apache-2.0`` / ``mit`` / ``gpl-3.0`` / ``gpl-2.0`` / ``lgpl-3.0`` /
``agpl-3.0`` / ``bsd-2-clause`` / ``bsd-3-clause`` / ``mpl-2.0`` /
``isc`` / ``unlicense`` / ``cc0-1.0``. ``None`` when no recognised
license header is present.

Detection scans the first 30 lines of the snippet for the
distinctive opening phrase of each license. The longer / more-
distinctive licenses (Apache 2.0, BSD-3-Clause, GPL family) are
checked BEFORE the shorter ones (MIT, ISC) so a full BSD-3-Clause
header tags as ``bsd-3-clause``, not MIT (BSD headers also contain
the ``permission is granted`` phrasing).

Case-insensitive matching throughout. Whitespace is normalised so
a header wrapped onto multiple comment lines still matches the
multi-needle requirement.
"""
from __future__ import annotations

from shotclassify_common import CodeFields, OCRResult
from shotclassify_extract import detect_license, enrich_code

# ---- detect_license: empty / edge cases ----------------------------


def test_empty_string_returns_none():
    assert detect_license("") is None


def test_whitespace_only_returns_none():
    assert detect_license("   \n\n  \n") is None


def test_plain_code_returns_none():
    code = "def foo():\n    return 42\n"
    assert detect_license(code) is None


def test_code_with_random_license_word_returns_none():
    """A stray ``license`` word in prose doesn't trigger detection."""
    code = "# Read the license before using\nimport os\n"
    assert detect_license(code) is None


# ---- detect_license: MIT ------------------------------------------


def test_mit_header_canonical_phrase():
    code = (
        "# MIT License\n"
        "# \n"
        "# Permission is hereby granted, free of charge, to any person obtaining\n"
        "# a copy of this software...\n"
    )
    assert detect_license(code) == "mit"


def test_mit_header_short_form():
    code = "// SPDX-License-Identifier: MIT\n// MIT License\nint main() { return 0; }\n"
    assert detect_license(code) == "mit"


def test_mit_phrase_wrapped_across_lines():
    """Multi-line license headers should still match -- the detector
    flattens the header into a single string before searching."""
    code = (
        "/* Permission is hereby granted, free of charge,\n"
        " * to any person obtaining a copy of this software */\n"
    )
    assert detect_license(code) == "mit"


# ---- detect_license: Apache 2.0 -----------------------------------


def test_apache_2_header():
    code = (
        "// Licensed under the Apache License, Version 2.0 (the \"License\");\n"
        "// you may not use this file except in compliance with the License.\n"
    )
    assert detect_license(code) == "apache-2.0"


def test_apache_2_with_version_phrase():
    code = "# Apache License\n# Version 2.0, January 2004\n"
    assert detect_license(code) == "apache-2.0"


# ---- detect_license: GPL family -----------------------------------


def test_gpl_3_header():
    code = (
        "# This program is free software: you can redistribute it and/or modify\n"
        "# it under the terms of the GNU General Public License as published by\n"
        "# the Free Software Foundation, either version 3 of the License...\n"
    )
    assert detect_license(code) == "gpl-3.0"


def test_gpl_3_short_tag():
    code = "// SPDX-License-Identifier: GPL-3.0\n"
    assert detect_license(code) == "gpl-3.0"


def test_gpl_3_gplv3_tag():
    code = "// Licensed under GPLv3\n"
    assert detect_license(code) == "gpl-3.0"


def test_gpl_2_header():
    code = (
        "# This program is distributed under the terms of the\n"
        "# GNU General Public License, version 2, as published by the FSF.\n"
    )
    assert detect_license(code) == "gpl-2.0"


def test_gpl_2_short_tag():
    code = "// SPDX-License-Identifier: GPL-2.0\n"
    assert detect_license(code) == "gpl-2.0"


def test_lgpl_3_header():
    code = (
        "/* This library is free software; you can redistribute it\n"
        " * under the terms of the GNU Lesser General Public License\n"
        " * version 3 as published by the Free Software Foundation. */\n"
    )
    assert detect_license(code) == "lgpl-3.0"


def test_agpl_3_header():
    code = (
        "# This file is part of an AGPL-3.0 project.\n"
        "# Distributed under the GNU Affero General Public License version 3.\n"
    )
    assert detect_license(code) == "agpl-3.0"


# ---- detect_license: BSD family -----------------------------------


def test_bsd_3_clause_full_header():
    code = (
        "/* Copyright (c) 2024 ACME Corp\n"
        " * Redistribution and use in source and binary forms, with or without\n"
        " * modification, are permitted provided that the following conditions\n"
        " * are met:\n"
        " *  - Redistributions of source code must retain the above copyright\n"
        " *  - Redistributions in binary form must reproduce the above copyright\n"
        " *  - Neither the name of the project nor the names of its contributors\n"
        " *    may be used to endorse or promote products derived from this\n"
        " *    software without specific prior written permission.\n"
        " */\n"
    )
    assert detect_license(code) == "bsd-3-clause"


def test_bsd_2_clause_header():
    code = (
        "/* Copyright (c) 2024 ACME Corp\n"
        " * Redistribution and use in source and binary forms, with or without\n"
        " * modification, are permitted provided that the following conditions\n"
        " * are met:\n"
        " *  - Redistributions of source code must retain the above copyright\n"
        " *  - Redistributions in binary form must reproduce the above copyright\n"
        " */\n"
    )
    # No 'Neither the name' clause -> 2-clause.
    assert detect_license(code) == "bsd-2-clause"


def test_bsd_short_tag():
    code = "// SPDX-License-Identifier: BSD-3-Clause\n"
    assert detect_license(code) == "bsd-3-clause"


# ---- detect_license: MPL 2.0 --------------------------------------


def test_mpl_2_header():
    code = (
        "/* This Source Code Form is subject to the terms of the Mozilla Public\n"
        " * License, Version 2.0. If a copy of the MPL was not distributed with this\n"
        " * file, You can obtain one at https://mozilla.org/MPL/2.0/. */\n"
    )
    assert detect_license(code) == "mpl-2.0"


def test_mpl_short_tag():
    code = "// SPDX-License-Identifier: MPL-2.0\n"
    assert detect_license(code) == "mpl-2.0"


# ---- detect_license: ISC ------------------------------------------


def test_isc_header():
    code = (
        "// Copyright (c) 2024 ACME Corp\n"
        "// \n"
        "// Permission to use, copy, modify, and/or distribute this software for\n"
        "// any purpose with or without fee is hereby granted...\n"
    )
    assert detect_license(code) == "isc"


def test_isc_short_form():
    code = "# ISC License\n"
    assert detect_license(code) == "isc"


# ---- detect_license: Public-domain dedications --------------------


def test_unlicense_header():
    code = (
        "# This is free and unencumbered software released into the public domain.\n"
        "# Anyone is free to copy, modify, publish, use, compile, sell, or\n"
        "# distribute this software...\n"
    )
    assert detect_license(code) == "unlicense"


def test_the_unlicense_short_form():
    code = "// The Unlicense\n"
    assert detect_license(code) == "unlicense"


def test_cc0_1_header():
    code = (
        "# CC0 1.0 Universal\n"
        "# To the extent possible under law, the authors have waived all\n"
        "# copyright and related or neighboring rights to this work.\n"
    )
    assert detect_license(code) == "cc0-1.0"


def test_creative_commons_zero():
    code = "// Creative Commons Zero v1.0 Universal\n"
    assert detect_license(code) == "cc0-1.0"


# ---- detect_license: priority ordering ----------------------------


def test_bsd_3_clause_does_not_get_mistagged_as_mit():
    """BSD-3-Clause headers contain the ``permission is granted``
    phrasing that overlaps with MIT. The BSD-3-Clause entry sits
    BEFORE MIT in the catalogue so the full BSD header tags correctly.
    """
    code = (
        "/* Copyright (c) 2024 ACME\n"
        " * Redistribution and use in source and binary forms, with or without\n"
        " * modification, are permitted ...\n"
        " *  - Redistributions of source code\n"
        " *  - Redistributions in binary form\n"
        " *  - Neither the name of ACME nor the names of contributors\n"
        " */\n"
    )
    assert detect_license(code) == "bsd-3-clause"


def test_apache_takes_priority_over_mit_when_both_phrases_present():
    """A header that mentions both Apache wording and MIT wording
    should tag as Apache because the Apache entry is checked first."""
    code = (
        "// Licensed under the Apache License, Version 2.0\n"
        "// Some text containing 'Permission is hereby granted, free of charge'\n"
    )
    assert detect_license(code) == "apache-2.0"


# ---- detect_license: header-window bound --------------------------


def test_license_in_body_past_30_lines_is_ignored():
    """A license phrase buried 50 lines into a snippet shouldn't fire."""
    code = "\n".join(["x = 1"] * 40) + "\n# Permission is hereby granted, free of charge\n"
    assert detect_license(code) is None


def test_license_in_first_30_lines_fires():
    code = "\n".join(["x = 1"] * 20) + "\n# Permission is hereby granted, free of charge\n"
    assert detect_license(code) == "mit"


# ---- detect_license: case insensitivity ---------------------------


def test_license_matches_case_insensitively():
    code = "# MIT LICENSE\n"
    assert detect_license(code) == "mit"


def test_apache_matches_case_insensitively():
    code = "# LICENSED UNDER THE APACHE LICENSE, VERSION 2.0\n"
    assert detect_license(code) == "apache-2.0"


# ---- enrich_code integration -------------------------------------


def test_enrich_code_populates_license_mit():
    existing = CodeFields(
        language="python",
        code=(
            "# Permission is hereby granted, free of charge, to any person\n"
            "# obtaining a copy of this software...\n"
            "def foo(): return 1\n"
        ),
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.license == "mit"


def test_enrich_code_populates_license_apache():
    existing = CodeFields(
        language="java",
        code=(
            "// Licensed under the Apache License, Version 2.0 (the \"License\");\n"
            "// you may not use this file except in compliance with the License.\n"
            "public class Foo {}\n"
        ),
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.license == "apache-2.0"


def test_enrich_code_none_when_no_header():
    existing = CodeFields(language="python", code="def foo(): return 1\n")
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.license is None


def test_enrich_code_preserves_caller_supplied_license():
    """LLM-supplied license wins over the heuristic."""
    existing = CodeFields(
        language="python",
        code="# Permission is hereby granted, free of charge\n",
        license="custom",
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.license == "custom"


def test_enrich_code_recomputes_when_caller_value_is_none():
    existing = CodeFields(
        language="python",
        code="# Permission is hereby granted, free of charge\n",
        license=None,
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.license == "mit"


def test_enrich_code_strips_numbered_gutter_before_detecting_license():
    """The line-numbering detector runs first; license detection sees
    the de-numbered body."""
    existing = CodeFields(
        language="python",
        code=(
            "1: # Permission is hereby granted, free of charge, to any person\n"
            "2: # obtaining a copy of this software\n"
            "3: def foo(): return 1\n"
        ),
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.numbered is True
    assert merged.license == "mit"


def test_enrich_code_license_field_independent_from_other_detectors():
    """License detection doesn't disturb language / framework / etc."""
    existing = CodeFields(
        language="python",
        code=(
            "# Permission is hereby granted, free of charge, to any person\n"
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "\n"
            "@app.get('/')\n"
            "def root(): return {'ok': True}\n"
        ),
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.license == "mit"
    assert merged.language == "python"


def test_enrich_code_gpl_3_with_other_text():
    existing = CodeFields(
        language="c",
        code=(
            "/*\n"
            " * Copyright (C) 2024 ACME\n"
            " * This program is free software: you can redistribute it under the\n"
            " * GNU General Public License version 3, as published by the FSF.\n"
            " */\n"
            "int main() { return 0; }\n"
        ),
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.license == "gpl-3.0"


def test_enrich_code_unlicense():
    existing = CodeFields(
        language="python",
        code=(
            "# This is free and unencumbered software released into the public domain.\n"
            "def foo(): return 1\n"
        ),
    )
    merged = enrich_code(existing, OCRResult(text=""))
    assert merged.license == "unlicense"
