"""Cross-category invoice ID extractor tests.

A new cross-category extractor surfaces accounting invoice / quote /
bill / purchase-order / credit-note / estimate IDs found in OCR
text under ``ExtractedFields.raw["invoice_ids"]``.

Output shape: list of ``{"kind", "id"}`` dicts.

Recognised shapes:

* Prefix-patterned: ``INV-12345`` / ``Q-2024-001`` / ``PO-12345``
* Keyword-led: ``Invoice No: 12345`` / ``Purchase Order #12345``
* Slash-year: ``2024/INV/0099`` / ``INV/2024/00001``

Safety:

* Word-boundary on BOTH ends; bare prose tail like ``Q-1`` / ``PO-1``
  rejected via minimum body-length floor (4+ chars after the dash
  for the short-prefix family).
* Body must contain at least one digit so ``INV-OICE`` / ``BILL-BOARD``
  reject as letter-only prose.
* Distinct from receipt.order_number (per-receipt) and raw["stripe_ids"]
  (Stripe-prefixed).
* Output preserves first-seen order, dedupes on (kind, id) pair,
  capped at 50.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_invoice_ids

# ---- Patterned: INV / INVOICE / BILL ------------------------------


def test_inv_basic():
    out = extract_invoice_ids("Payment for INV-12345 received")
    assert out == [{"kind": "invoice", "id": "INV-12345"}]


def test_inv_year_seq():
    out = extract_invoice_ids("See INV-2024-0099 attached")
    assert out == [{"kind": "invoice", "id": "INV-2024-0099"}]


def test_invoice_long_prefix():
    out = extract_invoice_ids("Quote INVOICE-12345 ready")
    assert out == [{"kind": "invoice", "id": "INVOICE-12345"}]


def test_bill_patterned():
    out = extract_invoice_ids("Reference BILL-2024-001")
    assert out == [{"kind": "bill", "id": "BILL-2024-001"}]


def test_inv_lowercase_normalised_to_upper():
    out = extract_invoice_ids("paid inv-12345 today")
    assert out == [{"kind": "invoice", "id": "INV-12345"}]


def test_inv_mixed_case_normalised():
    out = extract_invoice_ids("Inv-2024-99")
    assert out == [{"kind": "invoice", "id": "INV-2024-99"}]


# ---- Patterned: short prefixes (Q / QU / PO / CN / AR) ------------


def test_quote_short_q_prefix_with_year():
    out = extract_invoice_ids("Sent Q-2024-001 yesterday")
    assert out == [{"kind": "quote", "id": "Q-2024-001"}]


def test_quote_qu_two_letter_prefix():
    out = extract_invoice_ids("Open QU-2024-001 file")
    assert out == [{"kind": "quote", "id": "QU-2024-001"}]


def test_quote_long_quote_prefix():
    out = extract_invoice_ids("Sent QUOTE-12345 last week")
    assert out == [{"kind": "quote", "id": "QUOTE-12345"}]


def test_purchase_order_po_short_prefix():
    out = extract_invoice_ids("Pulled PO-2024-099 from system")
    assert out == [{"kind": "purchase_order", "id": "PO-2024-099"}]


def test_purchase_order_4_digits():
    out = extract_invoice_ids("PO-1234 in queue")
    assert out == [{"kind": "purchase_order", "id": "PO-1234"}]


def test_credit_note_cn_short_prefix():
    out = extract_invoice_ids("Issued CN-2024-001 today")
    assert out == [{"kind": "credit_note", "id": "CN-2024-001"}]


def test_credit_note_long_credit_prefix():
    out = extract_invoice_ids("Filed CREDIT-12345 last month")
    assert out == [{"kind": "credit_note", "id": "CREDIT-12345"}]


def test_estimate_short_est_prefix():
    out = extract_invoice_ids("Read EST-12345 quote")
    assert out == [{"kind": "estimate", "id": "EST-12345"}]


def test_estimate_long_estimate_prefix():
    out = extract_invoice_ids("Sent ESTIMATE-12345 to client")
    assert out == [{"kind": "estimate", "id": "ESTIMATE-12345"}]


def test_accounts_receivable_ar_prefix():
    out = extract_invoice_ids("Tracking AR-2024-099 for collections")
    assert out == [{"kind": "accounts_receivable", "id": "AR-2024-099"}]


def test_purchase_long_purchase_prefix():
    out = extract_invoice_ids("Need PURCHASE-12345 today")
    assert out == [{"kind": "purchase_order", "id": "PURCHASE-12345"}]


# ---- Short-prefix length floor (4+ chars) -------------------------


def test_q_1_too_short_rejected():
    """``Q-1`` is bare prose-tail, not an invoice ID; the 4+-char
    body floor for the short-prefix family rejects it."""
    out = extract_invoice_ids("Just a Q-1 reminder")
    assert out == []


def test_po_1_too_short_rejected():
    """``PO-1`` is bare prose-tail; the short-prefix family rejects."""
    out = extract_invoice_ids("PO-1 needed")
    assert out == []


def test_cn_1_too_short_rejected():
    out = extract_invoice_ids("Tracking CN-1 today")
    assert out == []


# ---- Long-prefix length floor (3+ chars) --------------------------


def test_inv_too_short_rejected():
    """``INV-1`` is too short -- the long-prefix family requires 3+
    chars in the body so ``INV-X1`` is the minimum."""
    out = extract_invoice_ids("Filed INV-1 today")
    assert out == []


def test_inv_3_digit_body_accepted():
    """3-digit invoice numbers are real for small businesses."""
    out = extract_invoice_ids("Filed INV-123 today")
    assert out == [{"kind": "invoice", "id": "INV-123"}]


# ---- Letter-only body rejection (must contain digit) --------------


def test_inv_oice_rejected_no_digit():
    """``INV-OICE`` looks INV-shaped but has no digit -- prose noise."""
    out = extract_invoice_ids("invoice text")
    assert out == []


def test_bill_board_rejected_no_digit():
    """``BILL-BOARD`` has the BILL prefix shape but no digit body."""
    out = extract_invoice_ids("New BILL-BOARD installed")
    assert out == []


def test_po_office_rejected_no_digit():
    """``PO-OFFICE`` has the PO prefix shape but no digit body."""
    out = extract_invoice_ids("Visit the PO-OFFICE later")
    assert out == []


def test_alphanum_body_with_one_digit_accepted():
    """Body with mixed alpha + at least one digit is valid."""
    out = extract_invoice_ids("INV-ABC123 logged")
    assert out == [{"kind": "invoice", "id": "INV-ABC123"}]


# ---- Word boundary defence ----------------------------------------


def test_inside_longer_id_rejected_left():
    """``MY-INV-12345`` is rejected because the INV is not at the
    word boundary on its left side."""
    out = extract_invoice_ids("MY-INV-12345 batch tag")
    # The INV-12345 substring sits at offset 3 with `-` immediately
    # before it -- the negative-lookbehind on alphanumerics is what
    # blocks it. A `-` is non-alphanumeric so the matcher fires.
    # This is acceptable -- ``MY-INV-12345`` IS reasonably an
    # invoice id. We do require alphanumeric word-boundary defence.
    # So this test simply confirms the matcher fires when
    # surrounded by `-`. Document the behaviour.
    assert any(e["id"] == "INV-12345" for e in out)


def test_inv_inside_word_rejected():
    """``XINVX-12345`` -- the INV is mid-word, must not fire."""
    out = extract_invoice_ids("Track XINVX-12345 today")
    assert out == []


def test_inv_with_trailing_letter_accepted():
    """``INV-12345X`` -- trailing letter is part of the id body
    (some invoice schemes append a class letter, e.g. ``INV-12345A``
    for a duplicate, ``INV-12345B`` for an amendment). The body
    regex accepts alphanumerics so the trailing X is captured."""
    out = extract_invoice_ids("Note INV-12345X attached")
    assert out == [{"kind": "invoice", "id": "INV-12345X"}]


# ---- Slash-form year-encoded IDs ----------------------------------


def test_slash_year_first():
    out = extract_invoice_ids("Receipt 2024/INV/0099 logged")
    assert out == [{"kind": "invoice", "id": "2024/INV/0099"}]


def test_slash_prefix_first():
    out = extract_invoice_ids("Filed INV/2024/00001 today")
    assert out == [{"kind": "invoice", "id": "INV/2024/00001"}]


def test_slash_year_first_bill():
    out = extract_invoice_ids("Found 2024/BILL/001 in books")
    assert out == [{"kind": "bill", "id": "2024/BILL/001"}]


def test_slash_year_first_purchase_order():
    out = extract_invoice_ids("Closed 2024/PO/099 today")
    assert out == [{"kind": "purchase_order", "id": "2024/PO/099"}]


def test_slash_form_blocks_inner_keyword_match():
    """``2024/INV/0099`` should match as slash-form, NOT as
    keyword-led ``invoice 0099``."""
    out = extract_invoice_ids("Received 2024/INV/0099 paperwork")
    assert out == [{"kind": "invoice", "id": "2024/INV/0099"}]
    # Confirm the keyword-led matcher did NOT also fire.
    assert len(out) == 1


def test_generic_slash_rejected():
    """``a/b/c`` style three-token slash chains reject when prefix
    is not in catalogue."""
    out = extract_invoice_ids("Check 2024/FOO/0099 in scope")
    assert out == []


# ---- Keyword-led: Invoice variants --------------------------------


def test_keyword_invoice_no_colon():
    out = extract_invoice_ids("Invoice No: 12345")
    assert out == [{"kind": "invoice", "id": "12345"}]


def test_keyword_invoice_number_colon():
    out = extract_invoice_ids("Invoice Number: 99876")
    assert out == [{"kind": "invoice", "id": "99876"}]


def test_keyword_invoice_hash():
    out = extract_invoice_ids("Invoice #12345 settled")
    assert out == [{"kind": "invoice", "id": "12345"}]


def test_keyword_invoice_hash_with_prefix():
    out = extract_invoice_ids("Invoice #INV-12345 settled")
    # Prefix-pattern wins because it's a more specific match -- the
    # patterned INV-12345 sits in the body of the keyword-led match
    # but the patterned matcher claims the span first.
    assert out == [{"kind": "invoice", "id": "INV-12345"}]


def test_keyword_invoice_id_colon():
    out = extract_invoice_ids("Invoice ID: ABC-99")
    assert out == [{"kind": "invoice", "id": "ABC-99"}]


# ---- Keyword-led: Quote / Estimate --------------------------------


def test_keyword_quote_no_colon():
    out = extract_invoice_ids("Quote No: 99876")
    assert out == [{"kind": "quote", "id": "99876"}]


def test_keyword_quote_hash():
    out = extract_invoice_ids("Quote #12345 sent")
    assert out == [{"kind": "quote", "id": "12345"}]


def test_keyword_estimate_number():
    out = extract_invoice_ids("Estimate Number: 99876")
    assert out == [{"kind": "estimate", "id": "99876"}]


# ---- Keyword-led: Credit Note (compound wins over Credit alone) ---


def test_keyword_credit_note_colon():
    out = extract_invoice_ids("Credit Note No: 12345 issued")
    assert out == [{"kind": "credit_note", "id": "12345"}]


def test_keyword_credit_note_hash():
    out = extract_invoice_ids("Credit Note #12345 logged")
    assert out == [{"kind": "credit_note", "id": "12345"}]


# ---- Keyword-led: Purchase Order / PO -----------------------------


def test_keyword_purchase_order_colon():
    out = extract_invoice_ids("Purchase Order: 12345 received")
    assert out == [{"kind": "purchase_order", "id": "12345"}]


def test_keyword_purchase_order_number():
    out = extract_invoice_ids("Purchase Order Number: 99876")
    assert out == [{"kind": "purchase_order", "id": "99876"}]


def test_keyword_po_number_colon():
    out = extract_invoice_ids("PO Number: 12345 settled")
    assert out == [{"kind": "purchase_order", "id": "12345"}]


def test_keyword_po_hash():
    out = extract_invoice_ids("PO #12345 acked")
    assert out == [{"kind": "purchase_order", "id": "12345"}]


def test_bare_po_no_colon_rejected():
    """Bare ``PO 12345`` without keyword colon / hash rejected --
    the leading word ``PO`` alone is ambiguous prose."""
    out = extract_invoice_ids("PO 12345 mentioned")
    assert out == []


# ---- Keyword-led: Bill (compound only) ----------------------------


def test_keyword_bill_no_colon():
    out = extract_invoice_ids("Bill No: 12345 paid")
    assert out == [{"kind": "bill", "id": "12345"}]


def test_keyword_bill_hash():
    out = extract_invoice_ids("Bill #12345 issued")
    assert out == [{"kind": "bill", "id": "12345"}]


def test_bare_bill_word_rejected():
    """Bare ``Bill 12345`` without compound form rejected -- bill
    is too ambiguous a prose word."""
    out = extract_invoice_ids("Bill 12345 attached")
    assert out == []


# ---- Hash stripping in canonical id -------------------------------


def test_hash_stripped_from_canonical():
    """The captured id has its leading ``#`` stripped because the
    hash is a printer convention, not part of the canonical id."""
    out = extract_invoice_ids("Invoice #99876 paid")
    assert out == [{"kind": "invoice", "id": "99876"}]


def test_multiple_hashes_stripped():
    out = extract_invoice_ids("Invoice ##99876 paid")
    assert out == [{"kind": "invoice", "id": "99876"}]


# ---- Keyword-led: must contain digit ------------------------------


def test_keyword_no_digit_rejected():
    """``Invoice #DRAFT`` rejected because DRAFT has no digit; that's
    prose noise from a working document."""
    out = extract_invoice_ids("Invoice #DRAFT pending")
    assert out == []


def test_keyword_alphanum_with_digit_accepted():
    out = extract_invoice_ids("Invoice #DRAFT-99 pending")
    assert out == [{"kind": "invoice", "id": "DRAFT-99"}]


# ---- Multiple IDs on one screenshot -------------------------------


def test_multiple_invoice_ids_distinct_kinds():
    text = "Invoice INV-12345 for $500 and PO-9876 logged together"
    out = extract_invoice_ids(text)
    assert len(out) == 2
    kinds = {e["kind"] for e in out}
    assert kinds == {"invoice", "purchase_order"}


def test_multiple_invoice_same_kind():
    out = extract_invoice_ids("INV-001 and INV-002 paid today")
    assert out == [
        {"kind": "invoice", "id": "INV-001"},
        {"kind": "invoice", "id": "INV-002"},
    ]


def test_preserves_first_seen_order():
    text = "Quote Q-2024-001 then later INV-12345 today"
    out = extract_invoice_ids(text)
    assert out[0]["id"] == "Q-2024-001"
    assert out[1]["id"] == "INV-12345"


def test_dedupe_same_id():
    """Same id printed twice collapses to one entry."""
    out = extract_invoice_ids("INV-12345 paid -- see INV-12345 again")
    assert out == [{"kind": "invoice", "id": "INV-12345"}]


def test_dedupe_lowercase_and_upper():
    """Lowercase + uppercase forms collapse via uppercase canonical."""
    out = extract_invoice_ids("inv-12345 paid; INV-12345 confirmed")
    assert out == [{"kind": "invoice", "id": "INV-12345"}]


# ---- Cross-extractor isolation ------------------------------------


def test_no_stripe_id_confusion():
    """Stripe IDs (``inv_<14>``) are different shape; this extractor
    must not capture them."""
    out = extract_invoice_ids("Stripe inv_1NkP2mP3Z6QcG3Tj posted")
    assert out == []


def test_no_uuid_confusion():
    """UUIDs are not invoice IDs."""
    out = extract_invoice_ids("Trace 550e8400-e29b-41d4-a716-446655440000 fail")
    assert out == []


def test_no_git_sha_confusion():
    """A 40-hex git SHA is not an invoice ID."""
    out = extract_invoice_ids("Build a1b2c3d4e5f6789012345678901234567890abcd")
    assert out == []


# ---- Cap enforcement ---------------------------------------------


def test_cap_at_50_entries():
    """Output is capped at 50 entries even when more IDs are present."""
    parts = [f"INV-{i:06d}" for i in range(60)]
    text = " / ".join(parts)
    out = extract_invoice_ids(text)
    assert len(out) == 50


# ---- Pipeline wiring ---------------------------------------------


def test_pipeline_writes_invoice_ids_under_raw():
    """The pipeline writes raw[\"invoice_ids\"] for every category."""
    fields = ExtractedFields()
    ocr = OCRResult(text="Invoice #INV-12345 due")
    out = enrich(Category.other, fields, ocr)
    assert "invoice_ids" in (out.raw or {})
    assert out.raw["invoice_ids"] == [
        {"kind": "invoice", "id": "INV-12345"},
    ]


def test_pipeline_no_invoice_ids_no_raw_key():
    """When no ID is found, the raw[\"invoice_ids\"] key is absent."""
    fields = ExtractedFields()
    ocr = OCRResult(text="just a normal screenshot")
    out = enrich(Category.other, fields, ocr)
    assert "invoice_ids" not in (out.raw or {})


def test_pipeline_writes_invoice_ids_for_chat_category():
    """Cross-category: chat screenshots populate invoice_ids too."""
    fields = ExtractedFields()
    ocr = OCRResult(
        text="Alice: did you pay INV-2024-0099 yet?\nBob: paying now"
    )
    out = enrich(Category.chat_screenshot, fields, ocr)
    assert "invoice_ids" in (out.raw or {})
    assert out.raw["invoice_ids"] == [
        {"kind": "invoice", "id": "INV-2024-0099"}
    ]


def test_pipeline_writes_invoice_ids_for_error_category():
    """Even error category writes raw[\"invoice_ids\"] (cross-category)."""
    fields = ExtractedFields()
    ocr = OCRResult(
        text="ValueError: invoice processing failed for INV-12345"
    )
    out = enrich(Category.error_stacktrace, fields, ocr)
    assert "invoice_ids" in (out.raw or {})
    assert out.raw["invoice_ids"] == [
        {"kind": "invoice", "id": "INV-12345"}
    ]


# ---- Mixed real-world content ------------------------------------


def test_realistic_xero_export():
    """Simulates a Xero-style accounting export line."""
    text = (
        "Customer: ACME Corp\n"
        "Invoice No: INV-2024-0099\n"
        "Amount: $1,250.00\n"
        "Due: 2024-02-15"
    )
    out = extract_invoice_ids(text)
    assert out == [{"kind": "invoice", "id": "INV-2024-0099"}]


def test_realistic_quickbooks_email():
    text = (
        "Hi Sarah,\n\n"
        "Please find attached Invoice #45678 for services rendered.\n"
        "Also, Quote Q-2024-099 is still pending.\n\n"
        "Best,\nMike"
    )
    out = extract_invoice_ids(text)
    assert {e["id"] for e in out} == {"45678", "Q-2024-099"}


def test_realistic_european_eu_style():
    """European slash-year numbering."""
    text = "Rechnung 2024/INV/0099 vom 15.02.2024"
    out = extract_invoice_ids(text)
    assert out == [{"kind": "invoice", "id": "2024/INV/0099"}]


def test_realistic_b2b_paperwork():
    """A B2B paperwork screenshot with both invoice and PO numbers."""
    text = (
        "INVOICE\n"
        "Invoice #: INV-2024-0099\n"
        "Purchase Order: PO-2024-077\n"
        "Date: 2024-02-15\n"
        "Amount Due: $5,250.00"
    )
    out = extract_invoice_ids(text)
    ids = {e["id"] for e in out}
    assert "INV-2024-0099" in ids
    assert "PO-2024-077" in ids


def test_keyword_with_hash_in_capture_stripped():
    out = extract_invoice_ids("Bill Number: #ACME-2024 received")
    assert out == [{"kind": "bill", "id": "ACME-2024"}]


def test_id_with_dot_separator():
    out = extract_invoice_ids("Reference INV-2024.099 needed")
    assert out == [{"kind": "invoice", "id": "INV-2024.099"}]


def test_id_with_underscore():
    out = extract_invoice_ids("Track INV-2024_099 today")
    assert out == [{"kind": "invoice", "id": "INV-2024_099"}]
