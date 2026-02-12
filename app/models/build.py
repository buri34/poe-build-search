from pydantic import BaseModel


class Build(BaseModel):
    id: int
    source: str
    source_id: str
    source_url: str
    name_en: str
    name_ja: str | None = None
    class_en: str
    class_ja: str | None = None
    ascendancy_en: str | None = None
    ascendancy_ja: str | None = None
    skills_en: str | None = None  # JSON配列
    skills_ja: str | None = None  # JSON配列
    description_en: str | None = None
    description_ja: str | None = None
    patch: str | None = None
    build_types: str | None = None  # JSON配列
    author: str | None = None
    favorites: int = 0
    verified: int = 0
    hc: int = 0
    ssf: int = 0
    playstyle: str | None = None
    activities: str | None = None
    cost_tier: str | None = None
    damage_types: str | None = None
    translation_status: str = "pending"
    scraped_at: str | None = None
    translated_at: str | None = None
    updated_at: str | None = None


class BuildSummary(BaseModel):
    """検索結果用の軽量モデル"""
    id: int
    source: str
    source_url: str
    name_en: str
    name_ja: str | None = None
    class_en: str
    class_ja: str | None = None
    ascendancy_en: str | None = None
    ascendancy_ja: str | None = None
    skills_ja: str | None = None
    build_types: str | None = None
    favorites: int = 0
    verified: int = 0
    cost_tier: str | None = None
    patch: str | None = None
