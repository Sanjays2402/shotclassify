"""VIN (Vehicle Identification Number) PII redaction mode.

A new ``vin`` redaction mode strips 17-character VIN identifiers
from OCR text. VINs appear on car titles, registrations, insurance
cards, dealer invoices, and sales contracts.

The character set is ISO 3779 restricted: digits 0-9 plus all
capital letters EXCEPT I, O, Q. The matcher requires at least one
digit AND at least one letter so pure-digit / pure-letter 17-char
runs do not misfire. Both labelled (``VIN: 1HGBH41JXMN109186``)
and bare (``1HGBH41JXMN109186`` standing alone) forms are captured.

The whole matched VIN (including the label, if present) collapses
to ``[REDACTED:vin]`` to guarantee no fragment survives.
"""
from __future__ import annotations

from shotclassify_common.redact import redact_fields, redact_text

# ---- Real-world VIN samples --------------------------------------
# Example VINs cherry-picked to satisfy the character-set rule
# (no I/O/Q) and to exercise both letter-heavy and digit-heavy
# patterns. These are dummy VINs, not real cars.


def test_bare_vin_redacted():
    text = "1HGBH41JXMN109186"
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN109186" not in out
    assert "[REDACTED:vin]" in out


def test_labelled_vin_redacted():
    text = "VIN: 1HGBH41JXMN109186"
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN109186" not in out
    assert "[REDACTED:vin]" in out


def test_vin_with_hash_label():
    text = "VIN # 1HGBH41JXMN109186"
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN109186" not in out
    assert "[REDACTED:vin]" in out


def test_vin_no_no_label():
    text = "VIN No: 1HGBH41JXMN109186"
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN109186" not in out


def test_vehicle_id_number_label():
    text = "Vehicle Identification Number: 1HGBH41JXMN109186"
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN109186" not in out


def test_chassis_no_label():
    text = "Chassis No: 1HGBH41JXMN109186"
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN109186" not in out


def test_vin_in_full_sentence():
    text = "Your VIN 1HGBH41JXMN109186 has been validated."
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN109186" not in out
    assert "[REDACTED:vin]" in out
    # Surrounding text preserved.
    assert "Your VIN" in out
    assert "has been validated" in out


# ---- Multiple VINs in same text ---------------------------------


def test_multiple_vins_all_redacted():
    text = "VIN 1: 1HGBH41JXMN109186\nVIN 2: 5YJ3E1EA4LF000316"
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN109186" not in out
    assert "5YJ3E1EA4LF000316" not in out
    assert out.count("[REDACTED:vin]") == 2


# ---- Character-set enforcement (no I/O/Q) -----------------------


def test_vin_with_letter_i_not_redacted():
    """VINs never contain the letter I (looks like 1). A 17-char
    candidate containing I must NOT be redacted as a VIN."""
    text = "1HGBH41IXMN109186"  # 'I' at position 8
    out = redact_text(text, ["vin"])
    assert "1HGBH41IXMN109186" in out


def test_vin_with_letter_o_not_redacted():
    """VINs never contain the letter O (looks like 0)."""
    text = "1HGBH41JXMNO09186"  # 'O' at position 11
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMNO09186" in out


def test_vin_with_letter_q_not_redacted():
    """VINs never contain the letter Q."""
    text = "1HGBH41JXMNQ09186"  # 'Q' at position 11
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMNQ09186" in out


# ---- Length enforcement (exactly 17) ----------------------------


def test_16_char_run_not_redacted():
    text = "1HGBH41JXMN10918"  # only 16 chars
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN10918" in out


def test_18_char_run_not_redacted():
    """An 18-char alphanumeric run must NOT be redacted because a
    valid VIN is exactly 17 chars."""
    text = "1HGBH41JXMN1091866"  # 18 chars
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN1091866" in out


def test_15_char_run_not_redacted():
    text = "1HGBH41JXMN1091"  # 15 chars
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN1091" in out


# ---- Pure-digit / pure-letter rejection -------------------------


def test_pure_digit_17_chars_not_redacted():
    """A 17-digit run (long order number / receipt ID) must NOT be
    redacted as a VIN -- the matcher requires at least one
    letter."""
    text = "12345678901234567"  # 17 digits
    out = redact_text(text, ["vin"])
    assert "12345678901234567" in out


def test_pure_letter_17_chars_not_redacted():
    """A 17-letter run (long prose acronym, code, etc.) must NOT
    be redacted as a VIN -- matcher requires at least one digit."""
    text = "ABCDEFGHJKLMNPRST"  # 17 letters, no I/O/Q
    out = redact_text(text, ["vin"])
    assert "ABCDEFGHJKLMNPRST" in out


def test_one_letter_plus_16_digits_redacted():
    """One letter + 16 digits = valid VIN shape."""
    text = "A1234567890123456"
    out = redact_text(text, ["vin"])
    assert "A1234567890123456" not in out
    assert "[REDACTED:vin]" in out


def test_one_digit_plus_16_letters_redacted():
    """One digit + 16 letters = valid VIN shape."""
    text = "ABCDEFGHJKLMNPRS1"
    out = redact_text(text, ["vin"])
    assert "ABCDEFGHJKLMNPRS1" not in out


# ---- Word-boundary defence --------------------------------------


def test_embedded_in_longer_hash_not_redacted():
    """A 17-char VIN-shaped sequence inside a longer hash must
    NOT misfire."""
    text = "hash=AB1HGBH41JXMN109186CD"
    out = redact_text(text, ["vin"])
    # The longer hash leaves no word boundary; VIN matcher rejects.
    assert "1HGBH41JXMN109186" in out


def test_vin_adjacent_to_punctuation_redacted():
    text = "(VIN: 1HGBH41JXMN109186)."
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN109186" not in out


# ---- Mode-not-active ---------------------------------------------


def test_vin_not_redacted_without_mode():
    """VIN must NOT be redacted when the vin mode is not active."""
    text = "VIN: 1HGBH41JXMN109186"
    out = redact_text(text, ["email"])  # different mode
    assert "1HGBH41JXMN109186" in out


def test_other_modes_dont_touch_vin():
    """Email mode doesn't touch a VIN-shaped run."""
    text = "VIN: 1HGBH41JXMN109186"
    out = redact_text(text, ["ssn", "phone", "credit_card"])
    assert "1HGBH41JXMN109186" in out


# ---- Real-world contexts ----------------------------------------


def test_insurance_card_block():
    text = (
        "ACME Insurance\n"
        "Policy: ABC-12345\n"
        "Insured: John Doe\n"
        "VIN: 1HGBH41JXMN109186\n"
        "Year: 2021 Make: Honda Model: Accord\n"
    )
    out = redact_text(text, ["vin"])
    assert "1HGBH41JXMN109186" not in out
    assert "[REDACTED:vin]" in out
    # Other context preserved.
    assert "Honda" in out
    assert "ACME Insurance" in out


def test_dealer_invoice_block():
    text = (
        "Tesla Dealer Invoice\n"
        "Customer: Jane Smith\n"
        "Vehicle: 2020 Model 3\n"
        "Chassis No: 5YJ3E1EA4LF000316\n"
        "Total: $42,000\n"
    )
    out = redact_text(text, ["vin"])
    assert "5YJ3E1EA4LF000316" not in out
    assert "[REDACTED:vin]" in out


def test_redact_fields_walks_nested_dict():
    """redact_fields walks nested dicts and redacts every VIN."""
    record = {
        "tenant": "acme",
        "captures": [
            {"text": "VIN: 1HGBH41JXMN109186", "id": 1},
            {"text": "Other: 5YJ3E1EA4LF000316 too", "id": 2},
        ],
        "meta": {"note": "1HGBH41JXMN109186"},
    }
    out = redact_fields(record, ["vin"])
    assert "1HGBH41JXMN109186" not in str(out)
    assert "5YJ3E1EA4LF000316" not in str(out)
    # Non-string fields preserved.
    assert out["captures"][0]["id"] == 1
    assert out["captures"][1]["id"] == 2


# ---- Negative real-world cases ----------------------------------


def test_random_alphanumeric_17_with_i_kept():
    """A random 17-char alphanumeric run that happens to contain
    I/O/Q must be left unchanged."""
    text = "ABCDEFGHIJKLMNOPQ"  # has I, O, Q
    out = redact_text(text, ["vin"])
    assert "ABCDEFGHIJKLMNOPQ" in out


def test_lowercase_17_char_run_kept():
    """VINs are uppercase by ISO convention. A lowercase 17-char
    run is treated as non-VIN."""
    text = "1hgbh41jxmn109186"  # lowercase
    out = redact_text(text, ["vin"])
    assert "1hgbh41jxmn109186" in out


def test_normal_paragraph_no_change():
    text = "This is a perfectly normal paragraph without any vehicle data."
    out = redact_text(text, ["vin"])
    assert out == text


def test_empty_text():
    out = redact_text("", ["vin"])
    assert out == ""


# ---- Compatibility with other modes -----------------------------


def test_vin_alongside_email_redaction():
    """VIN and email modes can be active together."""
    text = "Owner: a@b.com VIN: 1HGBH41JXMN109186"
    out = redact_text(text, ["email", "vin"])
    assert "a@b.com" not in out
    assert "1HGBH41JXMN109186" not in out
    assert "[REDACTED:email]" in out
    assert "[REDACTED:vin]" in out


def test_vin_alongside_ssn():
    text = "SSN: 123-45-6789 VIN: 1HGBH41JXMN109186"
    out = redact_text(text, ["ssn", "vin"])
    assert "123-45-6789" not in out
    assert "1HGBH41JXMN109186" not in out


def test_vin_in_pii_redact_modes_allowlist():
    """The new vin mode must be in the tenant settings allow-list."""
    from shotclassify_store.tenant_settings import PII_REDACT_MODES
    assert "vin" in PII_REDACT_MODES
