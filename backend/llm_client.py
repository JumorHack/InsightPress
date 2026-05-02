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


def load_prompt(name: str) -> str:
    from .config import PROMPTS_DIR

    path = PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")
