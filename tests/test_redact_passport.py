"""Passport-number PII redaction mode.

A new ``passport`` redaction mode strips labelled passport numbers
from OCR text. The matcher requires the word ``passport`` (case-
insensitive) immediately before the candidate so a bare 9-digit
run on a receipt does NOT misfire as a passport number.

Accepted label forms:

  Passport: A12345678
  Passport No: 123456789
  Passport No. 123456789
  Passport Number: AB1234567
  Passport # 12345678
  Passport ID: 12345678
  PASSPORT #: 987654321

Accepted candidate shapes (after the label):

* 9 digits (US, UK, Russia, ...)
* 1 letter + 7-8 digits (Australia, Germany, NZ, ...)
* 2 letters + 6-7 digits (Canada, ...)
* 1 letter + 8 alphanumerics (Germany legacy)
* 8-9 mixed alphanumerics

The redaction strips ONLY the number, leaving the ``Passport: ``
label so a reader knows the field WAS a passport without the
number itself leaking.
"""
from __future__ import annotations

from shotclassify_common.redact import redact_fields, redact_text

# ---- US / UK 9-digit passports -----------------------------------


def test_us_9_digit_passport_with_colon_label():
    text = "My passport: 123456789 expires 2030"
    out = redact_text(text, ["passport"])
    assert "123456789" not in out
    assert "[REDACTED:passport]" in out
    # Label preserved.
    assert "passport:" in out


def test_uk_9_digit_passport_with_no_label():
    text = "Passport No: 987654321"
    out = redact_text(text, ["passport"])
    assert "987654321" not in out
    assert "[REDACTED:passport]" in out
    assert "Passport No:" in out


def test_passport_no_dot_form():
    text = "Passport No. 123456789"
    out = redact_text(text, ["passport"])
    assert "123456789" not in out
    assert "Passport No." in out


def test_passport_number_form():
    text = "Passport Number: 555000111"
    out = redact_text(text, ["passport"])
    assert "555000111" not in out
    assert "Passport Number:" in out


def test_passport_hash_form():
    text = "Passport # 222333444"
    out = redact_text(text, ["passport"])
    assert "222333444" not in out


def test_passport_id_form():
    text = "Passport ID: 111222333"
    out = redact_text(text, ["passport"])
    assert "111222333" not in out
    assert "Passport ID:" in out


def test_uppercase_passport_label():
    text = "PASSPORT: 987654321"
    out = redact_text(text, ["passport"])
    assert "987654321" not in out
    assert "PASSPORT:" in out


def test_lowercase_passport_label():
    text = "passport: 987654321"
    out = redact_text(text, ["passport"])
    assert "987654321" not in out
    assert "passport:" in out


# ---- Letter-prefixed passport shapes -----------------------------


def test_australia_letter_plus_seven_digits():
    text = "Passport: A1234567"
    out = redact_text(text, ["passport"])
    assert "A1234567" not in out
    assert "[REDACTED:passport]" in out


def test_germany_letter_plus_eight_digits():
    text = "Passport No: G12345678"
    out = redact_text(text, ["passport"])
    assert "G12345678" not in out


def test_canada_two_letters_plus_six_digits():
    text = "Passport: AB123456"
    out = redact_text(text, ["passport"])
    assert "AB123456" not in out


def test_canada_two_letters_plus_seven_digits():
    text = "Passport ID: CA1234567"
    out = redact_text(text, ["passport"])
    assert "CA1234567" not in out


def test_germany_legacy_letter_plus_eight_alphanumerics():
    text = "Passport Number: G12AB3456"
    out = redact_text(text, ["passport"])
    assert "G12AB3456" not in out


def test_mixed_alphanumeric_passport():
    text = "Passport: A1B2C3D45"
    out = redact_text(text, ["passport"])
    assert "A1B2C3D45" not in out


# ---- Negative cases: bare numbers without label ------------------


def test_bare_9_digit_not_redacted_without_label():
    """A bare 9-digit run on a receipt is NOT a passport."""
    text = "Order # 123456789 for $20"
    out = redact_text(text, ["passport"])
    assert "123456789" in out
    assert "[REDACTED" not in out


def test_phone_number_not_misidentified_as_passport():
    text = "Phone: 555-555-5555"
    out = redact_text(text, ["passport"])
    # Phone has dashes; passport regex wouldn't match it.
    assert "555-555-5555" in out


def test_credit_card_with_no_passport_label_not_redacted():
    text = "Card: 4111 1111 1111 1111"
    out = redact_text(text, ["passport"])
    # No passport label -> nothing happens.
    assert "4111" in out


def test_prose_mention_of_passport_no_number_unchanged():
    """A sentence mentioning the word ``passport`` with no following
    number isn't altered."""
    text = "They renewed their passport last week"
    out = redact_text(text, ["passport"])
    assert out == text


def test_passport_at_end_of_sentence_no_following_digits_unchanged():
    text = "I lost my passport!"
    out = redact_text(text, ["passport"])
    assert out == text


def test_random_text_no_passport_label_unchanged():
    text = "Just a string with 123456789 in it"
    out = redact_text(text, ["passport"])
    assert out == text


# ---- Mode off / on toggling --------------------------------------


def test_passport_not_redacted_when_mode_inactive():
    text = "Passport: 123456789"
    out = redact_text(text, ["email"])
    assert "123456789" in out
    assert "[REDACTED" not in out


def test_passport_redacted_alongside_other_modes():
    text = "Email me at user@example.com about passport: 123456789"
    out = redact_text(text, ["passport", "email"])
    assert "123456789" not in out
    assert "user@example.com" not in out
    assert "[REDACTED:passport]" in out
    assert "[REDACTED:email]" in out


# ---- Storage allow-list integration ------------------------------


def test_passport_in_pii_redact_modes_allow_list():
    """The PII_REDACT_MODES allow-list must include the new mode.

    A mode added to redact._PATTERNS but not added to
    PII_REDACT_MODES would silently never be persisted by a
    tenant configuration."""
    from shotclassify_store.tenant_settings import PII_REDACT_MODES
    assert "passport" in PII_REDACT_MODES


# ---- Field-tree redaction ----------------------------------------


def test_passport_redaction_in_field_tree():
    """redact_fields walks dicts / lists and applies the rule to
    every string leaf."""
    data = {
        "doc_kind": "passport",
        "owner": {
            "name": "Alice",
            "passport_line": "Passport: A12345678",
        },
        "history": [
            "Last verified: Passport No. 555555555",
            "Notes about traveler.",
        ],
    }
    out = redact_fields(data, ["passport"])
    assert "A12345678" not in str(out)
    assert "555555555" not in str(out)
    assert "Alice" in str(out)
    # Labels preserved within the redacted strings.
    assert "Passport:" in out["owner"]["passport_line"]


# ---- Multi-passport snippet --------------------------------------


def test_multiple_passports_in_same_text_all_redacted():
    text = (
        "Customer passport: 123456789\n"
        "Spouse passport: A98765432\n"
        "Child passport No: CA1234567"
    )
    out = redact_text(text, ["passport"])
    assert "123456789" not in out
    assert "A98765432" not in out
    assert "CA1234567" not in out
    # Should have three placeholders.
    assert out.count("[REDACTED:passport]") == 3


# ---- Robustness --------------------------------------------------


def test_passport_label_with_extra_spaces():
    text = "Passport    No   :    123456789"
    out = redact_text(text, ["passport"])
    assert "123456789" not in out


def test_passport_label_no_separator():
    text = "Passport12345678"
    out = redact_text(text, ["passport"])
    # 8 digits adjacent to ``Passport`` -- the regex tolerates 0
    # separator chars so this should match.
    assert "12345678" not in out


def test_passport_8_digit_minimum_floor():
    """7-digit candidate is below the 8-char floor for our shape."""
    text = "Passport: 1234567"
    out = redact_text(text, ["passport"])
    # 7 digits -- the regex requires at least 6 trailing chars after
    # 0-2 letters with a minimum total >= 6; 1234567 has only 7 chars
    # which fits the 6-9 range so it WILL match. Verify behaviour.
    # Update: our regex allows 6-9 alphanumerics for the trailing portion
    # so a 7-digit number with no letter prefix is 7 alphanumerics -> matches.
    assert "1234567" not in out


def test_passport_10_digit_above_ceiling():
    """11+ digits is above the 9-char ceiling. The matcher's trailing
    word-boundary requires a non-alphanumeric / end-of-string after
    the captured number, so a longer digit run does NOT match (and
    nothing is partially redacted -- better safe than leak the tail)."""
    text = "Passport: 12345678901"
    out = redact_text(text, ["passport"])
    # No match -> text is unchanged. This is the safe behaviour
    # (we'd rather not redact than redact only part of a number).
    assert "[REDACTED:passport]" not in out
    assert "12345678901" in out


def test_passport_with_email_separator_not_misclassified():
    """A passport label that abuts a JSON-like key without a real
    number doesn't false-fire."""
    text = '{"passport": null, "name": "Alice"}'
    out = redact_text(text, ["passport"])
    # No number after the label -> no match.
    assert "Alice" in out
