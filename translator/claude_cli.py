"""Claude Code CLI を使った翻訳パイプライン

PoE ビルド情報を Claude Code CLI 経由で翻訳する。
非対話モードで CLI を呼び出し、用語辞書を活用して一貫性のある翻訳を生成。
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# プロジェクトルートを Python パスに追加
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.database import get_db


class ClaudeTranslator:
    """Claude Code CLI ベースの翻訳エンジン"""

    def __init__(self):
        self.term_dict: dict[str, dict[str, str]] = {}
        self.max_retries = 3
        self.timeout_seconds = 120

    async def load_term_dictionary(self) -> None:
        """PoE 用語辞書をDBから読み込み"""
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT category, term_en, term_ja FROM terms ORDER BY category, term_en"
            )
            rows = await cursor.fetchall()

            # カテゴリ別に辞書を構築
            for row in rows:
                category = row["category"]
                if category not in self.term_dict:
                    self.term_dict[category] = {}
                self.term_dict[category][row["term_en"]] = row["term_ja"]

            print(f"✅ 用語辞書読み込み完了: {len(rows)} 件")
        finally:
            await db.close()

    def _build_term_mapping_text(self) -> str:
        """翻訳プロンプトに埋め込む用語マッピングテキストを生成"""
        if not self.term_dict:
            return "（用語辞書なし）"

        lines = []
        for category, terms in self.term_dict.items():
            lines.append(f"# {category}")
            for en, ja in terms.items():
                lines.append(f"  {en} → {ja}")
        return "\n".join(lines)

    def translate_text(self, text: str, context: str) -> str:
        """Claude Code CLI で単一テキストを翻訳

        Args:
            text: 翻訳対象テキスト
            context: 翻訳の文脈（例: "PoE1ビルドの概要説明"）

        Returns:
            翻訳されたテキスト

        Raises:
            RuntimeError: CLI呼び出しが失敗した場合
        """
        term_mapping = self._build_term_mapping_text()

        prompt = f"""以下のPath of Exile 1の{context}を日本語に翻訳してください。

ルール:
- 自然で読みやすい日本語にすること
- ゲーム固有用語（スキル名、アイテム名）は原語を括弧内に併記
  例: サイクロン (Cyclone)、氷の槍 (Ice Spear)
- クラス名、アセンダンシー名はカタカナ + 英語併記
  例: スレイヤー (Slayer)
- ユニークアイテム名は英語のままでもよい
- 以下の既知用語マッピングを優先して使用してください:

{term_mapping}

翻訳対象テキスト:
{text}

回答は翻訳結果のみを出力してください（説明不要）。
"""

        for attempt in range(1, self.max_retries + 1):
            try:
                # CLAUDE関連の環境変数を除外した環境を作成
                clean_env = {k: v for k, v in os.environ.items()
                             if not k.startswith('CLAUDE')}

                result = subprocess.run(
                    ["claude", "-p", prompt, "--output-format", "text", "--model", "sonnet"],
                    input="",
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=True,
                    env=clean_env,
                )
                translated = result.stdout.strip()
                if translated:
                    return translated
                else:
                    raise RuntimeError("CLI returned empty output")

            except subprocess.TimeoutExpired:
                print(f"⚠️  翻訳タイムアウト (試行 {attempt}/{self.max_retries}): {context}")
                if attempt == self.max_retries:
                    raise RuntimeError(f"Translation timeout after {self.max_retries} retries")

            except subprocess.CalledProcessError as e:
                print(f"⚠️  CLI呼び出し失敗 (試行 {attempt}/{self.max_retries}): {e.stderr}")
                if attempt == self.max_retries:
                    raise RuntimeError(f"CLI failed after {self.max_retries} retries: {e.stderr}")

            except Exception as e:
                print(f"⚠️  予期しないエラー (試行 {attempt}/{self.max_retries}): {e}")
                if attempt == self.max_retries:
                    raise

            # リトライ前に少し待つ
            if attempt < self.max_retries:
                time.sleep(2)

        raise RuntimeError("Translation failed (should not reach here)")

    async def translate_build(self, build_id: int) -> bool:
        """単一ビルドを翻訳してDBに保存

        Args:
            build_id: ビルドID

        Returns:
            翻訳が成功した場合True、失敗した場合False
        """
        db = await get_db()
        try:
            # ビルドを取得
            cursor = await db.execute(
                """
                SELECT id, name_en, class_en, ascendancy_en, skills_en, description_en,
                       pros_cons_en, core_equipment_en
                FROM builds
                WHERE id = ?
                """,
                (build_id,),
            )
            row = await cursor.fetchone()
            if not row:
                print(f"❌ ビルドID {build_id} が見つかりません")
                return False

            print(f"🔄 翻訳中: ビルドID {build_id} - {row['name_en']}")

            # 各フィールドを翻訳
            name_ja = self.translate_text(row["name_en"], "ビルド名")

            class_ja = self.translate_text(row["class_en"], "クラス名")

            ascendancy_ja = None
            if row["ascendancy_en"]:
                ascendancy_ja = self.translate_text(row["ascendancy_en"], "アセンダンシー名")

            skills_ja = None
            if row["skills_en"]:
                try:
                    skills_list = json.loads(row["skills_en"])
                    translated_skills = [
                        self.translate_text(skill, "スキル名") for skill in skills_list
                    ]
                    skills_ja = json.dumps(translated_skills, ensure_ascii=False)
                except json.JSONDecodeError:
                    print(f"⚠️  skills_en のパースに失敗: {row['skills_en']}")
                    skills_ja = row["skills_en"]  # そのまま保存

            description_ja = None
            if row["description_en"]:
                description_ja = self.translate_text(row["description_en"], "ビルド説明文")

            pros_cons_ja = None
            if row["pros_cons_en"]:
                pros_cons_ja = self.translate_text(row["pros_cons_en"], "ビルドの長所と短所(Pros/Cons)")

            core_equipment_ja = None
            if row["core_equipment_en"]:
                core_equipment_ja = self.translate_text(row["core_equipment_en"], "ビルドのコア装備・ジュエル")

            # DBに保存
            await db.execute(
                """
                UPDATE builds
                SET name_ja = ?, class_ja = ?, ascendancy_ja = ?, skills_ja = ?, description_ja = ?,
                    pros_cons_ja = ?, core_equipment_ja = ?,
                    translation_status = 'completed', translated_at = ?
                WHERE id = ?
                """,
                (
                    name_ja,
                    class_ja,
                    ascendancy_ja,
                    skills_ja,
                    description_ja,
                    pros_cons_ja,
                    core_equipment_ja,
                    datetime.now().isoformat(),
                    build_id,
                ),
            )
            await db.commit()

            print(f"✅ 翻訳完了: ビルドID {build_id} - {name_ja}")
            return True

        except Exception as e:
            print(f"❌ 翻訳失敗: ビルドID {build_id} - {e}")
            # translation_status を 'failed' に更新
            await db.execute(
                """
                UPDATE builds
                SET translation_status = 'failed'
                WHERE id = ?
                """,
                (build_id,),
            )
            await db.commit()
            return False

        finally:
            await db.close()

    async def translate_all_untranslated(self) -> None:
        """未翻訳ビルドを全件翻訳"""
        db = await get_db()
        try:
            # 未翻訳ビルドのIDを取得
            cursor = await db.execute(
                """
                SELECT id
                FROM builds
                WHERE translation_status = 'pending'
                ORDER BY id
                """
            )
            rows = await cursor.fetchall()
            build_ids = [row["id"] for row in rows]

            if not build_ids:
                print("✅ 未翻訳ビルドはありません")
                return

            print(f"📊 未翻訳ビルド数: {len(build_ids)}")
            print()

            success_count = 0
            fail_count = 0

            for i, build_id in enumerate(build_ids, start=1):
                print(f"[{i}/{len(build_ids)}] ", end="")
                success = await self.translate_build(build_id)
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                print()

            print("=" * 60)
            print(f"✅ 翻訳完了: {success_count} 件")
            print(f"❌ 翻訳失敗: {fail_count} 件")
            print("=" * 60)

        finally:
            await db.close()


async def main():
    """メイン実行"""
    import argparse

    parser = argparse.ArgumentParser(description="Claude Code CLI 翻訳パイプライン")
    parser.add_argument("--test", action="store_true", help="未翻訳ビルドを1件だけ翻訳（テストモード）")
    parser.add_argument("--all", action="store_true", help="全未翻訳ビルドを翻訳")
    parser.add_argument("--build-id", type=int, help="特定IDのビルドを翻訳")
    parser.add_argument("--reset", action="store_true", help="全ビルドのtranslation_statusをpendingにリセット")

    args = parser.parse_args()

    if args.reset:
        # 全ビルドの翻訳ステータスをリセット
        db = await get_db()
        try:
            cursor = await db.execute("UPDATE builds SET translation_status = 'pending', translated_at = NULL")
            await db.commit()
            affected = cursor.rowcount
            print(f"✅ {affected} 件のビルドをリセットしました")
        finally:
            await db.close()
        return

    translator = ClaudeTranslator()
    print("📖 用語辞書を読み込み中...")
    await translator.load_term_dictionary()
    print()

    if args.test:
        # 未翻訳ビルドを1件だけ翻訳
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT id FROM builds WHERE translation_status = 'pending' LIMIT 1"
            )
            row = await cursor.fetchone()
            if row:
                await translator.translate_build(row["id"])
            else:
                print("✅ 未翻訳ビルドはありません")
        finally:
            await db.close()

    elif args.all:
        # 全未翻訳ビルドを翻訳
        await translator.translate_all_untranslated()

    elif args.build_id:
        # 特定IDのビルドを翻訳
        await translator.translate_build(args.build_id)

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
