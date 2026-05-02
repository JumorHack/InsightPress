from ..schemas import Critique, DimensionScores, GateVerdict, Synthesis


def run(synthesis: Synthesis, critique: Critique) -> GateVerdict:
    # MVP 占位：固定 pass + 7 分。后续接入 LLM-as-judge（独立 session，sonnet）。
    return GateVerdict(
        verdict="pass",
        overall_score=7,
        per_advice_scores={
            a.title: DimensionScores(
                specificity=7, evidence=7, actionability=7, anti_vagueness=7
            )
            for a in synthesis.core_advice
        },
        notes="MVP 占位评分，未经过真实 judge 评估。",
    )
