"""Tests for the cross-category MAC-address extractor.

MAC addresses found in OCR text are stashed under
``ExtractedFields.raw["macs"]`` by the enrich pipeline so dashboards
and routing rules have a single place to look regardless of which
category the screenshot belongs to.

The matcher accepts three EUI-48 shapes:

* **Colon-separated** (``00:11:22:33:44:55``) -- Unix / Cisco style.
* **Dash-separated** (``00-11-22-33-44-55``) -- Windows ``ipconfig``
  style.
* **Cisco dot-quad** (``0011.2233.4455``) -- three groups of four
  hex chars.

Output is canonical lowercase + colon-separated regardless of input
shape, so the same MAC in different formats collapses to one entry.
The null MAC (``00:00:00:00:00:00``) and broadcast MAC
(``ff:ff:ff:ff:ff:ff``) are rejected because they don't identify a
specific device. IPv6 spans are masked before scanning so a
compressed IPv6 doesn't false-positive as a MAC.
"""
from __future__ import annotations

import pytest
from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_macs

# ---- extract_macs: colon-separated -------------------------------------


def test_extract_basic_colon_lower():
    assert extract_macs("device 00:11:22:33:44:55") == ["00:11:22:33:44:55"]


def test_extract_basic_colon_upper_normalised():
    """MACs printed uppercase normalise to lowercase canonical form."""
    assert extract_macs("link AA:BB:CC:DD:EE:FF") == ["aa:bb:cc:dd:ee:ff"]


def test_extract_colon_mixed_case():
    assert extract_macs("nic 0a:1B:2c:3D:4e:5F") == ["0a:1b:2c:3d:4e:5f"]


def test_extract_colon_multiple_distinct():
    text = "if00 00:11:22:33:44:55 if01 a0:b1:c2:d3:e4:f5"
    assert extract_macs(text) == [
        "00:11:22:33:44:55",
        "a0:b1:c2:d3:e4:f5",
    ]


def test_extract_colon_at_end_of_line():
    assert extract_macs("mac 00:1a:2b:3c:4d:5e\n") == ["00:1a:2b:3c:4d:5e"]


def test_extract_colon_in_brackets():
    assert extract_macs("[b8:e8:56:11:22:33]") == ["b8:e8:56:11:22:33"]


def test_extract_ifconfig_block():
    """Real ``ifconfig`` output prints the MAC after ``ether``."""
    text = (
        "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n"
        "\tether b8:e8:56:11:22:33\n"
        "\tinet 192.168.1.10 netmask 0xffffff00\n"
    )
    assert extract_macs(text) == ["b8:e8:56:11:22:33"]


# ---- extract_macs: dash-separated --------------------------------------


def test_extract_basic_dash():
    """Windows ipconfig prints MACs with dashes."""
    assert extract_macs("Physical Address. . . : 00-11-22-33-44-55") == [
        "00:11:22:33:44:55"
    ]


def test_extract_dash_upper_normalised():
    assert extract_macs("link A0-B1-C2-D3-E4-F5") == ["a0:b1:c2:d3:e4:f5"]


def test_extract_dash_multiple():
    text = "nic1 00-11-22-33-44-55 nic2 aa-bb-cc-dd-ee-ff"
    assert extract_macs(text) == [
        "00:11:22:33:44:55",
        "aa:bb:cc:dd:ee:ff",
    ]


def test_extract_ipconfig_block():
    text = (
        "Ethernet adapter Local Area Connection:\n"
        "   Physical Address. . . . . . . . . : 00-1A-2B-3C-4D-5E\n"
        "   IPv4 Address. . . . . . . . . . . : 192.168.1.10\n"
    )
    assert extract_macs(text) == ["00:1a:2b:3c:4d:5e"]


# ---- extract_macs: Cisco dot-quad --------------------------------------


def test_extract_basic_dotquad():
    """Cisco IOS prints MACs as three dot-separated 4-hex groups."""
    assert extract_macs("hardware 0011.2233.4455") == ["00:11:22:33:44:55"]


def test_extract_dotquad_upper():
    assert extract_macs("0011.2233.AABB") == ["00:11:22:33:aa:bb"]


def test_extract_dotquad_show_arp_block():
    text = (
        "Router> show arp\n"
        "Internet  192.168.1.1   1   0011.2233.4455  ARPA   FastEthernet0/0\n"
    )
    assert extract_macs(text) == ["00:11:22:33:44:55"]


# ---- extract_macs: de-dup across shapes --------------------------------


def test_dedup_colon_and_dash():
    """Same MAC printed both ways collapses to one entry."""
    text = "configured 00:11:22:33:44:55 cached 00-11-22-33-44-55"
    assert extract_macs(text) == ["00:11:22:33:44:55"]


def test_dedup_colon_and_dotquad():
    text = "linux 00:11:22:33:44:55 cisco 0011.2233.4455"
    assert extract_macs(text) == ["00:11:22:33:44:55"]


def test_dedup_dash_and_dotquad():
    text = "win 00-11-22-33-44-55 ios 0011.2233.4455"
    assert extract_macs(text) == ["00:11:22:33:44:55"]


def test_dedup_case_insensitive():
    """``aa:bb:...`` and ``AA:BB:...`` are the same address."""
    text = "lower aa:bb:cc:dd:ee:ff upper AA:BB:CC:DD:EE:FF"
    assert extract_macs(text) == ["aa:bb:cc:dd:ee:ff"]


# ---- extract_macs: order preservation ----------------------------------


def test_source_order_preserved():
    """Output reflects reading order, not matcher iteration order."""
    text = (
        "first 11:11:11:11:11:11 then 22:22:22:22:22:22 "
        "then 33:33:33:33:33:33"
    )
    assert extract_macs(text) == [
        "11:11:11:11:11:11",
        "22:22:22:22:22:22",
        "33:33:33:33:33:33",
    ]


def test_source_order_across_shapes():
    """Dash printed first lands first even though colon iterates first."""
    text = "win aa-aa-aa-aa-aa-aa then linux bb:bb:bb:bb:bb:bb"
    assert extract_macs(text) == [
        "aa:aa:aa:aa:aa:aa",
        "bb:bb:bb:bb:bb:bb",
    ]


# ---- extract_macs: reject placeholders / broadcast ---------------------


def test_rejects_null_mac():
    """All-zero MAC is almost always an uninitialised placeholder."""
    assert extract_macs("default 00:00:00:00:00:00 entry") == []


def test_rejects_null_mac_dash_form():
    assert extract_macs("00-00-00-00-00-00") == []


def test_rejects_null_mac_dotquad_form():
    assert extract_macs("0000.0000.0000") == []


def test_rejects_broadcast_mac():
    """All-ones MAC is the Ethernet broadcast, not a device identifier."""
    assert extract_macs("arp ff:ff:ff:ff:ff:ff broadcast") == []


def test_rejects_broadcast_mac_dash_form():
    assert extract_macs("FF-FF-FF-FF-FF-FF") == []


def test_rejects_broadcast_mac_dotquad_form():
    assert extract_macs("ffff.ffff.ffff") == []


def test_keeps_real_macs_alongside_placeholders():
    """Filtering placeholders does not affect real MACs in the same text."""
    text = "real 00:11:22:33:44:55 null 00:00:00:00:00:00 bcast ff:ff:ff:ff:ff:ff"
    assert extract_macs(text) == ["00:11:22:33:44:55"]


# ---- extract_macs: reject false positives ------------------------------


def test_rejects_short_run():
    """5 groups is not a MAC."""
    assert extract_macs("partial 00:11:22:33:44") == []


def test_rejects_long_run():
    """7 groups is not a MAC."""
    assert extract_macs("over 00:11:22:33:44:55:66") == []


def test_rejects_non_hex_chars():
    """``gg`` is not hex."""
    assert extract_macs("badmac 00:11:22:33:44:gg") == []


def test_rejects_one_char_groups():
    """``0:1:2:3:4:5`` is too short for any MAC group."""
    assert extract_macs("bad 0:1:2:3:4:5") == []


def test_rejects_within_longer_hex():
    """A MAC-shaped substring inside a longer hex run is not a MAC."""
    # 8-group form -- this is an IPv6 shape, not a MAC.
    text = "addr aaaa:bbbb:cccc:dddd:eeee:ffff:gggg:hhhh"
    assert extract_macs(text) == []


def test_rejects_ipv6_compressed():
    """The compressed IPv6 ``::1`` is not a MAC."""
    assert extract_macs("ipv6 ::1 endpoint") == []


def test_rejects_ipv6_full():
    """A full 8-group IPv6 is masked / non-matching."""
    text = "ipv6 2001:0db8:0000:0042:0000:8a2e:0370:7334"
    assert extract_macs(text) == []


def test_rejects_ipv6_link_local():
    """Link-local IPv6 with a colon-heavy suffix doesn't masquerade."""
    assert extract_macs("addr fe80::1ff:fe23:4567:890a end") == []


def test_rejects_ipv6_with_embedded_macish():
    """An IPv6 span that happens to contain a MAC-shaped tail does
    not yield the tail as a MAC (the span is masked first)."""
    # fe80::aa:bb:cc:dd:ee:ff is an IPv6, NOT an aa:bb:cc:dd:ee:ff MAC.
    assert extract_macs("addr fe80::aa:bb:cc:dd:ee:ff end") == []


# ---- extract_macs: cap ------------------------------------------------


def test_cap_at_50():
    """Output is capped at 50 entries even when more are present."""
    macs = [f"00:11:22:33:44:{i:02x}" for i in range(60)]
    text = " ".join(macs)
    result = extract_macs(text)
    assert len(result) == 50
    assert result[0] == "00:11:22:33:44:00"
    assert result[-1] == "00:11:22:33:44:31"


# ---- extract_macs: degenerate inputs ----------------------------------


def test_empty_string():
    assert extract_macs("") == []


def test_none_input():
    assert extract_macs(None) == []  # type: ignore[arg-type]


def test_non_string_input():
    assert extract_macs(12345) == []  # type: ignore[arg-type]


def test_no_macs_in_text():
    assert extract_macs("hello world no addresses here") == []


def test_just_separators_no_hex():
    assert extract_macs(":::::") == []


# ---- enrich pipeline integration --------------------------------------


@pytest.mark.parametrize(
    "category",
    [
        Category.code_snippet,
        Category.error_stacktrace,
        Category.document,
        Category.other,
        Category.chat_screenshot,
    ],
)
def test_pipeline_stashes_macs_for_every_category(category):
    """The MAC extractor runs cross-category and writes to raw["macs"]."""
    text = "ifconfig en0 b8:e8:56:11:22:33 up"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(category, ExtractedFields(), ocr)
    assert out.raw.get("macs") == ["b8:e8:56:11:22:33"]


def test_pipeline_no_macs_no_key():
    """When no MAC is in the text, the raw key is NOT created."""
    text = "no addresses here"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(Category.other, ExtractedFields(), ocr)
    assert "macs" not in (out.raw or {})


def test_pipeline_dedup_across_shapes_in_enrich():
    """Same MAC in colon and dash form -> one entry in raw["macs"]."""
    text = "linux 00:11:22:33:44:55 win 00-11-22-33-44-55"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(Category.other, ExtractedFields(), ocr)
    assert out.raw.get("macs") == ["00:11:22:33:44:55"]


def test_pipeline_preserves_other_raw_keys():
    """raw["urls"] and raw["macs"] coexist when both are present."""
    text = "see https://example.com on en0 b8:e8:56:11:22:33"
    ocr = OCRResult(text=text, confidence=0.95)
    out = enrich(Category.other, ExtractedFields(), ocr)
    assert out.raw.get("macs") == ["b8:e8:56:11:22:33"]
    assert out.raw.get("urls") == ["https://example.com"]
