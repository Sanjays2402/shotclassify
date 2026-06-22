"""Drivers-license-number PII redaction mode.

A new ``drivers_license`` redaction mode strips labelled US drivers'
license numbers from OCR text. The matcher requires the word
``DL`` / ``license`` / ``licence`` / ``driver's license`` /
``drivers license`` / ``lic`` (case-insensitive) immediately before
the candidate so a bare 7-12 digit run on a receipt does NOT misfire
as a license number.

Accepted label forms:

  DL: A1234567
  DL # A1234567
  DL No: 12345678
  Driver's License: A1234567
  Drivers License: A1234567
  License No: A1234567
  License Number: 12345678
  License #: A1234567
  Lic: A1234567
  Lic. No. A1234567

Accepted candidate shapes (after the label) cover the 50 most common
US-state license formats:

* 7-12 pure digits (TX 8, NY 9, MI 13, OH 8, MA 9, GA 9, IL 12, NJ
  14, etc.)
* 1-2 letters + 6-13 alphanumerics (CA 1+7, NC 1+12, FL 1+12, WA
  1-7 letters+5 digits, MD 1+12, etc.)

The redaction strips ONLY the number, leaving the ``DL: `` label so
a reader knows the field WAS a license without the number itself
leaking.
"""
from __future__ import annotations

from shotclassify_common.redact import redact_fields, redact_text

# ---- DL: label forms ---------------------------------------------


def test_dl_colon_label_with_letter_prefix():
    text = "DL: A1234567"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out
    assert "[REDACTED:drivers_license]" in out
    assert "DL:" in out


def test_dl_hash_label():
    text = "DL # 12345678"
    out = redact_text(text, ["drivers_license"])
    assert "12345678" not in out
    assert "[REDACTED:drivers_license]" in out


def test_dl_no_colon_label():
    text = "DL No: A1234567"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out
    # "DL No:" preserved (it's not part of the captured num group).
    assert "DL No:" in out


def test_dl_period_form():
    text = "D.L. 12345678"
    out = redact_text(text, ["drivers_license"])
    assert "12345678" not in out
    assert "[REDACTED:drivers_license]" in out


# ---- License / Licence variations ------------------------------


def test_license_colon_label():
    text = "License: A1234567"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out
    assert "License:" in out


def test_license_no_label():
    text = "License No: 12345678"
    out = redact_text(text, ["drivers_license"])
    assert "12345678" not in out
    assert "License No:" in out


def test_license_number_label():
    text = "License Number: 12345678"
    out = redact_text(text, ["drivers_license"])
    assert "12345678" not in out
    assert "License Number:" in out


def test_license_hash_label():
    text = "License #: A1234567"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out
    assert "License" in out


def test_licence_british_spelling():
    # British / Canadian spelling supported.
    text = "Licence: A1234567"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out


def test_licence_no_british_spelling():
    text = "Licence No: 12345678"
    out = redact_text(text, ["drivers_license"])
    assert "12345678" not in out


# ---- Driver's License / Drivers License -----------------------


def test_drivers_license_with_apostrophe():
    text = "Driver's License: A1234567"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out


def test_drivers_license_without_apostrophe():
    text = "Drivers License: A1234567"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out


def test_drivers_licence_british():
    text = "Driver's Licence: 12345678"
    out = redact_text(text, ["drivers_license"])
    assert "12345678" not in out


def test_drivers_license_uppercase():
    text = "DRIVER'S LICENSE: 12345678"
    out = redact_text(text, ["drivers_license"])
    assert "12345678" not in out


# ---- Lic abbreviation ----------------------------------------


def test_lic_short_form():
    text = "Lic: A1234567"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out


def test_lic_no_period_form():
    text = "Lic. No. 12345678"
    out = redact_text(text, ["drivers_license"])
    assert "12345678" not in out


# ---- US state-specific shapes --------------------------------


def test_california_letter_plus_7_digits():
    # CA format: 1 letter + 7 digits (e.g., A1234567).
    text = "DL: A1234567"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out


def test_texas_8_digits():
    # TX format: 8 digits.
    text = "DL: 12345678"
    out = redact_text(text, ["drivers_license"])
    assert "12345678" not in out


def test_new_york_9_digits():
    # NY format: 9 digits.
    text = "DL: 123456789"
    out = redact_text(text, ["drivers_license"])
    assert "123456789" not in out


def test_florida_letter_plus_12_digits():
    # FL format: 1 letter + 12 digits (long).
    text = "DL: A123456789012"
    out = redact_text(text, ["drivers_license"])
    assert "A123456789012" not in out


def test_michigan_long_form():
    # MI format: 1 letter + 12 digits.
    text = "License: M987654321098"
    out = redact_text(text, ["drivers_license"])
    assert "M987654321098" not in out


def test_illinois_letter_plus_11_digits():
    # IL: 1 letter + 11 digits (12 total).
    text = "License: B12345678901"
    out = redact_text(text, ["drivers_license"])
    assert "B12345678901" not in out


def test_ohio_2_letters_plus_6_digits():
    # OH: 2 letters + 6 digits.
    text = "DL: AB123456"
    out = redact_text(text, ["drivers_license"])
    assert "AB123456" not in out


# ---- Label preservation -------------------------------------


def test_dl_label_preserved_after_redaction():
    text = "Vehicle reg DL: A1234567 expires 2028"
    out = redact_text(text, ["drivers_license"])
    assert "DL:" in out
    assert "[REDACTED:drivers_license]" in out
    # Tail still visible.
    assert "expires 2028" in out


def test_license_label_preserved_with_no_number_leak():
    text = "License No: 12345678 issued NY"
    out = redact_text(text, ["drivers_license"])
    assert "License No:" in out
    assert "12345678" not in out
    assert "NY" in out


# ---- Mode opt-in --------------------------------------------


def test_redaction_skipped_when_mode_not_requested():
    text = "DL: A1234567"
    out = redact_text(text, ["email"])  # different mode only
    assert "A1234567" in out


def test_empty_mode_list_returns_text_unchanged():
    text = "DL: A1234567"
    out = redact_text(text, [])
    assert out == text


def test_none_modes_returns_text_unchanged():
    text = "DL: A1234567"
    out = redact_text(text, None)
    assert out == text


# ---- False-positive defence --------------------------------


def test_bare_digit_run_without_label_not_redacted():
    # A bare 8-digit run (no "DL"/"license" label) is NOT redacted.
    text = "Order #12345678 was placed yesterday"
    out = redact_text(text, ["drivers_license"])
    assert "12345678" in out


def test_phone_number_without_dl_context_unchanged():
    # A 10-digit phone number with no label is not redacted.
    text = "Call 4155551234 for details"
    out = redact_text(text, ["drivers_license"])
    assert "4155551234" in out


def test_unrelated_text_unchanged():
    text = "The license was suspended last year"  # prose, no number
    out = redact_text(text, ["drivers_license"])
    assert out == text


# ---- Multiple licenses in one text ------------------------


def test_two_licenses_both_redacted():
    text = "Driver A DL: A1234567 and Driver B DL: B9876543"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out
    assert "B9876543" not in out
    # Both placeholders present.
    assert out.count("[REDACTED:drivers_license]") == 2


def test_three_licenses_in_sequence():
    text = "DL: 12345678\nLicense: 87654321\nLic: AB123456"
    out = redact_text(text, ["drivers_license"])
    assert "12345678" not in out
    assert "87654321" not in out
    assert "AB123456" not in out
    assert out.count("[REDACTED:drivers_license]") == 3


# ---- Coexistence with other modes ------------------------


def test_dl_and_email_both_redacted():
    text = "License: A1234567 / contact: alice@example.com"
    out = redact_text(text, ["drivers_license", "email"])
    assert "A1234567" not in out
    assert "alice@example.com" not in out
    assert "[REDACTED:drivers_license]" in out
    assert "[REDACTED:email]" in out


def test_dl_does_not_interfere_with_passport_redaction():
    text = "License: A1234567 / Passport: 999888777"
    out = redact_text(text, ["drivers_license", "passport"])
    assert "A1234567" not in out
    assert "999888777" not in out
    assert "[REDACTED:drivers_license]" in out
    assert "[REDACTED:passport]" in out


# ---- redact_fields walker -----------------------------------


def test_redact_fields_strips_dl_in_nested_dict():
    value = {
        "ocr_text": "License No: 12345678",
        "extracted": {
            "raw": "DL: A1234567",
        },
    }
    out = redact_fields(value, ["drivers_license"])
    assert "12345678" not in out["ocr_text"]
    assert "A1234567" not in out["extracted"]["raw"]


def test_redact_fields_walks_lists():
    value = {
        "ocr_lines": [
            "DL: 12345678",
            "License: AB123456",
        ]
    }
    out = redact_fields(value, ["drivers_license"])
    assert "12345678" not in out["ocr_lines"][0]
    assert "AB123456" not in out["ocr_lines"][1]


def test_redact_fields_preserves_numeric_values():
    # Non-string values pass through untouched.
    value = {"total": 12.34, "lines": [1, 2, 3], "dl": "DL: A1234567"}
    out = redact_fields(value, ["drivers_license"])
    assert out["total"] == 12.34
    assert out["lines"] == [1, 2, 3]
    assert "A1234567" not in out["dl"]


# ---- Allow-list integration ---------------------------------


def test_drivers_license_in_pii_redact_modes():
    from shotclassify_store.tenant_settings import PII_REDACT_MODES
    assert "drivers_license" in PII_REDACT_MODES


def test_drivers_license_normalises_via_redact_modes_allow_list():
    # The store-layer normalizer must accept the new mode and pass
    # it through unchanged.
    from shotclassify_store.tenant_settings import _normalize_modes
    out = _normalize_modes(["drivers_license"])
    assert out == ["drivers_license"]


# ---- Edge cases ---------------------------------------------


def test_dl_with_minimal_label():
    # DL alone (no colon) followed by space and number.
    text = "DL A1234567"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out


def test_license_lowercase_label():
    text = "license: a1234567"  # lowercased input
    out = redact_text(text, ["drivers_license"])
    # Match is case-insensitive on label AND on the candidate letters.
    assert "a1234567" not in out


def test_dl_with_many_separator_chars():
    text = "DL #: A1234567"
    out = redact_text(text, ["drivers_license"])
    assert "A1234567" not in out


def test_short_5_char_number_with_letter_accepted():
    # 1 letter + 5 digits = 6 char total -> matches A12345 form
    # (some older state licenses).
    text = "DL: A12345"
    out = redact_text(text, ["drivers_license"])
    assert "A12345" not in out


def test_too_short_4_char_rejected():
    # 4-char number is below the matcher's minimum (5 alphanum tail
    # after first letter). The matcher requires {5,13}.
    text = "DL: A123"
    out = redact_text(text, ["drivers_license"])
    # NOT redacted because the candidate doesn't match the shape.
    assert "A123" in out
