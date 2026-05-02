from pathlib import Path

from ..schemas import ParsedBook
from ..utils.pdf import parse_pdf


def run(pdf_path: Path) -> ParsedBook:
    return parse_pdf(pdf_path)
