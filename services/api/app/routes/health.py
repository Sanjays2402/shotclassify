from fastapi import APIRouter

from shotclassify_common import get_settings
from shotclassify_store import init_db

router = APIRouter(tags=["health"])


@router.get("/")
def root():
    return {"service": "shotclassify", "version": "0.1.0"}


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/readyz")
def readyz():
    s = get_settings()
    try:
        init_db()
        db = "ok"
    except Exception as exc:
        db = f"error: {exc}"
    return {
        "status": "ready" if db == "ok" else "degraded",
        "db": db,
        "llm_base_url": s.llm_base_url,
        "queue": s.redis_url,
    }
