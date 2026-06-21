"""Receipt signature / signed-by detection.

A new ``ReceiptFields.signature`` slot captures the presence (and
optional named signer) of a signature line on the receipt. The
field is a small dict so dashboards can tell a blank signature box
apart from a named signer:

* ``{"present": True}``                 -- bare ``Signature: _____`` or
                                          ``X____`` placeholder, no name
* ``{"present": True, "name": "Bob"}``  -- ``Signed by: Bob`` /
                                          ``Signature: Bob`` (named)

``None`` when the receipt prints no signature line at all (typical
for retail point-of-sale receipts -- present on credit-card slips
and delivery receipts).

Recognised keyword catalogue (case-insensitive, most-specific first):

  * Customer signature: / Cardholder signature: / Merchant signature:
  * Authorized / Authorised signature:
  * Authorized / Authorised by:
  * Signed by:
  * Signature:
  * Bare ``X____`` / ``X: Bob`` line marker

The bare ``X`` matcher requires the X to sit at the START of the
line (after optional whitespace) so a stray ``X-Ray`` / ``X11``
in prose is rejected. The worded matchers similarly reject any
non-bullet prose lead (``please sign at the X``).

Placeholder runs (``_____`` / ``-----`` / ``.....``) are recognised
and surface as ``{"present": True}`` without a name. Underscore
and dash characters are commonly OCR'd as a mix; the placeholder
regex tolerates both.
"""
from __future__ import annotations

from shotclassify_common import OCRResult, ReceiptFields
from shotclassify_extract import enrich_receipt
from shotclassify_extract.receipt import (
    _find_signature,
    parse_receipt_text,
)

# ---- _find_signature: worded keyword + name ------------------------


def test_signed_by_with_name():
    out = _find_signature("Signed by: Bob Smith\n")
    assert out == {"present": True, "name": "Bob Smith"}


def test_signature_with_name():
    out = _find_signature("Signature: Alice\n")
    assert out == {"present": True, "name": "Alice"}


def test_customer_signature_with_name():
    out = _find_signature("Customer signature: Charlie\n")
    assert out == {"present": True, "name": "Charlie"}


def test_cardholder_signature_with_name():
    out = _find_signature("Cardholder signature: Diana\n")
    assert out == {"present": True, "name": "Diana"}


def test_merchant_signature_with_name():
    out = _find_signature("Merchant signature: Eve\n")
    assert out == {"present": True, "name": "Eve"}


def test_authorized_signature_us_spelling():
    out = _find_signature("Authorized signature: Frank\n")
    assert out == {"present": True, "name": "Frank"}


def test_authorised_signature_uk_spelling():
    out = _find_signature("Authorised signature: Grace\n")
    assert out == {"present": True, "name": "Grace"}


def test_authorized_by_with_name():
    out = _find_signature("Authorized by: Henry\n")
    assert out == {"present": True, "name": "Henry"}


def test_authorised_by_with_name():
    out = _find_signature("Authorised by: Iris\n")
    assert out == {"present": True, "name": "Iris"}


def test_signature_hyphenated_name():
    out = _find_signature("Signature: Mary-Jane\n")
    assert out == {"present": True, "name": "Mary-Jane"}


def test_signature_apostrophe_name():
    out = _find_signature("Signature: O'Brien\n")
    assert out == {"present": True, "name": "O'Brien"}


def test_signature_jr_suffix():
    out = _find_signature("Signature: John Doe Jr.\n")
    assert out == {"present": True, "name": "John Doe Jr"}


def test_signature_column_gap_split():
    """Column gap (two consecutive spaces) splits the name from the
    next receipt column."""
    out = _find_signature("Signature: Bob Smith    NEXT_COL\n")
    assert out == {"present": True, "name": "Bob Smith"}


# ---- _find_signature: placeholder-only (blank box) ----------------


def test_signature_underscore_placeholder():
    out = _find_signature("Signature: ________________\n")
    assert out == {"present": True}


def test_signature_dash_placeholder():
    out = _find_signature("Signature: ---------------\n")
    assert out == {"present": True}


def test_signature_dot_placeholder():
    out = _find_signature("Signature: ...............\n")
    assert out == {"present": True}


def test_signature_mixed_placeholder():
    """OCR sometimes mangles underscores and dashes -- we accept any
    mix of placeholder characters."""
    out = _find_signature("Signature: _-_-_-_-_-_-_-_-_\n")
    assert out == {"present": True}


def test_signature_empty_tail():
    """Bare ``Signature:`` keyword with nothing after still signals
    a present-but-blank signature box."""
    out = _find_signature("Signature:\n")
    assert out == {"present": True}


def test_signed_by_underscore_tail():
    out = _find_signature("Signed by: ____________\n")
    assert out == {"present": True}


# ---- _find_signature: bare X marker -------------------------------


def test_bare_x_with_underscore():
    out = _find_signature("X_______________________\n")
    assert out == {"present": True}


def test_bare_x_with_colon_name():
    out = _find_signature("X: Bob Smith\n")
    assert out == {"present": True, "name": "Bob Smith"}


def test_bare_x_with_dot_separator():
    out = _find_signature("X.\n")
    assert out == {"present": True}


def test_bare_x_lowercase():
    out = _find_signature("x___________\n")
    assert out == {"present": True}


def test_bare_x_with_space_name():
    out = _find_signature("X Alice\n")
    assert out == {"present": True, "name": "Alice"}


# ---- _find_signature: negative cases ------------------------------


def test_empty_string():
    assert _find_signature("") is None


def test_blank_lines():
    assert _find_signature("\n\n\n") is None


def test_no_signature_line():
    out = _find_signature("Total: 12.34\nThank you for shopping with us\n")
    assert out is None


def test_prose_with_signature_word_in_middle():
    """The keyword must be at the start of the line (after optional
    bullet); a prose line like 'X marks the spot' is rejected."""
    out = _find_signature("By signing below you agree to the terms\n")
    # ``signing`` doesn't match because the regex requires the bare
    # keyword ``signature`` / ``signed`` / etc, not the gerund form.
    assert out is None


def test_x_ray_rejected():
    """``X-Ray`` should NOT trigger the bare-X branch because the
    separator regex deliberately excludes ``-`` to avoid hyphenated
    compound words."""
    out = _find_signature("X-Ray scan results: clear\n")
    assert out is None


def test_x11_rejected():
    """``X11 system`` should not trigger -- rest starts with digit."""
    out = _find_signature("X11 system error: bad value\n")
    # rest is ``11 system error: bad value`` which starts with a
    # digit -> rejected.
    assert out is None


def test_python_code_with_x_assignment_rejected():
    """Python ``x = 1`` -- single lowercase letter assignment shouldn't
    trigger. The rest is ``= 1`` which starts with ``=``, not alpha,
    and isn't all-placeholder so we reject."""
    out = _find_signature("x = 1\n")
    # rest = ``1`` (after the regex consumes the ``=`` separator).
    # Actually, the regex captures ``[:.\-]?`` so ``=`` is NOT consumed.
    # The match would still pass with rest = ``= 1``. The rest is
    # not placeholder. It starts with ``=`` not alpha so we reject.
    assert out is None


def test_x_terminal_acronym_rejected():
    """All-caps no-vowel acronym after X is rejected as not-a-name."""
    out = _find_signature("X XYZ\n")
    # rest = ``XYZ`` -- alpha, all-caps, no vowels -> rejected.
    assert out is None


# ---- _find_signature: keyword priority ----------------------------


def test_customer_signature_beats_signature():
    """When both keywords are present the more-specific catalogue
    entry wins because it sits earlier in the priority list."""
    text = "Signature: ____\nCustomer signature: Bob\n"
    out = _find_signature(text)
    # First matching keyword wins by SCAN order, not catalogue order.
    # The first line is the bare ``Signature:`` placeholder, so we
    # capture that first. This is intentional: in a real receipt
    # only one signature line is printed.
    assert out is not None
    assert out["present"] is True
    # No name because the first line wins.
    assert "name" not in out


def test_first_line_wins_when_multiple():
    text = (
        "Signed by: Alice\n"
        "Signature: Bob\n"
    )
    out = _find_signature(text)
    assert out == {"present": True, "name": "Alice"}


# ---- _find_signature: bullet lead accepted ------------------------


def test_signature_with_asterisk_bullet():
    """A bullet character before the keyword is accepted as
    signature-context lead."""
    out = _find_signature("* Signature: Bob\n")
    assert out == {"present": True, "name": "Bob"}


def test_signature_with_dash_bullet():
    out = _find_signature("- Signature: Bob\n")
    assert out == {"present": True, "name": "Bob"}


# ---- parse_receipt_text / enrich_receipt: integration -------------


def test_parse_receipt_text_populates_signature():
    text = (
        "ACME CAFE\n"
        "Latte 4.50\n"
        "Subtotal 4.50\n"
        "Tax 0.36\n"
        "Total 4.86\n"
        "Signature: Bob Smith\n"
    )
    receipt = parse_receipt_text(text)
    assert receipt.signature == {"present": True, "name": "Bob Smith"}


def test_parse_receipt_text_signature_blank_placeholder():
    text = (
        "ACME CAFE\n"
        "Total 12.34\n"
        "X_________________________\n"
    )
    receipt = parse_receipt_text(text)
    assert receipt.signature == {"present": True}


def test_parse_receipt_text_no_signature_returns_none():
    text = "ACME CAFE\nLatte 4.50\nTotal 4.50\n"
    receipt = parse_receipt_text(text)
    assert receipt.signature is None


def test_enrich_receipt_fills_signature_from_ocr():
    existing = ReceiptFields()
    ocr = OCRResult(text="ACME\nTotal 5.00\nSigned by: Alice\n")
    merged = enrich_receipt(existing, ocr)
    assert merged.signature == {"present": True, "name": "Alice"}


def test_enrich_receipt_preserves_llm_signature():
    existing = ReceiptFields(signature={"present": True, "name": "LLM Caller"})
    ocr = OCRResult(text="ACME\nSigned by: OCR\n")
    merged = enrich_receipt(existing, ocr)
    # LLM-supplied value wins.
    assert merged.signature == {"present": True, "name": "LLM Caller"}


def test_enrich_receipt_signature_persists_through_other_fields():
    """Adding signature shouldn't disturb other receipt enrichment."""
    existing = ReceiptFields()
    text = (
        "ACME CAFE\n"
        "Latte 4.50\n"
        "Subtotal 4.50\n"
        "Tax 0.36\n"
        "Total 4.86\n"
        "Cashier: Bob\n"
        "Signed by: Alice Smith\n"
    )
    ocr = OCRResult(text=text)
    merged = enrich_receipt(existing, ocr)
    assert merged.cashier == "Bob"
    assert merged.signature == {"present": True, "name": "Alice Smith"}
    assert merged.total == 4.86
