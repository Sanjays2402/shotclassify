"""Prometheus /metrics scrape endpoint."""
from __future__ import annotations

from fastapi import APIRouter

from ..middleware.metrics import metrics_response

router = APIRouter(tags=["observability"])


@router.get("/metrics")
def metrics():
    return metrics_response()
