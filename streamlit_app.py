"""
⚔️ PoE ビルド検索 - Streamlit Webアプリ
"""
import json
import re
import sqlite3
from pathlib import Path
from typing import Optional

import streamlit as st

# 設定読み込み
from app.config import settings

# ページ設定
st.set_page_config(page_title="PoE ビルド検索", layout="wide", page_icon="⚔️")


# ========== DB接続（同期版） ==========
def get_db_connection() -> sqlite3.Connection:
    """同期的にDB接続を取得"""
    db_path = settings.db_path
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ========== データ取得関数 ==========
def get_distinct_classes() -> list[str]:
    """クラス一覧を取得"""
    conn = get_db_connection()
    if conn is None:
        return []
    try:
        cursor = conn.execute("SELECT DISTINCT class_en FROM builds ORDER BY class_en")
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def get_distinct_ascendancies(class_filter: Optional[str] = None) -> list[str]:
    """アセンダンシー一覧を取得（クラスでフィルタ可能）"""
    conn = get_db_connection()
    if conn is None:
        return []
    try:
        if class_filter:
            cursor = conn.execute(
                "SELECT DISTINCT ascendancy_en FROM builds WHERE class_en = ? AND ascendancy_en IS NOT NULL ORDER BY ascendancy_en",
                (class_filter,)
            )
        else:
            cursor = conn.execute(
                "SELECT DISTINCT ascendancy_en FROM builds WHERE ascendancy_en IS NOT NULL ORDER BY ascendancy_en"
            )
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def get_distinct_combat_styles() -> list[str]:
    """戦闘スタイル一覧を取得"""
    conn = get_db_connection()
    if conn is None:
        return []
    try:
        cursor = conn.execute(
            "SELECT DISTINCT combat_style FROM builds WHERE combat_style IS NOT NULL ORDER BY combat_style"
        )
        return [row[0] for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        # combat_styleカラムが存在しない場合
        return []
    finally:
        conn.close()


def get_distinct_specialties() -> list[str]:
    """得意分野の一覧を取得（JSON配列から抽出）"""
    conn = get_db_connection()
    if conn is None:
        return []
    try:
        cursor = conn.execute("SELECT DISTINCT specialty FROM builds WHERE specialty IS NOT NULL")
        specialty_set = set()
        for row in cursor.fetchall():
            specialties = parse_json_field(row[0])
            specialty_set.update(specialties)
        return sorted(list(specialty_set))
    except sqlite3.OperationalError:
        # specialtyカラムが存在しない場合
        return []
    finally:
        conn.close()


def search_builds(
    keyword: str = "",
    class_filter: Optional[str] = None,
    ascendancy_filter: Optional[str] = None,
    source_filter: Optional[str] = None,
    translated_only: bool = False,
    combat_style_filter: Optional[str] = None,
    specialty_filters: Optional[list[str]] = None,
    patch_327_only: bool = False,
) -> list[sqlite3.Row]:
    """ビルド検索（全文検索 + フィルタ）"""
    conn = get_db_connection()
    if conn is None:
        return []

    try:
        # ベースクエリ
        if keyword:
            # FTS5全文検索
            query = """
                SELECT * FROM builds
                WHERE id IN (SELECT rowid FROM builds_fts WHERE builds_fts MATCH ?)
            """
            params = [keyword]
        else:
            query = "SELECT * FROM builds WHERE 1=1"
            params = []

        # フィルタ条件追加
        if class_filter:
            query += " AND class_en = ?"
            params.append(class_filter)

        if ascendancy_filter:
            query += " AND ascendancy_en = ?"
            params.append(ascendancy_filter)

        if source_filter and source_filter != "全て":
            query += " AND source = ?"
            params.append(source_filter)

        if translated_only:
            query += " AND translation_status = 'completed'"

        # 新フィルタ
        if combat_style_filter:
            query += " AND combat_style = ?"
            params.append(combat_style_filter)

        if specialty_filters:
            # 複数の得意分野フィルタ（OR条件）
            specialty_conditions = []
            for spec in specialty_filters:
                specialty_conditions.append(f"specialty LIKE ?")
                params.append(f'%"{spec}"%')
            query += f" AND ({' OR '.join(specialty_conditions)})"

        if patch_327_only:
            query += " AND patch = '3.27'"

        # ソート（お気に入り数順）
        query += " ORDER BY favorites DESC LIMIT 100"

        cursor = conn.execute(query, params)
        return cursor.fetchall()
    finally:
        conn.close()


def get_build_by_id(build_id: int) -> Optional[sqlite3.Row]:
    """ビルドIDで取得"""
    conn = get_db_connection()
    if conn is None:
        return None
    try:
        cursor = conn.execute("SELECT * FROM builds WHERE id = ?", (build_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def count_builds() -> int:
    """ビルド総数をカウント"""
    conn = get_db_connection()
    if conn is None:
        return 0
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM builds")
        return cursor.fetchone()[0]
    finally:
        conn.close()


# ========== マッピング辞書 ==========
COMBAT_STYLE_JA = {
    "melee": "近接",
    "ranged": "遠距離",
    "caster": "キャスター",
    "summoner": "召喚",
    "hybrid": "ハイブリッド",
}

SPECIALTY_JA = {
    "league_starter": "リーグスターター",
    "boss_killer": "対ボスDPS",
    "map_farmer": "マップファーム",
    "all_rounder": "オールラウンダー",
}

# アセンダンシーアイコンURL（poedb.tw CDN）
ASCENDANCY_ICON_URL = {
    # Ranger系 (Dex)
    "Warden": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconDex_Warden.webp",
    "Deadeye": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconDex_Deadeye.webp",
    "Pathfinder": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconDex_Pathfinder.webp",
    # Shadow系 (DexInt)
    "Assassin": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconDexInt_Assassin.webp",
    "Trickster": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconDexInt_Trickster.webp",
    "Saboteur": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconDexInt_Saboteur.webp",
    # Witch系 (Int)
    "Occultist": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconInt_Occultist.webp",
    "Elementalist": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconInt_Elementalist.webp",
    "Necromancer": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconInt_Necromancer.webp",
    # Marauder系 (Str)
    "Juggernaut": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconStr_Juggernaut.webp",
    "Berserker": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconStr_Berserker.webp",
    "Chieftain": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconStr_Chieftain.webp",
    # Duelist系 (StrDex)
    "Slayer": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconStrDex_Slayer.webp",
    "Gladiator": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconStrDex_Gladiator.webp",
    "Champion": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconStrDex_Champion.webp",
    # Scion系 (StrDexInt)
    "Ascendant": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconStrDexInt_Ascendant.webp",
    # Templar系 (StrInt)
    "Inquisitor": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconStrInt_Inquisitor.webp",
    "Hierophant": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconStrInt_Hierophant.webp",
    "Guardian": "https://cdn.poedb.tw/image/Art/2DArt/UIImages/Common/IconStrInt_Guardian.webp",
}


# ========== ユーティリティ関数 ==========
def parse_json_field(field_value: Optional[str]) -> list[str]:
    """JSON配列文字列をパース（エラー時は空リスト）"""
    if not field_value:
        return []
    try:
        return json.loads(field_value)
    except json.JSONDecodeError:
        return []


def extract_youtube_video_id(url: Optional[str]) -> Optional[str]:
    """YouTubeのURLから video_id を抽出"""
    if not url:
        return None
    match = re.search(r'v=([a-zA-Z0-9_-]+)', url)
    return match.group(1) if match else None


def get_youtube_thumbnail_url(url: Optional[str]) -> Optional[str]:
    """YouTubeのサムネイルURLを生成"""
    video_id = extract_youtube_video_id(url)
    if video_id:
        return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
    return None


def display_build_name(build: sqlite3.Row) -> str:
    """ビルド名を表示（日本語優先）"""
    return build["name_ja"] if build["name_ja"] else build["name_en"]


def display_class_ascendancy(build: sqlite3.Row) -> str:
    """クラス/アセンダンシーを表示"""
    class_name = build["class_ja"] if build["class_ja"] else build["class_en"]
    if build["ascendancy_en"]:
        asc_name = build["ascendancy_ja"] if build["ascendancy_ja"] else build["ascendancy_en"]
        return f"{class_name} / {asc_name}"
    return class_name


def display_skills(build: sqlite3.Row) -> str:
    """スキルを表示"""
    skills_ja = parse_json_field(build["skills_ja"])
    if skills_ja:
        return ", ".join(skills_ja)
    skills_en = parse_json_field(build["skills_en"])
    if skills_en:
        return ", ".join(skills_en)
    return "不明"


# ========== 画面レンダリング ==========
def render_sidebar():
    """サイドバー（フィルタ）"""
    st.sidebar.header("🔍 フィルタ")

    # クラス選択
    classes = get_distinct_classes()
    class_filter = st.sidebar.selectbox(
        "クラス",
        ["全て"] + classes,
        index=0
    )
    class_filter = None if class_filter == "全て" else class_filter

    # アセンダンシー選択
    ascendancies = get_distinct_ascendancies(class_filter)
    ascendancy_filter = st.sidebar.selectbox(
        "アセンダンシー",
        ["全て"] + ascendancies,
        index=0
    )
    ascendancy_filter = None if ascendancy_filter == "全て" else ascendancy_filter

    # ソース選択
    source_filter = st.sidebar.selectbox(
        "ソースサイト",
        ["全て", "mobalytics", "maxroll", "youtube"],
        index=0
    )

    # 翻訳済みのみ
    translated_only = st.sidebar.checkbox("翻訳済みのみ表示", value=False)

    # ========== 新フィルタ ==========
    st.sidebar.divider()
    st.sidebar.subheader("⚔️ 戦闘スタイル・得意分野")

    # 戦闘スタイル選択
    combat_styles = get_distinct_combat_styles()
    combat_style_options = ["全て"] + [COMBAT_STYLE_JA.get(cs, cs) for cs in combat_styles]
    combat_style_ja = st.sidebar.selectbox(
        "戦闘スタイル",
        combat_style_options,
        index=0
    )
    # 日本語→英語に逆変換
    if combat_style_ja == "全て":
        combat_style_filter = None
    else:
        combat_style_filter = next(
            (en for en, ja in COMBAT_STYLE_JA.items() if ja == combat_style_ja),
            combat_style_ja
        )

    # 得意分野選択（複数選択可）
    specialties = get_distinct_specialties()
    specialty_options_ja = [SPECIALTY_JA.get(sp, sp) for sp in specialties]
    specialty_selected_ja = st.sidebar.multiselect(
        "得意分野（複数選択可）",
        specialty_options_ja,
        default=[]
    )
    # 日本語→英語に逆変換
    specialty_filters = []
    for sp_ja in specialty_selected_ja:
        sp_en = next((en for en, ja in SPECIALTY_JA.items() if ja == sp_ja), sp_ja)
        specialty_filters.append(sp_en)

    # 3.27のビルドのみ表示
    patch_327_only = st.sidebar.checkbox("3.27のビルドのみ表示", value=False)

    return (
        class_filter,
        ascendancy_filter,
        source_filter,
        translated_only,
        combat_style_filter,
        specialty_filters,
        patch_327_only,
    )


def render_list_view():
    """メイン画面（検索・一覧）"""
    st.title("⚔️ PoE ビルド検索")

    # ビルド総数チェック
    total_builds = count_builds()
    if total_builds == 0:
        st.warning("⚠️ ビルドデータがまだありません。スクレイパーを実行してください。")
        return

    st.caption(f"全 {total_builds} 件のビルドが登録されています")

    # 検索バー
    keyword = st.text_input(
        "キーワード検索（ビルド名、クラス、スキル、説明を全文検索）",
        placeholder="例: ライトニング、メイジ、ボス特化",
        key="search_keyword"
    )

    # フィルタ取得
    (
        class_filter,
        ascendancy_filter,
        source_filter,
        translated_only,
        combat_style_filter,
        specialty_filters,
        patch_327_only,
    ) = render_sidebar()

    # 検索実行
    builds = search_builds(
        keyword,
        class_filter,
        ascendancy_filter,
        source_filter,
        translated_only,
        combat_style_filter,
        specialty_filters,
        patch_327_only,
    )

    if not builds:
        st.info("📭 該当するビルドが見つかりませんでした。フィルタを変更してみてください。")
        return

    st.success(f"🎯 {len(builds)} 件のビルドが見つかりました")

    # 一覧表示（カードスタイル）
    for build in builds:
        with st.container():
            col1, col2 = st.columns([4, 1])

            with col1:
                # アセンダンシーアイコン + タイトル（横並び）
                ascendancy_icon_url = ASCENDANCY_ICON_URL.get(build["ascendancy_en"]) if build["ascendancy_en"] else None

                if ascendancy_icon_url:
                    title_cols = st.columns([1, 12])
                    with title_cols[0]:
                        st.image(ascendancy_icon_url, width=35)
                    with title_cols[1]:
                        st.subheader(display_build_name(build))
                else:
                    st.subheader(display_build_name(build))

                st.markdown(f"**{display_class_ascendancy(build)}**")
                st.caption(f"スキル: {display_skills(build)}")

                # バッジ
                badges = []
                # ソース表示（YouTubeは専用アイコン）
                if build['source'] == 'youtube':
                    badges.append("▶️ YouTube")
                else:
                    badges.append(f"🌐 {build['source']}")
                if build["favorites"]:
                    badges.append(f"⭐ {build['favorites']}")
                if build["cost_tier"]:
                    badges.append(f"💰 {build['cost_tier']}")
                if build["patch"]:
                    badges.append(f"📦 {build['patch']}")

                # 新バッジ: 戦闘スタイル
                try:
                    if build["combat_style"]:
                        combat_style_ja = COMBAT_STYLE_JA.get(build["combat_style"], build["combat_style"])
                        badges.append(f"⚔️ {combat_style_ja}")
                except (KeyError, IndexError):
                    pass

                # 新バッジ: 得意分野（1つ目のみ）
                try:
                    specialty_list = parse_json_field(build["specialty"])
                    if specialty_list:
                        first_specialty = specialty_list[0]
                        specialty_ja = SPECIALTY_JA.get(first_specialty, first_specialty)
                        badges.append(f"🎯 {specialty_ja}")
                except (KeyError, IndexError):
                    pass

                st.caption(" | ".join(badges))

            with col2:
                # お気に入り数表示
                if build["favorites"]:
                    st.metric("⭐", build["favorites"])

                # 詳細を見るボタン
                if st.button("詳細を見る", key=f"detail_{build['id']}"):
                    st.session_state.view = "detail"
                    st.session_state.selected_build_id = build["id"]
                    st.rerun()

                # YouTubeサムネイル（240px）
                if build["source"] == "youtube":
                    youtube_thumbnail_url = get_youtube_thumbnail_url(build["source_url"])
                    if youtube_thumbnail_url:
                        st.image(youtube_thumbnail_url, width=240)

            st.divider()


def render_detail_view():
    """詳細画面"""
    build_id = st.session_state.get("selected_build_id")
    if not build_id:
        st.error("ビルドIDが指定されていません")
        return

    build = get_build_by_id(build_id)
    if not build:
        st.error("ビルドが見つかりませんでした")
        return

    # 戻るボタン
    if st.button("← 一覧に戻る"):
        st.session_state.view = "list"
        st.rerun()

    # アセンダンシーアイコン + タイトル（横並び）
    ascendancy_icon_url = ASCENDANCY_ICON_URL.get(build["ascendancy_en"]) if build["ascendancy_en"] else None

    if ascendancy_icon_url:
        title_cols = st.columns([1, 12])
        with title_cols[0]:
            st.image(ascendancy_icon_url, width=55)
        with title_cols[1]:
            st.title(display_build_name(build))
    else:
        st.title(display_build_name(build))

    # YouTubeサムネイル（480px、大きめ表示）
    if build["source"] == "youtube":
        youtube_thumbnail_url = get_youtube_thumbnail_url(build["source_url"])
        if youtube_thumbnail_url:
            st.image(youtube_thumbnail_url, width=480)

    # 基本情報
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("クラス", display_class_ascendancy(build))
    with col2:
        st.metric("お気に入り", build["favorites"])
    with col3:
        st.metric("ソース", build["source"])

    # 引用元リンク
    if build["source_url"]:
        if build["source"] == "youtube":
            st.markdown(f"▶️ [YouTube動画を見る]({build['source_url']})")
        else:
            st.markdown(f"🔗 [引用元ページ（{build['source']}）]({build['source_url']})")

    # メインスキル
    st.subheader("🎯 メインスキル")
    skills = display_skills(build)
    st.write(skills)

    # パッチ・コスト
    col1, col2 = st.columns(2)
    with col1:
        if build["patch"]:
            st.write(f"**📦 パッチバージョン:** {build['patch']}")
    with col2:
        if build["cost_tier"]:
            st.write(f"**💰 コスト:** {build['cost_tier']}")

    # ========== 新セクション ==========
    # 戦闘スタイル
    try:
        if build["combat_style"]:
            st.subheader("🏷️ 戦闘スタイル")
            combat_style_ja = COMBAT_STYLE_JA.get(build["combat_style"], build["combat_style"])
            st.write(combat_style_ja)
    except (KeyError, IndexError):
        pass

    # 得意分野
    try:
        specialty_list = parse_json_field(build["specialty"])
        if specialty_list:
            st.subheader("🎯 得意分野")
            specialty_ja_list = [SPECIALTY_JA.get(sp, sp) for sp in specialty_list]
            st.write(", ".join(specialty_ja_list))
    except (KeyError, IndexError):
        pass

    # 長所・短所
    try:
        pros_cons = build["pros_cons_ja"] if build["pros_cons_ja"] else build["pros_cons_en"]
        if pros_cons:
            st.subheader("✅ 長所 / ❌ 短所")
            st.write(pros_cons)
    except (KeyError, IndexError):
        pass

    # コア装備
    try:
        core_equipment = build["core_equipment_ja"] if build["core_equipment_ja"] else build["core_equipment_en"]
        if core_equipment:
            st.subheader("🛡️ コア装備")
            st.write(core_equipment)
    except (KeyError, IndexError):
        pass

    # ビルドタイプタグ
    build_types = parse_json_field(build["build_types"])
    if build_types:
        st.subheader("🏷️ ビルドタイプ")
        st.write(", ".join(build_types))

    # ビルド概要
    st.subheader("📝 ビルド概要")
    description = build["description_ja"] if build["description_ja"] else build["description_en"]
    if description:
        st.write(description)
    else:
        st.caption("説明なし")

    # その他情報
    with st.expander("📊 詳細情報"):
        st.write(f"**翻訳状態:** {build['translation_status']}")
        if build["verified"]:
            st.write("✅ 検証済みビルド")
        if build["hc"]:
            st.write("💀 ハードコア対応")
        if build["ssf"]:
            st.write("🚫 SSF対応")

    # 元サイトへのリンク
    st.subheader("🔗 元サイト")
    st.link_button(f"{build['source']} で開く", build["source_url"])


# ========== メインアプリ ==========
def main():
    # セッション初期化
    if "view" not in st.session_state:
        st.session_state.view = "list"
    if "selected_build_id" not in st.session_state:
        st.session_state.selected_build_id = None

    # ビュー切り替え
    if st.session_state.view == "list":
        render_list_view()
    elif st.session_state.view == "detail":
        render_detail_view()


if __name__ == "__main__":
    main()
