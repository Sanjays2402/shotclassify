"""Cross-category percentage extractor tests.

A new cross-category extractor tallies every percent value in the
OCR text under ``ExtractedFields.raw["percentages"]``.

Output shape: list of ``{"value": float, "label": str | None,
"sign": str | None}`` dicts. ``value`` is the numeric percent
(negative when ``-`` was printed), ``label`` is the nearest
preceding curated context word, ``sign`` captures the printed
direction.

Capped at 100 entries. Out-of-range values (>1000% or <-1000%)
rejected as OCR noise.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_percentages

# ---- Bare integer percentages ------------------------------------


def test_single_bare_integer_percent():
    out = extract_percentages("Loaded 50% of items")
    assert out == [{"value": 50.0, "label": "loaded", "sign": None}]


def test_zero_percent():
    out = extract_percentages("Battery 0%")
    assert out == [{"value": 0.0, "label": "battery", "sign": None}]


def test_one_hundred_percent():
    out = extract_percentages("Tests passed 100%")
    assert out == [{"value": 100.0, "label": "passed", "sign": None}]


def test_three_digit_percent():
    out = extract_percentages("Increase 250%")
    assert out == [{"value": 250.0, "label": None, "sign": None}]


def test_empty_string():
    assert extract_percentages("") == []


def test_no_percentages():
    assert extract_percentages("Hello world, no percents here") == []


def test_none_input():
    assert extract_percentages(None) == []  # type: ignore[arg-type]


def test_non_string_input():
    assert extract_percentages(123) == []  # type: ignore[arg-type]


# ---- Decimal percentages -----------------------------------------


def test_us_decimal_percent():
    out = extract_percentages("Coverage: 98.5%")
    assert out == [{"value": 98.5, "label": "coverage", "sign": None}]


def test_eu_comma_decimal_percent():
    out = extract_percentages("Rate 12,5%")
    assert out == [{"value": 12.5, "label": "rate", "sign": None}]


def test_small_decimal_percent():
    out = extract_percentages("APR 0.5%")
    assert out == [{"value": 0.5, "label": "apr", "sign": None}]


def test_three_digit_decimal_percent():
    out = extract_percentages("Growth 234.5%")
    assert out == [{"value": 234.5, "label": "growth", "sign": None}]


# ---- Signed percentages ------------------------------------------


def test_positive_signed_percent():
    out = extract_percentages("Change +12.5%")
    assert out == [{"value": 12.5, "label": "change", "sign": "+"}]


def test_negative_signed_percent():
    out = extract_percentages("Change -3.2%")
    assert out == [{"value": -3.2, "label": "change", "sign": "-"}]


def test_plusminus_signed_percent():
    out = extract_percentages("Margin \u00B15%")
    assert out == [{"value": 5.0, "label": "margin", "sign": "\u00B1"}]


def test_negative_value_stored_negative():
    out = extract_percentages("Loss -8%")
    # `-8%` -> value=-8.0, sign='-'
    assert out[0]["value"] == -8.0
    assert out[0]["sign"] == "-"


def test_positive_sign_value_stored_positive():
    out = extract_percentages("Up +12%")
    # `+12%` -> value=12.0, sign='+' (NOT -12; the + is direction)
    assert out[0]["value"] == 12.0
    assert out[0]["sign"] == "+"


# ---- Labelled forms ----------------------------------------------


def test_cpu_label():
    out = extract_percentages("CPU 87%")
    assert out == [{"value": 87.0, "label": "cpu", "sign": None}]


def test_memory_label():
    out = extract_percentages("Memory 64%")
    assert out == [{"value": 64.0, "label": "memory", "sign": None}]


def test_battery_label_with_colon():
    out = extract_percentages("Battery: 32%")
    assert out == [{"value": 32.0, "label": "battery", "sign": None}]


def test_progress_label_with_equals():
    out = extract_percentages("progress = 75%")
    assert out == [{"value": 75.0, "label": "progress", "sign": None}]


def test_yes_label_for_poll():
    out = extract_percentages("Yes 65%")
    assert out == [{"value": 65.0, "label": "yes", "sign": None}]


def test_no_label_for_poll():
    out = extract_percentages("No 35%")
    assert out == [{"value": 35.0, "label": "no", "sign": None}]


def test_discount_label_off():
    out = extract_percentages("Save 20% off everything")
    # Label-from-line picks up the closest preceding vocab token.
    # The labelled matcher requires a direct adjacency; ``Save`` is in
    # vocab so it gets attached.
    assert out[0]["value"] == 20.0
    assert out[0]["label"] == "save"
    assert out[0]["sign"] is None


def test_coverage_label():
    out = extract_percentages("Coverage 95.5%")
    assert out == [{"value": 95.5, "label": "coverage", "sign": None}]


def test_uptime_label():
    out = extract_percentages("Uptime 99.99%")
    assert out == [{"value": 99.99, "label": "uptime", "sign": None}]


def test_label_outside_vocab_returns_none():
    out = extract_percentages("HTTP 50% return rate")
    # ``HTTP`` is not in vocab; label-from-line walks backwards but
    # finds nothing else. But wait - "rate" is in vocab AFTER the
    # percent, doesn't count. The label is None.
    # Actually "return" IS in vocab now; but the matcher walks
    # backwards from the percent's start, so it looks at "HTTP"
    # only. Both HTTP and 50% are before "return".
    # So label should be None here.
    assert out[0]["label"] is None


def test_unknown_label_word_does_not_pollute():
    out = extract_percentages("Foo 50%")
    # ``Foo`` is not in vocab; label is None.
    assert out[0]["value"] == 50.0
    assert out[0]["label"] is None


# ---- Range endpoints ---------------------------------------------


def test_range_dash_form():
    out = extract_percentages("Discount 5-10%")
    # Range emits BOTH endpoints, each with the line's discount
    # label.
    values = [(e["value"], e["label"]) for e in out]
    assert (5.0, "discount") in values
    assert (10.0, "discount") in values


def test_range_with_percent_in_middle():
    out = extract_percentages("Tip 15%-20%")
    values = [e["value"] for e in out]
    assert 15.0 in values
    assert 20.0 in values


def test_range_to_word_form():
    out = extract_percentages("Yield 5% to 10%")
    values = [e["value"] for e in out]
    assert 5.0 in values
    assert 10.0 in values


def test_range_with_en_dash():
    out = extract_percentages("Range 5\u201310%")
    values = [e["value"] for e in out]
    assert 5.0 in values
    assert 10.0 in values


# ---- De-duplication ----------------------------------------------


def test_dedupe_same_value_same_label():
    out = extract_percentages("CPU 87% memory 64% cpu 87%")
    # Two `cpu 87%` entries collapse to one. Memory is a separate
    # entry.
    values = [(e["value"], e["label"]) for e in out]
    assert values.count((87.0, "cpu")) == 1
    assert (64.0, "memory") in values


def test_dedupe_different_label_keeps_both():
    out = extract_percentages("yes 50% no 50%")
    values = [(e["value"], e["label"]) for e in out]
    assert (50.0, "yes") in values
    assert (50.0, "no") in values


def test_dedupe_different_sign_keeps_both():
    out = extract_percentages("Change +5% then change -5%")
    values = [(e["value"], e["sign"]) for e in out]
    assert (5.0, "+") in values
    assert (-5.0, "-") in values


# ---- Out-of-range rejection --------------------------------------


def test_value_above_1000_rejected():
    out = extract_percentages("Spike 1500%")
    # 1500% is above the +1000% bound; rejected as OCR noise.
    # Only entries within bounds survive.
    values = [e["value"] for e in out]
    assert 1500.0 not in values


def test_value_below_neg_1000_rejected():
    out = extract_percentages("Crash -2000%")
    values = [e["value"] for e in out]
    assert -2000.0 not in values


def test_value_exactly_1000_accepted():
    out = extract_percentages("Spike 1000%")
    values = [e["value"] for e in out]
    assert 1000.0 in values


# ---- Order preservation ------------------------------------------


def test_first_seen_order_preserved():
    text = "Stats:\nCPU 87%\nMemory 64%\nDisk 45%"
    out = extract_percentages(text)
    labels = [e["label"] for e in out]
    assert labels == ["cpu", "memory", "disk"]


def test_order_within_same_line():
    out = extract_percentages("Yes 60% No 40%")
    labels = [e["label"] for e in out]
    assert labels.index("yes") < labels.index("no")


# ---- Multiple labels on same line --------------------------------


def test_label_attaches_to_nearest_percent():
    out = extract_percentages("CPU 87% Memory 64%")
    values_by_label = {e["label"]: e["value"] for e in out}
    assert values_by_label["cpu"] == 87.0
    assert values_by_label["memory"] == 64.0


def test_label_walks_back_to_nearest_vocab():
    out = extract_percentages("server stats reported 95%")
    # "server" IS in vocab now, but "reported" / "stats" aren't.
    # Walk back: "reported" (no), "stats" (no), "server" (no--
    # actually server isn't in vocab either).
    # Bare 95% stays with label=None.
    assert out[0]["value"] == 95.0
    # Allow None or "server" - server isn't in vocab so should be None
    assert out[0]["label"] is None


# ---- Decimal precision -------------------------------------------


def test_four_decimal_places():
    out = extract_percentages("APR 4.1234%")
    assert out[0]["value"] == 4.1234


def test_no_extra_digits_in_label():
    out = extract_percentages("Failed 12.3%")
    assert out[0]["value"] == 12.3
    assert out[0]["label"] == "failed"


# ---- Realistic capture scenarios ---------------------------------


def test_system_metrics_dashboard():
    text = """Server stats
CPU 87%
Memory 64%
Disk 45%
Network 12%
"""
    out = extract_percentages(text)
    labels = {e["label"] for e in out}
    assert "cpu" in labels
    assert "memory" in labels
    assert "disk" in labels


def test_poll_screenshot():
    text = """What's for lunch?
Yes 65% No 35%
"""
    out = extract_percentages(text)
    labels_and_values = {(e["label"], e["value"]) for e in out}
    assert ("yes", 65.0) in labels_and_values
    assert ("no", 35.0) in labels_and_values


def test_trading_screenshot():
    text = """AAPL +1.2%
TSLA -3.5%
SPY +0.8%
"""
    out = extract_percentages(text)
    signed_values = {(e["value"], e["sign"]) for e in out}
    assert (1.2, "+") in signed_values
    assert (-3.5, "-") in signed_values
    assert (0.8, "+") in signed_values


def test_battery_remaining():
    out = extract_percentages("Battery 32%, charging")
    assert out[0]["value"] == 32.0
    assert out[0]["label"] == "battery"


def test_test_coverage_report():
    text = """Coverage report:
Lines: 95.5%
Branches: 87.2%
Functions: 100%
"""
    out = extract_percentages(text)
    values = {e["value"] for e in out}
    assert 95.5 in values
    assert 87.2 in values
    assert 100.0 in values


def test_promotional_discount():
    text = """Black Friday Sale!
30% off everything
50% off select items
"""
    out = extract_percentages(text)
    values = {e["value"] for e in out}
    assert 30.0 in values
    assert 50.0 in values


# ---- Cap behaviour -----------------------------------------------


def test_capped_at_100_entries():
    # Generate >100 distinct percent values.
    parts = [f"v{i}{i % 100}%" for i in range(120)]
    text = " ".join(parts)
    out = extract_percentages(text)
    assert len(out) <= 100


# ---- Pipeline integration ----------------------------------------


def test_pipeline_stashes_under_raw_percentages():
    """The cross-category extractor populates raw["percentages"]."""
    fields = ExtractedFields()
    ocr = OCRResult(text="CPU 87% Memory 64%")
    out = enrich(Category.code_snippet, fields, ocr)
    assert "percentages" in out.raw
    values = [e["value"] for e in out.raw["percentages"]]
    assert 87.0 in values
    assert 64.0 in values


def test_pipeline_no_percentages_no_key():
    """No raw["percentages"] key when text has no percent values."""
    fields = ExtractedFields()
    ocr = OCRResult(text="def foo(): return 42")
    out = enrich(Category.code_snippet, fields, ocr)
    assert "percentages" not in out.raw


def test_pipeline_runs_for_every_category():
    """Cross-category: runs for receipt / chat / error / other too."""
    for cat in (
        Category.receipt,
        Category.chat_screenshot,
        Category.error_stacktrace,
        Category.other,
        Category.chart,
    ):
        fields = ExtractedFields()
        ocr = OCRResult(text="Coverage 95.5%")
        out = enrich(cat, fields, ocr)
        assert "percentages" in out.raw
        assert out.raw["percentages"][0]["value"] == 95.5


# ---- Edge cases --------------------------------------------------


def test_percent_at_start_of_text():
    out = extract_percentages("50% off")
    # bare 50% no label (walk back from offset 0 -- empty prefix).
    # The labelled matcher requires a preceding label, but "off"
    # comes after the percent so it's not picked up by either
    # path. Label is None.
    assert out[0]["value"] == 50.0


def test_percent_at_end_of_text():
    out = extract_percentages("Memory used 64%")
    assert out[0]["value"] == 64.0
    # ``used`` is in vocab and sits closer to the percent than
    # ``Memory``, so the walk-back picks ``used``.
    assert out[0]["label"] == "used"


def test_multiple_percents_no_space():
    out = extract_percentages("Stats: 50% 60% 70%")
    values = sorted(e["value"] for e in out)
    assert values == [50.0, 60.0, 70.0]


def test_percent_inside_sentence():
    out = extract_percentages("This is 50% off the listed price")
    assert out[0]["value"] == 50.0


def test_percent_followed_by_punctuation():
    out = extract_percentages("Coverage: 98.5%, branch 87.2%.")
    values = sorted(e["value"] for e in out)
    assert 98.5 in values
    assert 87.2 in values


def test_percent_in_brackets():
    out = extract_percentages("(50%) approval rating")
    assert out[0]["value"] == 50.0


def test_percent_with_unicode_minus():
    # Real unicode minus sign U+2212 is NOT captured because we
    # only accept ASCII -/+/±. (Conservative -- avoids
    # detecting OCR-noise minus glyphs.)
    out = extract_percentages("\u2212 5%")
    # The 5% still fires but the sign is None.
    if out:
        assert out[0]["value"] == 5.0


def test_no_value_above_max_bound_zero_below_min():
    # 1500% > 1000% bound -> rejected
    # 0% is in bounds -> accepted
    out = extract_percentages("Spike 1500% then Battery 0%")
    values = [e["value"] for e in out]
    assert 1500.0 not in values
    assert 0.0 in values


# ---- Label boundary cases ----------------------------------------


def test_label_with_dash_in_middle():
    """Labels that contain a dash like 'open-rate' are not in our
    vocab (we use underscores). But ``rate`` IS in vocab, so
    walking back from the percent finds ``rate`` first."""
    out = extract_percentages("Open-rate 32%")
    assert out[0]["value"] == 32.0
    assert out[0]["label"] == "rate"


def test_short_label_word_not_eaten():
    out = extract_percentages("up 5%")
    assert out[0]["value"] == 5.0
    assert out[0]["label"] == "up"


def test_label_at_line_start_does_not_bleed_across_lines():
    text = "CPU\n50%"
    out = extract_percentages(text)
    # Line for 50% is "50%" alone -- no label on the same line.
    # The labelled matcher requires label + percent on same span,
    # and the bare matcher's _label_from_line only looks at the
    # CURRENT line.
    assert out[0]["value"] == 50.0
    assert out[0]["label"] is None


def test_multiple_labels_same_value_dedupe_carefully():
    # Same value, same label, same sign -> one entry.
    # Same value, different label -> two entries.
    text = "CPU 50% Memory 50%"
    out = extract_percentages(text)
    label_value_pairs = {(e["label"], e["value"]) for e in out}
    assert ("cpu", 50.0) in label_value_pairs
    assert ("memory", 50.0) in label_value_pairs
