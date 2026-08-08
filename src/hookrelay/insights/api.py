"""Insights REST router — delivery insights endpoints with 422 validation.

Mounted flat in ``create_app`` and token-protected by the existing auth
middleware. Validation errors use the repo's manual-422 pattern (same as
``/api/dashboard/metrics``), never FastAPI's default validation body.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from hookrelay import _storage
from hookrelay.insights.service import (
    InsightsService,
    parse_bucket,
    parse_window,
)

_VALID_METRICS = ("deliveries", "success_rate", "latency_p95")


def _get_service() -> InsightsService:
    store = _storage.get()
    if store is None:
        from hookrelay.server import _get_or_create_storage

        store = _get_or_create_storage()
    return InsightsService(store)


def create_insights_router() -> APIRouter:
    """Build the insights REST router (endpoints + timeseries)."""
    router = APIRouter()

    @router.get("/api/insights/endpoints")
    async def insights_endpoints(window: str = "24h") -> dict[str, Any]:
        """Return per-endpoint delivery stats; 422 on invalid window."""
        try:
            parse_window(window)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="window must be one of 15m, 1h, 24h, 7d",
            )
        return {
            "window": window,
            "endpoints": _get_service().endpoints(window),
        }

    @router.get("/api/insights/timeseries")
    async def insights_timeseries(
        metric: str = "deliveries",
        window: str = "24h",
        bucket: str = "hourly",
    ) -> dict[str, Any]:
        """Return bucketed time series; 422 on invalid metric/window/bucket."""
        if metric not in _VALID_METRICS:
            raise HTTPException(
                status_code=422,
                detail="metric must be one of deliveries, success_rate, latency_p95",
            )
        try:
            parse_window(window)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="window must be one of 15m, 1h, 24h, 7d",
            )
        try:
            parse_bucket(bucket)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="bucket must be one of hourly, daily",
            )
        return {
            "metric": metric,
            "window": window,
            "bucket": bucket,
            "buckets": _get_service().timeseries(metric, window, bucket),
        }

    return router
