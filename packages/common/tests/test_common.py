from shotclassify_common import Category, Classification, Confidence, get_settings


def test_settings_defaults():
    from shotclassify_common.settings import get_settings

    get_settings.cache_clear()
    s = get_settings()
    assert s.app_port == 7441
    assert "/v" in s.llm_base_url


def test_category_enum_complete():
    assert "receipt" in Category.all()
    assert "code_snippet" in Category.all()
    assert len(Category.all()) == 9


def test_classification_confidence_lookup():
    c = Classification(
        primary=Category.receipt,
        confidences=[
            Confidence(category=Category.receipt, score=0.9),
            Confidence(category=Category.meme, score=0.05),
        ],
    )
    assert c.confidence_of(Category.receipt) == 0.9
    assert c.confidence_of(Category.chart) == 0.0
