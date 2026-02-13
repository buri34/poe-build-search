"""mobalytics.gg スクレイパー: GraphQL API傍受方式 + 詳細ページ抽出"""
import json
import re
import asyncio
from playwright.async_api import async_playwright, Page, Route

from scraper.base import (
    random_delay, save_cache, load_cache, save_builds_to_db,
    detect_combat_style, detect_specialty,
)

BASE_URL = "https://mobalytics.gg/poe/builds"
# ビルドカテゴリタブ
TABS = ["verified", "creator", "community"]
# 対象パッチバージョン
ALLOWED_PATCHES = {"3.27", "3.26"}


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
    """ビルド詳細ページからPros/Cons, コア装備を抽出"""
    url = build["source_url"]
    print(f"    詳細ページ: {url}")
    try:
        await page.goto(url, timeout=60000)
        await page.wait_for_timeout(3000)

        # inner_text = 可視テキストのみ（隠しJSON要素を除外）
        page_text = await page.inner_text("body") or ""

        # Strengths and Weaknesses セクションを抽出
        pros_cons = await _extract_pros_cons(page, page_text)
        if pros_cons:
            build["pros_cons_en"] = pros_cons

        # コア装備を抽出
        core_equipment = await _extract_core_equipment(page, page_text)
        if core_equipment:
            build["core_equipment_en"] = core_equipment

        # description_enを強化（概要テキストを取得）
        overview = await _extract_overview(page, page_text)
        if overview and (not build["description_en"] or len(build["description_en"]) < len(overview)):
            build["description_en"] = overview

        # 戦闘スタイルをページ内容で再判定（より正確に）
        skills_raw = json.loads(build["skills_en"]) if build["skills_en"] else []
        build["combat_style"] = detect_combat_style(
            build["name_en"], skills_raw, page_text[:2000]
        )

    except Exception as e:
        print(f"    詳細ページエラー({url}): {e}")

    return build


async def _extract_pros_cons(page: Page, page_text: str) -> str | None:
    """Strengths/Weaknesses セクションを抽出（section > h2 + bulleted-list方式）"""
    try:
        # sectionタグ内のh2で "Strengths" を含むセクションを探す
        saw_data = await page.evaluate("""() => {
            const sections = document.querySelectorAll('section');
            for (const s of sections) {
                const h2 = s.querySelector('h2');
                if (h2 && h2.textContent.includes('Strengths')) {
                    const header = s.querySelector('header');
                    const content = header ? header.nextElementSibling : null;
                    if (!content) return null;

                    const lists = content.querySelectorAll('div[style*="bulleted-list"]');
                    let pros = [];
                    let cons = [];
                    for (const list of lists) {
                        const style = list.getAttribute('style') || '';
                        const isStrength = style.includes('check');
                        const isWeakness = style.includes('cross');
                        const spans = list.querySelectorAll('span[data-lexical-text="true"]');
                        for (const span of spans) {
                            const t = span.textContent.trim();
                            if (t) {
                                if (isStrength) pros.push(t);
                                else if (isWeakness) cons.push(t);
                            }
                        }
                    }
                    return {pros: pros, cons: cons};
                }
            }
            return null;
        }""")

        if saw_data and (saw_data.get("pros") or saw_data.get("cons")):
            parts = []
            if saw_data.get("pros"):
                parts.append("Pros: " + "; ".join(saw_data["pros"]))
            if saw_data.get("cons"):
                parts.append("Cons: " + "; ".join(saw_data["cons"]))
            return "\n".join(parts)

        # フォールバック: page_textから抽出
        result_parts = []
        text_lower = page_text.lower()
        for label, keywords in [("Pros", ["strengths", "pros"]), ("Cons", ["weaknesses", "cons"])]:
            for keyword in keywords:
                idx = text_lower.find(keyword)
                if idx >= 0:
                    snippet = page_text[idx:idx+500]
                    for delim in ["\n\n", "Equipment", "Passive", "Skills"]:
                        end = snippet.find(delim, len(keyword))
                        if end > 0:
                            snippet = snippet[:end]
                            break
                    result_parts.append(f"{label}: {snippet.strip()}")
                    break

        return "\n".join(result_parts) if result_parts else None
    except Exception:
        return None


async def _extract_core_equipment(page: Page, page_text: str) -> str | None:
    """コア装備・ジュエルリストを抽出（section > h2="Equipment" + img[alt]方式）"""
    try:
        # Equipmentセクション内のimg alt属性からアイテム名を取得
        items = await page.evaluate("""() => {
            const sections = document.querySelectorAll('section');
            for (const s of sections) {
                const h2 = s.querySelector('h2');
                if (h2 && h2.textContent.trim() === 'Equipment') {
                    const imgs = s.querySelectorAll('img[alt]');
                    let names = [];
                    let seen = new Set();
                    for (const img of imgs) {
                        const alt = img.alt.trim();
                        if (alt && alt.length > 2 && !seen.has(alt)) {
                            seen.add(alt);
                            names.push(alt);
                        }
                    }
                    return names;
                }
            }
            return [];
        }""")

        if items:
            return ", ".join(items)

        # フォールバック: data-tippy要素からアイテム名を取得
        tippy_items = await page.evaluate("""() => {
            const sections = document.querySelectorAll('section');
            for (const s of sections) {
                const h2 = s.querySelector('h2');
                if (h2 && h2.textContent.trim() === 'Equipment') {
                    const tippys = s.querySelectorAll('[data-tippy-delegate-id]');
                    let names = [];
                    let seen = new Set();
                    for (const t of tippys) {
                        const text = t.textContent.trim();
                        if (text && text.length > 2 && text.length < 100 && !seen.has(text)) {
                            seen.add(text);
                            names.push(text);
                        }
                    }
                    return names;
                }
            }
            return [];
        }""")

        return ", ".join(tippy_items) if tippy_items else None
    except Exception:
        return None


async def _extract_overview(page: Page, page_text: str) -> str | None:
    """ビルド概要テキストを抽出（section > h2="Build Overview"方式）"""
    try:
        # sectionタグからBuild Overviewを取得
        text = await page.evaluate("""() => {
            const sections = document.querySelectorAll('section');
            for (const s of sections) {
                const h2 = s.querySelector('h2');
                if (h2 && h2.textContent.includes('Build Overview')) {
                    const header = s.querySelector('header');
                    const content = header ? header.nextElementSibling : null;
                    if (content) {
                        return content.textContent.trim();
                    }
                }
            }
            return null;
        }""")

        if text and len(text) > 10:
            return text[:1500]

        # フォールバック: page_textから "overview" を探す
        text_lower = page_text.lower()
        idx = text_lower.find("overview")
        if idx >= 0:
            snippet = page_text[idx:idx+1500].strip()
            return snippet if snippet else None

        return None
    except Exception:
        return None


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
            try:
                print(f"  [{i+1}/{len(all_builds)}] {build['name_en']}")
                all_builds[i] = await _scrape_detail_page(page, build)
                await random_delay(2, 4)
            except Exception as e:
                print(f"  詳細ページスキップ: {e}")

        await browser.close()

    print(f"\nmobalytics: 合計 {len(all_builds)}件取得（3.27/3.26のみ）")
    save_cache("mobalytics", all_builds)
    return all_builds
