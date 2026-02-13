"""mobalytics.py の LLM抽出方式をテスト（最初の3件のみ）"""
import asyncio
import sys
from scraper.mobalytics import scrape_tab, _scrape_detail_page
from playwright.async_api import async_playwright


async def test_llm_extraction():
    """最初の3件のビルドでLLM抽出をテスト"""
    print("=== mobalytics.py LLM抽出テスト（3件のみ） ===\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        # Phase 1: verifiedタブから最初の3件取得
        print("Phase 1: verifiedタブから最初の3件取得中...")
        builds = await scrape_tab(page, "verified")
        test_builds = builds[:3]  # 最初の3件のみ
        print(f"取得: {len(test_builds)}件\n")

        # Phase 2: 各ビルドの詳細ページでLLM抽出
        print("Phase 2: 詳細ページLLM抽出テスト\n")
        success_count = 0

        for i, build in enumerate(test_builds):
            print(f"--- [{i+1}/3] {build['name_en']} ---")
            print(f"URL: {build['source_url']}")

            # 詳細ページ抽出
            result = await _scrape_detail_page(page, build)

            # 結果検証
            fields = {
                "description_en": result.get("description_en"),
                "pros_cons_en": result.get("pros_cons_en"),
                "core_equipment_en": result.get("core_equipment_en"),
                "class_en": result.get("class_en"),
                "ascendancy_en": result.get("ascendancy_en"),
                "combat_style": result.get("combat_style"),
            }

            has_data = False
            for field, value in fields.items():
                if value:
                    char_count = len(str(value))
                    print(f"  ✓ {field}: {char_count}文字")
                    # 内容サマリー（最初の100文字）
                    preview = str(value)[:100].replace('\n', ' ')
                    print(f"    内容: {preview}...")
                    has_data = True
                else:
                    print(f"  ✗ {field}: なし")

            if has_data:
                success_count += 1
                print(f"  → 抽出成功")
            else:
                print(f"  → 抽出失敗（全フィールドが空）")
            print()

        await browser.close()

        # サマリー
        print("\n=== テスト結果サマリー ===")
        print(f"成功: {success_count}/3件")
        print(f"成功率: {success_count/3*100:.1f}%")

        if success_count == 3:
            print("\n✅ 全テスト成功")
            return 0
        elif success_count > 0:
            print(f"\n⚠️  一部成功 ({success_count}/3)")
            return 1
        else:
            print("\n❌ 全テスト失敗")
            return 2


if __name__ == "__main__":
    exit_code = asyncio.run(test_llm_extraction())
    sys.exit(exit_code)
