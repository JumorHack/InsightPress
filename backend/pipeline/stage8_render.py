from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import GENRE_LABELS, TEMPLATES_DIR
from ..schemas import (
    BookClassification,
    Critique,
    GateVerdict,
    ParsedBook,
    Synthesis,
)
from ..utils.quote_validator import enforce_quote_limits


def run(
    synthesis: Synthesis,
    critique: Critique,
    gate: GateVerdict,
    classification: BookClassification,
    parsed: ParsedBook,
) -> str:
    synthesis = enforce_quote_limits(synthesis)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(disabled_extensions=("jinja",)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template("practical.md.jinja")

    critique_by_title = {c.advice_title: c for c in critique.per_advice_critique}

    genre_label = GENRE_LABELS.get(classification.selected_genre, "—")

    return template.render(
        parsed=parsed,
        synthesis=synthesis,
        critique=critique,
        gate=gate,
        classification=classification,
        critique_by_title=critique_by_title,
        genre_label=genre_label,
    )
