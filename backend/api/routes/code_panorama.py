from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_code_panorama_service, get_optional_current_user, get_project_service
from backend.api.feature_flags import require_feature_enabled
from backend.models.schemas import CodePanoramaRequest, CodePanoramaResponse, WorkflowAnalysisRequest, WorkflowAnalysisResponse
from backend.services.concurrency_guard import ConcurrencyLockTimeoutError
from backend.services.code_panorama_service import CodePanoramaService
from backend.services.project_service import ProjectService


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


@router.post("/api/repo/workflow-analysis", response_model=WorkflowAnalysisResponse)
def generate_workflow_analysis(
    request: WorkflowAnalysisRequest,
    current_user: dict | None = Depends(get_optional_current_user),
    code_panorama_service: CodePanoramaService = Depends(get_code_panorama_service),
    project_service: ProjectService = Depends(get_project_service),
) -> WorkflowAnalysisResponse:
    require_feature_enabled("code_panorama")
    user_id = int(current_user["id"]) if current_user else None
    token = project_service.get_runtime_token(user_id=user_id)
    try:
        return code_panorama_service.generate_workflow_analysis(
            token=token,
            repo_url=str(request.repo_url),
            depth=request.depth,
            intent=request.intent,
            focus_areas=request.focus_areas,
            queries=request.queries,
        )
    except ConcurrencyLockTimeoutError as exc:
        raise HTTPException(status_code=503, detail={"code": "WORKFLOW_ANALYSIS_BUSY", "message": str(exc)}) from exc
    except (ValueError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail={"code": "WORKFLOW_ANALYSIS_INVALID_REPO", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "WORKFLOW_ANALYSIS_FAILED", "message": str(exc)}) from exc
