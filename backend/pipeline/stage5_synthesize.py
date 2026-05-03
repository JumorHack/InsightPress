import logging

from ..config import ENABLE_PROMPT_CACHING, MAIN_MODEL
from ..llm_client import _client, call, load_prompt
from ..schemas import (
    ChunkExtraction,
    ChunkSet,
    CoreAdvice,
    Quote,
    Synthesis,
)

logger = logging.getLogger(__name__)


SYNTHESIS_TOOL = {
    "name": "submit_synthesis",
    "description": "提交合成结果：核心论点、目标读者、3-5 条核心建议。",
    "input_schema": {
        "type": "object",
        "properties": {
            "core_thesis": {
                "type": "string",
                "description": "整本书的核心论点，2-4 句话概括。",
            },
            "target_audience": {
                "type": "string",
                "description": "这本书最适合什么人读，要具体（不能是'想成长的人'这种万能描述）。",
            },
            "core_advice": {
                "type": "array",
                "description": "3-5 条核心建议；宁少勿滥。",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "10 字以内的标题",
                        },
                        "detail": {
                            "type": "string",
                            "description": "如何执行该建议；必须具体到可操作（含具体动作/频率/场景）",
                        },
                        "when_applicable": {
                            "type": "string",
                            "description": "什么具体情境下适用",
                        },
                        "when_not_applicable": {
                            "type": "string",
                            "description": "什么情况下不适用；不能写'任何时候都适用'",
                        },
                        "evidence_quotes": {
                            "type": "array",
                            "description": "1-2 条原文金句作为证据，必须从输入 quotes 池中选；找不到就留空数组。",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string"},
                                    "chapter": {"type": "string"},
                                    "source_span": {"type": "string"},
                                },
                                "required": ["text", "source_span"],
                            },
                        },
                        "source_chapters": {
                            "type": "array",
                            "description": "该建议主要来自的 1-3 个章节名",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "title",
                        "detail",
                        "when_applicable",
                        "when_not_applicable",
                    ],
                },
            },
        },
        "required": ["core_thesis", "target_audience", "core_advice"],
    },
}


def _build_user_message(
    extractions: list[ChunkExtraction], chunks: ChunkSet
) -> str | None:
    chunk_by_id = {c.chunk_id: c for c in chunks.chunks}
    parts: list[str] = []

    for ext in extractions:
        if not (ext.principles or ext.evidence or ext.quotes or ext.claims):
            continue
        chunk = chunk_by_id.get(ext.chunk_id)
        chapter = (chunk.chapter_title if chunk else "") or "(未知章节)"
        block = [f"【块 {ext.chunk_id} / 章节: {chapter}】"]
        if ext.principles:
            block.append("原则：")
            for p in ext.principles:
                block.append(f'  - {p.statement}（原文："{p.source_span}"）')
        if ext.evidence:
            block.append("证据：")
            for e in ext.evidence:
                block.append(f'  - {e.text}（原文："{e.source_span}"）')
        if ext.quotes:
            block.append("金句：")
            for q in ext.quotes:
                block.append(f'  - "{q.text}"（原文："{q.source_span}"）')
        if ext.claims:
            block.append("论断：")
            for c in ext.claims:
                block.append(f'  - {c.text}（原文："{c.source_span}"）')
        parts.append("\n".join(block))

    if not parts:
        return None
    return "\n\n".join(parts)


def _build_system(system_prompt: str):
    block = {"type": "text", "text": system_prompt}
    if ENABLE_PROMPT_CACHING:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


def _extract_tool_input(resp) -> dict:
    for block in resp.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == SYNTHESIS_TOOL["name"]
        ):
            return block.input or {}
    return {}


def _build_synthesis(raw: dict) -> Synthesis:
    advice_list: list[CoreAdvice] = []
    for a in raw.get("core_advice", []):
        evidence_quotes: list[Quote] = []
        for q in a.get("evidence_quotes", []) or []:
            try:
                evidence_quotes.append(Quote(**q))
            except Exception as e:
                logger.info("Stage 5 dropped malformed quote: %s", e)
        try:
            advice_list.append(
                CoreAdvice(
                    title=a["title"],
                    detail=a["detail"],
                    when_applicable=a["when_applicable"],
                    when_not_applicable=a["when_not_applicable"],
                    evidence_quotes=evidence_quotes,
                    source_chapters=a.get("source_chapters", []) or [],
                )
            )
        except Exception as e:
            logger.warning("Stage 5 dropped malformed advice: %s", e)

    return Synthesis(
        core_thesis=raw.get("core_thesis") or "（合成结果缺失核心论点）",
        target_audience=raw.get("target_audience") or "（合成结果缺失目标读者）",
        core_advice=advice_list,
    )


def _empty_synthesis(reason: str) -> Synthesis:
    return Synthesis(
        core_thesis=f"（无法合成：{reason}）",
        target_audience="（未识别）",
        core_advice=[],
    )


def run(extractions: list[ChunkExtraction], chunks: ChunkSet) -> Synthesis:
    _client()  # API key 缺失早失败

    user_msg = _build_user_message(extractions, chunks)
    if user_msg is None:
        logger.warning("Stage 5: 无任何有效抽取材料")
        return _empty_synthesis("未抽取到任何有效原则/证据/金句")

    system_prompt = load_prompt("synthesize")

    try:
        resp = call(
            model=MAIN_MODEL,
            system=_build_system(system_prompt),
            messages=[{"role": "user", "content": user_msg}],
            tools=[SYNTHESIS_TOOL],
            tool_choice={"type": "any"},
            max_tokens=16000,
        )
    except Exception as e:
        logger.warning("Stage 5 LLM call failed: %s", e)
        return _empty_synthesis(f"LLM 调用失败: {e}")

    if getattr(resp, "stop_reason", None) == "max_tokens":
        logger.warning("Stage 5 hit max_tokens — synthesis output may be truncated")

    raw = _extract_tool_input(resp)
    if not raw:
        logger.warning("Stage 5: response had no submit_synthesis tool_use block")
        return _empty_synthesis("LLM 未返回结构化结果")

    return _build_synthesis(raw)
