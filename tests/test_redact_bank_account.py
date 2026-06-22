"""PII redact: ``bank_account`` mode (US bank routing + account numbers).

The new ``bank_account`` mode captures routing / ABA / RTN
numbers (9 digits) and account / acct / a/c numbers (6-17 digits)
when prefixed with a recognised label. Bare digit runs WITHOUT
a label are intentionally LEFT UNCHANGED to avoid false-positives
on phone numbers / order numbers / SSNs.
"""
from __future__ import annotations

from shotclassify_common.redact import redact_fields, redact_text
from shotclassify_store.tenant_settings import PII_REDACT_MODES

# ---- routing-number variants ----------------------------------


def test_routing_label_basic():
    out = redact_text("Routing: 123456789", ["bank_account"])
    assert out == "Routing: [REDACTED:bank_account]"


def test_routing_no_label():
    out = redact_text("Routing 121000358", ["bank_account"])
    assert out == "Routing [REDACTED:bank_account]"


def test_routing_number_label():
    out = redact_text("Routing Number: 011000028", ["bank_account"])
    assert out == "Routing Number: [REDACTED:bank_account]"


def test_routing_no_dot_label():
    out = redact_text("Routing No. 121000358", ["bank_account"])
    assert out == "Routing No. [REDACTED:bank_account]"


def test_routing_hash_label():
    out = redact_text("Routing #121000358", ["bank_account"])
    assert "[REDACTED:bank_account]" in out
    assert "121000358" not in out


def test_aba_label():
    out = redact_text("ABA: 011000028", ["bank_account"])
    assert out == "ABA: [REDACTED:bank_account]"


def test_aba_routing_label():
    out = redact_text("ABA Routing: 011000028", ["bank_account"])
    assert "[REDACTED:bank_account]" in out


def test_aba_routing_hash():
    out = redact_text("ABA Routing #: 011000028", ["bank_account"])
    assert "[REDACTED:bank_account]" in out


def test_rtn_label():
    out = redact_text("RTN 121000358", ["bank_account"])
    assert "[REDACTED:bank_account]" in out


def test_case_insensitive_routing():
    """``ROUTING`` / ``routing`` / ``Routing`` all work."""
    for label in ("ROUTING", "routing", "Routing"):
        out = redact_text(f"{label}: 121000358", ["bank_account"])
        assert "[REDACTED:bank_account]" in out


# ---- account-number variants ----------------------------------


def test_account_label_basic():
    out = redact_text("Account: 987654321", ["bank_account"])
    assert out == "Account: [REDACTED:bank_account]"


def test_account_no_label():
    out = redact_text("Account No: 12345678", ["bank_account"])
    assert out == "Account No: [REDACTED:bank_account]"


def test_account_no_dot_label():
    out = redact_text("Account No. 12345678", ["bank_account"])
    assert out == "Account No. [REDACTED:bank_account]"


def test_account_number_label():
    out = redact_text("Account Number: 12345678901", ["bank_account"])
    assert out == "Account Number: [REDACTED:bank_account]"


def test_acct_label():
    out = redact_text("Acct: 12345678", ["bank_account"])
    assert out == "Acct: [REDACTED:bank_account]"


def test_acct_no_label():
    out = redact_text("Acct No. 12345678", ["bank_account"])
    assert "[REDACTED:bank_account]" in out


def test_a_c_label():
    """``A/C`` slash form (common on UK/international statements)."""
    out = redact_text("A/C: 987654321", ["bank_account"])
    assert "[REDACTED:bank_account]" in out


def test_a_c_no_label():
    out = redact_text("A/C No: 12345678", ["bank_account"])
    assert "[REDACTED:bank_account]" in out


def test_account_hash_label():
    out = redact_text("Account #987654321", ["bank_account"])
    assert "[REDACTED:bank_account]" in out


def test_case_insensitive_account():
    for label in ("ACCOUNT", "account", "Account"):
        out = redact_text(f"{label}: 12345678", ["bank_account"])
        assert "[REDACTED:bank_account]" in out


# ---- account length boundaries --------------------------------


def test_account_6_digit_min():
    """Minimum 6-digit account accepted (savings suffix forms)."""
    out = redact_text("Account: 123456", ["bank_account"])
    assert "[REDACTED:bank_account]" in out


def test_account_17_digit_max():
    """Maximum 17-digit account accepted (large business accounts)."""
    out = redact_text("Account: 12345678901234567", ["bank_account"])
    assert "[REDACTED:bank_account]" in out


def test_account_5_digit_too_short():
    """5-digit run is too short to be an account number."""
    out = redact_text("Account: 12345", ["bank_account"])
    assert out == "Account: 12345"


def test_account_18_digit_too_long():
    """18+ digits: regex word-boundary fails so NO redaction fires.

    This is a safety property -- better to leave the number unchanged
    than to partially redact it (a 17-of-18 redaction leaks the
    trailing digit, which is exactly the wrong direction for a
    privacy mode). The matcher's trailing ``\\b`` boundary refuses
    to match when the captured 17-digit span sits next to another
    digit.
    """
    out = redact_text("Account: 123456789012345678", ["bank_account"])
    # NO redaction expected -- the 18-digit run is left unchanged.
    assert out == "Account: 123456789012345678"


# ---- paired routing + account ---------------------------------


def test_paired_routing_account_one_line():
    out = redact_text(
        "Routing # 121000358 Account # 987654321", ["bank_account"]
    )
    # Both numbers must be redacted; both labels must remain.
    assert "Routing # [REDACTED:bank_account]" in out
    assert "Account # [REDACTED:bank_account]" in out
    assert "121000358" not in out
    assert "987654321" not in out


def test_paired_routing_account_two_lines():
    out = redact_text(
        "Routing: 121000358\nAccount: 987654321", ["bank_account"]
    )
    assert "Routing: [REDACTED:bank_account]" in out
    assert "Account: [REDACTED:bank_account]" in out


# ---- false-positive defences -----------------------------------


def test_bare_9_digit_run_left_unchanged():
    """A bare ``123456789`` without label is NOT redacted."""
    out = redact_text("123456789", ["bank_account"])
    assert out == "123456789"


def test_phone_number_left_unchanged():
    out = redact_text("Phone: 1234567890", ["bank_account"])
    assert out == "Phone: 1234567890"


def test_ssn_left_unchanged():
    """SSN-shape doesn't match because of the dashes (\\d{6,17} requires
    contiguous digits)."""
    out = redact_text("SSN: 123-45-6789", ["bank_account"])
    assert out == "SSN: 123-45-6789"


def test_order_number_left_unchanged():
    """A ``Order #12345678`` doesn't false-positive (``order`` not in vocab)."""
    out = redact_text("Order #12345678", ["bank_account"])
    assert out == "Order #12345678"


def test_invoice_number_left_unchanged():
    out = redact_text("Invoice: 12345678", ["bank_account"])
    assert out == "Invoice: 12345678"


def test_random_text_with_digits_left_unchanged():
    out = redact_text("Lorem ipsum 123456789 dolor", ["bank_account"])
    assert out == "Lorem ipsum 123456789 dolor"


def test_account_with_letter_prefix_rejected():
    """``Account: A12345678`` -- the regex requires pure digits."""
    out = redact_text("Account: A12345678", ["bank_account"])
    assert out == "Account: A12345678"


# ---- substitution preserves label -----------------------------


def test_label_preserved_in_substitution():
    """The ``Routing: `` / ``Account: `` label MUST survive redaction
    so a reader knows the field was banking data without the number."""
    out = redact_text("Routing: 121000358", ["bank_account"])
    assert out.startswith("Routing:")
    assert "[REDACTED:bank_account]" in out


def test_label_preserved_with_hash_separator():
    out = redact_text("Routing #121000358", ["bank_account"])
    assert "Routing" in out
    assert "121000358" not in out


def test_label_preserved_with_period_separator():
    out = redact_text("Routing No. 121000358", ["bank_account"])
    assert "Routing No." in out
    assert "121000358" not in out


# ---- mode allow-list ------------------------------------------


def test_bank_account_in_allowlist():
    """The mode is wired into the tenant-settings allow-list."""
    assert "bank_account" in PII_REDACT_MODES


def test_mode_only_active_when_selected():
    """Without ``bank_account`` in the modes list, nothing fires."""
    out = redact_text("Routing: 121000358", ["email"])
    assert out == "Routing: 121000358"


def test_no_modes_returns_unchanged():
    out = redact_text("Routing: 121000358", None)
    assert out == "Routing: 121000358"


def test_multi_mode_with_bank():
    """Combining bank_account with other modes works."""
    text = "Routing: 121000358 Phone: +1-555-123-4567"
    out = redact_text(text, ["bank_account", "phone"])
    assert "[REDACTED:bank_account]" in out
    assert "[REDACTED:phone]" in out


# ---- redact_fields recursive --------------------------------


def test_redact_fields_on_dict():
    data = {
        "bank_info": "Routing: 121000358",
        "name": "Alice",
    }
    out = redact_fields(data, ["bank_account"])
    assert "[REDACTED:bank_account]" in out["bank_info"]
    assert out["name"] == "Alice"


def test_redact_fields_on_nested_list():
    data = [
        {"label": "Routing: 121000358"},
        {"label": "Account: 987654321"},
    ]
    out = redact_fields(data, ["bank_account"])
    assert "[REDACTED:bank_account]" in out[0]["label"]
    assert "[REDACTED:bank_account]" in out[1]["label"]


# ---- realistic transcript / receipt mix -----------------------


def test_check_micr_like_block():
    """A realistic check-bottom MICR encoding block."""
    text = (
        "Pay To The Order Of: Alice\n"
        "Routing Number: 121000358\n"
        "Account Number: 987654321012\n"
        "Check #: 1234\n"
    )
    out = redact_text(text, ["bank_account"])
    assert "Routing Number: [REDACTED:bank_account]" in out
    assert "Account Number: [REDACTED:bank_account]" in out
    assert "Check #: 1234" in out  # check# not in vocab -> preserved
    assert "Alice" in out


def test_ach_transfer_setup_form():
    text = (
        "Bank Transfer Setup\n"
        "ABA Routing #: 011000028\n"
        "Account: 9876543210987\n"
        "Account Type: Checking\n"
    )
    out = redact_text(text, ["bank_account"])
    assert "[REDACTED:bank_account]" in out
    assert "011000028" not in out
    assert "9876543210987" not in out
    assert "Account Type: Checking" in out


def test_uk_a_c_form_with_routing():
    text = "Sort Code: 12-34-56  A/C: 12345678"
    out = redact_text(text, ["bank_account"])
    # A/C: 12345678 should redact; sort code stays (not in vocab)
    assert "[REDACTED:bank_account]" in out
    assert "12-34-56" in out


# ---- digit boundary protection -------------------------------


def test_no_partial_redaction_when_label_followed_by_letters():
    """``Account: ABC123`` (letter+digit) -- regex requires pure digit
    body so this is left unchanged."""
    out = redact_text("Account: ABC1234567", ["bank_account"])
    assert out == "Account: ABC1234567"


def test_word_boundary_after_number():
    """Trailing word-boundary requirement: ``Account: 12345678abc``
    doesn't match because ``\\b`` between ``8`` and ``a`` is absent."""
    out = redact_text("Account: 12345678abc", ["bank_account"])
    assert out == "Account: 12345678abc"
