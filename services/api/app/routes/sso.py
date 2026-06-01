"""OIDC Single Sign-On for enterprise identity providers.

Generic OpenID Connect authorization-code flow that works with Google
Workspace, Okta, Azure AD, Auth0, Keycloak, anything that publishes a
discovery document at ``<issuer>/.well-known/openid-configuration``.

The deployment configures one IdP via env vars (``AUTH_SSO_ISSUER`` etc).
Each tenant then opts in by setting its ``sso_domain`` (e.g. ``acme.com``)
and optionally turning on ``sso_enforced`` so any session that did not
flow through the SSO callback is rejected. The session row stores
``auth_method='sso'`` for the enforce check.

Routes:
  GET /auth/sso/login            -> redirect to IdP authorize endpoint
  GET /auth/sso/callback         -> exchange code, verify id_token, mint session
  GET /auth/sso/config           -> what the dashboard needs to render the button

Discovery and JWKS are cached in-process; both are small JSON docs that
change rarely.
"""
from __future__ import annotations

import secrets
import time
import urllib.parse

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from shotclassify_common import get_settings
from shotclassify_store import tenant_for_sso_domain
from shotclassify_store.memberships import role_for_member, upsert_member
from shotclassify_store.tenant_settings import (
    email_matches_allowed_domains,
    get_allowed_invite_domains,
    get_sso_config,
    get_tenant_oidc,
    get_tenant_oidc_secret,
)

from ..middleware.auth import issue_session
from ..middleware.tenant import tenant_for_principal

router = APIRouter(prefix="/auth/sso", tags=["auth"])


_DISCOVERY_CACHE: dict[str, tuple[float, dict]] = {}
_JWKS_CACHE: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 3600.0  # seconds


def _discovery(issuer: str) -> dict:
    issuer = issuer.rstrip("/")
    now = time.time()
    cached = _DISCOVERY_CACHE.get(issuer)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]
    url = f"{issuer}/.well-known/openid-configuration"
    with httpx.Client(timeout=10) as client:
        r = client.get(url)
        r.raise_for_status()
        doc = r.json()
    if not isinstance(doc, dict) or "authorization_endpoint" not in doc:
        raise HTTPException(502, "Invalid OIDC discovery document.")
    _DISCOVERY_CACHE[issuer] = (now, doc)
    return doc


def _jwks(jwks_uri: str):
    now = time.time()
    cached = _JWKS_CACHE.get(jwks_uri)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]
    with httpx.Client(timeout=10) as client:
        r = client.get(jwks_uri)
        r.raise_for_status()
        ks = JsonWebKey.import_key_set(r.json())
    _JWKS_CACHE[jwks_uri] = (now, ks)
    return ks


def _redirect_uri(request: Request) -> str:
    s = get_settings()
    if s.auth_sso_redirect_uri:
        return s.auth_sso_redirect_uri
    return str(request.url_for("auth_sso_callback"))


@router.get("/config")
def sso_config(email: str | None = Query(default=None, max_length=320)):
    """Public summary used by the sign-in page to render the SSO button.

    When ``email`` is supplied and the domain matches a tenant with its own
    OIDC IdP configured, we report that tenant's issuer (no secrets) so
    the dashboard can show a "Sign in with Acme SSO" affordance even when
    the deployment-level shared IdP is disabled.
    """
    s = get_settings()
    if email and "@" in email:
        domain = email.split("@", 1)[1].lower().strip()
        tid = tenant_for_sso_domain(domain)
        if tid:
            tcfg = get_tenant_oidc(tid)
            if tcfg.configured:
                return {
                    "enabled": True,
                    "issuer": tcfg.issuer,
                    "source": "tenant",
                    "tenant_id": tid,
                }
    return {
        "enabled": bool(s.auth_sso_enabled and s.auth_sso_issuer and s.auth_sso_client_id),
        "issuer": s.auth_sso_issuer or None,
        "source": "deployment",
    }


def _resolve_idp(email: str | None) -> tuple[str, str, str, str, str | None]:
    """Pick the OIDC IdP for this sign-in attempt.

    Returns ``(issuer, client_id, client_secret, scopes, tenant_id)``.
    ``tenant_id`` is the tenant whose per-tenant IdP was selected, or
    ``None`` when we fell back to the deployment-level shared IdP.

    Resolution order:
      1. ``email`` provided AND domain matches a tenant with a fully
         configured per-tenant OIDC IdP -> use that.
      2. Otherwise fall back to the deployment ``AUTH_SSO_*`` env config.
    """
    s = get_settings()
    if email and "@" in email:
        domain = email.split("@", 1)[1].lower().strip()
        tid = tenant_for_sso_domain(domain)
        if tid:
            tcfg = get_tenant_oidc(tid)
            if tcfg.configured and tcfg.issuer and tcfg.client_id:
                secret = get_tenant_oidc_secret(tid) or ""
                if secret:
                    return (
                        tcfg.issuer,
                        tcfg.client_id,
                        secret,
                        tcfg.scopes or s.auth_sso_scopes,
                        tid,
                    )
    if not (s.auth_sso_enabled and s.auth_sso_issuer and s.auth_sso_client_id):
        raise HTTPException(
            400,
            "No OIDC IdP configured for this sign-in. Either provide an email "
            "whose domain is registered to a tenant with its own OIDC IdP, or "
            "set AUTH_SSO_* on the deployment.",
        )
    return (
        s.auth_sso_issuer,
        s.auth_sso_client_id,
        s.auth_sso_client_secret or "",
        s.auth_sso_scopes,
        None,
    )


@router.get("/login")
def login(request: Request, email: str | None = Query(default=None, max_length=320)):
    s = get_settings()
    try:
        issuer, client_id, _client_secret, scopes, tenant_idp = _resolve_idp(email)
    except HTTPException:
        if not (s.auth_sso_enabled and s.auth_sso_issuer and s.auth_sso_client_id):
            return HTMLResponse(
                "<h1>SSO not configured</h1>"
                "<p>Set AUTH_SSO_ENABLED=true, AUTH_SSO_ISSUER, AUTH_SSO_CLIENT_ID, "
                "AUTH_SSO_CLIENT_SECRET on the deployment, or configure a per-tenant "
                "OIDC IdP via PUT /v1/settings/security/oidc and sign in with an email "
                "whose domain matches that tenant's SSO domain.</p>",
                status_code=200,
            )
        raise
    try:
        disc = _discovery(issuer)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"OIDC discovery failed: {exc}") from exc
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    # Tenant routing: per-tenant IdP wins; otherwise fall back to
    # email-domain SSO routing for the shared deployment IdP.
    tenant_hint: str | None = tenant_idp
    if not tenant_hint and email and "@" in email:
        domain = email.split("@", 1)[1].lower().strip()
        tenant_hint = tenant_for_sso_domain(domain)
    redirect_uri = _redirect_uri(request)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "state": state,
        "nonce": nonce,
    }
    if email:
        # Most IdPs honor login_hint to prefill the username field.
        params["login_hint"] = email
    url = f"{disc['authorization_endpoint']}?{urllib.parse.urlencode(params)}"
    resp = RedirectResponse(url)
    cookie_opts = dict(httponly=True, samesite="lax", max_age=600, path="/auth/sso")
    resp.set_cookie("sc_sso_state", state, **cookie_opts)
    resp.set_cookie("sc_sso_nonce", nonce, **cookie_opts)
    if tenant_hint:
        resp.set_cookie("sc_sso_tenant", tenant_hint, **cookie_opts)
    if tenant_idp:
        # The callback must redirect to the IdP's token endpoint with the
        # *same* client used at /authorize. Persist the tenant whose IdP
        # we selected so the callback can re-resolve issuer + secret.
        resp.set_cookie("sc_sso_idp_tenant", tenant_idp, **cookie_opts)
    return resp


@router.get("/callback", name="auth_sso_callback")
def callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
):
    s = get_settings()
    if error:
        raise HTTPException(400, f"SSO error: {error} {error_description or ''}".strip())
    if not code or not state:
        raise HTTPException(400, "Missing code or state.")
    cookie_state = request.cookies.get("sc_sso_state")
    cookie_nonce = request.cookies.get("sc_sso_nonce")
    cookie_tenant_hint = request.cookies.get("sc_sso_tenant")
    cookie_idp_tenant = request.cookies.get("sc_sso_idp_tenant")
    if not cookie_state or not secrets.compare_digest(cookie_state, state):
        raise HTTPException(400, "Invalid SSO state.")
    # Resolve which IdP we sent the user to at /login. If we minted a
    # per-tenant IdP cookie, reuse those creds. Otherwise the deployment
    # client. Falling through to the deployment client when a tenant
    # cookie is present would be a confused-deputy bug: the IdP issued
    # the code for a different audience and our token exchange would
    # be rejected (or worse, accepted under the wrong client).
    idp_issuer: str
    idp_client_id: str
    idp_client_secret: str
    if cookie_idp_tenant:
        tcfg = get_tenant_oidc(cookie_idp_tenant)
        secret = get_tenant_oidc_secret(cookie_idp_tenant)
        if not (tcfg.configured and tcfg.issuer and tcfg.client_id and secret):
            raise HTTPException(400, "Per-tenant OIDC config was removed mid-flow.")
        idp_issuer = tcfg.issuer
        idp_client_id = tcfg.client_id
        idp_client_secret = secret
    else:
        if not (s.auth_sso_enabled and s.auth_sso_issuer and s.auth_sso_client_id):
            raise HTTPException(400, "OIDC not configured.")
        idp_issuer = s.auth_sso_issuer
        idp_client_id = s.auth_sso_client_id
        idp_client_secret = s.auth_sso_client_secret or ""
    try:
        disc = _discovery(idp_issuer)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"OIDC discovery failed: {exc}") from exc
    redirect_uri = _redirect_uri(request)
    with httpx.Client(timeout=10) as client:
        r = client.post(
            disc["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": idp_client_id,
                "client_secret": idp_client_secret,
            },
            headers={"Accept": "application/json"},
        )
        if r.status_code >= 400:
            raise HTTPException(400, f"Token exchange failed: {r.text[:200]}")
        tok = r.json()
    id_token = tok.get("id_token")
    if not id_token:
        raise HTTPException(400, "IdP did not return an id_token.")
    try:
        ks = _jwks(disc["jwks_uri"])
        claims = JsonWebToken(["RS256", "RS384", "RS512", "ES256", "ES384"]).decode(id_token, ks)
    except Exception as exc:
        raise HTTPException(400, f"id_token verification failed: {exc}") from exc
    # Standard OIDC claim validation.
    iss = claims.get("iss")
    if iss and iss.rstrip("/") != idp_issuer.rstrip("/"):
        raise HTTPException(400, f"Issuer mismatch: {iss}")
    aud = claims.get("aud")
    if isinstance(aud, list):
        aud_ok = idp_client_id in aud
    else:
        aud_ok = aud == idp_client_id
    if not aud_ok:
        raise HTTPException(400, "Audience mismatch.")
    now = int(time.time())
    exp = claims.get("exp")
    if not isinstance(exp, int) or exp <= now:
        raise HTTPException(400, "id_token expired.")
    if cookie_nonce and claims.get("nonce") and claims["nonce"] != cookie_nonce:
        raise HTTPException(400, "Nonce mismatch.")
    email = claims.get("email")
    sub = claims.get("sub")
    if not (email or sub):
        raise HTTPException(400, "id_token missing email and sub.")
    # Optional but valuable: enforce verified email when the IdP reports it.
    if email and claims.get("email_verified") is False:
        raise HTTPException(403, "Email not verified by identity provider.")
    principal = email or sub
    # Tenant routing: explicit cookie hint from /login wins. Otherwise look up
    # by email domain. Fall back to the principal's configured tenant.
    tenant_id: str | None = cookie_tenant_hint
    if not tenant_id and email and "@" in email:
        tenant_id = tenant_for_sso_domain(email.split("@", 1)[1].lower())
    if not tenant_id:
        tenant_id = tenant_for_principal(principal)
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    cookie, _sid = issue_session(
        principal,
        client_ip=client_ip,
        user_agent=user_agent,
        tenant_id=tenant_id,
        auth_method="sso",
    )
    # Domain auto-join. When the resolved tenant configured an auto-join
    # role and this principal's email domain matches the tenant's
    # ``sso_domain``, create a membership on first sign-in. This is the
    # standard "everyone at acme.com is a viewer in the Acme workspace"
    # enterprise SSO behaviour. Existing memberships are never downgraded.
    try:
        if tenant_id and email and "@" in email:
            domain_part = email.split("@", 1)[1].lower()
            cfg = get_sso_config(tenant_id)
            allowed_domains = get_allowed_invite_domains(tenant_id)
            if (
                cfg.auto_join_role
                and cfg.domain
                and cfg.domain == domain_part
                and role_for_member(tenant_id, principal) is None
                and email_matches_allowed_domains(email, allowed_domains)
            ):
                upsert_member(
                    tenant_id=tenant_id,
                    principal=principal,
                    role=cfg.auto_join_role,
                    invited_by="sso:auto-join",
                )
    except Exception:  # noqa: BLE001 - never block sign-in on auto-join issues
        pass
    resp = RedirectResponse("/")
    resp.set_cookie(
        "sc_session", cookie, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30
    )
    for c in ("sc_sso_state", "sc_sso_nonce", "sc_sso_tenant", "sc_sso_idp_tenant"):
        resp.delete_cookie(c, path="/auth/sso")
    return resp


@router.post("/_test/issue", include_in_schema=False)
def _test_issue(request: Request):
    """Test-only shortcut: mint an SSO-marked session without an external IdP.

    Disabled unless ``app_env`` is ``development``. Lets the cross-tenant
    enforce-SSO tests run without standing up Keycloak.
    """
    s = get_settings()
    if s.app_env != "development":
        return JSONResponse({"error": "disabled"}, status_code=404)
    body = request.query_params
    principal = body.get("principal") or "sso-user@example.com"
    tenant_id = body.get("tenant_id") or tenant_for_principal(principal)
    method = body.get("auth_method") or "sso"
    # Mirror the real callback's auto-join behavior for tests.
    try:
        if tenant_id and principal and "@" in principal:
            domain_part = principal.split("@", 1)[1].lower()
            cfg = get_sso_config(tenant_id)
            allowed_domains = get_allowed_invite_domains(tenant_id)
            if (
                cfg.auto_join_role
                and cfg.domain
                and cfg.domain == domain_part
                and role_for_member(tenant_id, principal) is None
                and email_matches_allowed_domains(principal, allowed_domains)
            ):
                upsert_member(
                    tenant_id=tenant_id,
                    principal=principal,
                    role=cfg.auto_join_role,
                    invited_by="sso:auto-join",
                )
    except Exception:  # noqa: BLE001
        pass
    cookie, sid = issue_session(
        principal,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        tenant_id=tenant_id,
        auth_method=method,
    )
    resp = JSONResponse({"sid": sid, "principal": principal, "tenant_id": tenant_id, "auth_method": method})
    resp.set_cookie("sc_session", cookie, httponly=True, samesite="lax")
    return resp
