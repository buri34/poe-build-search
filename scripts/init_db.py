"""DB初期化スクリプト: スキーマ適用 + 用語辞書投入"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import init_db, seed_terms


async def main():
    print("DB初期化中...")
    await init_db()
    print("用語辞書を投入中...")
    await seed_terms()
    print("完了")


if __name__ == "__main__":
    asyncio.run(main())
