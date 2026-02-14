#!/usr/bin/env python3
"""
翻訳データ破損の修正スクリプト

Claude CLIの構造化出力によるカスケード問題を修正:
- name_ja に **CLASS_JA:**、**ASCENDANCY_JA:** 等が含まれている
- 各フィールドから正しい値を抽出してUPDATE
"""
import sqlite3
import json
import re

DB_PATH = "/Users/thiroki34/poe-build-search/data/poe_builds.db"
TARGET_IDS = [205, 208, 209, 210]


def parse_field_value(text: str, field_marker: str = None, next_marker: str = None) -> str:
    """
    カスケードされたフィールドから正しい値を抽出

    Args:
        text: 元のテキスト
        field_marker: 抽出したいフィールドのマーカー（例: "**CLASS_JA:**"）
        next_marker: 次のフィールドのマーカー（切り取り位置の特定用）

    Returns:
        抽出された値（前後の空白、"** "プレフィックスを除去）
    """
    if not text:
        return ""

    # field_markerがNoneの場合は先頭から抽出
    if field_marker is None:
        if next_marker and next_marker in text:
            value = text.split(next_marker)[0]
        else:
            value = text
    else:
        # field_markerが含まれない場合はそのまま返す
        if field_marker not in text:
            return text.strip().lstrip('* ').strip()

        # field_marker以降を抽出
        parts = text.split(field_marker, 1)
        if len(parts) < 2:
            return ""
        value = parts[1]

        # next_markerで切り取り
        if next_marker and next_marker in value:
            value = value.split(next_marker)[0]

    # クリーンアップ: 前後の空白と "** " プレフィックスを除去
    value = value.strip()
    while value.startswith('** ') or value.startswith('**'):
        value = value.lstrip('* ').strip()

    return value


def fix_build_data(conn, build_id: int):
    """
    特定のビルドIDのデータを修正
    """
    cursor = conn.cursor()

    # 現在のデータを取得
    cursor.execute("""
        SELECT name_ja, class_ja, ascendancy_ja, description_ja, pros_cons_ja, skills_ja
        FROM builds
        WHERE id = ?
    """, (build_id,))

    row = cursor.fetchone()
    if not row:
        print(f"⚠️  ID {build_id} が見つかりません")
        return

    name_ja, class_ja, ascendancy_ja, description_ja, pros_cons_ja, skills_ja = row

    print(f"\n🔧 修正中: ID {build_id}")
    print(f"   元のname_ja: {name_ja[:80]}...")

    # name_ja の修正（最初の行のみ、**CLASS_JA:** 以前まで）
    fixed_name = parse_field_value(name_ja, None, "\n\n**CLASS_JA:**")

    # class_ja の修正
    if "**CLASS_JA:**" in name_ja:
        # name_jaからclass_jaを抽出
        fixed_class = parse_field_value(name_ja, "**CLASS_JA:**", "\n\n**ASCENDANCY_JA:**")
    else:
        # すでにclass_jaにある場合
        fixed_class = parse_field_value(class_ja, None, "\n\n**ASCENDANCY_JA:**")

    # ascendancy_ja の修正
    if "**ASCENDANCY_JA:**" in name_ja:
        # name_jaからascendancy_jaを抽出
        fixed_ascendancy = parse_field_value(name_ja, "**ASCENDANCY_JA:**", "\n\n**DESCRIPTION_JA:**")
        if not fixed_ascendancy or "\n\n**SKILLS_JA:**" in fixed_ascendancy:
            fixed_ascendancy = parse_field_value(name_ja, "**ASCENDANCY_JA:**", "\n\n**SKILLS_JA:**")
    elif "**ASCENDANCY_JA:**" in class_ja:
        # class_jaからascendancy_jaを抽出
        fixed_ascendancy = parse_field_value(class_ja, "**ASCENDANCY_JA:**", "\n\n**SKILLS_JA:**")
    else:
        # ascendancy_jaから直接抽出（**SKILLS_JA:** より前まで）
        fixed_ascendancy = parse_field_value(ascendancy_ja, None, "\n\n**SKILLS_JA:**")

    # description_ja の修正（先頭の "** " プレフィックス除去）
    fixed_description = description_ja
    if fixed_description and fixed_description.startswith('** '):
        fixed_description = fixed_description[3:]

    # pros_cons_ja の修正（先頭の "** " プレフィックス除去）
    fixed_pros_cons = pros_cons_ja
    if fixed_pros_cons and fixed_pros_cons.startswith('** '):
        fixed_pros_cons = fixed_pros_cons[3:]

    # skills_ja の修正（JSON配列の各要素の "** " プレフィックス除去）
    fixed_skills = skills_ja
    if fixed_skills:
        try:
            skills_list = json.loads(fixed_skills)
            if isinstance(skills_list, list):
                fixed_skills_list = []
                for skill in skills_list:
                    if isinstance(skill, str) and skill.startswith('** '):
                        fixed_skills_list.append(skill[3:])
                    else:
                        fixed_skills_list.append(skill)
                fixed_skills = json.dumps(fixed_skills_list, ensure_ascii=False)
        except json.JSONDecodeError:
            pass  # JSONパースエラーの場合はそのまま

    # UPDATE実行
    cursor.execute("""
        UPDATE builds
        SET name_ja = ?,
            class_ja = ?,
            ascendancy_ja = ?,
            description_ja = ?,
            pros_cons_ja = ?,
            skills_ja = ?
        WHERE id = ?
    """, (fixed_name, fixed_class, fixed_ascendancy, fixed_description, fixed_pros_cons, fixed_skills, build_id))

    print(f"   ✅ 修正後のname_ja: {fixed_name}")
    print(f"   ✅ 修正後のclass_ja: {fixed_class}")
    print(f"   ✅ 修正後のascendancy_ja: {fixed_ascendancy}")


def check_all_builds(conn):
    """
    全ビルド（69件）で同様の問題がないか確認
    """
    cursor = conn.cursor()

    # 問題のあるパターンを検出
    cursor.execute("""
        SELECT id, name_ja, class_ja, description_ja, pros_cons_ja
        FROM builds
        WHERE name_ja LIKE '%**CLASS_JA:**%'
           OR name_ja LIKE '%**DESCRIPTION_JA:**%'
           OR class_ja LIKE '%**ASCENDANCY_JA:**%'
           OR description_ja LIKE '** %'
           OR pros_cons_ja LIKE '** %'
    """)

    problems = cursor.fetchall()

    if problems:
        print(f"\n⚠️  {len(problems)}件の追加問題を検出:")
        for row in problems:
            build_id = row[0]
            print(f"   - ID {build_id}")
        return [row[0] for row in problems]
    else:
        print("\n✅ 他のビルドに問題は検出されませんでした")
        return []


def verify_fixes(conn, build_ids: list):
    """
    修正結果の検証
    """
    cursor = conn.cursor()

    print("\n📊 修正結果の検証:")
    for build_id in build_ids:
        cursor.execute("""
            SELECT id, name_ja, class_ja, ascendancy_ja
            FROM builds
            WHERE id = ?
        """, (build_id,))

        row = cursor.fetchone()
        if row:
            print(f"\nID {row[0]}:")
            print(f"  name_ja: {row[1]}")
            print(f"  class_ja: {row[2]}")
            print(f"  ascendancy_ja: {row[3]}")


def main():
    print("🚀 翻訳データ破損修正スクリプト開始\n")

    conn = sqlite3.connect(DB_PATH)

    try:
        # 指定された4件を修正
        print("📝 指定された4件を修正中...")
        for build_id in TARGET_IDS:
            fix_build_data(conn, build_id)

        conn.commit()
        print("\n✅ 4件の修正をコミット完了")

        # 全件チェック
        print("\n🔍 全件チェック実行中...")
        additional_problems = check_all_builds(conn)

        if additional_problems:
            # 追加問題も修正
            print("\n📝 追加問題を修正中...")
            for build_id in additional_problems:
                if build_id not in TARGET_IDS:
                    fix_build_data(conn, build_id)
            conn.commit()
            print("\n✅ 追加問題の修正をコミット完了")

            # すべての修正されたIDを検証
            all_fixed_ids = TARGET_IDS + [bid for bid in additional_problems if bid not in TARGET_IDS]
            verify_fixes(conn, all_fixed_ids)
        else:
            # 元の4件のみ検証
            verify_fixes(conn, TARGET_IDS)

        print("\n🎉 すべての修正が完了しました！")

    except Exception as e:
        print(f"\n❌ エラーが発生しました: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
