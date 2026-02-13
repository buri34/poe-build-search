"""mobalytics.gg スクレイパー: GraphQL API傍受方式 + 詳細ページ抽出"""
import json
import re
import asyncio
from playwright.async_api import async_playwright, Page, Route

from scraper.base import (
    random_delay, save_cache, load_cache, save_builds_to_db,
    detect_combat_style, detect_specialty,
)
from scraper.llm_extractor import extract_build_info_via_llm

BASE_URL = "https://mobalytics.gg/poe/builds"
# ビルドカテゴリタブ
TABS = ["verified", "creator", "community"]
# 対象パッチバージョン
ALLOWED_PATCHES = {"3.27", "3.26"}

# Apollo State等のゴミデータ検知パターン
GARBAGE_PATTERNS = ["__typename", "NgfDocument", "apolloState", "__APOLLO_STATE__",
                    "__NEXT_DATA__", "graphql", '"edges":', '"node":', '"cursor":']


def _normalize_build(raw: dict, tab: str) -> dict | None:
    """GraphQLレスポンスからビルドデータを正規化"""
    try:
        name = raw.get("name") or raw.get("title") or ""
        if not name:
            return None

        # パッチバージョンフィルタ
        patch = raw.get("patchVersion") or raw.get("patch") or ""
        patch_short = ""
        if patch:
            m = re.match(r"(\d+\.\d+)", str(patch))
            if m:
                patch_short = m.group(1)
        if patch_short not in ALLOWED_PATCHES:
            return None

        class_name = raw.get("className") or raw.get("class") or ""
        ascendancy = raw.get("ascendancyName") or raw.get("ascendancy") or ""

        # スキル抽出
        skills = []
        for key in ("mainSkillName", "primarySkillName", "mainSkill"):
            if raw.get(key):
                skills.append(raw[key])
                break
        skill_gems = raw.get("skillGems") or raw.get("gems") or []
        if isinstance(skill_gems, list):
            for gem in skill_gems:
                if isinstance(gem, dict):
                    skills.append(gem.get("name", ""))
                elif isinstance(gem, str):
                    skills.append(gem)

        # ビルドタイプタグ
        build_types = []
        tags = raw.get("tags") or raw.get("buildTags") or []
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, dict):
                    build_types.append(tag.get("name", str(tag.get("id", ""))))
                else:
                    build_types.append(str(tag))

        slug = raw.get("slug") or raw.get("id") or name.lower().replace(" ", "-")
        source_id = str(raw.get("id") or slug)
        description = raw.get("description") or raw.get("summary") or ""

        # 戦闘スタイル・得意分野を判定
        combat_style = detect_combat_style(name, skills, description)
        specialty = detect_specialty(build_types, description)

        return {
            "source": "mobalytics",
            "source_id": source_id,
            "source_url": f"https://mobalytics.gg/poe/builds/{slug}",
            "name_en": name,
            "class_en": class_name,
            "ascendancy_en": ascendancy,
            "skills_en": json.dumps(skills) if skills else None,
            "description_en": description,
            "patch": str(patch),
            "build_types": json.dumps(build_types) if build_types else None,
            "author": (raw.get("author") or {}).get("name") if isinstance(raw.get("author"), dict) else raw.get("authorName"),
            "favorites": raw.get("likesCount") or raw.get("favorites") or 0,
            "verified": 1 if tab == "verified" else 0,
            "hc": 1 if raw.get("isHardcore") or raw.get("hardcore") else 0,
            "ssf": 1 if raw.get("isSsf") or raw.get("ssf") else 0,
            "playstyle": None,
            "activities": None,
            "cost_tier": None,
            "damage_types": None,
            "combat_style": combat_style,
            "specialty": json.dumps(specialty),
            "pros_cons_en": None,  # 詳細ページから後で取得
            "pros_cons_ja": None,
            "core_equipment_en": None,  # 詳細ページから後で取得
            "core_equipment_ja": None,
        }
    except Exception as e:
        print(f"  正規化エラー: {e}")
        return None


async def _scrape_detail_page(page: Page, build: dict) -> dict:
    """ビルド詳細ページからLLM抽出でデータを取得"""
    url = build["source_url"]
    print(f"    詳細ページ: {url}")
    try:
        await page.goto(url, timeout=60000)
        await page.wait_for_load_state('domcontentloaded')
        await page.wait_for_timeout(5000)

        # innerText取得（可視テキストのみ）
        page_text = await page.inner_text("body")

        # LLM抽出
        llm_result = extract_build_info_via_llm(page_text, build["name_en"])

        # 結果をbuild dictにマージ
        if llm_result.get("description_en"):
            build["description_en"] = llm_result["description_en"]
        if llm_result.get("pros_cons_en"):
            build["pros_cons_en"] = llm_result["pros_cons_en"]
        if llm_result.get("core_equipment_en"):
            build["core_equipment_en"] = llm_result["core_equipment_en"]
        if llm_result.get("class_en") and not build.get("class_en"):
            build["class_en"] = llm_result["class_en"]
        if llm_result.get("ascendancy_en") and not build.get("ascendancy_en"):
            build["ascendancy_en"] = llm_result["ascendancy_en"]

        # 戦闘スタイルをLLM結果で再判定
        skills_raw = json.loads(build["skills_en"]) if build["skills_en"] else []
        build["combat_style"] = detect_combat_style(
            build["name_en"], skills_raw,
            llm_result.get("description_en") or ""
        )
    except Exception as e:
        print(f"    詳細ページエラー({url}): {e}")
    return build








async def _intercept_graphql(page: Page, captured: list[dict]):
    """GraphQLレスポンスを傍受してビルドデータを抽出"""

    async def handle_route(route: Route):
        response = await route.fetch()
        try:
            body = await response.text()
            data = json.loads(body)
            _extract_builds(data, captured)
        except Exception:
            pass
        await route.fulfill(response=response)

    await page.route("**/graphql**", handle_route)
    await page.route("**/api/**graphql**", handle_route)


def _extract_builds(data: dict | list, captured: list[dict]):
    """入れ子構造からビルドリストを再帰的に抽出"""
    if isinstance(data, list):
        for item in data:
            _extract_builds(item, captured)
        return
    if not isinstance(data, dict):
        return

    # ビルドらしきオブジェクトの判定
    if "name" in data and ("className" in data or "class" in data or "ascendancyName" in data):
        captured.append(data)
        return

    # 再帰探索
    for value in data.values():
        if isinstance(value, (dict, list)):
            _extract_builds(value, captured)


async def scrape_tab(page: Page, tab: str) -> list[dict]:
    """1タブ分のビルドをスクレイピング"""
    captured_raw: list[dict] = []
    await _intercept_graphql(page, captured_raw)

    url = f"{BASE_URL}?buildTab={tab}"
    print(f"  [{tab}] アクセス中: {url}")
    await page.goto(url, timeout=60000)
    await page.wait_for_timeout(5000)

    # 「Show more」ボタンをクリックしてビルドを追加読み込み
    show_more_clicks = 0
    max_clicks = 10
    while show_more_clicks < max_clicks:
        try:
            btn = page.locator("button:has-text('Show more'), button:has-text('Load more'), button:has-text('See more')")
            if await btn.count() == 0:
                break
            await btn.first.click()
            show_more_clicks += 1
            await random_delay(1.5, 3)
        except Exception:
            break

    # ページDOMからもビルドカードを取得（フォールバック）
    if not captured_raw:
        print(f"  [{tab}] GraphQL傍受なし。DOMパースにフォールバック")
        captured_raw = await _parse_dom_builds(page)

    # __APOLLO_STATE__ からもフォールバック
    if not captured_raw:
        print(f"  [{tab}] DOMパース失敗。Apollo State にフォールバック")
        captured_raw = await _parse_apollo_state(page)

    # 正規化（パッチフィルタ込み）
    builds = []
    seen_ids = set()
    for raw in captured_raw:
        b = _normalize_build(raw, tab)
        if b and b["source_id"] not in seen_ids:
            seen_ids.add(b["source_id"])
            builds.append(b)

    print(f"  [{tab}] 取得（3.27/3.26のみ）: {len(builds)}件")
    return builds


async def _parse_dom_builds(page: Page) -> list[dict]:
    """ページDOMからビルドカード情報を抽出"""
    builds = []
    cards = page.locator('[data-testid="discovery-item"]')
    count = await cards.count()
    print(f"  [DOM] discovery-item カード: {count}件")

    for i in range(count):
        card = cards.nth(i)
        try:
            link_el = card.locator('a[href*="/poe/builds/"]').first
            href = await link_el.get_attribute("href") if await link_el.count() > 0 else ""

            card_text_full = await card.text_content() or ""
            lines = [l.strip() for l in card_text_full.split('\n') if l.strip()]
            name = lines[0] if lines else ""
            if "By " in name:
                name = name.split("By ")[0].strip()

            author_el = card.locator('a[href*="/poe/profile/"]').first
            author = await author_el.text_content() if await author_el.count() > 0 else ""

            patch = ""
            patch_match = re.search(r'3\.\d+', card_text_full)
            if patch_match:
                patch = patch_match.group(0)

            img_style = await card.locator('div[style*="background"]').first.get_attribute("style") if await card.locator('div[style*="background"]').count() > 0 else ""
            class_hint = ""
            ascendancy_hint = ""
            if img_style:
                if "duelist" in img_style.lower():
                    class_hint = "Duelist"
                    if "slayer" in img_style.lower():
                        ascendancy_hint = "Slayer"
                    elif "gladiator" in img_style.lower():
                        ascendancy_hint = "Gladiator"
                    elif "champion" in img_style.lower():
                        ascendancy_hint = "Champion"

            if name and href:
                builds.append({
                    "name": name,
                    "className": class_hint,
                    "ascendancyName": ascendancy_hint,
                    "slug": href.split("/")[-1] if href else "",
                    "author": {"name": author.strip()} if author else None,
                    "patchVersion": patch,
                })
        except Exception as e:
            print(f"  [DOM] カード{i}解析エラー: {e}")
            continue
    return builds


async def _parse_apollo_state(page: Page) -> list[dict]:
    """__APOLLO_STATE__ からビルドデータを抽出"""
    builds = []
    try:
        state = await page.evaluate("""
            () => {
                const el = document.querySelector('script[id*="__APOLLO_STATE__"], script[id*="__NEXT_DATA__"]');
                if (el) return JSON.parse(el.textContent);
                if (window.__APOLLO_STATE__) return window.__APOLLO_STATE__;
                if (window.__NEXT_DATA__) return window.__NEXT_DATA__;
                return null;
            }
        """)
        if state:
            _extract_builds(state, builds)
    except Exception as e:
        print(f"  Apollo State パースエラー: {e}")
    return builds


async def scrape_mobalytics(use_cache: bool = True) -> list[dict]:
    """mobalytics.gg から全ビルドをスクレイピング（3.27/3.26のみ）"""
    if use_cache:
        cached = load_cache("mobalytics")
        if cached:
            print(f"mobalytics: キャッシュ使用 ({cached['count']}件, {cached['scraped_at']})")
            return cached["builds"]

    print("mobalytics.gg スクレイピング開始（パッチ3.27/3.26のみ）")
    all_builds: list[dict] = []
    seen_ids: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        # Phase 1: 一覧からビルド取得（パッチフィルタ済み）
        for tab in TABS:
            try:
                builds = await scrape_tab(page, tab)
                for b in builds:
                    if b["source_id"] not in seen_ids:
                        seen_ids.add(b["source_id"])
                        all_builds.append(b)
                await random_delay(2, 4)
            except Exception as e:
                print(f"  [{tab}] エラー: {e}")

        # Phase 2: 各ビルドの詳細ページにアクセスして追加情報を抽出
        print(f"\n詳細ページアクセス開始（{len(all_builds)}件）")
        for i, build in enumerate(all_builds):
            success = False
            for attempt in range(2):  # 最大2回試行（初回+リトライ1回）
                try:
                    if attempt > 0:
                        print(f"    → リトライ {attempt}回目")
                    print(f"  [{i+1}/{len(all_builds)}] {build['name_en']}")
                    all_builds[i] = await _scrape_detail_page(page, build)
                    success = True
                    break
                except Exception as e:
                    if attempt == 0:
                        print(f"    詳細ページエラー: {e}")
                    else:
                        print(f"    詳細ページスキップ（リトライ失敗）: {e}")

            if success:
                await random_delay(2, 4)

        await browser.close()

    print(f"\nmobalytics: 合計 {len(all_builds)}件取得（3.27/3.26のみ）")
    save_cache("mobalytics", all_builds)
    return all_builds


async def main():
    """メインエントリポイント"""
    import argparse
    parser = argparse.ArgumentParser(description="mobalytics.gg スクレイパー")
    parser.add_argument("--no-cache", action="store_true", help="キャッシュを使用しない")
    parser.add_argument("--no-db", action="store_true", help="DB保存をスキップ")
    args = parser.parse_args()

    use_cache = not args.no_cache
    builds = await scrape_mobalytics(use_cache=use_cache)

    if not args.no_db:
        print(f"\nデータベースに保存中...")
        await save_builds_to_db(builds)
        print(f"完了: {len(builds)}件保存")
    else:
        print(f"\n完了: {len(builds)}件取得（DB保存スキップ）")


if __name__ == "__main__":
    asyncio.run(main())
