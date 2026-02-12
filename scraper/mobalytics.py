"""mobalytics.gg スクレイパー: GraphQL API傍受方式"""
import json
import asyncio
from playwright.async_api import async_playwright, Page, Route

from scraper.base import random_delay, save_cache, load_cache, save_builds_to_db

BASE_URL = "https://mobalytics.gg/poe/builds"
# ビルドカテゴリタブ
TABS = ["verified", "creator", "community"]


def _normalize_build(raw: dict, tab: str) -> dict | None:
    """GraphQLレスポンスからビルドデータを正規化"""
    try:
        name = raw.get("name") or raw.get("title") or ""
        if not name:
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

        return {
            "source": "mobalytics",
            "source_id": source_id,
            "source_url": f"https://mobalytics.gg/poe/builds/{slug}",
            "name_en": name,
            "class_en": class_name,
            "ascendancy_en": ascendancy,
            "skills_en": json.dumps(skills) if skills else None,
            "description_en": raw.get("description") or raw.get("summary"),
            "patch": raw.get("patchVersion") or raw.get("patch"),
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
        }
    except Exception as e:
        print(f"  正規化エラー: {e}")
        return None


async def _intercept_graphql(page: Page, captured: list[dict]):
    """GraphQLレスポンスを傍受してビルドデータを抽出"""

    async def handle_route(route: Route):
        response = await route.fetch()
        try:
            body = await response.text()
            data = json.loads(body)
            # GraphQLレスポンスからビルドリストを探索
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
    await page.goto(url, timeout=60000)  # wait_untilを指定しない（デフォルト動作）
    await page.wait_for_timeout(5000)  # JavaScript実行完了を待つ

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

    # 正規化
    builds = []
    seen_ids = set()
    for raw in captured_raw:
        b = _normalize_build(raw, tab)
        if b and b["source_id"] not in seen_ids:
            seen_ids.add(b["source_id"])
            builds.append(b)

    print(f"  [{tab}] 取得: {len(builds)}件")
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
            # ビルドへのリンクを取得
            link_el = card.locator('a[href*="/poe/builds/"]').first
            href = await link_el.get_attribute("href") if await link_el.count() > 0 else ""

            # ビルド名: タイトル部分のみを抽出（"By" より前）
            card_text_full = await card.text_content() or ""
            lines = [l.strip() for l in card_text_full.split('\n') if l.strip()]
            name = lines[0] if lines else ""  # 最初の行がタイトル
            if "By " in name:
                name = name.split("By ")[0].strip()

            # 作者名（プロフィールリンクから）
            author_el = card.locator('a[href*="/poe/profile/"]').first
            author = await author_el.text_content() if await author_el.count() > 0 else ""

            # パッチバージョン（"3.27" のような形式）
            patch = ""
            import re
            patch_match = re.search(r'3\.\d+', card_text_full)
            if patch_match:
                patch = patch_match.group(0)

            # 背景画像からクラス/アセンダンシー情報を推測
            img_style = await card.locator('div[style*="background"]').first.get_attribute("style") if await card.locator('div[style*="background"]').count() > 0 else ""
            class_hint = ""
            ascendancy_hint = ""
            if img_style:
                # duelist-slayer.jpg → class=duelist, ascendancy=slayer
                if "duelist" in img_style.lower():
                    class_hint = "Duelist"
                    if "slayer" in img_style.lower():
                        ascendancy_hint = "Slayer"
                    elif "gladiator" in img_style.lower():
                        ascendancy_hint = "Gladiator"
                    elif "champion" in img_style.lower():
                        ascendancy_hint = "Champion"
                # 他のクラスも同様に推測可能だが、今は簡易実装

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
    """mobalytics.gg から全ビルドをスクレイピング"""
    if use_cache:
        cached = load_cache("mobalytics")
        if cached:
            print(f"mobalytics: キャッシュ使用 ({cached['count']}件, {cached['scraped_at']})")
            return cached["builds"]

    print("mobalytics.gg スクレイピング開始")
    all_builds: list[dict] = []
    seen_ids: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

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

        await browser.close()

    print(f"mobalytics: 合計 {len(all_builds)}件取得")
    save_cache("mobalytics", all_builds)
    return all_builds
