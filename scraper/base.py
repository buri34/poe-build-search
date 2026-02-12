"""スクレイパー共通機能: ディレイ、キャッシュ、リトライ"""
import json
import random
import asyncio
from pathlib import Path
from datetime import datetime

from app.config import settings


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
    """スクレイピング結果をDBに保存"""
    import aiosqlite
    db = await aiosqlite.connect(settings.db_path)
    try:
        for b in builds:
            await db.execute(
                """INSERT OR REPLACE INTO builds (
                    source, source_id, source_url,
                    name_en, class_en, ascendancy_en, skills_en, description_en,
                    patch, build_types, author,
                    favorites, verified, hc, ssf,
                    playstyle, activities, cost_tier, damage_types,
                    translation_status, scraped_at
                ) VALUES (
                    :source, :source_id, :source_url,
                    :name_en, :class_en, :ascendancy_en, :skills_en, :description_en,
                    :patch, :build_types, :author,
                    :favorites, :verified, :hc, :ssf,
                    :playstyle, :activities, :cost_tier, :damage_types,
                    'pending', datetime('now')
                )""",
                b,
            )
        await db.commit()
        print(f"  DB保存完了: {len(builds)}件")
    finally:
        await db.close()
