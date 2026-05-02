from ..schemas import AdviceCritique, Critique, ParsedBook, Synthesis


def run(synthesis: Synthesis, parsed: ParsedBook) -> Critique:
    # MVP 占位：每条建议默认 holds + 占位推理。后续接入 LLM (sonnet) 红队提示词。
    return Critique(
        per_advice_critique=[
            AdviceCritique(
                advice_title=a.title,
                verdict="holds",
                reasoning="（待阶段 6 LLM 红队分析）",
            )
            for a in synthesis.core_advice
        ],
        factual_issues=[],
        alternative_books=[],
    )
