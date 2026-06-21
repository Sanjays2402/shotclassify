"""Tests for ReceiptFields.tip_percent derivation.

``tip_percent`` is computed from ``tip / subtotal * 100`` (preferred,
US convention is to tip on the pre-tax subtotal) and falls back to
``tip / (total - tip)`` when only the total is available. Rounded to
one decimal place because OCR + receipt rounding makes two decimals
spurious. ``None`` when the receipt has no tip or no usable base.
"""
from __future__ import annotations

import pytest
from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract.receipt import enrich_receipt, parse_receipt_text


def test_tip_percent_from_subtotal():
    text = (
        "Subtotal           20.00\n"
        "Tax                 1.80\n"
        "Tip                 4.00\n"
        "Total              25.80\n"
    )
    r = parse_receipt_text(text)
    assert r.tip == 4.0
    assert r.subtotal == 20.0
    assert r.tip_percent == 20.0


def test_tip_percent_rounding_one_decimal():
    """3.50 / 22.00 = 15.9090..., rounds to 15.9."""
    text = (
        "Subtotal           22.00\n"
        "Tax                 1.98\n"
        "Tip                 3.50\n"
        "Total              27.48\n"
    )
    r = parse_receipt_text(text)
    assert r.tip_percent == 15.9


def test_tip_percent_falls_back_to_total_minus_tip():
    """No subtotal available; we derive base = total - tip."""
    text = "Tip 3.00\nTotal 23.00\n"
    r = parse_receipt_text(text)
    assert r.tip == 3.0
    assert r.subtotal is None
    # 3 / (23 - 3) * 100 = 15.0
    assert r.tip_percent == 15.0


def test_tip_percent_none_without_tip():
    text = "Subtotal 10.00\nTax 1.00\nTotal 11.00\n"
    r = parse_receipt_text(text)
    assert r.tip is None
    assert r.tip_percent is None


def test_tip_percent_none_without_base():
    """Tip present but nothing to compute the base from."""
    text = "Tip: 5.00\n"  # no subtotal, no total
    r = parse_receipt_text(text)
    assert r.tip == 5.0
    assert r.subtotal is None
    assert r.total is None
    assert r.tip_percent is None


def test_tip_percent_zero_tip_returns_none():
    """A printed 'Tip 0.00' line should not poison downstream charts
    with a 0.0% bucket; we treat it the same as no tip."""
    text = "Subtotal 10.00\nTip 0.00\nTotal 10.00\n"
    r = parse_receipt_text(text)
    assert r.tip == 0.0
    assert r.tip_percent is None


def test_tip_percent_subtotal_preferred_over_total():
    """When both are present we use subtotal, not total - tip."""
    text = (
        "Subtotal 100.00\n"
        "Tax        9.00\n"
        "Tip       20.00\n"
        "Total    129.00\n"
    )
    r = parse_receipt_text(text)
    # 20 / 100 = 20.0%  (vs. 20 / 109 = 18.3% if we'd used total - tip)
    assert r.tip_percent == 20.0


@pytest.mark.parametrize(
    "tip,subtotal,expected",
    [
        (1.0, 10.0, 10.0),
        (2.0, 10.0, 20.0),
        (3.0, 15.0, 20.0),
        (1.5, 12.0, 12.5),
        (0.99, 9.99, 9.9),
    ],
)
def test_tip_percent_table(tip, subtotal, expected):
    text = f"Subtotal {subtotal:.2f}\nTip {tip:.2f}\nTotal {tip + subtotal:.2f}\n"
    r = parse_receipt_text(text)
    assert r.tip_percent == expected


def test_enrich_recomputes_tip_percent_when_existing_lacks_it():
    """The LLM gives us subtotal but no tip; OCR pass discovers the tip;
    enrich should compute tip_percent on the merged values."""
    existing = ReceiptFields(subtotal=20.0)
    ocr = OCRResult(
        text="Subtotal 20.00\nTip 4.00\nTotal 24.00\n", word_count=6
    )
    merged = enrich_receipt(existing, ocr)
    assert merged.subtotal == 20.0
    assert merged.tip == 4.0
    assert merged.tip_percent == 20.0


def test_enrich_keeps_existing_tip_percent_if_set():
    """A caller that has already computed a percent (e.g. an LLM that
    saw the on-screen 'Tip 20%' header) is trusted."""
    existing = ReceiptFields(subtotal=20.0, tip=4.0, tip_percent=22.0)
    ocr = OCRResult(text="", word_count=0)
    merged = enrich_receipt(existing, ocr)
    assert merged.tip_percent == 22.0
