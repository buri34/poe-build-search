from pydantic import BaseModel, Field

from app.models.build import BuildSummary


class SearchQuery(BaseModel):
    q: str = ""
    class_filter: str | None = None
    ascendancy_filter: str | None = None
    source_filter: str | None = None
    build_type: str | None = None
    sort: str = "favorites"  # favorites / updated / name
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=24, ge=1, le=100)


class SearchResult(BaseModel):
    builds: list[BuildSummary]
    total: int
    page: int
    per_page: int
    total_pages: int
    query: str
