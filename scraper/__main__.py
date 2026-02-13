"""scraper モジュールのエントリーポイント"""
import asyncio
import sys


async def main():
    # コマンドライン引数でスクレイパーを選択
    if len(sys.argv) < 2:
        print("Usage: python -m scraper [mobalytics|maxroll]")
        sys.exit(1)

    scraper_name = sys.argv[1]

    if scraper_name == "mobalytics":
        from scraper.mobalytics import scrape_mobalytics
        from scraper.base import save_builds_to_db

        print("mobalytics スクレイピング開始...")
        builds = await scrape_mobalytics(use_cache=False)

        print(f"\nデータベースに保存中（{len(builds)}件）...")
        await save_builds_to_db(builds)
        print("完了")

    elif scraper_name == "maxroll":
        from scraper.maxroll import scrape_maxroll
        from scraper.base import save_builds_to_db

        print("maxroll スクレイピング開始...")
        builds = await scrape_maxroll(use_cache=False)

        print(f"\nデータベースに保存中（{len(builds)}件）...")
        await save_builds_to_db(builds)
        print("完了")

    else:
        print(f"Unknown scraper: {scraper_name}")
        print("Available: mobalytics, maxroll")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
