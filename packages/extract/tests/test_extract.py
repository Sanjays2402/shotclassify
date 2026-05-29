from shotclassify_common import OCRResult
from shotclassify_extract.code import detect_language, enrich_code
from shotclassify_extract.error import parse_error_text
from shotclassify_extract.receipt import parse_receipt_text


def test_receipt_parse_basic():
    text = """Blue Bottle Coffee
123 Mission St
2026-01-02
Latte               6.00
Croissant           3.50
Subtotal            9.50
Tax                 0.80
Total              $10.30
Thank you
"""
    r = parse_receipt_text(text)
    assert r.vendor == "Blue Bottle Coffee"
    assert r.date == "2026-01-02"
    assert r.subtotal == 9.5
    assert r.tax == 0.8
    assert r.total == 10.3
    assert r.currency == "USD"
    assert any(i.description.lower().startswith("latte") for i in r.items)


def test_code_language_python():
    code = "def add(a, b):\n    return a + b\nprint(add(2,3))\n"
    lang = detect_language(code)
    assert lang in {"python", "python3", "py", "text"}


def test_code_enrich_uses_ocr_when_empty():
    ocr = OCRResult(text="const x = 1;\nfunction f() {}\n", word_count=5)
    c = enrich_code(None, ocr)
    assert c.code.startswith("const")
    assert c.line_count == 2


def test_error_python_traceback():
    text = """Traceback (most recent call last):
  File "app.py", line 12, in <module>
    main()
  File "app.py", line 8, in main
    config["nope"]
KeyError: 'nope'
"""
    e = parse_error_text(text)
    assert e.framework == "python"
    assert e.exception == "KeyError"
    assert e.file == "app.py"
    assert e.line == 8
    assert e.likely_cause and "key" in e.likely_cause.lower()


def test_error_node_traceback():
    text = """TypeError: Cannot read properties of undefined (reading 'foo')
    at Object.<anonymous> (/srv/app/index.js:42:13)
"""
    e = parse_error_text(text)
    assert e.framework == "node"
    assert e.exception == "TypeError"
    assert e.file.endswith("index.js")
    assert e.line == 42
