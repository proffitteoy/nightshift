from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.clients.llm_client import LLMClient
from backend.prompts import render_prompt


router = APIRouter(tags=["llm_proxy"])


class LLMProxyRequest(BaseModel):
    prompt_name: Optional[str] = Field(default=None, max_length=120)
    prompt: Optional[str] = Field(default=None, max_length=20000)
    prompt_vars: Optional[Dict[str, object]] = None
    config_overrides: Optional[Dict[str, object]] = None


class LLMProxyResponse(BaseModel):
    answer: str


@router.post("/api/llm/generate", response_model=LLMProxyResponse)
def generate_llm(
    request: LLMProxyRequest,
) -> LLMProxyResponse:
    # Build prompt: prefer explicit prompt, else use named prompt with vars
    prompt_text = None
    prompt_name = request.prompt_name
    try:
        if request.prompt and str(request.prompt).strip():
            prompt_text = str(request.prompt)
            prompt_name = prompt_name or "custom"
        elif prompt_name:
            vars_map = request.prompt_vars or {}
            prompt_text = render_prompt(prompt_name, **vars_map)
        else:
            raise HTTPException(status_code=400, detail={"code": "MISSING_PROMPT", "message": "prompt or prompt_name required"})

        client = LLMClient(config_overrides=request.config_overrides or {}, use_env_overrides=True)
        answer = client._call_openai_compatible(prompt_name=prompt_name or "custom", prompt=prompt_text)
        return LLMProxyResponse(answer=answer or "")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "LLM_PROXY_FAILED", "message": str(exc)}) from exc
