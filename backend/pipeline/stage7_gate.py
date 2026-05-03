import logging

# 注意：CLAUDE.md 推荐 JUDGE_MODEL = v4-pro 做主判官，但 v4-pro 在与 stage 6 同类的
# tool_use schema 下偶发"调 tool 传空参数"。此处直接用 v4-flash 稳定输出；
# 待 DeepSeek 修复或换 v5 后可切回 JUDGE_MODEL。判官与生成模型的"provider 隔离"
# 要等接入第二个 provider 时再做。
from ..config import (
    CHEAP_MODEL,
    ENABLE_PROMPT_CACHING,
    GATE_MAX_RETRIES,
    GATE_MIN_DIMENSION_SCORE,
    GATE_MIN_OVERALL_SCORE,
    GENRE_ITEM_HEADER,
    GENRE_ITEM_NOUN,
)
from ..llm_client import _client, call_tool_use_with_retry, load_prompt
from ..schemas import (
    Critique,
    DimensionScores,
    GateVerdict,
    Genre,
    ParsedBook,
    Synthesis,
)

logger = logging.getLogger(__name__)


GATE_TOOL = {
    "name": "submit_gate",
    "description": "提交对稿件中核心建议部分的四维评分。",
    "input_schema": {
        "type": "object",
        "properties": {
            "per_advice_scores": {
                "type": "array",
                "description": "每条核心建议的 4 维独立评分；每条建议必须有一条记录。",
                "items": {
                    "type": "object",
                    "properties": {
                        "advice_title": {
                            "type": "string",
                            "description": "对应稿件中的建议标题，必须完全一致",
                        },
                        "specificity": {
                            "type": "integer",
                            "description": "具体性 0-10",
                        },
                        "evidence": {
                            "type": "integer",
                            "description": "证据支撑 0-10",
                        },
                        "actionability": {
                            "type": "integer",
                            "description": "行动性 0-10",
                        },
                        "anti_vagueness": {
                            "type": "integer",
                            "description": "反空泛（删书名仍成立的扣分） 0-10",
                        },
                    },
                    "required": [
                        "advice_title",
                        "specificity",
                        "evidence",
                        "actionability",
                        "anti_vagueness",
                    ],
                },
            },
            "overall_score": {
                "type": "integer",
                "description": "稿件核心建议部分整体质量分 0-10",
            },
            "notes": {
                "type": "string",
                "description": "50-200 字总结最大不足 + 一条最重要的修改建议",
            },
        },
        "required": ["per_advice_scores", "overall_score", "notes"],
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
    parts.append("# 核心论点")
    parts.append(synthesis.core_thesis)
    parts.append("")
    parts.append("# 适合读者")
    parts.append(synthesis.target_audience)
    parts.append("")
    parts.append(f"# {item_header}")
    for i, a in enumerate(synthesis.core_advice, 1):
        # 把序号和 title 拆开，避免 LLM 把"1. xxx"当成 advice_title 的一部分
        parts.append(f"\n[第 {i} 条]")
        parts.append(f"标题：{a.title}")
        parts.append(f"详情：{a.detail}")
        parts.append(f"适用：{a.when_applicable}")
        parts.append(f"不适用：{a.when_not_applicable}")
    parts.append("")
    parts.append(
        "请按 4 个维度逐条评分，调用 submit_gate 工具输出完整结果。"
        f"**严禁传空参数**——per_advice_scores 必须为稿件中每条{item_noun}都给一组分数。"
    )
    return "\n".join(parts)


def _build_system(system_prompt: str):
    block = {"type": "text", "text": system_prompt}
    if ENABLE_PROMPT_CACHING:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


def _clamp(score, lo: int = 0, hi: int = 10) -> int:
    try:
        v = int(score)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


def _compute_verdict(
    per_advice_scores: dict[str, DimensionScores], overall_score: int
) -> str:
    """根据分数计算判决档。pass/warn/fail 由代码确定，不让 LLM 自评。"""
    if not per_advice_scores:
        return "fail"

    min_dim = min(
        min(s.specificity, s.evidence, s.actionability, s.anti_vagueness)
        for s in per_advice_scores.values()
    )

    # fail：明显不合格
    if min_dim < 3 or overall_score < 5:
        return "fail"
    # warn：未达 pass 阈值，但还没到 fail（对应 CLAUDE.md "任一维 < 5 或总分 < 7 触发重试"）
    if min_dim < GATE_MIN_DIMENSION_SCORE or overall_score < GATE_MIN_OVERALL_SCORE:
        return "warn"
    return "pass"


def _build_gate_verdict(raw: dict, synthesis: Synthesis) -> GateVerdict:
    overall = _clamp(raw.get("overall_score", 0))
    notes = raw.get("notes") or ""

    per_advice: dict[str, DimensionScores] = {}
    for item in raw.get("per_advice_scores") or []:
        try:
            title = item["advice_title"]
            per_advice[title] = DimensionScores(
                specificity=_clamp(item.get("specificity", 0)),
                evidence=_clamp(item.get("evidence", 0)),
                actionability=_clamp(item.get("actionability", 0)),
                anti_vagueness=_clamp(item.get("anti_vagueness", 0)),
            )
        except Exception as e:
            logger.warning("Stage 7 dropped malformed score: %s", e)

    # 兜底：LLM 漏评某条建议，给 0 分占位（会被记成 fail）
    for a in synthesis.core_advice:
        if a.title not in per_advice:
            logger.info(
                "Stage 7 LLM omitted score for %r, filling zeros (counts as fail)",
                a.title,
            )
            per_advice[a.title] = DimensionScores(
                specificity=0, evidence=0, actionability=0, anti_vagueness=0
            )

    verdict = _compute_verdict(per_advice, overall)

    return GateVerdict(
        verdict=verdict,
        overall_score=overall,
        per_advice_scores=per_advice,
        notes=notes,
    )


def _fallback_verdict(synthesis: Synthesis, reason: str) -> GateVerdict:
    return GateVerdict(
        verdict="fail",
        overall_score=0,
        per_advice_scores={
            a.title: DimensionScores(
                specificity=0, evidence=0, actionability=0, anti_vagueness=0
            )
            for a in synthesis.core_advice
        },
        notes=f"（评分生成失败：{reason}）",
    )


def run(
    synthesis: Synthesis,
    critique: Critique,
    parsed: ParsedBook,
    genre: Genre = "practical",
) -> GateVerdict:
    _client()  # API key 缺失早失败

    if not synthesis.core_advice:
        logger.warning("Stage 7: synthesis 没有核心建议，跳过 LLM 调用")
        return GateVerdict(
            verdict="fail",
            overall_score=0,
            per_advice_scores={},
            notes="稿件没有核心建议，无法评分。",
        )

    # 重要：判官 prompt 不暗示"AI 生成"，让 judge 当成人写稿件来评。
    # 不传 critique —— judge 应基于稿件本身评，不要被前面的批判影响。
    system_prompt = load_prompt(f"judge_{genre}")
    user_msg = _build_user_message(synthesis, parsed, genre)

    try:
        raw, stop_reason = call_tool_use_with_retry(
            model=CHEAP_MODEL,
            system=_build_system(system_prompt),
            messages=[{"role": "user", "content": user_msg}],
            tools=[GATE_TOOL],
            tool_name=GATE_TOOL["name"],
            max_tokens=16000,
            max_retries=GATE_MAX_RETRIES,
        )
    except Exception as e:
        logger.warning("Stage 7 LLM call failed: %s", e)
        return _fallback_verdict(synthesis, f"LLM 调用失败: {e}")

    if stop_reason == "max_tokens":
        logger.warning("Stage 7 hit max_tokens — judge output may be truncated")

    if not raw:
        logger.warning(
            "Stage 7: 重试 %d 次后仍未拿到非空 tool_use input", GATE_MAX_RETRIES
        )
        return _fallback_verdict(synthesis, "LLM 多次未返回结构化结果")

    return _build_gate_verdict(raw, synthesis)
