"""Tests for the ``address`` PII redaction mode.

The ``address`` mode targets one-line postal addresses that appear
on receipts ("123 Main St, Springfield, IL 62704"), signatures,
document captures of shipping labels, and chat captures of contact
cards. The matcher accepts:

* US format: NUMBER + STREET + suffix (St / Avenue / Blvd / etc.),
  optional Apt / Suite / Unit prefix, optional ", City", optional
  ", STATE ZIP" tail (5- or 5+4-digit ZIP).
* UK postcode tail in the ", City, POSTCODE" position
  (``SW1A 1AA`` / ``M1 1AE``).
* Cardinal direction prefix (``123 N Main St``).
* House-number range / split (``101-103 Oak Ave``,
  ``1/2 Pine Rd``).

The matcher is deliberately conservative -- a serious address
parser belongs in a downstream service. These tests pin the common
high-precision shapes and document the cases we accept as misses
(multi-line addresses, addresses without a street suffix).
"""
from __future__ import annotations

import pytest
from shotclassify_common.redact import redact_fields, redact_text

# -- Basic US shapes ----------------------------------------------------


def test_redacts_basic_us_street_only():
    text = "ship to 123 Main St please"
    out = redact_text(text, ["address"])
    assert "123 Main St" not in out
    assert "[REDACTED:address]" in out


def test_redacts_full_us_address():
    text = "ship to 123 Main St, Springfield, IL 62704 fast"
    out = redact_text(text, ["address"])
    assert "123 Main St" not in out
    assert "Springfield" not in out
    assert "62704" not in out
    assert "[REDACTED:address]" in out


def test_redacts_zip_plus_4():
    text = "addr 123 Main St, Springfield, IL 62704-1234 ok"
    out = redact_text(text, ["address"])
    assert "62704-1234" not in out
    assert "[REDACTED:address]" in out


@pytest.mark.parametrize(
    "suffix",
    [
        "St",
        "Street",
        "Ave",
        "Avenue",
        "Blvd",
        "Boulevard",
        "Rd",
        "Road",
        "Dr",
        "Drive",
        "Ln",
        "Lane",
        "Way",
        "Ct",
        "Court",
        "Plaza",
        "Pkwy",
        "Parkway",
        "Hwy",
        "Highway",
        "Sq",
        "Square",
        "Ter",
        "Terrace",
        "Pl",
        "Place",
        "Trail",
        "Cir",
        "Circle",
        "Loop",
        "Row",
    ],
)
def test_redacts_each_street_suffix(suffix):
    text = f"contact 456 Oak {suffix} for service"
    out = redact_text(text, ["address"])
    assert f"456 Oak {suffix}" not in out
    assert "[REDACTED:address]" in out


def test_redacts_with_trailing_period_on_suffix():
    """Abbreviated suffixes sometimes carry a period (St., Ave.)."""
    text = "live at 789 Pine St. now"
    out = redact_text(text, ["address"])
    assert "789 Pine St." not in out
    assert "[REDACTED:address]" in out


# -- Cardinal direction prefix -----------------------------------------


def test_redacts_with_cardinal_direction_n():
    text = "office 100 N Main St, Boston, MA 02101 here"
    out = redact_text(text, ["address"])
    assert "100 N Main St" not in out
    assert "[REDACTED:address]" in out


def test_redacts_with_cardinal_direction_w_period():
    text = "live 200 W. Pine Ave, Austin, TX 73301 ok"
    out = redact_text(text, ["address"])
    assert "200 W. Pine Ave" not in out
    assert "[REDACTED:address]" in out


# -- House number range / split ----------------------------------------


def test_redacts_house_number_range():
    text = "office 101-103 Oak Ave, Boston, MA 02101 cool"
    out = redact_text(text, ["address"])
    assert "101-103 Oak Ave" not in out


def test_redacts_house_number_slash():
    text = "loc 1/2 Pine Rd, London, SW1A 1AA today"
    out = redact_text(text, ["address"])
    assert "1/2 Pine Rd" not in out


# -- Apt / Suite / Unit / # --------------------------------------------


def test_redacts_with_apt_prefix():
    text = "ship 123 Main St Apt 4B today"
    out = redact_text(text, ["address"])
    assert "123 Main St Apt 4B" not in out
    assert "[REDACTED:address]" in out


def test_redacts_with_suite_prefix():
    text = "office 500 Pine Ave Suite 200 here"
    out = redact_text(text, ["address"])
    assert "500 Pine Ave Suite 200" not in out


def test_redacts_with_unit_prefix():
    text = "go 700 Oak Rd, Unit C, Boston, MA 02101 now"
    out = redact_text(text, ["address"])
    assert "700 Oak Rd, Unit C" not in out


def test_redacts_with_hash_prefix():
    text = "office 800 Elm Blvd #12 here"
    out = redact_text(text, ["address"])
    assert "800 Elm Blvd #12" not in out


# -- UK postcode tail --------------------------------------------------


def test_redacts_uk_postcode_short():
    text = "office 10 Downing St, London, SW1A 1AA today"
    out = redact_text(text, ["address"])
    assert "SW1A 1AA" not in out
    assert "[REDACTED:address]" in out


def test_redacts_uk_postcode_short_form():
    text = "live 20 Baker St, London, M1 1AE here"
    out = redact_text(text, ["address"])
    assert "M1 1AE" not in out


# -- Multi-word city / state ----------------------------------------


def test_redacts_multi_word_street_name():
    text = "live 123 Martin Luther King Blvd, Atlanta, GA 30301 today"
    out = redact_text(text, ["address"])
    assert "[REDACTED:address]" in out
    assert "Martin Luther King" not in out


def test_redacts_multi_word_city():
    text = "go 456 Elm St, San Francisco, CA 94102 fast"
    out = redact_text(text, ["address"])
    assert "[REDACTED:address]" in out
    assert "San Francisco" not in out


# -- Negative cases ----------------------------------------------------


def test_no_redact_when_mode_inactive():
    text = "live 123 Main St, Boston, MA 02101"
    out = redact_text(text, ["email"])
    assert "123 Main St" in out


def test_no_redact_when_no_address():
    text = "no addresses in this prose at all"
    out = redact_text(text, ["address"])
    assert out == text


def test_no_redact_bare_number():
    """A bare number with no street suffix is not an address."""
    text = "see line 42 in the log"
    out = redact_text(text, ["address"])
    assert out == text


def test_no_redact_phone_number():
    """``415-555-1234`` is a phone, not an address."""
    text = "call 415-555-1234 today"
    out = redact_text(text, ["address"])
    assert out == text


def test_no_redact_random_text():
    """``Hello St`` without a leading house number is not an address."""
    # The matcher requires a leading number, so "Hello St" alone fails.
    text = "say Hello St to anyone"
    out = redact_text(text, ["address"])
    assert "Hello St" in out


def test_no_redact_lowercase_street_name():
    """``123 main st`` (all lowercase street word) should not match
    -- we require a capitalised street name to avoid prose false-
    positives like ``123 second class``."""
    # The first street-name token must start with a capital. ``main``
    # lowercase fails the first-token check.
    text = "I'm at 123 main st somewhere"
    out = redact_text(text, ["address"])
    assert "123 main st" in out


# -- Field walker integration -------------------------------------------


def test_redact_fields_address_inside_dict():
    fields = {
        "name": "Alice",
        "shipping": "200 Oak Rd, Boston, MA 02108",
        "city": "Boston",
    }
    out = redact_fields(fields, ["address"])
    assert out["name"] == "Alice"
    assert "200 Oak Rd" not in out["shipping"]
    assert "[REDACTED:address]" in out["shipping"]


def test_redact_fields_address_inside_list():
    fields = ["a", "b", "ship to 123 Pine St, Boston, MA 02101"]
    out = redact_fields(fields, ["address"])
    assert out[0] == "a"
    assert out[1] == "b"
    assert "[REDACTED:address]" in out[2]


# -- Multi-mode interaction --------------------------------------------


def test_address_alongside_email():
    text = "alice@example.com lives at 123 Main St, Boston, MA 02101"
    out = redact_text(text, ["email", "address"])
    assert "alice@example.com" not in out
    assert "123 Main St" not in out
    assert "[REDACTED:email]" in out
    assert "[REDACTED:address]" in out


def test_address_doesnt_eat_phone():
    """``phone`` and ``address`` modes operate on disjoint patterns."""
    text = "call 415-555-1234 at 123 Main St"
    out = redact_text(text, ["phone", "address"])
    assert "415-555-1234" not in out
    assert "123 Main St" not in out


# -- Allow-list integration --------------------------------------------


def test_address_mode_in_allow_list():
    from shotclassify_store.tenant_settings import PII_REDACT_MODES

    assert "address" in PII_REDACT_MODES
