import logging
from concurrent.futures import ThreadPoolExecutor

from ..config import CHEAP_MODEL, ENABLE_PROMPT_CACHING, MAP_PHASE_CONCURRENCY
from ..llm_client import _client, call_tool_use_with_retry, load_prompt
from ..schemas import (
    Chunk,
    ChunkExtraction,
    ChunkSet,
    Claim,
    Evidence,
    Genre,
    Principle,
    Quote,
)
from ..utils.source_span import validate_span

logger = logging.getLogger(__name__)


EXTRACT_TOOL = {
    "name": "submit_extraction",
    "description": "提交从书籍片段中抽取的结构化材料。",
    "input_schema": {
        "type": "object",
        "properties": {
            "principles": {
                "type": "array",
                "description": "作者明确提出的、可执行的原则或方法。",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {
                            "type": "string",
                            "description": "原则陈述（你自己的概括）",
                        },
                        "source_span": {
                            "type": "string",
                            "description": "5-30 字的原文 substring，必须严格出自 <text>",
                        },
                    },
                    "required": ["statement", "source_span"],
                },
            },
            "evidence": {
                "type": "array",
                "description": "支撑原则的具体案例、数据、故事。",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "source_span": {"type": "string"},
                    },
                    "required": ["text", "source_span"],
                },
            },
            "quotes": {
                "type": "array",
                "description": "值得直接引用的短句（≤25 汉字 / ≤15 英文词）。",
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
            "claims": {
                "type": "array",
                "description": "作者的事实性论断，后续可能需要核查。",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "source_span": {"type": "string"},
                    },
                    "required": ["text", "source_span"],
                },
            },
        },
        "required": ["principles", "evidence", "quotes", "claims"],
    },
}


def _build_user_message(chunk: Chunk) -> str:
    return (
        f"<chunk_id>{chunk.chunk_id}</chunk_id>\n"
        f"<chapter_title>{chunk.chapter_title or ''}</chapter_title>\n"
        f"<context_before>{chunk.context_before}</context_before>\n"
        f"<text>\n{chunk.text}\n</text>"
    )


def _filter_valid(items: list[dict], source: str) -> list[dict]:
    return [it for it in items if validate_span(it.get("source_span", ""), source)]


def _build_system(system_prompt: str):
    block = {"type": "text", "text": system_prompt}
    if ENABLE_PROMPT_CACHING:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


def _extract_chunk(chunk: Chunk, system_prompt: str) -> ChunkExtraction:
    user_msg = _build_user_message(chunk)
    try:
        # v4-flash 偶发"调 tool 但传空参数"，retry 自动应对；max_tokens 给足以防被
        # thinking 占满后 tool_use input 截断（截断也表现为空 input）。
        raw, stop_reason = call_tool_use_with_retry(
            model=CHEAP_MODEL,
            system=_build_system(system_prompt),
            messages=[{"role": "user", "content": user_msg}],
            tools=[EXTRACT_TOOL],
            tool_name=EXTRACT_TOOL["name"],
            max_tokens=16000,
            # 多给点重试名额：v4-flash 偶有连续 2-3 次空 input 的运气问题；
            # 单 chunk 失败会让整本书评跑空，所以这里宁可多花几次 token。
            max_retries=4,
        )
    except Exception as e:
        logger.warning("Stage 4 LLM call failed for %s: %s", chunk.chunk_id, e)
        return ChunkExtraction(chunk_id=chunk.chunk_id)

    if stop_reason == "max_tokens":
        logger.warning(
            "Stage 4 hit max_tokens for %s — output truncated, may be incomplete",
            chunk.chunk_id,
        )
    if not raw:
        logger.warning("Stage 4 empty extraction for %s after retries", chunk.chunk_id)
        return ChunkExtraction(chunk_id=chunk.chunk_id)

    src = chunk.text

    valid_principles = _filter_valid(raw.get("principles", []), src)
    valid_evidence = _filter_valid(raw.get("evidence", []), src)
    valid_quotes = _filter_valid(raw.get("quotes", []), src)
    valid_claims = _filter_valid(raw.get("claims", []), src)

    dropped = (
        len(raw.get("principles", [])) - len(valid_principles)
        + len(raw.get("evidence", [])) - len(valid_evidence)
        + len(raw.get("quotes", [])) - len(valid_quotes)
        + len(raw.get("claims", [])) - len(valid_claims)
    )
    if dropped:
        logger.info("Stage 4 dropped %d items in %s due to invalid source_span", dropped, chunk.chunk_id)

    try:
        return ChunkExtraction(
            chunk_id=chunk.chunk_id,
            principles=[Principle(**p) for p in valid_principles],
            evidence=[Evidence(**e) for e in valid_evidence],
            quotes=[Quote(**q) for q in valid_quotes],
            claims=[Claim(**c) for c in valid_claims],
        )
    except Exception as e:
        logger.warning("Stage 4 schema validation failed for %s: %s", chunk.chunk_id, e)
        return ChunkExtraction(chunk_id=chunk.chunk_id)


def run(chunks: ChunkSet, genre: Genre = "practical") -> list[ChunkExtraction]:
    # 失败前置：API key 缺失立即抛错，不要等 N 个并发都失败一遍
    _client()

    system_prompt = load_prompt(f"extract_{genre}")

    if not chunks.chunks:
        return []

    with ThreadPoolExecutor(max_workers=MAP_PHASE_CONCURRENCY) as ex:
        return list(ex.map(lambda c: _extract_chunk(c, system_prompt), chunks.chunks))
