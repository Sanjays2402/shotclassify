"""POST /v1/classify must translate corrupt-image decode errors into a
clean 400 ``invalid_image`` response instead of leaking a 500.

The single-upload classify path runs the image through OCR + classify
in a worker thread, which in turn opens the file with Pillow. A
truncated or otherwise undecodable payload used to surface as an
unhandled ``OSError`` and crashed the request with HTTP 500. The route
now catches that and returns a structured 400 the API client can
display, plus deletes the saved upload so the storage volume does not
fill up with garbage uploads.
"""
from __future__ import annotations

import io

from fastapi.testclient import TestClient

from services.api.app.main import create_app


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'api.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def test_truncated_png_returns_400_invalid_image(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # Valid PNG magic + IHDR but a deliberately broken IDAT chunk so
    # Pillow raises OSError ("broken data stream") on decode.
    broken_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03"
        b"\x00\x01\x86\x82\x91\xa9\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = c.post(
        "/v1/classify",
        headers={"X-API-Key": "k"},
        files={"file": ("broken.png", io.BytesIO(broken_png), "image/png")},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    detail = body.get("detail", body)
    assert detail.get("error") == "invalid_image"
    assert detail.get("filename") == "broken.png"


def test_garbage_bytes_with_image_content_type_returns_400(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    resp = c.post(
        "/v1/classify",
        headers={"X-API-Key": "k"},
        files={"file": ("junk.png", io.BytesIO(b"not an image at all"), "image/png")},
    )
    # Either the content-type sniffer rejects it (415) before decode, or
    # decode itself fails (400). Both are clean user-facing errors and
    # neither should be a 500.
    assert resp.status_code in (400, 415), resp.text
