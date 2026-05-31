"""CSRF protection for cookie-authenticated state-changing requests.

Cookie sessions (``sc_session``) are sent automatically by the browser
on every request to the API origin, which means a malicious page on a
different origin can convince a logged-in browser to issue a POST or
DELETE against our API and have it succeed purely on the basis of the
ambient cookie. The browser-origin allowlist mitigates this for
configured tenants but is opt-in and only narrows the set of *Origins*
the request claims to come from. SameSite=Lax on the session cookie
blocks the cross-site cookie ride for top-level POSTs but does *not*
protect against same-site subdomain takeover or browser quirks, and
PUT/PATCH/DELETE issued via ``fetch`` are explicitly NOT covered.

This middleware adds a double-submit CSRF check on top of the cookie
session:

* On every authenticated cookie-session request we issue a
  ``sc_csrf`` cookie (``Secure`` in non-dev, ``SameSite=Lax``,
  *not* HttpOnly so JS can read it). The cookie value is an HMAC of
  the session id signed with ``APP_SECRET_KEY``.
* Mutating verbs (``POST``, ``PUT``, ``PATCH``, ``DELETE``) over a
  cookie session must echo that value back in the ``X-CSRF-Token``
  request header **when the request carries an ``Origin`` (or
  ``Sec-Fetch-Site``) header**. That gate keeps the check tight to
  the actual attack surface: browsers always attach ``Origin`` to
  fetches and to cross-site form posts, so a CSRF attempt cannot
  evade the check, but non-browser clients (curl, CI scripts) that
  reuse a cookie session for one-off debugging are not penalised
  for not knowing about the token. Mismatch returns
  ``403 csrf_token_invalid``.
* ``GET``/``HEAD``/``OPTIONS`` are exempt because they must be safe
  by HTTP definition.
* API-key callers and SCIM bearer callers are exempt: they do not
  ride on ambient browser cookies and a cross-origin page cannot
  cause a victim to send those headers.
* A small allowlist of pre-login auth endpoints is exempt so we can
  bootstrap a session before a CSRF token exists.

The token itself is also exposed via ``GET /auth/csrf`` so SPA
clients that mount on the same origin can read it once at boot and
attach the header to every fetch, without depending on cookies being
visible to JS in older browsers.
"""
from __future__ import annotations

import hmac
import hashlib

from shotclassify_common import get_settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth import _decode_sid


CSRF_COOKIE = "sc_csrf"
CSRF_HEADER = "x-csrf-token"

# Verbs whose semantics are safe by HTTP definition. We do not require a
# CSRF token to read data, only to mutate it.
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Auth endpoints that must work *before* a cookie session (and therefore
# a CSRF token) exists. These are either redirect-driven OAuth flows
# protected by the OAuth ``state`` parameter, or the logout endpoint
# which we deliberately want to be tolerant so a partially-broken
# client can always sign out.
_CSRF_EXEMPT_PATHS = {
    "/auth/login",
    "/auth/callback",
    "/auth/logout",
    "/auth/sso/login",
    "/auth/sso/callback",
}

# Path prefixes that are exempt because they have their own dedicated
# auth (SCIM bearer) or are non-browser machine surfaces.
_CSRF_EXEMPT_PREFIXES = (
    "/scim/v2",
)


def _hmac_token(sid: str, secret: str) -> str:
    """Return the canonical CSRF token for a session id.

    HMAC-SHA256 binds the token to both the session id (so a stolen
    token from one session cannot be replayed on another) and the
    app secret (so an attacker who guesses a session id cannot forge
    a token without also stealing the secret).
    """
    mac = hmac.new(secret.encode("utf-8"), sid.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()


def token_for_session(sid: str) -> str:
    """Public helper used by route handlers (eg. ``GET /auth/csrf``)."""
    return _hmac_token(sid, get_settings().app_secret_key)


def _path_exempt(path: str) -> bool:
    if path in _CSRF_EXEMPT_PATHS:
        return True
    for prefix in _CSRF_EXEMPT_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF guard for cookie-authenticated mutations.

    Runs *after* the auth middleware on the inbound path so it can
    distinguish cookie sessions from API keys via
    ``request.state.session_id`` (set by ``APIKeyAndSessionAuth``
    only on the cookie branch).
    """

    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        method = request.method.upper()
        path = request.url.path

        # Identify whether this request is riding on an ambient browser
        # cookie. We trust ``request.state.session_id`` because it is
        # only set after the auth middleware validated the cookie's
        # signature against the server-side ``sessions`` table.
        session_id = getattr(request.state, "session_id", None)

        if (
            session_id
            and method not in _SAFE_METHODS
            and not _path_exempt(path)
            # Only enforce when the request looks like it came from a
            # browser. Browsers attach ``Origin`` to every fetch (and
            # to cross-site form posts); non-browser clients such as
            # curl, server-to-server scripts, and unit-test runners
            # do not. The threat we are blocking is the cross-origin
            # ride of the ambient ``sc_session`` cookie, which only a
            # browser can perform, so gating on ``Origin`` keeps the
            # check tight to the actual attack surface and avoids
            # breaking machine callers that legitimately reuse a
            # cookie session (eg. an admin running curl from a saved
            # browser cookie for one-off debugging).
            and (
                request.headers.get("origin")
                or request.headers.get("sec-fetch-site")
            )
        ):
            expected = _hmac_token(session_id, s.app_secret_key)
            supplied = request.headers.get(CSRF_HEADER) or ""
            # Constant-time compare so a timing oracle cannot reveal
            # the token byte by byte.
            if not supplied or not hmac.compare_digest(expected, supplied):
                return JSONResponse(
                    {
                        "error": "csrf_token_invalid",
                        "detail": (
                            "Cookie-authenticated mutations require the "
                            "X-CSRF-Token header. Fetch the current value "
                            "from GET /auth/csrf or read the sc_csrf "
                            "cookie."
                        ),
                    },
                    status_code=403,
                )

        response: Response = await call_next(request)

        # Refresh the double-submit cookie on every cookie-authenticated
        # response. We re-derive the value from the (already validated)
        # session id so it stays in sync with rotation events such as
        # session renewal or force-logout-all. The cookie is *readable*
        # by JS on purpose: the entire point of double-submit is that
        # JS reads it and copies the value into a header that the
        # browser will *not* attach automatically on cross-origin
        # navigations.
        if session_id:
            token = _hmac_token(session_id, s.app_secret_key)
            response.set_cookie(
                CSRF_COOKIE,
                token,
                httponly=False,
                samesite="lax",
                secure=s.app_env != "development",
                # No max_age: track the session cookie lifetime so the
                # token rolls forward with the session and never lives
                # longer than the credential it protects.
            )
        return response
