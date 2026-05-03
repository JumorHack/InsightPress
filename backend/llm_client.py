import os
from functools import lru_cache

from anthropic import Anthropic


@lru_cache(maxsize=1)
def _client() -> Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY 未设置。请复制 .env.example 为 .env 并填入 key。"
        )
    kwargs: dict = {"api_key": api_key}
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return Anthropic(**kwargs)


def call(
    *,
    model: str,
    messages: list[dict],
    system: str | list | None = None,
    max_tokens: int = 4096,
    tools: list[dict] | None = None,
    tool_choice: dict | None = None,
):
    """所有 Anthropic API 调用必须经过这里 — 便于统一加日志、retry、prompt caching。"""
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        kwargs["system"] = system
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    return _client().messages.create(**kwargs)


def call_tool_use_with_retry(
    *,
    model: str,
    messages: list[dict],
    tools: list[dict],
    tool_name: str,
    system: str | list | None = None,
    max_tokens: int = 16000,
    max_retries: int = 2,
):
    """调 LLM 强制使用某个 tool；如果返回的 tool_use input 为空，自动重试。

    DeepSeek 的 reasoning 模型偶发"调 tool 但传空参数"（thinking 完整、input={}），
    这是 transient bug。重试通常能拿到非空结果。

    返回 (input_dict, stop_reason)。最终仍为空时返回 ({}, last_stop_reason)。
    """
    import logging

    logger = logging.getLogger(__name__)
    last_resp = None
    for attempt in range(max_retries + 1):
        resp = call(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice={"type": "any"},
            max_tokens=max_tokens,
        )
        last_resp = resp
        for block in resp.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == tool_name
                and block.input
            ):
                return block.input, resp.stop_reason
        if attempt < max_retries:
            logger.warning(
                "LLM 返回空 tool_use input (tool=%s)，重试 %d/%d",
                tool_name,
                attempt + 1,
                max_retries,
            )
    return {}, getattr(last_resp, "stop_reason", None)


def load_prompt(name: str) -> str:
    from .config import PROMPTS_DIR

    path = PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")
