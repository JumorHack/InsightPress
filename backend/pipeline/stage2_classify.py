from ..schemas import BookClassification, ParsedBook


def run(parsed: ParsedBook) -> BookClassification:
    # MVP 占位：默认致用类。后续接入 LLM (cheap model) 输出概率分布。
    return BookClassification(
        practical_prob=0.7,
        narrative_prob=0.1,
        theory_prob=0.15,
        reference_prob=0.05,
    )
