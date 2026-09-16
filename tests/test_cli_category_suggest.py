"""The ``correct`` command suggests the nearest valid category on a typo."""
from shotclassify_common.schemas import suggest_category


def test_suggest_category_typo():
    assert suggest_category("reciept") == "receipt"
    assert suggest_category("chrt") == "chart"
    assert suggest_category("ui_mockups") == "ui_mockup"


def test_suggest_category_exact_value():
    assert suggest_category("meme") == "meme"


def test_suggest_category_no_match_returns_none():
    assert suggest_category("zzz-not-a-category") is None
    assert suggest_category("") is None
