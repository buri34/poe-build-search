"""スクレイパー共通機能: ディレイ、キャッシュ、リトライ、戦闘スタイル/得意分野判定"""
import json
import random
import asyncio
from pathlib import Path
from datetime import datetime

from app.config import settings

# 戦闘スタイル判定用キーワード
MELEE_KEYWORDS = [
    "cyclone", "strike", "slam", "melee", "cleave", "lacerate", "reave",
    "blade flurry", "double strike", "molten strike", "ground slam",
    "earthquake", "tectonic", "boneshatter", "sunder", "heavy strike",
    "viper strike", "spectral throw", "blade vortex", "whirlwind",
    "general's cry", "rage vortex", "perforate", "smite",
]
RANGED_KEYWORDS = [
    "bow", "arrow", "shot", "barrage", "rain of arrows", "tornado shot",
    "lightning arrow", "ice shot", "split arrow", "blast rain", "ballista",
    "shrapnel", "galvanic", "kinetic bolt", "kinetic blast", "kinetic fusillade",
    "wand", "power siphon",
]
CASTER_KEYWORDS = [
    "spell", "cast", "arc", "fireball", "spark", "ice nova", "freezing pulse",
    "storm call", "orb of storms", "firestorm", "ball lightning", "lightning warp",
    "flame surge", "magma orb", "glacial cascade", "volatile dead", "detonate dead",
    "essence drain", "contagion", "bane", "soulrend", "dark pact", "forbidden rite",
    "cremation", "wave of conviction", "divine ire", "storm brand", "armageddon brand",
    "winter orb", "righteous fire", "wintertide brand",
]
SUMMONER_KEYWORDS = [
    "summon", "minion", "zombie", "skeleton", "spectre", "golem", "animate",
    "raise", "srs", "phantasm", "carrion", "herald of purity", "dominating blow",
    "absolution",
]


def detect_combat_style(name: str, skills: list[str], description: str) -> str:
    """ビルド名・スキル・説明文から戦闘スタイルを判定"""
    text = f"{name} {' '.join(skills)} {description}".lower()
    scores = {
        "melee": sum(1 for kw in MELEE_KEYWORDS if kw in text),
        "ranged": sum(1 for kw in RANGED_KEYWORDS if kw in text),
        "caster": sum(1 for kw in CASTER_KEYWORDS if kw in text),
        "summoner": sum(1 for kw in SUMMONER_KEYWORDS if kw in text),
    }
    max_score = max(scores.values())
    if max_score == 0:
        return "hybrid"
    top = [k for k, v in scores.items() if v == max_score]
    if len(top) > 1:
        return "hybrid"
    return top[0]


def detect_specialty(build_types: list[str], description: str) -> list[str]:
    """ビルドタグと説明文から得意分野を判定"""
    specialties = []
    text = f"{' '.join(build_types)} {description}".lower()

    if any(kw in text for kw in ["starter", "league start", "league-start"]):
        specialties.append("league_starter")
    if any(kw in text for kw in ["boss", "bossing", "boss killer"]):
        specialties.append("boss_killer")
    if any(kw in text for kw in ["map", "mapping", "clear", "farmer", "farming"]):
        specialties.append("map_farmer")
    if any(kw in text for kw in ["all-around", "all around", "all rounder", "versatile"]):
        specialties.append("all_rounder")
    if any(kw in text for kw in ["speed", "fast", "zoom"]):
        specialties.append("speed_farmer")
    if any(kw in text for kw in ["tank", "tanky", "defensive", "survive"]):
        specialties.append("tanky")

    return specialties if specialties else ["all_rounder"]


async def random_delay(min_sec: float = 2.0, max_sec: float = 5.0):
    """リクエスト間のランダムディレイ"""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


def load_cache(source: str) -> dict | None:
    """キャッシュからデータを読み込む"""
    cache_file = settings.cache_path / f"{source}_builds.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    return None


def save_cache(source: str, data: list[dict]):
    """データをキャッシュに保存"""
    settings.cache_path.mkdir(parents=True, exist_ok=True)
    cache_file = settings.cache_path / f"{source}_builds.json"
    payload = {
        "scraped_at": datetime.now().isoformat(),
        "count": len(data),
        "builds": data,
    }
    cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def save_builds_to_db(builds: list[dict]):
    """スクレイピング結果をDBに保存（格納前バリデーション付き）"""
    import aiosqlite
    db = await aiosqlite.connect(settings.db_path)
    try:
        saved_count = 0
        skipped_count = 0
        for b in builds:
            # バリデーション: データ品質チェック
            skip_reason = []
            desc = b.get("description_en") or ""
            if not desc or len(desc) < 50:
                skip_reason.append(f"description_en不足({len(desc)}文字)")
            if not b.get("pros_cons_en"):
                skip_reason.append("pros_cons_en空")
            if not b.get("core_equipment_en"):
                skip_reason.append("core_equipment_en空")

            if skip_reason:
                print(f"  [SKIP] {b.get('source_id', 'unknown')}: {', '.join(skip_reason)}")
                skipped_count += 1
                continue

            await db.execute(
                """INSERT OR REPLACE INTO builds (
                    source, source_id, source_url,
                    name_en, class_en, ascendancy_en, skills_en, description_en,
                    patch, build_types, author,
                    favorites, verified, hc, ssf,
                    playstyle, activities, cost_tier, damage_types,
                    combat_style, specialty, pros_cons_en, pros_cons_ja,
                    core_equipment_en, core_equipment_ja,
                    translation_status, scraped_at
                ) VALUES (
                    :source, :source_id, :source_url,
                    :name_en, :class_en, :ascendancy_en, :skills_en, :description_en,
                    :patch, :build_types, :author,
                    :favorites, :verified, :hc, :ssf,
                    :playstyle, :activities, :cost_tier, :damage_types,
                    :combat_style, :specialty, :pros_cons_en, :pros_cons_ja,
                    :core_equipment_en, :core_equipment_ja,
                    'pending', datetime('now')
                )""",
                b,
            )
            saved_count += 1
        await db.commit()
        print(f"  DB保存完了: {saved_count}件 (スキップ: {skipped_count}件)")
    finally:
        await db.close()
