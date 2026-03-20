from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.dependencies import get_optional_current_user, get_project_service
from backend.models.schemas import (
    DailyReport,
    ProjectSubscribeResponse,
    RepoReportRequest,
    ReportQaResponse,
    ReportQuestionRequest,
    RepoSubscriptionRequest,
    ReportByUserResponse,
)
from backend.services.concurrency_guard import ConcurrencyLockTimeoutError
from backend.services.project_service import ProjectService


router = APIRouter(tags=["project"])


@router.post("/api/project/subscribe", response_model=ProjectSubscribeResponse)
def subscribe_to_project(
    request: RepoSubscriptionRequest,
    current_user: dict | None = Depends(get_optional_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ProjectSubscribeResponse:
    user_id = int(current_user["id"]) if current_user else None
    token = project_service.get_runtime_token(user_id=user_id)
    try:
        result = project_service.subscribe_project(
            token=token,
            repo_url=str(request.repo_url),
            user_id=user_id,
        )
    except ConcurrencyLockTimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "SUBSCRIBE_BUSY", "message": str(exc)},
        ) from exc
    except (ValueError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_REPO", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "SUBSCRIBE_FAILED", "message": str(exc)}) from exc

    message = f"subscription completed for '{result['repository']}'"
    if result.get("used_fallback_snapshot"):
        message = f"subscription completed for '{result['repository']}' (anonymous fallback snapshot)"

    return {
        "message": message,
        "data_file": result["data_file"],
    }


@router.get("/api/project/daily-report", response_model=DailyReport)
def get_daily_report(
    current_user: dict | None = Depends(get_optional_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> DailyReport:
    try:
        return project_service.generate_daily_report(
            user_id=int(current_user["id"]) if current_user else None,
        )
    except ConcurrencyLockTimeoutError as exc:
        raise HTTPException(status_code=503, detail={"code": "REPORT_BUSY", "message": str(exc)}) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": "DATA_NOT_FOUND", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "REPORT_FAILED", "message": str(exc)}) from exc


@router.post("/api/project/report-by-user", response_model=ReportByUserResponse)
def report_by_user(
    request: RepoReportRequest,
    current_user: dict | None = Depends(get_optional_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ReportByUserResponse:
    user_id = int(current_user["id"]) if current_user else None
    token = project_service.get_runtime_token(user_id=user_id)
    try:
        result = project_service.generate_report_by_user(
            token=token,
            repo_url=str(request.repo_url),
            user_id=user_id,
        )
    except ConcurrencyLockTimeoutError as exc:
        raise HTTPException(status_code=503, detail={"code": "REPORT_BUSY", "message": str(exc)}) from exc
    except (ValueError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_REPO", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "REPORT_FAILED", "message": str(exc)}) from exc

    message = "report generated successfully"
    if result.get("used_fallback_snapshot"):
        message = "report generated with fallback snapshot (建议配置 GITHUB_TOKEN 以获取可比较提交差异)"

    return {
        "message": message,
        "report": result["report"],
        "data_file": result["data_file"],
    }


@router.post("/api/project/report-qa", response_model=ReportQaResponse)
def report_qa(
    request: ReportQuestionRequest,
    current_user: dict | None = Depends(get_optional_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> ReportQaResponse:
    try:
        return project_service.answer_report_question(
            report=request.report.model_dump(by_alias=True),
            question=request.question,
            repo_url=str(request.repo_url) if request.repo_url else None,
            user_id=int(current_user["id"]) if current_user else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_REPORT", "message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "REPORT_QA_FAILED", "message": str(exc)}) from exc
