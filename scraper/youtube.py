"""YouTube ビルドガイド動画スクレイパー

YouTube動画の検索・スコアリング・字幕取得・LLM抽出・DB格納を一貫して行う。
"""
import asyncio
import json
import math
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp

from scraper.base import save_builds_to_db, detect_combat_style, detect_specialty
from scraper.llm_extractor import extract_build_info_via_llm


# 検索クエリ
SEARCH_QUERIES = [
    "PoE 3.27 build guide",
    "Path of Exile 3.27 build",
    "PoE Keepers of the Flame build guide",
    "PoE 3.27 league starter",
    "PoE 3.27 starter build guide",
]

# 事前フィルタ設定
MIN_DURATION_SECONDS = 300  # 5分
MAX_AGE_DAYS = 180  # 6ヶ月


def search_youtube_videos() -> list[dict]:
    """YouTube動画を検索し、重複排除・事前フィルタを適用"""
    print("=" * 60)
    print("STEP 1: YouTube動画検索")
    print("=" * 60)

    all_videos = {}  # video_id -> video_data

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'skip_download': True,
    }

    for query in SEARCH_QUERIES:
        print(f"\n🔍 検索クエリ: {query}")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # ytsearch20: で20件取得
                search_results = ydl.extract_info(f"ytsearch20:{query}", download=False)

                if not search_results or 'entries' not in search_results:
                    print(f"  検索結果なし")
                    continue

                for video in search_results['entries']:
                    if not video:
                        continue

                    video_id = video.get('id')
                    if not video_id:
                        continue

                    # 重複チェック
                    if video_id in all_videos:
                        continue

                    # メタデータ抽出
                    duration_seconds = video.get('duration', 0)

                    # 投稿日（unixタイムスタンプまたは文字列）
                    timestamp = video.get('timestamp')
                    if timestamp:
                        published_date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    else:
                        # フォールバック: 現在時刻
                        published_date = datetime.now(timezone.utc)

                    # 事前フィルタ: 5分未満除外
                    if duration_seconds < MIN_DURATION_SECONDS:
                        continue

                    # 事前フィルタ: 6ヶ月以内のみ
                    days_ago = (datetime.now(timezone.utc) - published_date).days
                    if days_ago > MAX_AGE_DAYS:
                        continue

                    # チャンネル登録者数
                    subscriber_count = video.get('channel_follower_count', 0) or 0

                    # 視聴回数
                    view_count = video.get('view_count', 0) or 0

                    video_data = {
                        'video_id': video_id,
                        'title': video.get('title', ''),
                        'channel_name': video.get('channel', '') or video.get('uploader', ''),
                        'channel_subscriber_count': subscriber_count,
                        'view_count': view_count,
                        'published_date': published_date,
                        'duration_seconds': duration_seconds,
                        'video_url': f"https://www.youtube.com/watch?v={video_id}",
                        'thumbnail': video.get('thumbnail', ''),
                    }

                    all_videos[video_id] = video_data

                print(f"  ヒット: {len(search_results['entries'])}件, フィルタ後追加: {len(all_videos)}件（累計）")

            # レート制限対策（同期的にsleep）
            import time
            time.sleep(1.5)

        except Exception as e:
            print(f"  ⚠️ 検索エラー: {e}")
            import traceback
            traceback.print_exc()
            continue

    print(f"\n✅ 検索完了: {len(all_videos)}件の動画を取得（重複排除・事前フィルタ済み）")
    return list(all_videos.values())


def calculate_metadata_score(video: dict) -> float:
    """メタデータスコアを計算"""
    now = datetime.now(timezone.utc)
    published_date = video['published_date']

    days_since_publish = max((now - published_date).days, 1)
    view_count = video['view_count']
    subscriber_count = video['channel_subscriber_count']

    # 簡易的にlike/comment数を推定（実際のAPIでは取得可能）
    # ここでは view_count の 5% をlike, 0.5% をcommentと仮定
    like_count = int(view_count * 0.05)
    comment_count = int(view_count * 0.005)

    # スコアリング
    view_velocity = view_count / days_since_publish
    like_ratio = like_count / max(view_count, 1)
    comment_density = comment_count / max(view_count, 1)
    channel_factor = math.log10(max(subscriber_count, 1)) / 7

    score = (
        view_velocity * 0.35 +
        like_ratio * 0.25 * 10000 +
        comment_density * 0.20 * 10000 +
        channel_factor * 0.20 * 1000
    )

    # 投稿7日以内ボーナス
    if days_since_publish <= 7:
        score += 500

    return score


def score_and_filter_videos(videos: list[dict], top_n: int = 50) -> list[dict]:
    """メタデータスコアリングして上位N件を抽出"""
    print("\n" + "=" * 60)
    print("STEP 2: メタデータスコアリング + フィルタリング")
    print("=" * 60)

    # 複数ビルド紹介動画を除外（Tier List, Top 10, Best Builds など）
    exclude_keywords = [
        "tier list", "top 10", "top 5", "top tier", "best builds",
        "best starters", "best league", "ranking", "flowchart"
    ]

    filtered_videos = []
    excluded_count = 0
    for video in videos:
        title_lower = video['title'].lower()
        if any(kw in title_lower for kw in exclude_keywords):
            excluded_count += 1
            continue
        filtered_videos.append(video)

    print(f"  除外: {excluded_count}件（複数ビルド紹介動画）")
    print(f"  残り: {len(filtered_videos)}件")

    for video in filtered_videos:
        video['metadata_score'] = calculate_metadata_score(video)

    # スコア降順でソート
    filtered_videos.sort(key=lambda v: v['metadata_score'], reverse=True)

    print(f"\n📊 スコア分布（上位10件）:")
    for i, video in enumerate(filtered_videos[:10], 1):
        days_ago = (datetime.now(timezone.utc) - video['published_date']).days
        print(f"  {i}. {video['title'][:50]}... (スコア: {video['metadata_score']:.1f}, {days_ago}日前, {video['view_count']:,} views)")

    top_videos = filtered_videos[:top_n]
    print(f"\n✅ 上位{top_n}件を選抜")

    return top_videos


async def get_video_transcript(video_id: str) -> str | None:
    """動画の字幕を取得（英語優先）"""
    try:
        # 新しいAPIを使用してインスタンスを作成
        api = YouTubeTranscriptApi()
        # 英語字幕を取得（手動または自動生成）
        fetched = api.fetch(video_id, languages=['en'])

        # FetchedTranscript オブジェクトから snippets を取得
        full_text = ' '.join([snippet.text for snippet in fetched.snippets])

        # 先頭15000文字に切り詰め
        if len(full_text) > 15000:
            full_text = full_text[:15000]

        return full_text

    except Exception as e:
        # 字幕なし or エラー（詳細ログ出力）
        print(f"    字幕取得エラー: {type(e).__name__}: {str(e)[:100]}")
        return None


async def extract_build_from_transcript(video: dict, transcript: str) -> dict | None:
    """字幕テキストからビルド情報をLLM抽出"""
    # プロンプトに追加指示を含めて既存のLLM抽出を呼び出す
    enhanced_prompt = f"""このテキストはYouTube動画の書き起こしです。
フィラー（uh, um等）は無視し、ビルド情報のみ抽出してください。
複数ビルド紹介時はメインビルドを抽出してください。

{transcript}"""

    # 既存のextract_build_info_via_llmを使用
    result = extract_build_info_via_llm(enhanced_prompt, video['title'])

    if not result or not result.get('description_en'):
        return None

    # ビルドデータ構築
    build = {
        'source': 'youtube',
        'source_id': video['video_id'],
        'source_url': video['video_url'],
        'name_en': video['title'],  # LLM抽出結果があればそれを使用
        'class_en': result.get('class_en') or 'Unknown',
        'ascendancy_en': result.get('ascendancy_en'),
        'skills_en': json.dumps([]),  # LLMから抽出したスキルがあれば追加可能
        'description_en': result.get('description_en'),
        'patch': '3.27',
        'build_types': json.dumps([]),
        'author': video['channel_name'],
        'favorites': video['view_count'],
        'verified': 0,
        'hc': 0,
        'ssf': 0,
        'playstyle': None,
        'activities': None,
        'cost_tier': None,
        'damage_types': None,
        'combat_style': detect_combat_style(
            video['title'],
            [],
            result.get('description_en', '')
        ),
        'specialty': json.dumps(detect_specialty([], result.get('description_en', ''))),
        'pros_cons_en': result.get('pros_cons_en'),
        'pros_cons_ja': None,
        'core_equipment_en': result.get('core_equipment_en'),
        'core_equipment_ja': None,
    }

    return build


async def scrape_youtube_builds():
    """YouTubeビルドガイド動画のスクレイピング全体フロー"""
    print("\n" + "=" * 60)
    print("YouTubeビルドガイドスクレイパー 開始")
    print("=" * 60)

    # STEP 1: 動画検索
    videos = search_youtube_videos()

    if not videos:
        print("❌ 検索結果が0件です")
        return

    # STEP 2: メタデータスコアリング（上位50件）
    top_videos = score_and_filter_videos(videos, top_n=50)

    # STEP 3: コメントセンチメント判定はスキップ（技術的困難性）
    print("\n" + "=" * 60)
    print("STEP 3: コメントセンチメント判定")
    print("=" * 60)
    print("⚠️ コメント取得APIの制限により、このステップはスキップします")
    print("   メタデータスコアのみで上位30件を選抜します")

    selected_videos = top_videos[:30]

    # STEP 4-5: 字幕取得 & LLM抽出
    print("\n" + "=" * 60)
    print("STEP 4-5: 字幕取得 & LLM抽出")
    print("=" * 60)

    builds = []
    skipped_videos = []

    for i, video in enumerate(selected_videos, 1):
        print(f"\n[{i}/{len(selected_videos)}] {video['title'][:60]}...")

        # 字幕取得
        transcript = await get_video_transcript(video['video_id'])

        if not transcript:
            print(f"  ⚠️ 字幕取得失敗 - スキップ")
            skipped_videos.append({
                'video_id': video['video_id'],
                'title': video['title'],
                'reason': '字幕なし'
            })
            continue

        print(f"  ✅ 字幕取得成功 ({len(transcript)}文字)")

        # LLM抽出
        build = await extract_build_from_transcript(video, transcript)

        if not build:
            print(f"  ⚠️ LLM抽出失敗 - スキップ")
            skipped_videos.append({
                'video_id': video['video_id'],
                'title': video['title'],
                'reason': 'LLM抽出失敗'
            })
            continue

        print(f"  ✅ LLM抽出成功")
        builds.append(build)

        # レート制限対策
        await asyncio.sleep(2)

    # STEP 6: DB格納
    print("\n" + "=" * 60)
    print("STEP 6: DB格納")
    print("=" * 60)

    if builds:
        await save_builds_to_db(builds)
        print(f"\n✅ DB格納完了: {len(builds)}件")
    else:
        print("⚠️ 格納するビルドが0件です")

    # スキップした動画のサマリー
    if skipped_videos:
        print(f"\n⚠️ スキップした動画: {len(skipped_videos)}件")
        for sv in skipped_videos[:5]:
            print(f"  - {sv['title'][:50]}... ({sv['reason']})")
        if len(skipped_videos) > 5:
            print(f"  ... 他 {len(skipped_videos) - 5}件")

    # STEP 7: 翻訳
    print("\n" + "=" * 60)
    print("STEP 7: 翻訳")
    print("=" * 60)
    print("翻訳は translator/claude_cli.py を使って別途実行してください:")
    print("  cd /Users/thiroki34/poe-build-search")
    print("  python -m translator.claude_cli --all")

    # STEP 8: 検証
    print("\n" + "=" * 60)
    print("STEP 8: 検証")
    print("=" * 60)
    await validate_youtube_builds()

    print("\n" + "=" * 60)
    print("✅ YouTubeスクレイパー完了")
    print("=" * 60)


async def validate_youtube_builds():
    """YouTube由来ビルドの検証"""
    import aiosqlite
    from app.config import settings

    db = await aiosqlite.connect(settings.db_path)
    try:
        # YouTube由来ビルド件数
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM builds WHERE source = 'youtube'"
        )
        row = await cursor.fetchone()
        youtube_count = row[0] if row else 0

        # ゴミパターン検出（description_enにGARBAGE_PATTERNSが含まれる）
        from scraper.base import GARBAGE_PATTERNS
        garbage_count = 0
        for pattern in GARBAGE_PATTERNS:
            cursor = await db.execute(
                f"SELECT COUNT(*) as cnt FROM builds WHERE source = 'youtube' AND description_en LIKE '%{pattern}%'"
            )
            row = await cursor.fetchone()
            if row and row[0] > 0:
                garbage_count += row[0]

        # class_ja NULL（YouTube由来）
        cursor = await db.execute(
            "SELECT COUNT(*) as cnt FROM builds WHERE source = 'youtube' AND class_ja IS NULL"
        )
        row = await cursor.fetchone()
        class_ja_null = row[0] if row else 0

        print(f"  YouTube由来ビルド件数: {youtube_count}件")
        print(f"  ゴミパターン検出: {garbage_count}件")
        print(f"  class_ja NULL: {class_ja_null}件")

        if garbage_count == 0 and class_ja_null == 0:
            print("  ✅ 検証OK")
        else:
            print("  ⚠️ 検証エラーあり")

    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(scrape_youtube_builds())
