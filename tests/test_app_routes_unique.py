"""Regression: the FastAPI app must not register duplicate routes.

A previous refactor double-included ``access_reviews`` (once near the
api-keys block and again at the bottom of ``create_app``), which left
every access-review endpoint registered twice in the router table. That
inflates the OpenAPI schema, doubles dependency execution per request,
and silently obscures future duplicate-include mistakes. This test
locks in single registration for every route.
"""
from __future__ import annotations

from collections import Counter

from services.api.app.main import create_app


def test_no_duplicate_route_registration():
    app = create_app()
    keys = []
    for route in app.router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if path is None:
            continue
        for method in sorted(methods):
            keys.append((method, path))
    dupes = [k for k, c in Counter(keys).items() if c > 1]
    assert dupes == [], f"duplicate route registrations: {dupes}"
