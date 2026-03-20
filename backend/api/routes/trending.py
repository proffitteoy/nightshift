from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_optional_current_user, get_trending_service
from backend.models.schemas import (
    TrendingAnalysisResponse,
    TrendingDetailSummaryRequest,
    TrendingDetailSummaryResponse,
    TrendingItem,
)
from backend.services.concurrency_guard import ConcurrencyLockTimeoutError
from backend.services.trending_service import TrendingService


router = APIRouter(tags=["trending"])


@router.get("/api/trending/weekly", response_model=List[TrendingItem])
def get_weekly_trending(trending_service: TrendingService = Depends(get_trending_service)) -> List[TrendingItem]:
    try:
        return trending_service.get_weekly_trending()
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "TRENDING_FAILED", "message": str(exc)}) from exc


@router.get("/api/trending/generate-analysis", response_model=TrendingAnalysisResponse)
def trigger_analysis_generation(trending_service: TrendingService = Depends(get_trending_service)) -> TrendingAnalysisResponse:
    try:
        return trending_service.generate_analysis()
    except ConcurrencyLockTimeoutError as exc:
        raise HTTPException(status_code=503, detail={"code": "ANALYSIS_BUSY", "message": str(exc)}) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "ANALYSIS_NOT_FOUND", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "ANALYSIS_FAILED", "message": str(exc)}) from exc


@router.post("/api/trending/detail-summary", response_model=TrendingDetailSummaryResponse)
def generate_trending_detail_summary(
    request: TrendingDetailSummaryRequest,
    current_user: dict | None = Depends(get_optional_current_user),
    trending_service: TrendingService = Depends(get_trending_service),
) -> TrendingDetailSummaryResponse:
    try:
        return trending_service.generate_detail_summary(
            request.model_dump(),
            user_id=int(current_user["id"]) if current_user else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_TRENDING_ITEM", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "TRENDING_DETAIL_SUMMARY_FAILED", "message": str(exc)}) from exc
