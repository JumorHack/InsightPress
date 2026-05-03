from typing import Literal

from pydantic import BaseModel, Field


class BookMetadata(BaseModel):
    title: str
    author: str | None = None
    page_count: int


class ChapterNode(BaseModel):
    title: str
    char_start: int
    char_end: int
    level: int = 1


class ParsedBook(BaseModel):
    metadata: BookMetadata
    chapters: list[ChapterNode]
    raw_text: str


Genre = Literal["practical", "narrative", "theory", "reference"]


class BookClassification(BaseModel):
    selected_genre: Genre
    practical_prob: float = Field(default=0.0, ge=0, le=1)
    narrative_prob: float = Field(default=0.0, ge=0, le=1)
    theory_prob: float = Field(default=0.0, ge=0, le=1)
    reference_prob: float = Field(default=0.0, ge=0, le=1)


class Chunk(BaseModel):
    chunk_id: str
    text: str
    char_start: int
    char_end: int
    context_before: str = ""
    chapter_title: str | None = None


class ChunkSet(BaseModel):
    chunks: list[Chunk]


class Quote(BaseModel):
    text: str
    chapter: str | None = None
    source_span: str


class Principle(BaseModel):
    statement: str
    source_span: str


class Evidence(BaseModel):
    text: str
    source_span: str


class Claim(BaseModel):
    text: str
    source_span: str


class ChunkExtraction(BaseModel):
    chunk_id: str
    principles: list[Principle] = []
    evidence: list[Evidence] = []
    quotes: list[Quote] = []
    claims: list[Claim] = []


class CoreAdvice(BaseModel):
    title: str
    detail: str
    when_applicable: str
    when_not_applicable: str
    evidence_quotes: list[Quote] = []
    source_chapters: list[str] = []


class Synthesis(BaseModel):
    core_thesis: str
    target_audience: str
    core_advice: list[CoreAdvice]


class AdviceCritique(BaseModel):
    advice_title: str
    verdict: Literal["holds", "partial", "disagree"]
    reasoning: str


class Critique(BaseModel):
    per_advice_critique: list[AdviceCritique]
    factual_issues: list[str] = []
    alternative_books: list[str] = []


class DimensionScores(BaseModel):
    specificity: int = Field(ge=0, le=10)
    evidence: int = Field(ge=0, le=10)
    actionability: int = Field(ge=0, le=10)
    anti_vagueness: int = Field(ge=0, le=10)


class GateVerdict(BaseModel):
    verdict: Literal["pass", "warn", "fail"]
    overall_score: int = Field(ge=0, le=10)
    per_advice_scores: dict[str, DimensionScores]
    notes: str = ""
