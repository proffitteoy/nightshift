from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_code_panorama_service
from backend.api.feature_flags import require_feature_enabled
from backend.models.schemas import CodePanoramaRequest, CodePanoramaResponse
from backend.services.concurrency_guard import ConcurrencyLockTimeoutError
from backend.services.code_panorama_service import CodePanoramaService


router = APIRouter(tags=["code_panorama"])


@router.post("/api/repo/code-panorama", response_model=CodePanoramaResponse)
def generate_code_panorama(
    request: CodePanoramaRequest,
    code_panorama_service: CodePanoramaService = Depends(get_code_panorama_service),
) -> CodePanoramaResponse:
    require_feature_enabled("code_panorama")
    try:
        return code_panorama_service.generate_panorama(
            repo_url=str(request.repo_url),
            depth=request.depth,
            entry_hint=request.entry_hint,
        )
    except ConcurrencyLockTimeoutError as exc:
        raise HTTPException(status_code=503, detail={"code": "PANORAMA_BUSY", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_REPO_URL", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "PANORAMA_FAILED", "message": str(exc)}) from exc
