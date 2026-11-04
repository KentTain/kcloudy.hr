"""ai 通道 LLM 客户端（hr → ai inner 零依赖消费）

经通用 LLM API `/ai/inner/v1/llm/chat/completions` 调租户平台模型
（model=逻辑名 default，服务端经平台设置槽位路由）。基地址解析对齐
hermes ai_inner_client 先例：环境变量 AI_INNER_BASE > 本体 server.port 推导。
AI 失败不阻断业务主流程——异常透传由调用方决定降级姿势。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_TIMEOUT_SECONDS = 90.0


def _default_ai_inner_base() -> str:
    env_base = os.getenv("AI_INNER_BASE")
    if env_base:
        return env_base.rstrip("/")
    try:
        from framework.configs import get_settings

        return f"http://127.0.0.1:{get_settings().server.port}"
    except Exception:
        return "http://127.0.0.1:8080"


async def llm_chat(
    tenant_id: str,
    messages: list[dict[str, str]],
    *,
    model: str = "default",
    timeout: float = _TIMEOUT_SECONDS,
) -> str:
    """非流式 chat completion，返回首条回复文本。

    HTTP/包络/模型路由失败均抛异常（httpx.HTTPError / RuntimeError）。
    """
    base = _default_ai_inner_base()
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            "/ai/inner/v1/llm/chat/completions",
            headers={"X-Tenant-Id": tenant_id, "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "stream": False},
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"ai inner llm 调用失败 status={response.status_code} body={response.text[:200]}"
        )
    data: dict[str, Any] = response.json()
    error = data.get("error")
    if error:
        raise RuntimeError(f"ai inner llm 返回错误: {error}")
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("ai inner llm 返回空 choices")
    content = choices[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError("ai inner llm 返回空 content")
    return str(content)
