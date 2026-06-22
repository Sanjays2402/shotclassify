"""Cross-category postal-code extractor (raw["postal_codes"]).

The extractor recognises postal codes from 10 countries (US / UK /
CA / DE / FR / NL / AU / JP / IN / BR) and produces a typed list
of ``{"country", "code"}`` dicts.

Anchored shapes (US, DE, FR, AU, IN) require a same-line country /
state / city anchor; self-anchored shapes (UK, CA, JP, BR, NL)
fire on the format alone.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_postal_codes

# ---- US ZIP --------------------------------------------------------


def test_us_zip_5_digit_with_state_anchor():
    out = extract_postal_codes("San Francisco, CA 94103")
    assert {"country": "US", "code": "94103"} in out


def test_us_zip_5plus4_with_state_anchor():
    out = extract_postal_codes("Manhattan, NY 10001-1234")
    assert {"country": "US", "code": "10001-1234"} in out


def test_us_zip_state_after_zip():
    """Some lines print ``94103 CA`` (less common but valid)."""
    out = extract_postal_codes("Address: 94103 CA")
    assert {"country": "US", "code": "94103"} in out


def test_us_zip_rejected_without_state_anchor():
    """A bare 5-digit run with no US state on the line is dropped."""
    out = extract_postal_codes("Random number 94103 in middle")
    # The "in" doesn't match a US state, so US ZIP rejected.
    assert all(e["country"] != "US" for e in out)


def test_us_state_anchor_must_be_real_state():
    """``ZZ 12345`` shouldn't fire because ZZ isn't a real state."""
    out = extract_postal_codes("Made up state ZZ 12345")
    assert all(e["country"] != "US" for e in out)


def test_us_zip_all_states_accepted():
    """A representative sample of US states should each anchor a ZIP."""
    for state in ("CA", "NY", "TX", "FL", "WA", "DC", "HI", "AK"):
        out = extract_postal_codes(f"City, {state} 12345")
        assert any(e["country"] == "US" for e in out), state


# ---- UK postcode --------------------------------------------------


def test_uk_postcode_canonical():
    out = extract_postal_codes("London SW1A 1AA")
    assert {"country": "GB", "code": "SW1A 1AA"} in out


def test_uk_postcode_short_form():
    out = extract_postal_codes("Manchester M1 1AE")
    assert {"country": "GB", "code": "M1 1AE"} in out


def test_uk_postcode_no_space_normalised():
    """``SW1A1AA`` (no space) -> output ``SW1A 1AA`` (canonical with space)."""
    out = extract_postal_codes("postcode SW1A1AA today")
    assert {"country": "GB", "code": "SW1A 1AA"} in out


def test_uk_postcode_birmingham_form():
    out = extract_postal_codes("ship to B33 8TH")
    assert {"country": "GB", "code": "B33 8TH"} in out


def test_uk_postcode_ec_form():
    out = extract_postal_codes("EC1A 1BB London")
    assert {"country": "GB", "code": "EC1A 1BB"} in out


def test_uk_postcode_self_anchored_no_extra_keyword():
    """The UK shape is unique enough; no anchor required."""
    out = extract_postal_codes("CR2 6XH")
    assert any(e["country"] == "GB" for e in out)


# ---- Canadian postcode --------------------------------------------


def test_ca_postcode_canonical():
    out = extract_postal_codes("Toronto K1A 0B1")
    assert {"country": "CA", "code": "K1A 0B1"} in out


def test_ca_postcode_no_space_normalised():
    """``M5V3L9`` -> ``M5V 3L9`` (space inserted)."""
    out = extract_postal_codes("ship to M5V3L9")
    assert {"country": "CA", "code": "M5V 3L9"} in out


def test_ca_postcode_dash_normalised():
    """``K1A-0B1`` -> ``K1A 0B1`` (dash converted to space)."""
    out = extract_postal_codes("postal K1A-0B1 north")
    assert {"country": "CA", "code": "K1A 0B1"} in out


def test_ca_postcode_lowercase_input():
    """Lowercase Canadian postcode input is canonicalised to upper."""
    out = extract_postal_codes("postal m5v 3l9 today")
    assert {"country": "CA", "code": "M5V 3L9"} in out


def test_ca_postcode_invalid_first_letter_rejected():
    """Canadian postcodes never start with D / F / I / O / Q / U."""
    out = extract_postal_codes("ship to D1A 0B1")  # D not allowed
    assert all(e["country"] != "CA" for e in out)


# ---- German PLZ ---------------------------------------------------


def test_de_plz_with_country_anchor():
    out = extract_postal_codes("Berlin, Deutschland 10115")
    assert {"country": "DE", "code": "10115"} in out


def test_de_plz_with_germany_anchor():
    out = extract_postal_codes("10115 Berlin, Germany")
    assert {"country": "DE", "code": "10115"} in out


def test_de_plz_with_city_anchor():
    out = extract_postal_codes("80331 Munich, Bavaria")
    assert {"country": "DE", "code": "80331"} in out


def test_de_plz_with_label():
    out = extract_postal_codes("PLZ 10115 Berlin")
    assert {"country": "DE", "code": "10115"} in out


def test_de_plz_rejected_without_anchor():
    """A bare 5-digit run with no German anchor doesn't fire."""
    out = extract_postal_codes("random 80331 number")
    assert all(e["country"] != "DE" for e in out)


# ---- French CP ----------------------------------------------------


def test_fr_cp_with_country_anchor():
    out = extract_postal_codes("Paris, France 75001")
    assert {"country": "FR", "code": "75001"} in out


def test_fr_cp_with_city_anchor():
    out = extract_postal_codes("Marseille 13001")
    assert {"country": "FR", "code": "13001"} in out


def test_fr_cp_rejected_when_departement_is_zero():
    """``00xxx`` is not a real French CP (departement 0 doesn't exist)."""
    out = extract_postal_codes("Paris, France 00123")
    assert all(e["country"] != "FR" for e in out)


def test_fr_cp_rejected_without_anchor():
    out = extract_postal_codes("number 75001 isolated")
    assert all(e["country"] != "FR" for e in out)


# ---- Netherlands postcode -----------------------------------------


def test_nl_postcode_canonical():
    out = extract_postal_codes("Amsterdam 1011 AB")
    assert {"country": "NL", "code": "1011 AB"} in out


def test_nl_postcode_no_space_normalised():
    """``1011AB`` -> ``1011 AB``."""
    out = extract_postal_codes("postal 1011AB")
    assert {"country": "NL", "code": "1011 AB"} in out


# ---- Australian postcode ------------------------------------------


def test_au_postcode_with_state_anchor():
    out = extract_postal_codes("Sydney NSW 2000")
    assert {"country": "AU", "code": "2000"} in out


def test_au_postcode_with_country_anchor():
    out = extract_postal_codes("3000 Melbourne, Australia")
    assert {"country": "AU", "code": "3000"} in out


def test_au_postcode_all_states():
    for state in ("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"):
        out = extract_postal_codes(f"City {state} 4000")
        assert any(e["country"] == "AU" for e in out), state


def test_au_postcode_rejected_without_anchor():
    out = extract_postal_codes("4000 isolated")
    assert all(e["country"] != "AU" for e in out)


# ---- Japanese postal code -----------------------------------------


def test_jp_postcode_canonical():
    out = extract_postal_codes("Tokyo 100-0001")
    assert {"country": "JP", "code": "100-0001"} in out


def test_jp_postcode_self_anchored():
    out = extract_postal_codes("123-4567")
    assert {"country": "JP", "code": "123-4567"} in out


# ---- Indian PIN ---------------------------------------------------


def test_in_pin_with_country_anchor():
    out = extract_postal_codes("Delhi, India 110001")
    assert {"country": "IN", "code": "110001"} in out


def test_in_pin_with_label():
    out = extract_postal_codes("PIN 110001")
    assert {"country": "IN", "code": "110001"} in out


def test_in_pin_with_city_anchor():
    out = extract_postal_codes("Mumbai 400001")
    assert {"country": "IN", "code": "400001"} in out


def test_in_pin_rejected_without_anchor():
    out = extract_postal_codes("110001 isolated number")
    assert all(e["country"] != "IN" for e in out)


# ---- Brazilian CEP -----------------------------------------------


def test_br_cep_canonical():
    out = extract_postal_codes("São Paulo 01310-100")
    assert {"country": "BR", "code": "01310-100"} in out


def test_br_cep_self_anchored():
    out = extract_postal_codes("CEP 20000-000")
    assert {"country": "BR", "code": "20000-000"} in out


# ---- de-dupe / order / cap ---------------------------------------


def test_dedup_same_country_and_code():
    out = extract_postal_codes("ship to SW1A 1AA from SW1A 1AA")
    uk_entries = [e for e in out if e["country"] == "GB"]
    assert len(uk_entries) == 1


def test_distinct_codes_kept_separate():
    text = "London SW1A 1AA\nManchester M1 1AE\nBirmingham B33 8TH"
    out = extract_postal_codes(text)
    codes = sorted(e["code"] for e in out if e["country"] == "GB")
    assert codes == ["B33 8TH", "M1 1AE", "SW1A 1AA"]


def test_multi_country_mixed():
    text = (
        "London SW1A 1AA\n"
        "Toronto K1A 0B1\n"
        "San Francisco, CA 94103\n"
        "Berlin, Germany 10115\n"
        "Tokyo 100-0001\n"
    )
    out = extract_postal_codes(text)
    countries = {e["country"] for e in out}
    assert countries == {"GB", "CA", "US", "DE", "JP"}


def test_cap_at_50_entries():
    # 60 distinct UK postcodes -- cap should kick in at 50.
    lines = [f"PR{i} 1AA" for i in range(1, 61)]
    text = "\n".join(lines)
    out = extract_postal_codes(text)
    assert len(out) == 50


# ---- edge / rejection cases --------------------------------------


def test_empty_input():
    assert extract_postal_codes("") == []
    assert extract_postal_codes(None) == []  # type: ignore[arg-type]


def test_inside_longer_digit_run_not_matched():
    """A 9-digit phone number must not pull a US ZIP out of its middle."""
    out = extract_postal_codes("phone 5551234567 CA call")
    # The US matcher requires word-boundary on both sides; the
    # 10-digit phone is bounded, so the embedded 5-digit run is not
    # extracted.
    assert all(e["country"] != "US" for e in out)


def test_versions_not_matched_as_postcode():
    """``v1.10`` / ``2.3.4`` shouldn't pull postal codes."""
    out = extract_postal_codes("ship v1.10.100 to user")
    # No US state on the line, so US matcher rejects; other matchers
    # need stronger shape constraints that 10.100 doesn't satisfy.
    assert all(e["country"] != "US" for e in out)


def test_pipeline_populates_raw_postal_codes():
    ocr = OCRResult(
        text="Sender: 123 Main St, San Francisco, CA 94103\nReceiver: London SW1A 1AA",
        word_count=15,
    )
    fields = ExtractedFields()
    out = enrich(Category.other, fields, ocr)
    assert "postal_codes" in (out.raw or {})
    entries = out.raw["postal_codes"]
    assert {"country": "US", "code": "94103"} in entries
    assert {"country": "GB", "code": "SW1A 1AA"} in entries


def test_pipeline_skips_when_no_postal_codes():
    ocr = OCRResult(text="just some text no addresses here", word_count=6)
    fields = ExtractedFields()
    out = enrich(Category.other, fields, ocr)
    assert "postal_codes" not in (out.raw or {})
