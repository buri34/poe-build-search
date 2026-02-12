"""
⚔️ PoE ビルド検索 - Streamlit Webアプリ
"""
import json
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


def search_builds(
    keyword: str = "",
    class_filter: Optional[str] = None,
    ascendancy_filter: Optional[str] = None,
    source_filter: Optional[str] = None,
    translated_only: bool = False,
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


# ========== ユーティリティ関数 ==========
def parse_json_field(field_value: Optional[str]) -> list[str]:
    """JSON配列文字列をパース（エラー時は空リスト）"""
    if not field_value:
        return []
    try:
        return json.loads(field_value)
    except json.JSONDecodeError:
        return []


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
        ["全て", "mobalytics", "maxroll"],
        index=0
    )

    # 翻訳済みのみ
    translated_only = st.sidebar.checkbox("翻訳済みのみ表示", value=False)

    return class_filter, ascendancy_filter, source_filter, translated_only


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
    class_filter, ascendancy_filter, source_filter, translated_only = render_sidebar()

    # 検索実行
    builds = search_builds(keyword, class_filter, ascendancy_filter, source_filter, translated_only)

    if not builds:
        st.info("📭 該当するビルドが見つかりませんでした。フィルタを変更してみてください。")
        return

    st.success(f"🎯 {len(builds)} 件のビルドが見つかりました")

    # 一覧表示（カードスタイル）
    for build in builds:
        with st.container():
            col1, col2 = st.columns([4, 1])

            with col1:
                st.subheader(display_build_name(build))
                st.markdown(f"**{display_class_ascendancy(build)}**")
                st.caption(f"スキル: {display_skills(build)}")

                # バッジ
                badges = []
                badges.append(f"🌐 {build['source']}")
                if build["favorites"]:
                    badges.append(f"⭐ {build['favorites']}")
                if build["cost_tier"]:
                    badges.append(f"💰 {build['cost_tier']}")
                if build["patch"]:
                    badges.append(f"📦 {build['patch']}")
                st.caption(" | ".join(badges))

            with col2:
                if st.button("詳細を見る", key=f"detail_{build['id']}"):
                    st.session_state.view = "detail"
                    st.session_state.selected_build_id = build["id"]
                    st.rerun()

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

    st.title(display_build_name(build))

    # 基本情報
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("クラス", display_class_ascendancy(build))
    with col2:
        st.metric("お気に入り", build["favorites"])
    with col3:
        st.metric("ソース", build["source"])

    # メインスキル
    st.subheader("🎯 メインスキル")
    skills = display_skills(build)
    st.write(skills)

    # パッチ・コスト
    col1, col2 = st.columns(2)
    with col1:
        if build["patch"]:
            st.write(f"**パッチ:** {build['patch']}")
    with col2:
        if build["cost_tier"]:
            st.write(f"**コスト:** {build['cost_tier']}")

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
