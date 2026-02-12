import aiosqlite
from pathlib import Path

from app.config import settings

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


async def get_db() -> aiosqlite.Connection:
    """DBコネクションを取得"""
    db = await aiosqlite.connect(settings.db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """スキーマを適用してDBを初期化"""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await get_db()
    try:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        await db.executescript(schema)
        await db.commit()
    finally:
        await db.close()


async def seed_terms():
    """PoE用語辞書をDBに投入"""
    import json

    terms_path = Path(__file__).resolve().parent.parent / "db" / "seed_terms.json"
    data = json.loads(terms_path.read_text(encoding="utf-8"))

    db = await get_db()
    try:
        for category, terms in data.items():
            for en, ja in terms.items():
                await db.execute(
                    "INSERT OR IGNORE INTO terms (category, term_en, term_ja) VALUES (?, ?, ?)",
                    (category, en, ja),
                )
        await db.commit()
    finally:
        await db.close()
