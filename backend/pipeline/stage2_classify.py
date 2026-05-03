from ..schemas import BookClassification, Genre, ParsedBook


def run(parsed: ParsedBook, selected_genre: Genre) -> BookClassification:
    """MVP 阶段不调 LLM 自动分类，由用户上传时显式指定书种。

    保留 *_prob 字段以备未来接入 LLM 分类时复用：用户选定 = 1.0，其它 = 0.0。
    """
    probs = {"practical": 0.0, "narrative": 0.0, "theory": 0.0, "reference": 0.0}
    probs[selected_genre] = 1.0
    return BookClassification(
        selected_genre=selected_genre,
        practical_prob=probs["practical"],
        narrative_prob=probs["narrative"],
        theory_prob=probs["theory"],
        reference_prob=probs["reference"],
    )
