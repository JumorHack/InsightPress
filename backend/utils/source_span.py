import re
import unicodedata

MIN_SPAN_LEN = 4
MAX_SPAN_LEN = 50


def _normalize(s: str) -> str:
    """NFKC（消除全角/半角差异）+ 折叠所有空白。"""
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", "", s)


def validate_span(span: str, source: str) -> bool:
    """source_span 必须是 source 的连续 substring（归一化后）。

    防幻觉的最后一道防线：LLM 抽取的每条记录必须能在原文中定位。
    """
    if not isinstance(span, str) or not span:
        return False
    if len(span) < MIN_SPAN_LEN or len(span) > MAX_SPAN_LEN:
        return False
    norm_span = _normalize(span)
    if len(norm_span) < MIN_SPAN_LEN:
        return False
    return norm_span in _normalize(source)
