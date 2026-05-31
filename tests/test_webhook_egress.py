"""Tests that the webhook dispatcher refuses SSRF-prone targets.

These cover the egress allowlist module independently of the database/
subscription layer so a regression here fails fast and points at the
right file.
"""
from __future__ import annotations

import pytest

from shotclassify_store.webhook_egress import (
    EgressBlocked,
    validate_target,
)


DEFAULTS = dict(allow_http=True, allow_private=False)


@pytest.mark.parametrize(
    "url, needle",
    [
        # Cloud instance metadata: highest-value SSRF target on AWS/GCP/Azure.
        ("http://169.254.169.254/latest/meta-data/", "169.254"),
        # IPv4 loopback.
        ("http://127.0.0.1/hook", "loopback"),
        # IPv6 loopback.
        ("http://[::1]/hook", "loopback"),
        # RFC1918 private ranges.
        ("http://10.0.0.5/hook", "private"),
        ("http://192.168.1.1/hook", "private"),
        ("http://172.16.0.1/hook", "private"),
        # IPv6 ULA.
        ("http://[fd00::1]/hook", "private"),
        # Link-local IPv6.
        ("http://[fe80::1]/hook", "fe80"),
        # CGNAT.
        ("http://100.64.0.1/hook", "100.64"),
        # Multicast.
        ("http://224.0.0.1/hook", "multicast"),
        # 0.0.0.0/8 is private per ipaddress.
        ("http://0.0.0.0/hook", "private"),
    ],
)
def test_blocks_ssrf_targets(url, needle):
    with pytest.raises(EgressBlocked) as exc:
        validate_target(url, **DEFAULTS)
    assert needle.lower() in str(exc.value).lower()


def test_blocks_plain_http_when_disabled():
    with pytest.raises(EgressBlocked, match="plain http"):
        validate_target(
            "http://example.com/hook", allow_http=False, allow_private=False
        )


def test_blocks_userinfo():
    with pytest.raises(EgressBlocked, match="userinfo"):
        validate_target(
            "https://user:pass@example.com/hook",
            allow_http=False,
            allow_private=False,
        )


def test_blocks_non_http_scheme():
    with pytest.raises(EgressBlocked, match="scheme"):
        validate_target("file:///etc/passwd", **DEFAULTS)
    with pytest.raises(EgressBlocked, match="scheme"):
        validate_target("gopher://example.com/", **DEFAULTS)


def test_blocks_disallowed_port():
    with pytest.raises(EgressBlocked, match="port"):
        validate_target("https://example.com:22/hook", **DEFAULTS)
    with pytest.raises(EgressBlocked, match="port"):
        validate_target("https://example.com:6379/hook", **DEFAULTS)


def test_extra_blocked_cidrs():
    with pytest.raises(EgressBlocked, match="operator-blocked"):
        validate_target(
            "http://198.51.100.5/hook",
            allow_http=True,
            allow_private=False,
            extra_blocked_cidrs="198.51.100.0/24, 203.0.113.0/24",
        )


def test_allow_private_still_blocks_metadata():
    with pytest.raises(EgressBlocked, match="169.254"):
        validate_target(
            "http://169.254.169.254/", allow_http=True, allow_private=True
        )
    target = validate_target(
        "http://127.0.0.1/hook", allow_http=True, allow_private=True
    )
    assert target.ip == "127.0.0.1"
