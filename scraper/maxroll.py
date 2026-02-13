"""maxroll.gg スクレイパー: window.__remixContext + Playwright方式 + 詳細ページ抽出"""
import json
import re
import asyncio
import argparse
from playwright.async_api import async_playwright, Page

from scraper.base import (
    random_delay, save_cache, load_cache, save_builds_to_db,
    detect_combat_style, detect_specialty,
)

BASE_URL = "https://maxroll.gg/poe/build-guides"
# 対象パッチバージョン
ALLOWED_PATCHES = {"3.27", "3.26"}
# パッチ情報が取れない場合のデフォルト
DEFAULT_PATCH = "3.27"


def _normalize_build(raw: dict) -> dict | None:
    """ビルドデータを正規化してDB保存用dictを返す"""
    try:
        name = raw.get("name_en") or ""
        if not name:
            return None

        # パッチフィルタ
        patch = raw.get("patch") or DEFAULT_PATCH
        patch_short = ""
        if patch:
            m = re.match(r"(\d+\.\d+)", str(patch))
            if m:
                patch_short = m.group(1)
        if patch_short not in ALLOWED_PATCHES:
            return None

        # スキルJSON変換
        skills = raw.get("skills_en") or []
        if isinstance(skills, list):
            skills_json = json.dumps(skills) if skills else None
        else:
            skills_json = skills

        # ビルドタイプJSON変換
        build_types = raw.get("build_types") or []
        if isinstance(build_types, list):
            build_types_json = json.dumps(build_types) if build_types else None
        else:
            build_types_json = build_types

        # プレイスタイルJSON変換
        playstyle = raw.get("playstyle") or []
        if isinstance(playstyle, list):
            playstyle_json = json.dumps(playstyle) if playstyle else None
        else:
            playstyle_json = playstyle

        # アクティビティJSON変換
        activities = raw.get("activities") or []
        if isinstance(activities, list):
            activities_json = json.dumps(activities) if activities else None
        else:
            activities_json = activities

        # ダメージタイプJSON変換
        damage_types = raw.get("damage_types") or []
        if isinstance(damage_types, list):
            damage_types_json = json.dumps(damage_types) if damage_types else None
        else:
            damage_types_json = damage_types

        description = raw.get("description_en") or ""

        # 戦闘スタイル判定
        skills_list = raw.get("skills_en") or []
        if isinstance(skills_list, str):
            try:
                skills_list = json.loads(skills_list)
            except (json.JSONDecodeError, TypeError):
                skills_list = []
        combat_style = raw.get("combat_style") or detect_combat_style(name, skills_list, description)

        # 得意分野判定（playstyle/activities/build_typesを全て活用）
        all_tags = []
        for tag_source in [build_types, playstyle, activities]:
            if isinstance(tag_source, list):
                all_tags.extend(tag_source)
            elif isinstance(tag_source, str):
                all_tags.append(tag_source)
        specialty = raw.get("specialty") or detect_specialty(all_tags, description)

        return {
            "source": "maxroll",
            "source_id": raw.get("source_id") or "",
            "source_url": raw.get("source_url") or "",
            "name_en": name,
            "class_en": raw.get("class_en") or "",
            "ascendancy_en": raw.get("ascendancy_en") or "",
            "skills_en": skills_json,
            "description_en": description,
            "patch": str(patch),
            "build_types": build_types_json,
            "author": raw.get("author"),
            "favorites": raw.get("favorites") or 0,
            "verified": raw.get("verified") or 0,
            "hc": raw.get("hc") or 0,
            "ssf": raw.get("ssf") or 0,
            "playstyle": playstyle_json,
            "activities": activities_json,
            "cost_tier": raw.get("cost_tier"),
            "damage_types": damage_types_json,
            "combat_style": combat_style,
            "specialty": json.dumps(specialty) if isinstance(specialty, list) else specialty,
            "pros_cons_en": raw.get("pros_cons_en"),
            "pros_cons_ja": None,
            "core_equipment_en": raw.get("core_equipment_en"),
            "core_equipment_ja": None,
        }
    except Exception as e:
        print(f"  正規化エラー: {e}")
        return None


async def _extract_remix_context(page: Page) -> dict | None:
    """window.__remixContext からデータを抽出"""
    try:
        remix_data = await page.evaluate("""
            () => {
                if (window.__remixContext) {
                    return window.__remixContext;
                }
                return null;
            }
        """)
        return remix_data
    except Exception as e:
        print(f"  __remixContext 抽出エラー: {e}")
        return None


async def _scrape_build_list(page: Page, max_pages: int = None) -> list[dict]:
    """ビルド一覧ページからビルド情報を取得（ページネーション対応）"""
    all_builds = []
    seen_ids = set()
    current_page = 1

    while True:
        if max_pages and current_page > max_pages:
            break

        if current_page == 1:
            url = BASE_URL
        else:
            url = f"{BASE_URL}/page/{current_page}"

        print(f"  一覧ページ {current_page} アクセス中: {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await random_delay(1.5, 3.0)
        except Exception as e:
            print(f"  ページ {current_page} アクセス失敗: {e}")
            break

        remix_data = await _extract_remix_context(page)
        if not remix_data:
            print(f"  ページ {current_page}: __remixContext が見つかりません")
            break

        builds = _extract_builds_from_remix(remix_data)
        if not builds:
            print(f"  ページ {current_page}: ビルドデータが見つかりません")
            break

        # PoE1のビルドのみフィルタ（PoE2除外）
        poe1_builds = []
        for b in builds:
            game = b.get("game") or b.get("post_game") or ""
            if game and "poe2" in game.lower():
                continue
            if game and "path of exile 2" in game.lower():
                continue

            permalink = b.get("post_permalink") or b.get("permalink") or ""
            if "/poe2/" in permalink or "/path-of-exile-2/" in permalink:
                continue

            build_id = b.get("post_permalink") or b.get("permalink") or ""
            if build_id and build_id not in seen_ids:
                seen_ids.add(build_id)
                poe1_builds.append(b)

        print(f"  ページ {current_page}: {len(poe1_builds)} 件のPoE1ビルド取得")
        all_builds.extend(poe1_builds)

        has_next = await _check_next_page(page)
        if not has_next:
            print(f"  ページネーション終了（ページ {current_page}）")
            break

        current_page += 1
        await random_delay(2.0, 4.0)

    print(f"  一覧取得完了: 全 {len(all_builds)} 件")
    return all_builds


def _extract_builds_from_remix(remix_data: dict) -> list[dict]:
    """__remixContext から ビルドリスト（hits）を抽出"""
    try:
        loader_data = remix_data.get("state", {}).get("loaderData", {})

        for route_key, route_value in loader_data.items():
            if not isinstance(route_value, dict):
                continue

            search_data = route_value.get("searchData", {})
            if search_data and "initialSearchResponse" in search_data:
                initial_response = search_data["initialSearchResponse"]
                if isinstance(initial_response, dict) and "hits" in initial_response:
                    hits = initial_response["hits"]
                    if isinstance(hits, list):
                        return hits

            if search_data and "initialResults" in search_data:
                results = search_data["initialResults"]
                if isinstance(results, list):
                    return results

            if "initialResults" in route_value:
                results = route_value["initialResults"]
                if isinstance(results, list):
                    return results

        return []
    except Exception as e:
        print(f"  ビルドリスト抽出エラー: {e}")
        return []


async def _check_next_page(page: Page) -> bool:
    """次ページのリンクが存在するか確認"""
    try:
        next_btn = page.locator("a:has-text('Next'), a[rel='next']")
        count = await next_btn.count()
        return count > 0
    except Exception:
        return False


async def _extract_pros_cons(page: Page, page_text: str) -> str | None:
    """Pros/Cons セクションを抽出"""
    try:
        result_parts = []
        text_lower = page_text.lower()

        # "Pros" / "Pros and Cons" セクションを探す
        for keyword_pair in [("pros", "cons"), ("strengths", "weaknesses")]:
            pros_kw, cons_kw = keyword_pair
            pros_idx = text_lower.find(pros_kw)
            cons_idx = text_lower.find(cons_kw)

            if pros_idx >= 0:
                # Prosの範囲: キーワードからConsまで、またはセクション終端まで
                end = cons_idx if cons_idx > pros_idx else pros_idx + 500
                snippet = page_text[pros_idx:min(end, pros_idx + 500)].strip()
                if snippet:
                    result_parts.append(f"Pros: {snippet}")

            if cons_idx >= 0:
                # Consの範囲: キーワードから次のセクションまで
                snippet = page_text[cons_idx:cons_idx + 500]
                for delimiter in ["Equipment", "Gear", "Passive", "Skills", "Leveling", "Build Overview"]:
                    delim_idx = snippet.find(delimiter)
                    if delim_idx > len(cons_kw):
                        snippet = snippet[:delim_idx]
                        break
                result_parts.append(f"Cons: {snippet.strip()}")

            if result_parts:
                break

        return "\n".join(result_parts) if result_parts else None
    except Exception:
        return None


async def _extract_core_equipment(page: Page, page_text: str) -> str | None:
    """コア装備・ジュエルを抽出"""
    try:
        equipment_items = []

        # ページ内のPoEアイテムリンクを探す
        item_links = page.locator('a[href*="/poe/items/"], a[href*="/poe/unique/"], .poe-item')
        count = await item_links.count()
        for i in range(min(count, 30)):
            text = await item_links.nth(i).text_content()
            if text and text.strip() and len(text.strip()) > 2:
                equipment_items.append(text.strip())

        # テキストからGear/Equipmentセクションのアイテムを探す
        if not equipment_items:
            text_lower = page_text.lower()
            for section_kw in ["gear", "equipment", "items"]:
                idx = text_lower.find(section_kw)
                if idx >= 0:
                    snippet = page_text[idx:idx + 2000]
                    lines = snippet.split('\n')
                    for line in lines[1:30]:
                        line = line.strip()
                        if line and 3 < len(line) < 80 and not line.lower().startswith(('gear', 'equipment', 'slot', 'type', 'item')):
                            equipment_items.append(line)
                    if equipment_items:
                        break

        # 重複排除
        seen = set()
        unique_items = []
        for item in equipment_items:
            if item not in seen:
                seen.add(item)
                unique_items.append(item)

        return ", ".join(unique_items[:15]) if unique_items else None
    except Exception:
        return None


async def _scrape_build_detail(page: Page, build_meta: dict) -> dict | None:
    """ビルド詳細ページから情報を取得"""
    permalink = build_meta.get("post_permalink") or build_meta.get("permalink") or ""
    if not permalink:
        return None

    if not permalink.startswith("http"):
        url = f"https://maxroll.gg{permalink}"
    else:
        url = permalink

    print(f"    詳細取得: {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await random_delay(1.0, 2.0)
    except Exception as e:
        print(f"    詳細ページアクセス失敗: {e}")
        return None

    try:
        # ビルド名（h1タグ）
        build_name = build_meta.get("post_title") or ""
        h1_el = page.locator("h1").first
        if await h1_el.count() > 0:
            h1_text = await h1_el.text_content()
            if h1_text:
                build_name = h1_text.strip()

        # クラス・アセンダンシー（taxonomies から）
        taxonomies = build_meta.get("taxonomies", {})
        classes_list = taxonomies.get("classes", [])
        ascendancy = ""
        class_name = ""

        cleaned_classes = [cls.replace("poe-", "").replace("-", " ").title() for cls in classes_list]

        if len(cleaned_classes) >= 2:
            ascendancy = cleaned_classes[0]
            class_name = cleaned_classes[1]
        elif len(cleaned_classes) == 1:
            ascendancy = cleaned_classes[0]

        if ascendancy and not class_name:
            class_mapping = {
                "Deadeye": "Ranger", "Raider": "Ranger", "Pathfinder": "Ranger",
                "Elementalist": "Witch", "Necromancer": "Witch", "Occultist": "Witch",
                "Juggernaut": "Marauder", "Berserker": "Marauder", "Chieftain": "Marauder",
                "Assassin": "Shadow", "Trickster": "Shadow", "Saboteur": "Shadow",
                "Slayer": "Duelist", "Gladiator": "Duelist", "Champion": "Duelist",
                "Inquisitor": "Templar", "Hierophant": "Templar", "Guardian": "Templar",
                "Ascendant": "Scion"
            }
            class_name = class_mapping.get(ascendancy, "")

        # スキル（.poe-item 要素）
        skills = []
        skill_elements = page.locator(".poe-item")
        skill_count = await skill_elements.count()
        for i in range(min(skill_count, 20)):
            skill_el = skill_elements.nth(i)
            skill_text = await skill_el.text_content()
            if skill_text:
                skills.append(skill_text.strip())

        seen_skills = set()
        unique_skills = []
        for s in skills:
            if s and s not in seen_skills:
                seen_skills.add(s)
                unique_skills.append(s)

        # ビルド概要
        description = build_meta.get("post_excerpt") or ""
        if not description:
            first_p = page.locator("article p, .gutenbergBlock p").first
            if await first_p.count() > 0:
                p_text = await first_p.text_content()
                if p_text:
                    description = p_text.strip()[:500]

        # ページ全文（Pros/Cons、装備抽出用）
        page_text = await page.text_content("body") or ""

        # Pros/Cons 抽出
        pros_cons = await _extract_pros_cons(page, page_text)

        # コア装備抽出
        core_equipment = await _extract_core_equipment(page, page_text)

        # パッチバージョン（ページ内テキストから推定）
        patch = None
        patch_match = re.search(r'(?:patch|version|update)\s*(\d+\.\d+)', page_text.lower())
        if patch_match:
            patch = patch_match.group(1)
        if not patch:
            # URLやタイトルから推定
            patch_match2 = re.search(r'3\.\d+', build_name + url)
            if patch_match2:
                patch = patch_match2.group(0)
        if not patch:
            patch = DEFAULT_PATCH

        # ビルドタイプ（misc から抽出）
        misc_list = taxonomies.get("misc", [])
        build_types = [m.replace("poe-", "").replace("-", " ").title() for m in misc_list]

        # プレイスタイル
        num_list = taxonomies.get("num", [])
        playstyle = [n.replace("poe-", "").replace("-", " ").title() for n in num_list]

        # アクティビティ
        metas_list = taxonomies.get("metas", [])
        activities = [m.replace("poe-", "").replace("-", " ").title() for m in metas_list]

        # コストティア
        cost_tier = None
        for misc in misc_list:
            if "budget" in misc.lower() or "cheap" in misc.lower():
                cost_tier = "Budget"
            elif "expensive" in misc.lower() or "high" in misc.lower():
                cost_tier = "Expensive"

        # ダメージタイプ
        damage_type_list = taxonomies.get("damage_type", [])
        damage_types = [d.replace("-", " ").title() for d in damage_type_list]

        # 著者
        author_info = build_meta.get("post_author", {})
        author = author_info.get("display_name") if isinstance(author_info, dict) else ""

        source_id = permalink.split("/")[-1] or permalink

        # description_en強化: 戦闘スタイルとメインスキルを含める
        combat_style = detect_combat_style(build_name, unique_skills, description + " " + page_text[:1000])
        enhanced_desc = description
        if unique_skills and not any(s.lower() in description.lower() for s in unique_skills[:3]):
            skill_info = f"Main skills: {', '.join(unique_skills[:5])}. "
            enhanced_desc = skill_info + description

        return {
            "source_id": source_id,
            "source_url": url,
            "name_en": build_name,
            "class_en": class_name,
            "ascendancy_en": ascendancy,
            "skills_en": unique_skills,
            "description_en": enhanced_desc,
            "patch": patch,
            "build_types": build_types,
            "author": author,
            "favorites": 0,
            "verified": 0,
            "hc": 0,
            "ssf": 0,
            "playstyle": playstyle,
            "activities": activities,
            "cost_tier": cost_tier,
            "damage_types": damage_types,
            "combat_style": combat_style,
            "pros_cons_en": pros_cons,
            "core_equipment_en": core_equipment,
        }

    except Exception as e:
        print(f"    詳細解析エラー: {e}")
        return None


async def scrape_maxroll(use_cache: bool = True, test_mode: bool = False) -> list[dict]:
    """maxroll.gg から全PoE1ビルドをスクレイピング（3.27/3.26のみ）"""
    if use_cache:
        cached = load_cache("maxroll")
        if cached:
            print(f"maxroll: キャッシュ使用 ({cached['count']}件, {cached['scraped_at']})")
            return cached["builds"]

    print("maxroll.gg スクレイピング開始（パッチ3.27/3.26のみ）")
    all_builds: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        try:
            max_pages = 1 if test_mode else None
            build_list = await _scrape_build_list(page, max_pages=max_pages)

            if test_mode:
                build_list = build_list[:5]
                print(f"  テストモード: 最初の {len(build_list)} 件のみ処理")

            # 各ビルドの詳細を取得（Pros/Cons、装備情報含む）
            for idx, build_meta in enumerate(build_list, 1):
                print(f"  [{idx}/{len(build_list)}] ビルド詳細取得中...")
                build_detail = await _scrape_build_detail(page, build_meta)
                if build_detail:
                    normalized = _normalize_build(build_detail)
                    if normalized:
                        all_builds.append(normalized)
                    else:
                        print(f"    パッチフィルタで除外")
                await random_delay(2.0, 5.0)

        except Exception as e:
            print(f"  スクレイピングエラー: {e}")
        finally:
            await browser.close()

    print(f"maxroll: 合計 {len(all_builds)} 件取得（3.27/3.26のみ）")

    if all_builds:
        save_cache("maxroll", all_builds)

    return all_builds


async def main():
    """メインエントリポイント"""
    parser = argparse.ArgumentParser(description="maxroll.gg スクレイパー")
    parser.add_argument("--no-cache", action="store_true", help="キャッシュを使用しない")
    parser.add_argument("--test", action="store_true", help="テストモード（最初の5件のみ）")
    parser.add_argument("--no-db", action="store_true", help="DB保存をスキップ")
    args = parser.parse_args()

    use_cache = not args.no_cache
    builds = await scrape_maxroll(use_cache=use_cache, test_mode=args.test)

    if builds and not args.no_db:
        print("DB保存中...")
        await save_builds_to_db(builds)
        print("完了")
    elif not builds:
        print("ビルドが取得できませんでした")
    else:
        print("スクレイピング完了（DB保存スキップ）")


if __name__ == "__main__":
    asyncio.run(main())
