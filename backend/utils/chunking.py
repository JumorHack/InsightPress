from ..schemas import Chunk, ChunkSet, ParsedBook

CHARS_PER_TOKEN = 2.5


def chunk_text(parsed: ParsedBook, target_tokens: int, overlap_tokens: int) -> ChunkSet:
    """字符级切分，按章节标题归属。中文按 ~2.5 字/token 估算。"""
    text = parsed.raw_text
    target_chars = int(target_tokens * CHARS_PER_TOKEN)
    overlap_chars = int(overlap_tokens * CHARS_PER_TOKEN)

    chunks: list[Chunk] = []
    i = 0
    cid = 0
    while i < len(text):
        end = min(i + target_chars, len(text))
        ctx_before = text[max(0, i - overlap_chars) : i] if i > 0 else ""
        chapter_title = _chapter_for(parsed, i)
        chunks.append(
            Chunk(
                chunk_id=f"c{cid:04d}",
                text=text[i:end],
                char_start=i,
                char_end=end,
                context_before=ctx_before,
                chapter_title=chapter_title,
            )
        )
        cid += 1
        i = end

    return ChunkSet(chunks=chunks)


def _chapter_for(parsed: ParsedBook, char_pos: int) -> str | None:
    for ch in parsed.chapters:
        if ch.char_start <= char_pos < ch.char_end:
            return ch.title
    return None
