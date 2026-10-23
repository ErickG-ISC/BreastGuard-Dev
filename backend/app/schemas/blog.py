from datetime import date

from pydantic import BaseModel


class ArticleSummary(BaseModel):
    slug: str
    title: str
    tags: list[str]
    summary: str
    reviewed_by: str | None
    review_date: date | None
    status: str
    reading_minutes: int


class ArticleOut(ArticleSummary):
    sources: list[str]
    body: str
