"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from shotclassify_common import configure_logging, get_settings
from shotclassify_common.telemetry import instrument_fastapi, setup_telemetry
from shotclassify_common.utils import ensure_dir
from shotclassify_store import init_db

from .middleware.audit import AuditLogMiddleware
from .middleware.auth import APIKeyAndSessionAuth
from .middleware.request_id import RequestIdMiddleware
from .routes import audit as audit_routes
from .routes import auth as auth_routes
from .routes import classify as classify_routes
from .routes import health as health_routes
from .routes import history as history_routes
from .routes import settings as settings_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(level=s.app_log_level, fmt=s.app_log_format)
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Middleware execution order is outer-to-inner in the order added.
    # We want: RequestId (assign id) -> Auth (set principal) -> Audit (record)
    # Starlette runs the LAST-added middleware OUTERMOST, so add Audit last.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(APIKeyAndSessionAuth)
    app.add_middleware(AuditLogMiddleware)
    app.include_router(health_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(classify_routes.router)
    app.include_router(history_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(audit_routes.router)
    storage_root = Path(s.storage_local_dir)
    storage_root.mkdir(parents=True, exist_ok=True)
    app.mount("/blob", StaticFiles(directory=str(storage_root)), name="blob")
    instrument_fastapi(app)
    return app


app = create_app()
