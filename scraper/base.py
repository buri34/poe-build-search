"""スクレイパー共通機能: ディレイ、キャッシュ、リトライ、戦闘スタイル/得意分野判定"""
import json
import random
import asyncio
import subprocess
import os
import re
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


# Layer 2: 形式バリデーション用パターン
GARBAGE_PATTERNS = [
    "__typename", "NgfDocument", "apolloState", "__APOLLO_STATE__",
    "__NEXT_DATA__", "graphql", '"edges":', '"node":', '"cursor":',
]


def is_garbage_text(text: str) -> bool:
    """JSONメタデータ・構造データが混入していないかチェック"""
    if not text:
        return True
    text_lower = text.lower()
    for pattern in GARBAGE_PATTERNS:
        if pattern.lower() in text_lower:
            return True
    json_chars = text.count('{') + text.count('}') + text.count('":')
    if len(text) > 0 and json_chars / len(text) > 0.05:
        return True
    return False


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


# Layer 3: 意味的バリデーション関数
def validate_build_semantically(build: dict) -> dict:
    """Claude CLIで各フィールドの内容が意味的に正しいか検証"""
    prompt = f"""以下はPoE 1のビルドガイドから抽出したデータです。各フィールドが適切か判定してください。
ビルド名: {build.get('name_en', '')}
概要: {build.get('description_en', '')[:500]}
長所短所: {build.get('pros_cons_en', '')[:500]}
コア装備: {build.get('core_equipment_en', '')[:300]}

判定基準:
1. 概要はそのビルドの説明として意味をなすか？（JSONデータ、HTMLタグ、ナビゲーション文字列ではないか）
2. 長所短所にはビルドのPros/Consが書かれているか？
3. コア装備にはPoEの装備・アイテム名が含まれているか？

回答: JSON形式のみ {{"valid": true/false, "issues": ["問題点"]}}"""

    clean_env = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE')}
    try:
        result = subprocess.run(
            ["claude", "--model", "sonnet", "-p", prompt],
            capture_output=True, text=True, timeout=60,
            env=clean_env,
        )
        # JSON抽出
        match = re.search(r'\{.*\}', result.stdout, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"  意味的バリデーションエラー: {e}")
    return {"valid": True, "issues": []}  # エラー時はパスさせる


def regenerate_field(build: dict, field: str, page_text: str) -> str | None:
    """Claude CLIでページ本文から該当フィールドを要約・再生成"""
    field_prompts = {
        "description_en": "Summarize this PoE build guide in 2-3 sentences. Focus on the main attack skill, synergies, and combat style (melee/ranged/caster).",
        "pros_cons_en": "Extract the Pros and Cons of this PoE build. Format:\nPros:\n- ...\nCons:\n- ...",
        "core_equipment_en": "List the core/required unique items and equipment for this PoE build. Just item names, comma-separated.",
    }
    prompt_text = field_prompts.get(field, "")
    if not prompt_text or not page_text:
        return None

    full_prompt = f"{prompt_text}\n\nBuild guide text:\n{page_text[:3000]}"
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE')}
    try:
        result = subprocess.run(
            ["claude", "--model", "sonnet", "-p", full_prompt],
            capture_output=True, text=True, timeout=60,
            env=clean_env,
        )
        output = result.stdout.strip()
        if output and len(output) > 20:
            return output
    except Exception:
        pass
    return None


async def save_builds_to_db(builds: list[dict]):
    """スクレイピング結果をDBに保存（3層バリデーション付き）"""
    import aiosqlite
    db = await aiosqlite.connect(settings.db_path)
    try:
        saved_count = 0
        skipped_count = 0
        semantic_invalid_count = 0
        semantic_issues_summary = []

        for b in builds:
            # Layer 1: 基本バリデーション（長さチェック）
            skip_reason = []
            desc = b.get("description_en") or ""
            if not desc or len(desc) < 50:
                skip_reason.append(f"description_en不足({len(desc)}文字)")

            pros_cons = b.get("pros_cons_en") or ""
            core_eq = b.get("core_equipment_en") or ""

            # Layer 2: 形式バリデーション（GARBAGE_PATTERNS検知）
            if is_garbage_text(desc):
                skip_reason.append("description_enにゴミデータ検出")
                print(f"  [GARBAGE] {b.get('source_id', 'unknown')}: description_enがJSONメタデータ")
                skipped_count += 1
                continue

            if is_garbage_text(pros_cons):
                print(f"  [GARBAGE] {b.get('source_id', 'unknown')}: pros_cons_enをNULLにリセット")
                b["pros_cons_en"] = None

            if is_garbage_text(core_eq):
                print(f"  [GARBAGE] {b.get('source_id', 'unknown')}: core_equipment_enをNULLにリセット")
                b["core_equipment_en"] = None

            # 必須フィールドの空チェック（Layer 2通過後）
            if not b.get("pros_cons_en"):
                skip_reason.append("pros_cons_en空")
            if not b.get("core_equipment_en"):
                skip_reason.append("core_equipment_en空")

            if skip_reason:
                print(f"  [SKIP] {b.get('source_id', 'unknown')}: {', '.join(skip_reason)}")
                skipped_count += 1
                continue

            # Layer 3: 意味的バリデーション（Claude CLI LLMチェック）
            validation_result = validate_build_semantically(b)
            if not validation_result.get("valid", True):
                issues = validation_result.get("issues", ["不明な問題"])
                print(f"  [SEMANTIC] {b.get('source_id', 'unknown')}: 意味的バリデーション失敗 - {', '.join(issues)}")
                semantic_invalid_count += 1
                semantic_issues_summary.extend(issues)
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

        # Layer 3バリデーション結果のサマリー
        if semantic_invalid_count > 0:
            print(f"\n  [意味的バリデーション] 無効: {semantic_invalid_count}件")
            unique_issues = list(set(semantic_issues_summary))
            print(f"  主な問題点: {', '.join(unique_issues[:5])}")

        print(f"  DB保存完了: {saved_count}件 (スキップ: {skipped_count}件)")
    finally:
        await db.close()
