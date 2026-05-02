from ..config import CHUNK_OVERLAP_TOKENS, CHUNK_TARGET_TOKENS
from ..schemas import ChunkSet, ParsedBook
from ..utils.chunking import chunk_text


def run(parsed: ParsedBook) -> ChunkSet:
    return chunk_text(parsed, CHUNK_TARGET_TOKENS, CHUNK_OVERLAP_TOKENS)
