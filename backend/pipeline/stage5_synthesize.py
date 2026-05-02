from ..schemas import ChunkExtraction, CoreAdvice, Synthesis


def run(extractions: list[ChunkExtraction]) -> Synthesis:
    # MVP 占位：固定 3 条占位建议。后续接入 embedding 聚类 + LLM (sonnet) 选代表。
    return Synthesis(
        core_thesis="（待阶段 5 LLM 合成）核心论点占位。",
        target_audience="（待阶段 5 LLM 识别）目标读者占位。",
        core_advice=[
            CoreAdvice(
                title=f"占位建议 {i}",
                detail="该建议待阶段 5 的 LLM 合成调用填充。当前为骨架占位，用于验证端到端流水线串联。",
                when_applicable="待 LLM 补充。",
                when_not_applicable="待 LLM 补充。",
            )
            for i in range(1, 4)
        ],
    )
