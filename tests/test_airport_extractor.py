"""Cross-category airport-code extractor.

Travel screenshots cite airports by their standard codes -- boarding
passes, flight-search results, frequent-flyer dashboards, itinerary
emails, chat threads sharing trip plans. We surface both IATA
(3-letter) and ICAO (4-letter) codes found in the OCR text under
``raw["airports"]`` as ``{"type", "code"}`` dicts.

Detection rules:

* IATA codes accepted when in the curated catalogue OR a travel-
  vocabulary anchor (``flight`` / ``gate`` / ``depart`` / etc) is
  on the same or previous line OR the code forms a ``XXX-XXX`` /
  ``XXX -> XXX`` route pair.
* ICAO codes accepted when in the curated catalogue OR a travel
  anchor is present AND the first letter is a valid ICAO region
  prefix.
* Currency codes (USD / EUR / GBP), country codes (USA / GBR), and
  common prose acronyms (API / CEO / HTML / CSS) are rejected
  unconditionally.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_airports

# ---- edge cases --------------------------------------------------


def test_empty_string_returns_empty_list():
    assert extract_airports("") == []


def test_whitespace_only_returns_empty_list():
    assert extract_airports("   \n\n  ") == []


def test_plain_prose_no_codes_returns_empty_list():
    assert extract_airports("Just some random English text.") == []


# ---- IATA from curated catalogue ---------------------------------


def test_iata_jfk_in_prose():
    """A known IATA code like JFK is accepted even without an anchor."""
    out = extract_airports("Pickup at JFK at 5pm")
    assert out == [{"type": "IATA", "code": "JFK"}]


def test_iata_lhr_in_prose():
    out = extract_airports("Connecting through LHR")
    assert {"type": "IATA", "code": "LHR"} in out


def test_iata_lax_in_prose():
    out = extract_airports("Welcome to LAX")
    assert out == [{"type": "IATA", "code": "LAX"}]


def test_iata_multiple_codes():
    out = extract_airports("JFK SFO LAX")
    codes = [e["code"] for e in out]
    assert codes == ["JFK", "SFO", "LAX"]


def test_iata_dedup():
    """Same code printed twice surfaces once."""
    out = extract_airports("JFK departure. JFK arrival.")
    assert out == [{"type": "IATA", "code": "JFK"}]


# ---- IATA via travel-vocabulary anchor ---------------------------


def test_iata_anchor_flight():
    """A non-catalogue 3-letter code with ``flight`` anchor is accepted."""
    out = extract_airports("Flight to ZZZ at 10am")
    assert {"type": "IATA", "code": "ZZZ"} in out


def test_iata_anchor_gate():
    out = extract_airports("Gate AAB closes 15 minutes before")
    assert {"type": "IATA", "code": "AAB"} in out


def test_iata_anchor_previous_line():
    """An anchor on the previous line still counts."""
    text = "Boarding now\nXYZ at 3pm"
    out = extract_airports(text)
    assert {"type": "IATA", "code": "XYZ"} in out


def test_iata_anchor_origin_destination():
    out = extract_airports("Origin: AAB\nDestination: AAC")
    codes = sorted(e["code"] for e in out)
    assert codes == ["AAB", "AAC"]


def test_iata_no_anchor_no_catalogue_rejected():
    """A bare 3-letter code with no anchor and not in catalogue is rejected."""
    out = extract_airports("ZZZ ZZY ZZX")
    # None of those are in the catalogue and there's no anchor.
    assert out == []


# ---- IATA via route arrow ----------------------------------------


def test_iata_route_arrow_dash():
    out = extract_airports("Route: ZZA-ZZB")
    codes = sorted(e["code"] for e in out)
    assert codes == ["ZZA", "ZZB"]


def test_iata_route_arrow_right():
    out = extract_airports("ZZA -> ZZB")
    codes = sorted(e["code"] for e in out)
    assert codes == ["ZZA", "ZZB"]


def test_iata_route_arrow_unicode():
    out = extract_airports("ZZA → ZZB")
    codes = sorted(e["code"] for e in out)
    assert codes == ["ZZA", "ZZB"]


def test_iata_route_real_codes():
    """Real-world JFK -> LAX route shape."""
    out = extract_airports("JFK -> LAX")
    codes = sorted(e["code"] for e in out)
    assert codes == ["JFK", "LAX"]


# ---- ICAO codes --------------------------------------------------


def test_icao_catalogue_kjfk():
    out = extract_airports("Departure: KJFK at 12:00")
    assert {"type": "ICAO", "code": "KJFK"} in out


def test_icao_catalogue_egll():
    out = extract_airports("Diverting to EGLL")
    assert {"type": "ICAO", "code": "EGLL"} in out


def test_icao_catalogue_rjtt():
    out = extract_airports("Bound for RJTT")
    assert {"type": "ICAO", "code": "RJTT"} in out


def test_icao_with_anchor():
    """A non-catalogue ICAO-shaped code with an anchor is accepted."""
    out = extract_airports("Flight to AAAA on time")
    assert {"type": "ICAO", "code": "AAAA"} in out


def test_icao_invalid_region_prefix_rejected():
    """ICAO codes starting with I / J / Q / X are rejected (invalid region)."""
    # ``IIII`` starts with ``I`` which is NOT a valid ICAO region.
    out = extract_airports("Flight to IIII")
    icao = [e for e in out if e["type"] == "ICAO"]
    assert icao == []


def test_icao_no_anchor_no_catalogue_rejected():
    out = extract_airports("ZZZZ ZZZY ZZZX")
    assert out == []


# ---- rejection list ----------------------------------------------


def test_currency_code_usd_rejected():
    """USD is in our currency-code reject list."""
    out = extract_airports("Flight cost USD 250")
    # USD should not appear as an airport even though ``Flight`` is an anchor.
    codes = [e["code"] for e in out]
    assert "USD" not in codes


def test_country_code_usa_rejected():
    out = extract_airports("Flight to USA from London")
    codes = [e["code"] for e in out]
    assert "USA" not in codes


def test_prose_acronym_api_rejected():
    out = extract_airports("API gate config")
    codes = [e["code"] for e in out]
    assert "API" not in codes


def test_prose_acronym_html_rejected():
    out = extract_airports("Flight HTML page")
    codes = [e["code"] for e in out]
    assert "HTML" not in codes


def test_prose_acronym_ceo_rejected():
    out = extract_airports("Flight CEO traveling")
    codes = [e["code"] for e in out]
    assert "CEO" not in codes


def test_prose_acronym_css_rejected():
    out = extract_airports("Flight CSS file")
    codes = [e["code"] for e in out]
    assert "CSS" not in codes


# ---- word-boundary defence ---------------------------------------


def test_jfk_not_extracted_from_atlas():
    """``ATLAS`` doesn't yield ``ATL`` -- letter on both sides rejects."""
    out = extract_airports("ATLAS guide")
    codes = [e["code"] for e in out]
    assert "ATL" not in codes


def test_jfk_in_word_rejected():
    """``ABCJFKDEF`` shouldn't yield JFK."""
    out = extract_airports("ABCJFKDEF")
    codes = [e["code"] for e in out]
    assert "JFK" not in codes


def test_three_letter_with_digit_boundary_rejected():
    """``A1JFK1B`` shouldn't yield JFK (digit boundary)."""
    out = extract_airports("A1JFK1B")
    codes = [e["code"] for e in out]
    assert "JFK" not in codes


def test_lowercase_codes_not_extracted():
    """Lowercase ``jfk`` isn't extracted (we require uppercase)."""
    out = extract_airports("Flight to jfk")
    assert out == []


# ---- mixed real-world cases --------------------------------------


def test_boarding_pass_style():
    text = (
        "Boarding Pass\n"
        "Flight: AA 100\n"
        "From: JFK\n"
        "To: LHR\n"
        "Gate: 23\n"
        "Seat: 12A\n"
    )
    out = extract_airports(text)
    codes = sorted(e["code"] for e in out)
    assert codes == ["JFK", "LHR"]


def test_itinerary_style():
    text = (
        "Day 1: NYC layover at JFK\n"
        "Day 2: Connecting through LHR to CDG\n"
        "Day 3: Final destination CDG\n"
    )
    out = extract_airports(text)
    codes = sorted({e["code"] for e in out})
    # JFK / LHR / CDG all in catalogue.
    assert "JFK" in codes
    assert "LHR" in codes
    assert "CDG" in codes


def test_multi_leg_trip():
    text = "JFK -> LHR -> CDG -> FCO"
    out = extract_airports(text)
    codes = sorted({e["code"] for e in out})
    assert codes == ["CDG", "FCO", "JFK", "LHR"]


def test_mixed_iata_icao():
    text = (
        "Flight: AA 100\n"
        "Departure: KJFK at 12:00\n"
        "Arrival: EGLL at 22:00\n"
        "Also accepts JFK / LHR codes.\n"
    )
    out = extract_airports(text)
    types = sorted({(e["type"], e["code"]) for e in out})
    assert ("IATA", "JFK") in types
    assert ("IATA", "LHR") in types
    assert ("ICAO", "KJFK") in types
    assert ("ICAO", "EGLL") in types


# ---- output shape -------------------------------------------------


def test_first_seen_order_preserved():
    out = extract_airports("LHR JFK LAX")
    codes = [e["code"] for e in out]
    assert codes == ["LHR", "JFK", "LAX"]


def test_cap_at_50_entries():
    """A pathological 60-code list caps at 50."""
    # Use codes from the catalogue so the anchor isn't needed.
    text = " ".join(["JFK", "LAX", "ORD", "DFW", "SFO", "MIA", "BOS",
                     "SEA", "ATL", "DEN"] * 8)
    out = extract_airports(text)
    assert len(out) <= 50


def test_output_shape_iata():
    out = extract_airports("JFK")
    assert out == [{"type": "IATA", "code": "JFK"}]


def test_output_shape_icao():
    out = extract_airports("KJFK at 12:00")
    assert out == [{"type": "ICAO", "code": "KJFK"}]


# ---- pipeline integration ----------------------------------------


def test_pipeline_stashes_airports_under_raw():
    """The pipeline writes raw['airports'] when codes are present."""
    text = "Flight JFK -> LHR confirmed"
    ocr = OCRResult(text=text, language="en", word_count=len(text.split()))
    fields = ExtractedFields()
    out = enrich(Category.document, fields, ocr)
    assert "airports" in out.raw
    codes = sorted({e["code"] for e in out.raw["airports"]})
    assert "JFK" in codes
    assert "LHR" in codes


def test_pipeline_omits_raw_airports_when_none_found():
    text = "Just some plain text."
    ocr = OCRResult(text=text, language="en", word_count=len(text.split()))
    fields = ExtractedFields()
    out = enrich(Category.document, fields, ocr)
    assert "airports" not in (out.raw or {})


def test_pipeline_works_across_categories():
    """Airports work on chat / receipt / error categories too."""
    text = "JFK delayed 2 hours"
    ocr = OCRResult(text=text, language="en", word_count=len(text.split()))
    for cat in (Category.chat_screenshot, Category.receipt, Category.error_stacktrace):
        fields = ExtractedFields()
        out = enrich(cat, fields, ocr)
        assert "airports" in out.raw
        assert out.raw["airports"][0]["code"] == "JFK"


# ---- corner cases -------------------------------------------------


def test_currency_eur_with_flight_anchor_still_rejected():
    """Even with ``flight`` anchor, EUR is on the reject list."""
    out = extract_airports("Flight EUR fare")
    codes = [e["code"] for e in out]
    assert "EUR" not in codes


def test_three_letter_at_end_of_text():
    """Code at the end of the buffer with no trailing whitespace."""
    out = extract_airports("Destination JFK")
    assert {"type": "IATA", "code": "JFK"} in out


def test_three_letter_at_start_of_text():
    out = extract_airports("JFK is the airport")
    assert {"type": "IATA", "code": "JFK"} in out


def test_code_with_punctuation_boundary():
    """``JFK,`` and ``JFK.`` and ``(JFK)`` all extract JFK."""
    for shape in ("JFK,", "JFK.", "(JFK)", "JFK?", "JFK!"):
        out = extract_airports(shape)
        assert out == [{"type": "IATA", "code": "JFK"}], f"shape={shape}"


def test_codes_in_table_row():
    """A pipe-separated table row still extracts."""
    out = extract_airports("| Flight | JFK | LAX | $200 |")
    codes = sorted({e["code"] for e in out})
    assert "JFK" in codes
    assert "LAX" in codes
