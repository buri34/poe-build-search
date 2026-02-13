"""Reddit評価スクレイパー: .jsonエンドポイントでPoEビルド評価を収集"""
import json
import sqlite3
import subprocess
import time
import urllib.parse
from pathlib import Path

# プロジェクトルートとDB
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "poe_builds.db"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
RATE_LIMIT_SEC = 2.0

# 検索対象subreddit
SUBREDDITS = ["pathofexile", "PathOfExileBuilds"]

# 固定検索キーワード
BASE_QUERIES = [
    "3.27",
    "league starter 3.27",
    "keepers of the flame build",
    "build guide 3.27",
]

# センチメント分析キーワード
POSITIVE_KEYWORDS = [
    "league starter", "strong", "broken", "recommended", "best",
    "top tier", "s tier", "amazing", "great", "insane", "busted",
]
NEGATIVE_KEYWORDS = [
    "dead", "gutted", "don't play", "nerfed", "worst",
    "trash", "avoid", "terrible", "bad",
]


def _fetch_json(url: str) -> dict | None:
    """curlでJSONを取得（urllibはRedditに403でブロックされるため）"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-H", f"User-Agent: {USER_AGENT}", url],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode != 0:
            print(f"  curl失敗({url[:80]}...): exit {result.returncode}")
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print(f"  タイムアウト({url[:80]}...)")
        return None
    except (json.JSONDecodeError, Exception) as e:
        print(f"  HTTP取得エラー({url[:80]}...): {e}")
        return None


def _search_reddit(subreddit: str, query: str) -> list[dict]:
    """Reddit検索APIで投稿一覧を取得"""
    params = urllib.parse.urlencode({
        "q": query,
        "restrict_sr": "on",
        "sort": "relevance",
        "t": "month",
        "limit": "50",
    })
    url = f"https://www.reddit.com/r/{subreddit}/search.json?{params}"
    data = _fetch_json(url)
    if not data:
        return []

    posts = []
    children = data.get("data", {}).get("children", [])
    for child in children:
        d = child.get("data", {})
        posts.append({
            "title": d.get("title", ""),
            "selftext": d.get("selftext", ""),
            "score": d.get("score", 0),
            "num_comments": d.get("num_comments", 0),
            "upvote_ratio": d.get("upvote_ratio", 0.5),
            "url": f"https://www.reddit.com{d.get('permalink', '')}",
            "created_utc": d.get("created_utc", 0),
            "link_flair_text": d.get("link_flair_text", ""),
        })
    return posts


def _get_builds_from_db() -> list[dict]:
    """DBからビルド情報を取得（マッチング用）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name_en, skills_en, ascendancy_en FROM builds"
    ).fetchall()
    conn.close()

    builds = []
    for r in rows:
        skills = []
        if r["skills_en"]:
            try:
                skills = json.loads(r["skills_en"])
            except (json.JSONDecodeError, TypeError):
                pass
        builds.append({
            "id": r["id"],
            "name_en": r["name_en"],
            "skills_en": skills,
            "ascendancy_en": r["ascendancy_en"] or "",
        })
    return builds


def _get_top_skill_queries(builds: list[dict], top_n: int = 10) -> list[str]:
    """既存ビルドのスキル名上位N件を検索キーワードとして抽出"""
    skill_count: dict[str, int] = {}
    # サポートジェムや装備を除外するキーワード
    exclude = {"support", "flask", "orb", "gear", "hybrid", "divine", "cast when",
               "immortal call", "frenzy", "mark", "recall", "offering"}
    for b in builds:
        for s in b["skills_en"]:
            s_lower = s.lower()
            if any(ex in s_lower for ex in exclude):
                continue
            if len(s) < 4:
                continue
            skill_count[s] = skill_count.get(s, 0) + 1

    sorted_skills = sorted(skill_count.items(), key=lambda x: -x[1])
    return [s for s, _ in sorted_skills[:top_n]]


def _match_build(post_text: str, builds: list[dict]) -> list[dict]:
    """投稿テキストに対してビルドをマッチング（部分一致）"""
    text_lower = post_text.lower()
    matched = []
    for b in builds:
        # スキル名でマッチ（メインスキル = skills_en の先頭要素を優先）
        main_skills = b["skills_en"][:3] if b["skills_en"] else []
        for skill in main_skills:
            if len(skill) >= 4 and skill.lower() in text_lower:
                matched.append(b)
                break
        else:
            # ascendancy名でマッチ
            if b["ascendancy_en"] and len(b["ascendancy_en"]) >= 4:
                if b["ascendancy_en"].lower() in text_lower:
                    matched.append(b)
    return matched


def _analyze_sentiment(title: str, selftext: str, score: int, upvote_ratio: float) -> str | None:
    """センチメント判定。ポジティブなら"positive"、ネガティブならNone（除外対象）"""
    text_lower = f"{title} {selftext}".lower()

    has_positive = any(kw in text_lower for kw in POSITIVE_KEYWORDS)
    has_negative = any(kw in text_lower for kw in NEGATIVE_KEYWORDS)

    # ネガティブ判定 → 除外
    if has_negative and not has_positive:
        return None

    # ポジティブ判定: ポジティブKW + upvote_ratio > 0.8 + score > 10
    if has_positive and upvote_ratio > 0.8 and score > 10:
        return "positive"

    # ポジティブKWなしでもスコアが高ければポジティブとみなす
    if score > 50 and upvote_ratio > 0.85 and not has_negative:
        return "positive"

    # 判定不能 → 除外
    return None


def _generate_summary(posts: list[dict]) -> str:
    """マッチした投稿群から要約を生成"""
    if not posts:
        return ""

    # 最もスコアが高い投稿のタイトルを軸にサマリー生成
    top_post = max(posts, key=lambda p: p["score"])
    mention_count = len(posts)
    total_score = sum(p["score"] for p in posts)

    parts = []
    if mention_count > 1:
        parts.append(f"Mentioned in {mention_count} posts with total score {total_score}.")
    else:
        parts.append(f"Mentioned in 1 post with score {total_score}.")

    # ポジティブキーワードを抽出
    all_text = " ".join(f"{p['title']} {p['selftext']}" for p in posts).lower()
    found_positive = [kw for kw in POSITIVE_KEYWORDS if kw in all_text]
    if found_positive:
        parts.append(f"Praised as: {', '.join(found_positive[:3])}.")

    # 最高スコア投稿のタイトルを引用
    parts.append(f'Top post: "{top_post["title"][:100]}"')

    return " ".join(parts)


def scrape_reddit():
    """メイン処理: Reddit検索 → マッチング → センチメント分析 → DB保存"""
    print("Reddit評価スクレイパー開始")

    # 既存ビルドを取得
    builds = _get_builds_from_db()
    if not builds:
        print("  エラー: DBにビルドが見つかりません")
        return

    print(f"  既存ビルド: {len(builds)}件")

    # スキル名ベースの追加キーワード
    skill_queries = _get_top_skill_queries(builds)
    print(f"  スキルキーワード: {skill_queries}")

    all_queries = BASE_QUERIES + skill_queries

    # 全投稿を収集（URL重複排除）
    all_posts: list[dict] = []
    seen_urls: set[str] = set()

    for subreddit in SUBREDDITS:
        for query in all_queries:
            print(f"  [{subreddit}] 検索: {query}")
            posts = _search_reddit(subreddit, query)
            for post in posts:
                # r/pathofexile のみフレアフィルタを適用（"Build Guide"のみ）
                if subreddit == "pathofexile":
                    flair = post.get("link_flair_text", "").lower()
                    if flair != "build guide":
                        continue

                if post["url"] not in seen_urls:
                    seen_urls.add(post["url"])
                    all_posts.append(post)
            time.sleep(RATE_LIMIT_SEC)

    print(f"\n  投稿収集完了: {len(all_posts)}件（重複排除済み）")

    # ビルドごとにマッチング・スコア集計
    # key: build_id, value: {build, posts, score, weighted_score, comment_count}
    build_ratings: dict[int, dict] = {}

    for post in all_posts:
        post_text = f"{post['title']} {post['selftext']}"

        # センチメント判定
        sentiment = _analyze_sentiment(
            post["title"], post["selftext"],
            post["score"], post["upvote_ratio"]
        )
        if sentiment is None:
            continue  # ネガティブ or 判定不能 → スキップ

        # ビルドマッチング
        matched_builds = _match_build(post_text, builds)
        for b in matched_builds:
            bid = b["id"]
            if bid not in build_ratings:
                build_ratings[bid] = {
                    "build": b,
                    "posts": [],
                    "score": 0,
                    "weighted_score": 0.0,
                    "comment_count": 0,
                }
            build_ratings[bid]["posts"].append(post)
            build_ratings[bid]["score"] += post["score"]
            build_ratings[bid]["weighted_score"] += post["score"] * post["upvote_ratio"]
            build_ratings[bid]["comment_count"] += post["num_comments"]

    print(f"  ポジティブ評価ビルド: {len(build_ratings)}件\n")

    # DB保存
    conn = sqlite3.connect(DB_PATH)
    # 既存のreddit_ratingsをクリア（再実行対応）
    conn.execute("DELETE FROM reddit_ratings")

    saved = 0
    for bid, data in build_ratings.items():
        build = data["build"]
        posts = data["posts"]
        source_urls = json.dumps([p["url"] for p in posts])
        summary_en = _generate_summary(posts)

        conn.execute(
            """INSERT INTO reddit_ratings
            (build_id, build_name_matched, score, weighted_score,
             mention_count, comment_count, sentiment, summary_en, source_urls)
            VALUES (?, ?, ?, ?, ?, ?, 'positive', ?, ?)""",
            (
                build["id"],
                build["name_en"],
                data["score"],
                round(data["weighted_score"], 2),
                len(posts),
                data["comment_count"],
                summary_en,
                source_urls,
            ),
        )
        saved += 1
        print(f"  保存: {build['name_en']} (score={data['score']}, mentions={len(posts)})")

    conn.commit()
    conn.close()
    print(f"\nDB保存完了: {saved}件")


if __name__ == "__main__":
    scrape_reddit()
