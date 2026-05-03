import logging

# 注意：本应用 MAIN_MODEL (v4-pro)，但 v4-pro 在本阶段 schema 下偶发"调 tool 传空参数"
# bug（thinking 块完整、tool_use input={}）。v4-flash 与 deepseek-chat 都正常。
# 暂用 CHEAP_MODEL；待 DeepSeek 修复或换 v5 后再切回 MAIN_MODEL。
from ..config import (
    CHEAP_MODEL,
    ENABLE_PROMPT_CACHING,
    GENRE_ITEM_HEADER,
    GENRE_ITEM_NOUN,
)
from ..llm_client import _client, call_tool_use_with_retry, load_prompt
from ..schemas import AdviceCritique, Critique, Genre, ParsedBook, Synthesis

logger = logging.getLogger(__name__)


CRITIQUE_TOOL = {
    "name": "submit_critique",
    "description": "提交对核心建议的红队批判结果。",
    "input_schema": {
        "type": "object",
        "properties": {
            "per_advice_critique": {
                "type": "array",
                "description": "对每条核心建议的判定，每条建议都要有一条对应记录。",
                "items": {
                    "type": "object",
                    "properties": {
                        "advice_title": {
                            "type": "string",
                            "description": "对应建议标题，必须与输入完全一致",
                        },
                        "verdict": {
                            "type": "string",
                            "description": "三选一: holds（立得住）/ partial（部分立得住）/ disagree（不同意）",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "具体的边界、反例、漏洞分析；至少一个具体反例情境",
                        },
                    },
                    "required": ["advice_title", "verdict", "reasoning"],
                },
            },
            "factual_issues": {
                "type": "array",
                "description": "0-5 条事实性问题，每条一句话",
                "items": {"type": "string"},
            },
            "alternative_books": {
                "type": "array",
                "description": "0-5 本同主题更值得读的书，格式：《书名》· 作者",
                "items": {"type": "string"},
            },
        },
        "required": ["per_advice_critique"],
    },
}


def _build_user_message(
    synthesis: Synthesis, parsed: ParsedBook, genre: Genre
) -> str:
    item_header = GENRE_ITEM_HEADER[genre]
    item_noun = GENRE_ITEM_NOUN[genre]

    parts = [f"书名：《{parsed.metadata.title}》"]
    if parsed.metadata.author:
        parts.append(f"作者：{parsed.metadata.author}")
    parts.append("")
    parts.append(f"核心论点：{synthesis.core_thesis}")
    parts.append(f"目标读者：{synthesis.target_audience}")
    parts.append("")
    parts.append(f"{item_header}：")
    for i, a in enumerate(synthesis.core_advice, 1):
        parts.append(f"\n--- {item_noun} {i}: {a.title} ---")
        parts.append(f"详情：{a.detail}")
        parts.append(f"适用场景：{a.when_applicable}")
        parts.append(f"不适用：{a.when_not_applicable}")
    parts.append("")
    parts.append(
        f"请逐条审视上述每条{item_noun}，调用 submit_critique 工具输出完整结果。"
        f"**严禁传空参数**——per_advice_critique 数组必须包含上述每条{item_noun}的批判，"
        f"advice_title 字段必须与上述{item_noun}标题完全一致。"
    )
    return "\n".join(parts)


def _build_system(system_prompt: str):
    block = {"type": "text", "text": system_prompt}
    if ENABLE_PROMPT_CACHING:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


_VALID_VERDICTS = {"holds", "partial", "disagree"}


def _build_critique(raw: dict, synthesis: Synthesis) -> Critique:
    crits: list[AdviceCritique] = []
    for item in raw.get("per_advice_critique") or []:
        try:
            verdict = item.get("verdict", "")
            if verdict not in _VALID_VERDICTS:
                logger.info(
                    "Stage 6 unknown verdict %r, falling back to 'partial'", verdict
                )
                verdict = "partial"
            crits.append(
                AdviceCritique(
                    advice_title=item["advice_title"],
                    verdict=verdict,
                    reasoning=item.get("reasoning") or "（无具体推理）",
                )
            )
        except Exception as e:
            logger.warning("Stage 6 dropped malformed critique entry: %s", e)

    # 兜底：LLM 漏写某条建议的批判，补 partial 占位
    seen = {c.advice_title for c in crits}
    for a in synthesis.core_advice:
        if a.title not in seen:
            logger.info("Stage 6 LLM omitted critique for %r, filling partial", a.title)
            crits.append(
                AdviceCritique(
                    advice_title=a.title,
                    verdict="partial",
                    reasoning="（LLM 未对该建议给出批判，按部分立得住保守处理）",
                )
            )

    return Critique(
        per_advice_critique=crits,
        factual_issues=raw.get("factual_issues") or [],
        alternative_books=raw.get("alternative_books") or [],
    )


def _fallback_critique(synthesis: Synthesis, reason: str) -> Critique:
    return Critique(
        per_advice_critique=[
            AdviceCritique(
                advice_title=a.title,
                verdict="partial",
                reasoning=f"（批判生成失败：{reason}）",
            )
            for a in synthesis.core_advice
        ],
        factual_issues=[],
        alternative_books=[],
    )


def run(
    synthesis: Synthesis, parsed: ParsedBook, genre: Genre = "practical"
) -> Critique:
    _client()  # API key 缺失早失败

    if not synthesis.core_advice:
        logger.warning("Stage 6: synthesis 没有任何核心建议，跳过 LLM 调用")
        return Critique(per_advice_critique=[], factual_issues=[], alternative_books=[])

    system_prompt = load_prompt(f"critique_{genre}")
    user_msg = _build_user_message(synthesis, parsed, genre)

    try:
        raw, stop_reason = call_tool_use_with_retry(
            model=CHEAP_MODEL,
            system=_build_system(system_prompt),
            messages=[{"role": "user", "content": user_msg}],
            tools=[CRITIQUE_TOOL],
            tool_name=CRITIQUE_TOOL["name"],
            max_tokens=16000,
            max_retries=2,
        )
    except Exception as e:
        logger.warning("Stage 6 LLM call failed: %s", e)
        return _fallback_critique(synthesis, f"LLM 调用失败: {e}")

    if stop_reason == "max_tokens":
        logger.warning("Stage 6 hit max_tokens — critique output may be truncated")

    if not raw:
        logger.warning("Stage 6: 重试后仍未拿到 submit_critique 结果")
        return _fallback_critique(synthesis, "LLM 多次未返回结构化结果")

    return _build_critique(raw, synthesis)
