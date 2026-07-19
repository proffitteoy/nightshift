from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.api.dependencies import get_optional_current_user, get_project_service
from backend.models.schemas import (
    DailyReport,
    DeepAnalysisRequest,
    DeepAnalysisResponse,
    ProjectSubscribeResponse,
    RepoReportRequest,
    ReportQaResponse,
    ReportQuestionRequest,
    RepoSubscriptionRequest,
    ReportByUserResponse,
)
from backend.services.concurrency_guard import ConcurrencyLockTimeoutError
from backend.clients.workflow_client import call_workflow, stream_workflow
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


@router.post("/api/project/deep-analysis", response_model=DeepAnalysisResponse)
def deep_analysis(
    request: DeepAnalysisRequest,
    current_user: dict | None = Depends(get_optional_current_user),
) -> DeepAnalysisResponse:
    """
    调用讯飞星火工作流对 GitHub 项目进行深度分析。
    用户输入可以是 GitHub 仓库地址或自然语言问题。
    """
    user_input = str(request.user_input).strip()
    if not user_input:
        raise HTTPException(status_code=400, detail={"code": "EMPTY_INPUT", "message": "输入内容不能为空"})

    result = call_workflow(user_input)

    return DeepAnalysisResponse(
        code=result.get("code", -1),
        message=result.get("message", ""),
        content=result.get("content", ""),
    )


@router.post("/api/project/deep-analysis/stream")
def deep_analysis_stream(
    request: DeepAnalysisRequest,
    current_user: dict | None = Depends(get_optional_current_user),
) -> StreamingResponse:
    user_input = str(request.user_input).strip()
    if not user_input:
        raise HTTPException(status_code=400, detail={"code": "EMPTY_INPUT", "message": "input cannot be empty"})

    def event_stream():
        yield _format_sse({"type": "start", "content": "正在启动工作流分析..."})

        for event in stream_workflow(user_input):
            payload = _normalize_workflow_stream_event(event)
            yield _format_sse(payload)
            if payload.get("type") in {"done", "error"}:
                return

        yield _format_sse({"type": "done"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _normalize_workflow_stream_event(event: dict) -> dict:
    if not isinstance(event, dict):
        return {"type": "message", "content": str(event)}

    event_type = str(event.get("type") or "").strip()
    if event_type in {"done", "error"}:
        return event

    choices = event.get("choices") or []
    delta = {}
    if choices and isinstance(choices[0], dict):
        delta = choices[0].get("delta") or {}

    workflow_step = event.get("workflow_step") or event.get("workflowStep") or {}
    content = (
        delta.get("content")
        or event.get("content")
        or event.get("message")
        or ""
    )

    payload = {
        "type": "message",
        "content": str(content),
    }
    if isinstance(workflow_step, dict):
        if workflow_step.get("seq") is not None:
            payload["seq"] = workflow_step.get("seq")
        if workflow_step.get("progress") is not None:
            payload["progress"] = workflow_step.get("progress")
        if workflow_step.get("name") is not None:
            payload["stage"] = workflow_step.get("name")

    return payload
