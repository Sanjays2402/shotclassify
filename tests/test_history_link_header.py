"""RFC 5988 Link header pagination for /v1/history."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from services.api.app.main import create_app
from shotclassify_common import Category


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'hist.db'}")
    monkeypatch.setenv("STORAGE_LOCAL_DIR", str(tmp_path / "storage"))
    from shotclassify_common.settings import get_settings
    from shotclassify_store import db

    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    return TestClient(create_app())


def _seed(n: int = 25):
    from shotclassify_store.db import ClassificationRow, get_session, init_db

    init_db()
    now = datetime.now(timezone.utc)
    with get_session() as s:
        for i in range(n):
            row = ClassificationRow(
                id=f"rec-{i:03d}",
                created_at=now - timedelta(minutes=i),
                filename=f"shot-{i}.png",
                primary_category=Category.receipt.value,
                confidence=0.5,
                ocr_text="hello",
                image_path=None,
                tenant_id=None,
            )
            s.add(row)
        s.commit()


def _parse_links(header: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in header.split(", "):
        url_part, _, rel_part = part.partition("; ")
        rel = rel_part.split("=", 1)[1].strip('"')
        url = url_part.strip("<>")
        out[rel] = url
    return out


def test_link_header_first_page_has_next_and_last_no_prev(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(25)
    r = c.get("/v1/history?limit=10&offset=0", headers={"X-API-Key": "k"})
    assert r.status_code == 200
    assert "link" in {k.lower() for k in r.headers}
    links = _parse_links(r.headers["link"])
    assert set(links) == {"first", "next", "last"}
    assert "offset=0" in links["first"]
    assert "offset=10" in links["next"]
    assert "offset=20" in links["last"]
    # access-control-expose-headers now includes link
    assert "link" in r.headers["access-control-expose-headers"]


def test_link_header_middle_page_has_all_four(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(25)
    r = c.get("/v1/history?limit=10&offset=10", headers={"X-API-Key": "k"})
    links = _parse_links(r.headers["link"])
    assert set(links) == {"first", "prev", "next", "last"}
    assert "offset=0" in links["prev"]
    assert "offset=20" in links["next"]


def test_link_header_last_page_drops_next(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(25)
    r = c.get("/v1/history?limit=10&offset=20", headers={"X-API-Key": "k"})
    links = _parse_links(r.headers["link"])
    assert "next" not in links
    assert "prev" in links and "first" in links and "last" in links


def test_link_header_preserves_filters(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(25)
    r = c.get(
        "/v1/history?limit=5&offset=0&sort=old&category=receipt",
        headers={"X-API-Key": "k"},
    )
    links = _parse_links(r.headers["link"])
    nxt = urlparse(links["next"])
    q = parse_qs(nxt.query)
    assert q["sort"] == ["old"]
    assert q["category"] == ["receipt"]
    assert q["limit"] == ["5"]
    assert q["offset"] == ["5"]


def test_link_header_empty_result_has_only_first(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    _seed(5)
    r = c.get(
        "/v1/history?limit=10&offset=0&min_conf=0.99",
        headers={"X-API-Key": "k"},
    )
    assert r.status_code == 200
    assert r.json() == []
    links = _parse_links(r.headers["link"])
    assert set(links) == {"first"}
