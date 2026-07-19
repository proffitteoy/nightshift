"""
workflow_client.py - 讯飞星火工作流 API 代理客户端
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, Iterator

import httpx

LOGGER = logging.getLogger(__name__)

WORKFLOW_API_URL = "https://xingchen-api.xf-yun.com/workflow/v1/chat/completions"
WORKFLOW_TIMEOUT_SECONDS = 120.0

# 从环境变量或直接配置（后续建议迁移到 .env）
DEFAULT_WORKFLOW_API_KEY = "5ebbaf1e24c70fea3c98e52d1b902fd9"
DEFAULT_WORKFLOW_API_SECRET = "ZjFkMWU4Mjg3NzljZDZlMzc4ZTU5Y2I2"
DEFAULT_WORKFLOW_FLOW_ID = "7477665191444942849"


def _get_workflow_credentials() -> tuple[str, str, str]:
    """获取工作流 API 凭证，优先从环境变量读取。"""
    api_key = os.getenv("WORKFLOW_API_KEY", "").strip() or DEFAULT_WORKFLOW_API_KEY
    api_secret = os.getenv("WORKFLOW_API_SECRET", "").strip() or DEFAULT_WORKFLOW_API_SECRET
    flow_id = os.getenv("WORKFLOW_FLOW_ID", "").strip() or DEFAULT_WORKFLOW_FLOW_ID
    return api_key, api_secret, flow_id


def call_workflow(user_input: str, *, stream: bool = False) -> Dict[str, object]:
    """
    调用讯飞星火工作流 API，传入用户输入，返回工作流执行结果。

    Args:
        user_input: 用户输入内容（GitHub URL 或自然语言问题）
        stream: 是否使用流式返回（当前默认非流式）

    Returns:
        工作流 API 返回的完整 JSON 响应
    """
    api_key, api_secret, flow_id = _get_workflow_credentials()

    if not api_key or not api_secret or not flow_id:
        return {
            "code": -1,
            "message": "工作流 API 凭证未配置，请设置 WORKFLOW_API_KEY / WORKFLOW_API_SECRET / WORKFLOW_FLOW_ID",
            "content": "",
        }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}:{api_secret}",
    }

    body = {
        "flow_id": flow_id,
        "stream": stream,
        "parameters": {
            "AGENT_USER_INPUT": user_input,
        },
    }

    try:
        with httpx.Client(timeout=WORKFLOW_TIMEOUT_SECONDS) as client:
            response = client.post(WORKFLOW_API_URL, headers=headers, json=body)
            response.raise_for_status()

            result = response.json()
            code = result.get("code", -1)

            if code != 0:
                error_message = result.get("message", "未知错误")
                LOGGER.warning("workflow API returned error: code=%s message=%s", code, error_message)
                return {
                    "code": code,
                    "message": error_message,
                    "content": "",
                }

            # 从 choices 中提取工作流输出内容
            choices = result.get("choices", [])
            if not choices:
                return {
                    "code": 0,
                    "message": "Success",
                    "content": "工作流执行完成，但未返回内容",
                }

            delta = choices[0].get("delta", {})
            content = delta.get("content", "")

            return {
                "code": 0,
                "message": "Success",
                "content": content,
            }

    except httpx.TimeoutException:
        LOGGER.error("workflow API request timeout after %.0fs", WORKFLOW_TIMEOUT_SECONDS)
        return {
            "code": -2,
            "message": f"工作流执行超时（{WORKFLOW_TIMEOUT_SECONDS}秒），请稍后重试",
            "content": "",
        }
    except httpx.HTTPStatusError as exc:
        LOGGER.error("workflow API HTTP error: status=%s body=%s", exc.response.status_code, exc.response.text[:500])
        return {
            "code": -3,
            "message": f"工作流 API 请求失败: HTTP {exc.response.status_code}",
            "content": "",
        }
    except Exception as exc:
        LOGGER.error("workflow API call failed: %s", exc)
        return {
            "code": -4,
            "message": f"工作流调用异常: {str(exc)}",
            "content": "",
        }


def stream_workflow(user_input: str) -> Iterator[Dict[str, object]]:
    api_key, api_secret, flow_id = _get_workflow_credentials()

    if not api_key or not api_secret or not flow_id:
        yield {
            "type": "error",
            "message": "workflow API credentials are not configured",
        }
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}:{api_secret}",
    }
    body = {
        "flow_id": flow_id,
        "stream": True,
        "parameters": {
            "AGENT_USER_INPUT": user_input,
        },
    }

    try:
        with httpx.Client(timeout=None) as client:
            with client.stream("POST", WORKFLOW_API_URL, headers=headers, json=body) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue

                    line = raw_line.strip()
                    if line.startswith("data:"):
                        line = line[len("data:") :].strip()
                    if not line:
                        continue
                    if line == "[DONE]":
                        yield {"type": "done"}
                        return

                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        yield {
                            "type": "message",
                            "content": line,
                        }

        yield {"type": "done"}
    except httpx.TimeoutException:
        LOGGER.error("workflow stream timeout")
        yield {
            "type": "error",
            "message": "workflow stream timeout",
        }
    except httpx.HTTPStatusError as exc:
        LOGGER.error("workflow stream HTTP error: status=%s body=%s", exc.response.status_code, exc.response.text[:500])
        yield {
            "type": "error",
            "message": f"workflow API request failed: HTTP {exc.response.status_code}",
        }
    except Exception as exc:
        LOGGER.error("workflow stream failed: %s", exc)
        yield {
            "type": "error",
            "message": f"workflow stream failed: {str(exc)}",
        }
