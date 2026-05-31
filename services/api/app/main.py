"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from shotclassify_common import (
    configure_logging,
    get_settings,
    init_sentry,
    validate_for_production,
)
from shotclassify_common.telemetry import instrument_fastapi, setup_telemetry
from shotclassify_common.utils import ensure_dir
from shotclassify_store import init_db

from .middleware.audit import AuditLogMiddleware
from .middleware.auth import APIKeyAndSessionAuth
from .middleware.ip_allowlist import IPAllowlistMiddleware
from .middleware.metrics import PrometheusMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.request_id import RequestIdMiddleware
from .middleware.security_headers import SecurityHeadersMiddleware
from .middleware.tenant import TenantResolutionMiddleware
from .routes import audit as audit_routes
from .routes import auth as auth_routes
from .routes import classify as classify_routes
from .routes import health as health_routes
from .routes import history as history_routes
from .routes import me as me_routes
from .routes import usage as usage_routes
from .routes import metrics as metrics_routes
from .routes import saved_views as saved_views_routes
from .routes import security_settings as security_settings_routes
from .routes import sessions as sessions_routes
from .routes import settings as settings_routes
from .routes import sso as sso_routes
from .routes import mfa as mfa_routes
from .routes import api_keys as api_keys_routes
from .routes import memberships as memberships_routes
from .routes import workspace_data as workspace_data_routes
from .routes import admin as admin_routes
from .routes import webhooks as webhooks_routes
from .routes import scim as scim_routes
from .routes import scim_admin as scim_admin_routes
from .routes import subprocessors as subprocessors_routes
from .routes import incidents as incidents_routes
from .routes import support_access as support_access_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(level=s.app_log_level, fmt=s.app_log_format)
    # Fail fast if production/staging is missing required secrets or has the
    # dev API key / wildcard CORS / sqlite still in place. No-op in dev.
    validate_for_production(s)
    init_sentry(service_name="shotclassify-api")
    setup_telemetry(service_name="shotclassify-api")
    init_db()
    ensure_dir(s.storage_local_dir)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="ShotClassify API",
        version="0.1.0",
        description="Screenshot classifier with vision LLM + OCR.",
        lifespan=lifespan,
    )
    # CORS allowlist. Wildcard origins are only honored in development; any
    # other environment requires an explicit comma-separated list so we never
    # ship a production API with ``Access-Control-Allow-Origin: *`` in front
    # of authenticated routes.
    raw_origins = [o.strip() for o in s.cors_allowed_origins.split(",") if o.strip()]
    if s.app_env == "development":
        origins = raw_origins or ["*"]
    else:
        origins = [o for o in raw_origins if o != "*"]
        if not origins:
            # Fail closed: no origins means no cross-origin browser traffic.
            origins = []
    allow_methods = [m.strip() for m in s.cors_allowed_methods.split(",") if m.strip()]
    allow_headers = [h.strip() for h in s.cors_allowed_headers.split(",") if h.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=s.cors_allow_credentials and "*" not in origins,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    # Middleware execution order is outer-to-inner in the order added.
    # We want: RequestId (assign id) -> Auth (set principal) -> Audit (record)
    # Starlette runs the LAST-added middleware OUTERMOST, so add Audit last.
    # Order: outermost middleware is added last. We want Prometheus outermost
    # so it observes every response status (including auth 401s), then Audit,
    # then Auth, then RequestId innermost so the request_id contextvar is set
    # before audit/auth log handlers fire.
    app.add_middleware(RequestIdMiddleware)
    # IP allowlist runs AFTER tenant resolution on the inbound path; with
    # Starlette's outer-to-inner add semantics that means add it BEFORE
    # TenantResolutionMiddleware so it ends up more inner.
    app.add_middleware(IPAllowlistMiddleware)
    # Tenant resolution must run AFTER auth on the inbound path so it sees
    # request.state.principal/role. Starlette runs LAST-added middleware
    # OUTERMOST, so add Tenant before Auth (Tenant is inner -> runs after
    # Auth on the way in). Audit and Prometheus stay outermost so they still
    # observe 401s from auth.
    app.add_middleware(TenantResolutionMiddleware)
    app.add_middleware(APIKeyAndSessionAuth)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AuditLogMiddleware)
    app.add_middleware(PrometheusMiddleware)
    # SecurityHeadersMiddleware is added last so it ends up OUTERMOST and
    # decorates every response (including 401s from auth and 429s from rate
    # limiting) with the baseline security headers.
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health_routes.router)
    app.include_router(metrics_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(classify_routes.router)
    app.include_router(history_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(audit_routes.router)
    app.include_router(me_routes.router)
    app.include_router(usage_routes.router)
    app.include_router(saved_views_routes.router)
    app.include_router(security_settings_routes.router)
    app.include_router(sessions_routes.router)
    app.include_router(sso_routes.router)
    app.include_router(mfa_routes.router)
    app.include_router(api_keys_routes.router)
    app.include_router(memberships_routes.router)
    app.include_router(workspace_data_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(webhooks_routes.router)
    app.include_router(scim_routes.router)
    app.include_router(scim_admin_routes.router)
    app.include_router(subprocessors_routes.router)
    app.include_router(incidents_routes.router)
    app.include_router(support_access_routes.router)
    app.include_router(support_access_routes.admin_router)
    storage_root = Path(s.storage_local_dir)
    storage_root.mkdir(parents=True, exist_ok=True)
    app.mount("/blob", StaticFiles(directory=str(storage_root)), name="blob")
    instrument_fastapi(app)
    return app


app = create_app()
