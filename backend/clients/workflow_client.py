"""
workflow_client.py - 讯飞星火工作流 API 代理客户端（带缓存）
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Dict, Iterator

import httpx

LOGGER = logging.getLogger(__name__)

WORKFLOW_API_URL = "https://xingchen-api.xf-yun.com/workflow/v1/chat/completions"
WORKFLOW_TIMEOUT_SECONDS = 120.0
WORKFLOW_INPUT_FIELD = "AGENT-USER-INPUT"

# 缓存配置：同一 user_input 的分析结果缓存 1 小时
CACHE_TTL_SECONDS = 3600

# 从环境变量或直接配置（后续建议迁移到 .env）
DEFAULT_WORKFLOW_API_KEY = "5ebbaf1e24c70fea3c98e52d1b902fd9"
DEFAULT_WORKFLOW_API_SECRET = "ZjFkMWU4Mjg3NzljZDZlMzc4ZTU5Y2I2"
DEFAULT_WORKFLOW_FLOW_ID = "7477665191444942849"

# 内存缓存：{ cache_key: {"result": dict, "timestamp": float} }
_workflow_cache: Dict[str, dict] = {}


def _cache_key(user_input: str) -> str:
    """根据 user_input 生成缓存键（MD5，忽略空白和大小写）。"""
    normalized = user_input.strip().lower()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _get_cached(user_input: str) -> dict | None:
    """从缓存获取结果，过期返回 None。"""
    key = _cache_key(user_input)
    entry = _workflow_cache.get(key)
    if entry is None:
        return None
    if time.time() - entry["timestamp"] > CACHE_TTL_SECONDS:
        del _workflow_cache[key]
        return None
    LOGGER.info("workflow cache hit: %s", user_input[:80])
    return entry["result"]


def _set_cached(user_input: str, result: dict) -> None:
    """将结果写入缓存，最多保留 100 条。"""
    key = _cache_key(user_input)
    _workflow_cache[key] = {"result": result, "timestamp": time.time()}
    if len(_workflow_cache) > 100:
        oldest = min(_workflow_cache, key=lambda k: _workflow_cache[k]["timestamp"])
        del _workflow_cache[oldest]


def _get_workflow_credentials() -> tuple[str, str, str]:
    """获取工作流 API 凭证，优先从环境变量读取。"""
    api_key = os.getenv("WORKFLOW_API_KEY", "").strip() or DEFAULT_WORKFLOW_API_KEY
    api_secret = os.getenv("WORKFLOW_API_SECRET", "").strip() or DEFAULT_WORKFLOW_API_SECRET
    flow_id = os.getenv("WORKFLOW_FLOW_ID", "").strip() or DEFAULT_WORKFLOW_FLOW_ID
    return api_key, api_secret, flow_id


def call_workflow(user_input: str, *, stream: bool = False, use_cache: bool = True) -> dict:
    """
    调用讯飞星火工作流 API，支持结果缓存。

    Args:
        user_input: 用户输入内容（GitHub URL 或自然语言问题）
        stream: 是否使用流式返回（当前默认非流式）
        use_cache: 是否使用缓存（默认 True，传 False 强制重新分析）

    Returns:
        {"code": 0, "message": "Success", "content": "..."} 或错误信息
    """
    # 缓存命中则直接返回
    if use_cache:
        cached = _get_cached(user_input)
        if cached is not None:
            return cached

    api_key, api_secret, flow_id = _get_workflow_credentials()

    if not api_key or not api_secret or not flow_id:
        return {
            "code": -1,
            "message": "工作流 API 凭证未配置",
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
            WORKFLOW_INPUT_FIELD: user_input,
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
                LOGGER.warning("workflow API error: code=%s message=%s", code, error_message)
                return {
                    "code": code,
                    "message": error_message,
                    "content": "",
                }

            choices = result.get("choices", [])
            if not choices:
                return {
                    "code": 0,
                    "message": "Success",
                    "content": "工作流执行完成，但未返回内容",
                }

            delta = choices[0].get("delta", {})
            content = delta.get("content", "")

            response_data = {
                "code": 0,
                "message": "Success",
                "content": content,
            }

            # 成功结果写入缓存
            if use_cache and code == 0:
                _set_cached(user_input, response_data)

            return response_data

    except httpx.TimeoutException:
        LOGGER.error("workflow API timeout after %.0fs", WORKFLOW_TIMEOUT_SECONDS)
        return {
            "code": -2,
            "message": f"工作流执行超时（{WORKFLOW_TIMEOUT_SECONDS}秒），请稍后重试",
            "content": "",
        }
    except httpx.HTTPStatusError as exc:
        LOGGER.error("workflow API HTTP error: status=%s", exc.response.status_code)
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


def stream_workflow(user_input: str) -> Iterator[dict]:
    """流式调用工作流 API（不走缓存）。"""
    api_key, api_secret, flow_id = _get_workflow_credentials()

    if not api_key or not api_secret or not flow_id:
        yield {"type": "error", "message": "workflow API credentials are not configured"}
        return

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}:{api_secret}",
    }
    body = {
        "flow_id": flow_id,
        "stream": True,
        "parameters": {
            WORKFLOW_INPUT_FIELD: user_input,
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
                        line = line[len("data:"):].strip()
                    if not line:
                        continue
                    if line == "[DONE]":
                        yield {"type": "done"}
                        return
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        yield {"type": "message", "content": line}
        yield {"type": "done"}
    except httpx.TimeoutException:
        LOGGER.error("workflow stream timeout")
        yield {"type": "error", "message": "workflow stream timeout"}
    except httpx.HTTPStatusError as exc:
        LOGGER.error("workflow stream HTTP error: status=%s", exc.response.status_code)
        yield {"type": "error", "message": f"workflow API request failed: HTTP {exc.response.status_code}"}
    except Exception as exc:
        LOGGER.error("workflow stream failed: %s", exc)
        yield {"type": "error", "message": f"workflow stream failed: {str(exc)}"}
