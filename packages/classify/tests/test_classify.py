from shotclassify_classify.client import _fallback_classification, _parse_llm_payload
from shotclassify_common import Category, OCRResult


def test_fallback_receipt():
    ocr = OCRResult(text="Subtotal 12.00\nTax 1.00\nTotal $13.00", word_count=8)
    cls, fields = _fallback_classification(ocr)
    assert cls.primary == Category.receipt
    assert fields.raw["source"] == "heuristic"


def test_fallback_error():
    ocr = OCRResult(text="Traceback (most recent call last):\nException: boom", word_count=8)
    cls, _ = _fallback_classification(ocr)
    assert cls.primary == Category.error_stacktrace


def test_parse_llm_payload_full():
    payload = {
        "primary": "receipt",
        "confidences": [{"category": "receipt", "score": 0.9}],
        "rationale": "Looks like a coffee receipt.",
        "fields": {
            "receipt": {
                "vendor": "Blue Bottle",
                "date": "2026-01-02",
                "total": 7.5,
                "currency": "USD",
                "items": [{"description": "Latte", "qty": 1, "price": 6.0}],
            }
        },
    }
    cls, fields = _parse_llm_payload(payload)
    assert cls.primary == Category.receipt
    assert fields.receipt is not None
    assert fields.receipt.vendor == "Blue Bottle"
    assert fields.receipt.items[0].description == "Latte"
    # all categories should be represented in confidences
    assert {c.category for c in cls.confidences} == set(Category)


def test_parse_llm_payload_invalid_category_defaults_other():
    payload = {"primary": "spaceship", "confidences": [], "fields": {}}
    cls, _ = _parse_llm_payload(payload)
    assert cls.primary == Category.other
