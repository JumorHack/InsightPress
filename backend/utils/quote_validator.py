from ..config import MAX_QUOTE_CHARS_ZH, MAX_QUOTE_WORDS_EN, MAX_TOTAL_QUOTES_CHARS
from ..schemas import Quote, Synthesis


def _is_mostly_ascii(text: str) -> bool:
    if not text:
        return False
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return ascii_chars / len(text) > 0.7


def truncate_quote(text: str) -> str:
    if _is_mostly_ascii(text):
        words = text.split()
        if len(words) > MAX_QUOTE_WORDS_EN:
            return " ".join(words[:MAX_QUOTE_WORDS_EN]) + "…"
        return text
    if len(text) > MAX_QUOTE_CHARS_ZH:
        return text[:MAX_QUOTE_CHARS_ZH] + "…"
    return text


def enforce_quote_limits(synthesis: Synthesis) -> Synthesis:
    """阶段 8 渲染前最后一道版权检查：单条截断 + 总量截断。"""
    total = 0
    for advice in synthesis.core_advice:
        kept: list[Quote] = []
        for q in advice.evidence_quotes:
            q.text = truncate_quote(q.text)
            if total + len(q.text) > MAX_TOTAL_QUOTES_CHARS:
                break
            total += len(q.text)
            kept.append(q)
        advice.evidence_quotes = kept
    return synthesis
