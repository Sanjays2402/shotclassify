"""Tests for the Sentry error tracking wiring.

The Sentry SDK is initialized only when ``SENTRY_DSN`` is set. We avoid any
network egress by pointing the DSN at a local-only host and asserting on the
SDK state directly, plus by exercising the ``before_send`` scrubber that
strips auth headers and cookies from outgoing events.
"""
from __future__ import annotations

import importlib

import pytest
from shotclassify_common import errors as errors_mod
from shotclassify_common.settings import get_settings


@pytest.fixture(autouse=True)
def _reset_sentry_state():
    errors_mod._reset_for_tests()
    get_settings.cache_clear()
    yield
    errors_mod._reset_for_tests()
    get_settings.cache_clear()
    # If a previous test initialized the real client, close it so other tests
    # do not see a leaked hub.
    try:
        import sentry_sdk

        client = sentry_sdk.get_client()
        if client is not None:
            client.close()
    except Exception:  # noqa: S110 - cleanup must never raise
        pass


def test_init_noop_when_dsn_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    get_settings.cache_clear()
    assert errors_mod.init_sentry() is False
    assert errors_mod.is_initialized() is False
    assert errors_mod.capture_exception(RuntimeError("boom")) is None


def test_init_sets_state_when_dsn_present(monkeypatch: pytest.MonkeyPatch) -> None:
    # Use a syntactically valid DSN pointing at a host we never contact.
    # We override the transport so no network call is made.
    monkeypatch.setenv("SENTRY_DSN", "https://public@127.0.0.1/1")
    monkeypatch.setenv("APP_ENV", "staging")
    get_settings.cache_clear()

    assert errors_mod.init_sentry(service_name="shotclassify-test") is True
    assert errors_mod.is_initialized() is True

    # Re-init is a no-op on second call.
    assert errors_mod.init_sentry() is False

    import sentry_sdk

    client = sentry_sdk.get_client()
    assert client is not None
    assert client.options["environment"] == "staging"
    assert client.options["send_default_pii"] is False
    # before_send must be wired so we can scrub auth headers.
    assert client.options["before_send"] is errors_mod._scrub_event


def test_scrubber_redacts_sensitive_request_fields() -> None:
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer secret-token",
                "Cookie": "session=abc",
                "X-API-Key": "k-123",
                "User-Agent": "pytest",
            },
            "cookies": {"session": "abc"},
            "env": {"QUERY_STRING": "api_key=leak&foo=bar"},
        },
        "extra": {
            "api_key": "k-123",
            "user_secret": "shhh",
            "other": "fine",
        },
    }
    scrubbed = errors_mod._scrub_event(event, {})
    assert scrubbed is not None
    headers = scrubbed["request"]["headers"]
    assert headers["Authorization"] == "[Filtered]"
    assert headers["Cookie"] == "[Filtered]"
    assert headers["X-API-Key"] == "[Filtered]"
    assert headers["User-Agent"] == "pytest"
    assert scrubbed["request"]["cookies"] == {}
    assert scrubbed["request"]["env"]["QUERY_STRING"] == "[Filtered]"
    extra = scrubbed["extra"]
    assert extra["api_key"] == "[Filtered]"
    assert extra["user_secret"] == "[Filtered]"
    assert extra["other"] == "fine"


def test_capture_exception_returns_event_id_when_initialized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRY_DSN", "https://public@127.0.0.1/1")
    get_settings.cache_clear()

    import sentry_sdk
    from sentry_sdk.transport import Transport

    captured: list[dict] = []

    class _CapturingTransport(Transport):
        def __init__(self, options=None):  # type: ignore[no-untyped-def]
            super().__init__(options)

        def capture_envelope(self, envelope):  # type: ignore[no-untyped-def]
            for item in envelope.items:
                payload = item.payload
                # sentry-sdk 2.x stores parsed json on payload.json
                if getattr(payload, "json", None):
                    captured.append(payload.json)

        def flush(self, timeout, callback=None):  # type: ignore[no-untyped-def]
            return None

        def kill(self):  # type: ignore[no-untyped-def]
            return None

    # Reinit Sentry with a custom transport so no network IO occurs.
    sentry_sdk.init(
        dsn="https://public@127.0.0.1/1",
        transport=_CapturingTransport,
        before_send=errors_mod._scrub_event,
        send_default_pii=False,
    )
    # Force errors module to consider itself initialized against this client.
    errors_mod._initialized = True
    errors_mod._sentry_module = sentry_sdk

    event_id = errors_mod.capture_exception(RuntimeError("boom-for-test"))
    assert event_id is not None and isinstance(event_id, str)
    sentry_sdk.get_client().flush(timeout=2.0)
    # At least one event must have made it into the capturing transport.
    assert any("boom-for-test" in str(ev) for ev in captured)


def test_module_reexports_public_helpers() -> None:
    mod = importlib.import_module("shotclassify_common")
    assert hasattr(mod, "init_sentry")
    assert hasattr(mod, "capture_exception")
    assert hasattr(mod, "sentry_is_initialized")
