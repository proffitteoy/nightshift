from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_code_panorama_service, get_optional_current_user, get_project_service
from backend.api.feature_flags import require_feature_enabled
from backend.models.schemas import (
    CodePanoramaRequest,
    CodePanoramaResponse,
    RepoContextQaRequest,
    RepoContextQaResponse,
    RepoContextRequest,
    RepoContextResponse,
    WorkflowAnalysisRequest,
    WorkflowAnalysisResponse,
)
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


@router.post("/api/repo/context", response_model=RepoContextResponse)
def generate_repo_context(
    request: RepoContextRequest,
    current_user: dict | None = Depends(get_optional_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> RepoContextResponse:
    user_id = int(current_user["id"]) if current_user else None
    token = project_service.get_runtime_token(user_id=user_id)
    try:
        result = project_service.generate_repo_context(
            token=token,
            repo_url=str(request.repo_url),
            question=request.question,
            intent=request.intent,
            hours=request.hours,
            context_mode=request.context_mode,
            max_context_chars=request.max_context_chars,
            max_evidence_items=request.max_evidence_items,
            include_raw=request.include_raw,
            cache_ttl_seconds=request.cache_ttl_seconds,
            force_refresh=request.force_refresh,
            user_id=user_id,
        )
        return _build_repo_context_response(result, message="repo context generated")
    except ConcurrencyLockTimeoutError as exc:
        raise HTTPException(status_code=503, detail={"code": "REPO_CONTEXT_BUSY", "message": str(exc)}) from exc
    except (ValueError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail={"code": "REPO_CONTEXT_INVALID_REPO", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "REPO_CONTEXT_FAILED", "message": str(exc)}) from exc


@router.post("/api/repo/context-qa", response_model=RepoContextQaResponse)
def answer_repo_context_question(
    request: RepoContextQaRequest,
    current_user: dict | None = Depends(get_optional_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> RepoContextQaResponse:
    user_id = int(current_user["id"]) if current_user else None
    token = project_service.get_runtime_token(user_id=user_id)
    try:
        result = project_service.answer_repo_context_question(
            token=token,
            repo_url=str(request.repo_url),
            question=request.question,
            hours=request.hours,
            context_mode=request.context_mode,
            max_context_chars=request.max_context_chars,
            max_evidence_items=request.max_evidence_items,
            include_raw=request.include_raw,
            cache_ttl_seconds=request.cache_ttl_seconds,
            force_refresh=request.force_refresh,
            user_id=user_id,
        )
        response = _build_repo_context_response(result, message="repo context question answered")
        response["answer"] = str(result.get("answer", "") or "")
        response["answer_source"] = str(result.get("answer_source", "") or "rules")
        return response
    except ConcurrencyLockTimeoutError as exc:
        raise HTTPException(status_code=503, detail={"code": "REPO_CONTEXT_BUSY", "message": str(exc)}) from exc
    except (ValueError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail={"code": "REPO_CONTEXT_INVALID_REPO", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "REPO_CONTEXT_QA_FAILED", "message": str(exc)}) from exc


def _build_repo_context_response(result: dict, *, message: str) -> dict:
    include_raw = bool(result.get("include_raw", False))
    if include_raw:
        context = {key: value for key, value in result.items() if key not in {"answer", "answer_source"}}
    else:
        context = {
            "repository": result.get("repository", "unknown/unknown"),
            "repo_url": result.get("repo_url", ""),
            "description": result.get("description", ""),
            "default_branch": result.get("default_branch", ""),
            "topics": result.get("topics", []),
            "auth_mode": result.get("auth_mode", ""),
            "hours": result.get("hours", 72),
            "generated_at": result.get("generated_at", ""),
        }
    return {
        "message": message,
        "repository": str(result.get("repository", "unknown/unknown") or "unknown/unknown"),
        "repo_url": str(result.get("repo_url", "") or ""),
        "source": str(result.get("source", "") or "github"),
        "context": context,
        "context_quality": str(result.get("context_quality", "") or "weak"),
        "analysis_prompt_context": str(result.get("analysis_prompt_context", "") or ""),
        "repo_summary_text": str(result.get("repo_summary_text", "") or ""),
        "recent_changes_text": str(result.get("recent_changes_text", "") or ""),
        "evidence_blocks": result.get("evidence_blocks", []) if isinstance(result.get("evidence_blocks"), list) else [],
        "omitted_evidence_count": int(result.get("omitted_evidence_count", 0) or 0),
        "missing_context": result.get("missing_context", []) if isinstance(result.get("missing_context"), list) else [],
        "readme_text": str(result.get("readme_text", "") or ""),
        "root_entries_text": str(result.get("root_entries_text", "") or ""),
        "changed_files_text": str(result.get("changed_files_text", "") or ""),
        "recent_prs_text": str(result.get("recent_prs_text", "") or ""),
        "recent_commits_text": str(result.get("recent_commits_text", "") or ""),
        "merged_context": str(result.get("merged_context", "") or ""),
    }
