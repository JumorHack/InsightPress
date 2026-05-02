from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from ..schemas import BookMetadata, ChapterNode, ParsedBook


def parse_pdf(pdf_path: Path) -> ParsedBook:
    """提取 PDF 文字 + 元数据。MVP 阶段章节切分降级为单章。"""
    text_parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_parts.append(t)
    raw_text = "\n\n".join(text_parts).strip()

    if len(raw_text) < 500 and page_count >= 10:
        raise ValueError(
            "未提取到足够文字（< 500 字符）。可能是扫描件 PDF — MVP 阶段不支持 OCR。"
        )

    title = pdf_path.stem
    author: str | None = None
    try:
        meta = PdfReader(str(pdf_path)).metadata
        if meta:
            if meta.title:
                title = str(meta.title).strip() or title
            if meta.author:
                author = str(meta.author).strip() or None
    except Exception:
        pass

    chapters = [
        ChapterNode(title="正文", char_start=0, char_end=len(raw_text), level=1)
    ]

    return ParsedBook(
        metadata=BookMetadata(title=title, author=author, page_count=page_count),
        chapters=chapters,
        raw_text=raw_text,
    )
