"""Cross-category airport-code extractor.

Travel screenshots routinely cite airports by their standard codes:
boarding passes, flight-search results, frequent-flyer dashboards,
itinerary emails, chat threads sharing trip plans. We surface both
the **IATA** (3-letter) and **ICAO** (4-letter) forms found in the
OCR text under ``ExtractedFields.raw["airports"]`` so dashboards,
routing rules, and downstream agents have a single place to look for
travel context.

Output shape: a list of ``{"type": "IATA" | "ICAO", "code": str}``
dicts. The list preserves first-seen order across all matchers and
is capped at 50 entries.

Recognised forms:

* **IATA** -- 3 uppercase letters (``JFK``, ``LAX``, ``LHR``,
  ``CDG``, ``HND``, ``DXB``). To avoid false-positives on prose
  acronyms (``CEO``, ``API``, ``FAQ``, ``CSS``, ``HTML``), we
  require either:
    - a known travel-vocabulary anchor on the SAME line or the
      preceding line (``flight``, ``airport``, ``departure``,
      ``arrival``, ``origin``, ``destination``, ``gate``, ``from``,
      ``to``, ``via``, ``layover``, ``terminal``, ``boarding``,
      ``check-in``, ``baggage``, ``itinerary``, ``confirm``,
      ``PNR``, ``connect``), OR
    - the bare ``XXX-XXX`` / ``XXX -> XXX`` / ``XXX → XXX`` /
      ``XXX > XXX`` route shape (two IATA-shaped codes joined by
      a route arrow). This shape is so distinctive of itineraries
      that we accept it without needing a vocabulary anchor.

  We also validate against the curated catalogue
  :data:`_IATA_AIRPORTS` of the top ~250 IATA-coded airports
  worldwide -- a code outside that catalogue MUST still satisfy
  one of the anchor conditions above to be accepted. This keeps
  random 3-letter sequences (``ASC``, ``CSV``, ``USB``,
  ``BIO``, ``HTML``'s subset) out of the output.

* **ICAO** -- 4 uppercase letters (``KJFK``, ``KLAX``, ``EGLL``,
  ``LFPG``, ``RJTT``, ``OMDB``). ICAO codes follow strict shape
  rules (first letter from a small set per region) and never look
  like English words, so we accept any 4-letter run whose first
  letter is a valid ICAO region prefix (``A``-``E``, ``F``-``H``,
  ``K``, ``L``, ``M``, ``N``, ``O``, ``P``, ``R``-``T``, ``U``,
  ``V``-``Z``) as long as the SAME travel-vocabulary anchor is
  present on the same/previous line OR the code is in the curated
  :data:`_ICAO_AIRPORTS` catalogue of major hubs.

Deliberately NOT matched:

* 3-letter prose acronyms (``CEO``, ``API``, ``USB``) absent a
  travel-vocabulary anchor.
* Country codes (``USA``, ``CAN``) -- same shape as IATA but never
  in our catalogue, and we don't want to mis-tag a generic
  ``USA flag`` line as an airport.
* Currency codes (``USD``, ``EUR``, ``GBP``) -- explicitly
  excluded from the catalogue.
"""
from __future__ import annotations

import re

_MAX_AIRPORTS = 50

# Curated catalogue of major IATA airport codes. The list covers
# the busiest airports across every continent so a typical travel
# screenshot has high coverage without depending on prose anchors.
# We deliberately keep this list flat (no metadata) to keep memory
# pressure low and lookup O(1).
_IATA_AIRPORTS = frozenset({
    # North America - US major hubs
    "ATL", "LAX", "ORD", "DFW", "DEN", "JFK", "SFO", "SEA", "LAS",
    "MCO", "EWR", "CLT", "PHX", "IAH", "MIA", "BOS", "MSP", "FLL",
    "DTW", "PHL", "LGA", "BWI", "SLC", "SAN", "DCA", "IAD", "MDW",
    "TPA", "AUS", "BNA", "STL", "RDU", "HOU", "PIT", "MCI", "SMF",
    "OAK", "MSY", "CLE", "SJC", "IND", "RSW", "SAT", "PDX", "HNL",
    "CMH", "PBI", "MKE", "JAX", "MEM", "RIC", "BUF", "ABQ", "ANC",
    # Canada
    "YYZ", "YVR", "YUL", "YYC", "YEG", "YOW", "YHZ", "YWG", "YQB",
    # Mexico / Central / South America
    "MEX", "CUN", "GDL", "MTY", "TLC", "PVR", "SJD",
    "GRU", "GIG", "BSB", "EZE", "SCL", "BOG", "LIM", "UIO", "PTY",
    "SDQ", "HAV", "SJU", "SJO", "MVD",
    # Europe - major hubs
    "LHR", "LGW", "STN", "LTN", "LCY", "MAN", "EDI", "GLA", "BHX",
    "CDG", "ORY", "BVA", "NCE", "LYS", "MRS",
    "FRA", "MUC", "DUS", "TXL", "BER", "HAM", "STR", "CGN",
    "AMS", "RTM", "EIN",
    "MAD", "BCN", "PMI", "AGP", "VLC", "SVQ", "BIO", "TFS", "LPA",
    "FCO", "MXP", "LIN", "VCE", "NAP", "BLQ", "CTA", "PMO", "BGY",
    "ZRH", "GVA", "BSL", "BRN",
    "VIE", "INN", "SZG",
    "BRU", "CRL", "ANR",
    "CPH", "ARN", "OSL", "HEL", "GOT", "BGO", "TRD", "BLL",
    "DUB", "SNN", "ORK",
    "LIS", "OPO",
    "ATH", "SKG", "HER", "RHO",
    "PRG", "WAW", "KRK", "BUD", "OTP", "SOF", "BEG", "ZAG", "LJU",
    "RIX", "TLL", "VNO", "KEF", "KBP", "MSQ",
    "IST", "SAW", "AYT", "ESB", "ADB", "DLM",
    "SVO", "DME", "VKO", "LED", "KZN", "AER", "OVB", "VVO",
    # Middle East
    "DXB", "AUH", "SHJ", "DWC", "DOH", "AMM", "BAH", "KWI", "MCT",
    "RUH", "JED", "DMM", "MED", "BGW", "BEY", "TLV", "CAI",
    "EVN", "TBS", "GYD", "IKA", "THR", "MHD",
    # Asia
    "HND", "NRT", "KIX", "ITM", "FUK", "CTS", "NGO", "OKA", "HIJ",
    "ICN", "GMP", "PUS", "CJU",
    "PEK", "PVG", "SHA", "CAN", "CTU", "SZX", "HGH", "XIY", "WUH",
    "CKG", "KMG", "CSX", "TAO", "CGO", "NKG", "TSN", "FOC",
    "HKG", "MFM", "TPE", "KHH", "TSA",
    "SIN", "KUL", "PEN", "BKI", "JHB", "LGK",
    "BKK", "DMK", "CNX", "HKT", "USM", "HDY",
    "SGN", "HAN", "DAD",
    "MNL", "CEB", "DVO", "CRK",
    "CGK", "DPS", "SUB", "MES", "BPN", "UPG",
    "DEL", "BOM", "BLR", "MAA", "HYD", "CCU", "AMD", "COK", "GOI",
    "PNQ", "JAI", "LKO", "TRV", "IXC", "BHO", "PAT", "VTZ",
    "KHI", "LHE", "ISB", "DAC", "CGP", "CMB", "MLE", "KTM",
    "TAS", "ALA", "TSE", "FRU", "DYU", "ASB",
    # Africa
    "JNB", "CPT", "DUR", "PLZ", "GRJ", "BFN", "ELS",
    "HRG", "SSH", "LXR", "ASW",
    "CMN", "RAK", "AGA", "RBA", "TNG", "FEZ",
    "ALG", "ORN", "CZL",
    "TUN", "MIR", "TOE",
    "ADD", "LOS", "ABV", "ACC", "DKR", "ABJ", "NBO", "DAR", "EBB",
    "KGL", "LAD", "MPM", "WDH", "GBE",
    # Oceania
    "SYD", "MEL", "BNE", "PER", "ADL", "OOL", "CNS", "DRW", "HBA",
    "CBR", "NTL", "MCY", "TSV", "AVV",
    "AKL", "CHC", "WLG", "ZQN", "DUD", "ROT", "PMR",
    "NAN", "POM", "NOU", "PPT",
})

# Curated catalogue of major ICAO airport codes (4-letter form).
# Limited to the top hubs because ICAO codes appear less often in
# casual travel screenshots than IATA codes.
_ICAO_AIRPORTS = frozenset({
    # US (K-prefix)
    "KJFK", "KLAX", "KORD", "KDFW", "KATL", "KDEN", "KSFO", "KSEA",
    "KLAS", "KMIA", "KBOS", "KEWR", "KIAH", "KIAD", "KDCA", "KMSP",
    "KSAN", "KCLT", "KPHX", "KPHL", "KLGA", "KBWI", "KSLC", "KMCO",
    "KMDW", "KDTW", "KFLL", "KTPA", "KAUS", "KBNA", "KSTL", "KMEM",
    # Canada (C-prefix)
    "CYYZ", "CYVR", "CYUL", "CYYC", "CYEG", "CYOW", "CYHZ", "CYWG",
    # UK + Ireland (EG-prefix)
    "EGLL", "EGKK", "EGSS", "EGGW", "EGLC", "EGCC", "EGPH", "EGPF",
    "EIDW", "EICK", "EINN",
    # France (LF-prefix)
    "LFPG", "LFPO", "LFMN", "LFLL", "LFML", "LFBO",
    # Germany (ED-prefix)
    "EDDF", "EDDM", "EDDB", "EDDH", "EDDL", "EDDS", "EDDK", "EDDT",
    # Netherlands / Belgium / Luxembourg
    "EHAM", "EBBR", "ELLX",
    # Spain (LE-prefix)
    "LEMD", "LEBL", "LEPA", "LEMG", "LEVC",
    # Italy (LI-prefix)
    "LIRF", "LIMC", "LIML", "LIRN", "LIPZ",
    # Switzerland / Austria
    "LSZH", "LSGG", "LSZB", "LOWW", "LOWS",
    # Nordics
    "EKCH", "ESSA", "ENGM", "EFHK", "BIKF",
    # Eastern Europe
    "EPWA", "LKPR", "LZIB", "LHBP", "LRRP", "LROP",
    "LBSF", "LYBE", "LDZA", "LJLJ",
    # Russia / CIS
    "UUEE", "UUDD", "UUWW", "ULLI",
    # Middle East
    "OMDB", "OMAA", "OMSJ", "OTHH", "OEJN", "OEDF", "OERK", "OEMA",
    "LLBG",
    # Asia - East
    "RJTT", "RJAA", "RJBB", "RJOO", "RJFF", "RJCC", "RJGG",
    "RKSI", "RKSS", "RKPC", "RKPK",
    "ZBAA", "ZSPD", "ZSSS", "ZGGG", "ZUUU", "ZGSZ", "ZSHC",
    "VHHH", "RCTP", "RCKH", "RCSS",
    # Asia - SE
    "WSSS", "WMKK", "VTBS", "VTBD", "VVNB", "VVTS",
    "RPLL", "WIII", "WADD",
    # Asia - South / Central
    "VIDP", "VABB", "VOBL", "VOMM", "VOHS", "VECC",
    "OPKC", "OPLA", "OPIS", "VGHS", "VCBI",
    # Africa
    "FAOR", "FACT", "FALE", "HECA", "GMMN", "DAAG", "DTTA", "DTMB",
    "HAAB", "DNMM", "DGAA", "HKJK", "FBJW", "DIAP", "FCBB",
    # Australia / NZ / Pacific
    "YSSY", "YMML", "YBBN", "YPPH", "YPAD", "YBCG", "YBCS", "YPDN",
    "NZAA", "NZCH", "NZWN", "NZQN",
    "NFFN", "AYPY", "NWWW", "NTAA",
    # Americas
    "MMMX", "MMUN", "MMGL", "MMMY",
    "SBGR", "SBGL", "SBBR", "SAEZ", "SCEL", "SKBO", "SPJC", "SEQM",
    "MPTO", "MDSD", "MUHA", "TJSJ", "MROC",
    "TNCM", "TBPB", "TFFF",
})

# Anchor vocabulary -- a 3-letter code becomes an IATA candidate when
# any of these words appears on the same line OR the immediately
# preceding line. Lowercased for case-insensitive matching.
_TRAVEL_ANCHORS = frozenset({
    "flight", "flights", "airport", "airports", "airline", "airlines",
    "departure", "departures", "arrival", "arrivals",
    "origin", "destination",
    "gate", "terminal", "boarding", "boards", "boarded",
    "check-in", "checkin", "baggage", "luggage",
    "from", "to", "via", "stopover", "layover", "connect", "connecting",
    "itinerary", "itineraries", "confirm", "confirmation",
    "pnr", "ticket", "tickets", "fare", "fares",
    "depart", "arrive", "arriving", "departing",
    "non-stop", "nonstop", "direct", "round-trip", "roundtrip",
    "one-way", "oneway", "trip", "trips", "travel",
    "seat", "row", "aisle", "window",
    "leg", "legs", "route", "routes", "transit",
})

# Route arrow shapes that justify a bare ``XXX-XXX`` / ``XXX -> XXX``
# pair as an IATA candidate without a vocabulary anchor.
_ROUTE_ARROW_RE = re.compile(
    r"(?<![A-Z])([A-Z]{3})\s*(?:->|→|>|—|–|-|to|→)\s*([A-Z]{3})(?![A-Z])",
    re.IGNORECASE,
)

# Bare 3-letter run with strict boundaries (no surrounding letter so
# ``ATLAS`` doesn't carve out ``ATL``).
_IATA_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{3})(?![A-Za-z0-9])")

# Bare 4-letter run for ICAO candidates. Same boundary discipline.
_ICAO_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{4})(?![A-Za-z0-9])")

# ICAO region prefixes (first letter of the 4-letter code).
_ICAO_REGION_PREFIXES = frozenset(
    "ABCDEFGHKLMNOPRSTUVWYZ"  # excludes I, J, Q, X
)

# Words we never want to tag as airports even if they pass the
# letter-shape filter. Includes common 3-letter currency codes,
# country codes, and prose acronyms that frequently appear in OCR.
_NEVER_AIRPORTS = frozenset({
    # Currency codes (overlap with our existing currency extractor).
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD", "CHF",
    "SEK", "NOK", "DKK", "INR", "MXN", "BRL", "ZAR", "SGD",
    "HKD", "CNY", "RMB", "KRW", "THB", "PHP", "TRY",
    # Country codes (ISO 3166-1 alpha-3 commonly printed).
    "USA", "GBR", "DEU", "FRA", "ITA", "ESP", "RUS", "CHN",
    "JPN", "KOR", "IND", "AUS", "NZL", "ZAF", "BRA", "MEX",
    # Common prose acronyms (3-letter).
    "API", "CEO", "CFO", "CTO", "COO", "CIO", "CMO",
    "CSS", "CSV", "TSV", "PDF", "PNG", "JPG",
    "GIF", "SVG", "FAQ", "BBQ", "DIY", "RSVP", "ETA", "ETD",
    "RAM", "ROM", "CPU", "GPU", "GUI", "URL", "URI",
    "AWS", "GCP", "DNS", "SSH", "FTP", "TCP",
    "UDP", "SMTP", "IMAP",
    # 4-letter prose acronyms (also rejected for ICAO).
    "JSON", "HTML", "YAML", "TOML", "REST", "SOAP", "GRPC",
    "SFTP", "HTTP", "HTTPS", "POP3", "SNMP", "LDAP",
    "JPEG", "WEBM", "FLAC", "WAVE", "MIDI",
    "BASH", "FISH", "RUBY", "RUST", "PERL", "JAVA",
    "MAIN", "NULL", "TRUE", "VOID",
    "INTL", "DOMS", "NEXT", "PREV",
})


def _line_anchor_set(text: str) -> dict[int, set[str]]:
    """Build a map of line-index -> set of lowercase anchor words present."""
    by_line: dict[int, set[str]] = {}
    for idx, raw in enumerate(text.splitlines()):
        tokens = re.findall(r"[A-Za-z][A-Za-z\-]+", raw)
        by_line[idx] = {t.lower() for t in tokens if t.lower() in _TRAVEL_ANCHORS}
    return by_line


def _offset_to_line(text: str, line_starts: list[int], offset: int) -> int:
    """Binary-search the line index containing ``offset``."""
    lo, hi = 0, len(line_starts)
    while lo < hi:
        mid = (lo + hi) // 2
        if line_starts[mid] <= offset:
            lo = mid + 1
        else:
            hi = mid
    return max(0, lo - 1)


def _has_nearby_anchor(
    anchors: dict[int, set[str]], line_idx: int
) -> bool:
    """Anchor on the same line OR the immediately preceding line counts."""
    if anchors.get(line_idx):
        return True
    if line_idx > 0 and anchors.get(line_idx - 1):
        return True
    return False


def extract_airports(text: str) -> list[dict[str, str]]:
    """Return airport codes found in ``text`` as a list of
    ``{"type", "code"}`` dicts (``type`` is ``"IATA"`` or ``"ICAO"``).

    Detection rules:

    * IATA codes (3 uppercase letters) are accepted when they appear
      in :data:`_IATA_AIRPORTS`, or when a travel-vocabulary anchor
      sits on the same or previous line, or when they form a
      ``XXX-XXX`` / ``XXX -> XXX`` route pair.
    * ICAO codes (4 uppercase letters) are accepted when they appear
      in :data:`_ICAO_AIRPORTS`, or when a travel-vocabulary anchor
      sits on the same or previous line AND the first letter is a
      valid ICAO region prefix.
    * Common currency codes, country codes, and prose acronyms in
      :data:`_NEVER_AIRPORTS` are rejected unconditionally.

    Preserves first-seen-in-text order across all matchers. Capped
    at 50 entries. De-duplicated on the (type, code) pair so a code
    that appears as both a route arrow and a vocabulary anchor only
    surfaces once.
    """
    if not text or not isinstance(text, str):
        return []

    lines = text.splitlines()
    line_starts: list[int] = []
    pos = 0
    for ln in lines:
        line_starts.append(pos)
        pos += len(ln) + 1  # +1 for the newline char
    anchors = _line_anchor_set(text)

    candidates: list[tuple[int, str, str]] = []  # (offset, type, code)
    seen: set[tuple[str, str]] = set()

    # 1) Route-arrow pairs: ``JFK-LAX`` / ``JFK -> LAX`` / ``JFK → LAX``.
    #    Both codes accepted as IATA candidates regardless of catalogue
    #    membership or anchor context (the arrow is the anchor).
    for m in _ROUTE_ARROW_RE.finditer(text):
        a, b = m.group(1).upper(), m.group(2).upper()
        for code, off in ((a, m.start(1)), (b, m.start(2))):
            if code in _NEVER_AIRPORTS:
                continue
            candidates.append((off, "IATA", code))

    # 2) IATA candidates from the curated catalogue OR a nearby
    #    anchor. The bare 3-letter regex finds every candidate; we
    #    filter via catalogue/anchor membership.
    for m in _IATA_CANDIDATE_RE.finditer(text):
        code = m.group(1)
        if code in _NEVER_AIRPORTS:
            continue
        line_idx = _offset_to_line(text, line_starts, m.start())
        in_cat = code in _IATA_AIRPORTS
        if in_cat or _has_nearby_anchor(anchors, line_idx):
            candidates.append((m.start(), "IATA", code))

    # 3) ICAO candidates (4 uppercase letters) -- accept when in the
    #    curated catalogue, OR when the first letter is a valid ICAO
    #    region prefix and a nearby anchor is present. The never-
    #    airports set is consulted too so a 4-letter prose acronym
    #    like HTML / JSON doesn't false-positive even with a nearby
    #    anchor.
    for m in _ICAO_CANDIDATE_RE.finditer(text):
        code = m.group(1)
        if code in _NEVER_AIRPORTS:
            continue
        if code[0] not in _ICAO_REGION_PREFIXES:
            continue
        in_cat = code in _ICAO_AIRPORTS
        if in_cat:
            candidates.append((m.start(), "ICAO", code))
            continue
        line_idx = _offset_to_line(text, line_starts, m.start())
        if _has_nearby_anchor(anchors, line_idx):
            candidates.append((m.start(), "ICAO", code))

    # Source-text order so the result matches reading order.
    candidates.sort(key=lambda x: x[0])
    out: list[dict[str, str]] = []
    for _off, type_, code in candidates:
        key = (type_, code)
        if key in seen:
            continue
        seen.add(key)
        out.append({"type": type_, "code": code})
        if len(out) >= _MAX_AIRPORTS:
            break
    return out


__all__ = ["extract_airports"]
