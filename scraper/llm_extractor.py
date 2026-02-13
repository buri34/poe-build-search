"""LLM抽出モジュール: Claude CLIを使ってビルドガイドから情報を抽出"""
import subprocess
import os
import re

from scraper.base import is_garbage_text


def _call_claude_cli(prompt: str, timeout: int = 90) -> str | None:
    """Claude CLI（Sonnet）を呼び出してテキストを生成"""
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith('CLAUDE')}

    # Claude CLI PATH確認
    try:
        which_result = subprocess.run(
            ["which", "claude"],
            capture_output=True, text=True, timeout=5,
            env=clean_env,
        )
        if which_result.returncode == 0:
            claude_path = which_result.stdout.strip()
            print(f"  [DEBUG] Claude CLI path: {claude_path}")
        else:
            print(f"  [WARN] 'which claude' failed: {which_result.stderr}")
    except Exception as e:
        print(f"  [WARN] Claude CLI path check failed: {e}")

    try:
        result = subprocess.run(
            ["claude", "--model", "sonnet", "-p", prompt],
            capture_output=True, text=True, timeout=timeout,
            env=clean_env,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception as e:
        print(f"  Claude CLI error: {e}")
        return None


def _parse_llm_output(output: str) -> dict:
    """LLM出力をパースしてdictに変換"""
    result = {
        "description_en": None,
        "pros_cons_en": None,
        "core_equipment_en": None,
        "class_en": None,
        "ascendancy_en": None,
    }
    if not output:
        return result

    # DESCRIPTION セクション抽出
    desc_match = re.search(
        r'DESCRIPTION:\s*\n(.*?)(?=\nPROS:|\nCONS:|\nCORE_EQUIPMENT:|\nCLASS:|\nASCENDANCY:|\Z)',
        output, re.DOTALL
    )
    if desc_match:
        desc = desc_match.group(1).strip()
        if desc and not is_garbage_text(desc):
            result["description_en"] = desc

    # PROS セクション抽出
    pros_match = re.search(
        r'PROS:\s*\n(.*?)(?=\nCONS:|\nCORE_EQUIPMENT:|\nCLASS:|\nASCENDANCY:|\Z)',
        output, re.DOTALL
    )
    # CONS セクション抽出
    cons_match = re.search(
        r'CONS:\s*\n(.*?)(?=\nCORE_EQUIPMENT:|\nCLASS:|\nASCENDANCY:|\Z)',
        output, re.DOTALL
    )
    pros_text = pros_match.group(1).strip() if pros_match else ""
    cons_text = cons_match.group(1).strip() if cons_match else ""
    if pros_text or cons_text:
        parts = []
        if pros_text:
            parts.append(f"Pros:\n{pros_text}")
        if cons_text:
            parts.append(f"Cons:\n{cons_text}")
        combined = "\n\n".join(parts)
        if not is_garbage_text(combined):
            result["pros_cons_en"] = combined

    # CORE_EQUIPMENT セクション抽出
    equip_match = re.search(
        r'CORE_EQUIPMENT:\s*\n(.*?)(?=\nCLASS:|\nASCENDANCY:|\Z)',
        output, re.DOTALL
    )
    if equip_match:
        raw_items = equip_match.group(1).strip()
        # 箇条書きからアイテム名を抽出してカンマ区切りに変換
        items = []
        for line in raw_items.split('\n'):
            line = line.strip()
            # "- アイテム名" 形式を処理
            line = re.sub(r'^[-*•]\s*', '', line)
            if line and len(line) > 1:
                items.append(line)
        if items:
            equipment_str = ", ".join(items)
            if not is_garbage_text(equipment_str):
                result["core_equipment_en"] = equipment_str

    # CLASS 抽出
    class_match = re.search(r'CLASS:\s*(.+)', output)
    if class_match:
        class_val = class_match.group(1).strip()
        if class_val and len(class_val) < 50:
            result["class_en"] = class_val

    # ASCENDANCY 抽出
    asc_match = re.search(r'ASCENDANCY:\s*(.+)', output)
    if asc_match:
        asc_val = asc_match.group(1).strip()
        if asc_val and len(asc_val) < 50:
            result["ascendancy_en"] = asc_val

    return result


def extract_build_info_via_llm(page_text: str, build_name: str) -> dict:
    """ページ全文からClaude CLIでビルド情報を抽出

    Args:
        page_text: ビルドガイドページのテキスト
        build_name: ビルド名（ログ用）

    Returns:
        抽出結果のdict（各フィールドはstr|None）
    """
    if not page_text or len(page_text.strip()) < 50:
        print(f"  [LLM] {build_name}: ページテキストが短すぎます")
        return _parse_llm_output("")

    # 先頭8000文字に切り詰め
    truncated = page_text[:8000]

    prompt = f"""以下はPath of Exile 1のビルドガイドページから取得したテキストです。
このテキストからビルドガイドの情報を抽出してください。

重要な注意:
- サイトのナビゲーション、フッター、プライバシーポリシー、JavaScriptコード、
  Cookie同意文、広告テキスト、UI操作説明（ドラッグ、スペースバー等）は無視してください
- ビルドガイドの本文のみを対象にしてください
- 通貨アイテム（Divine Orb, Chaos Orb, Exalted Orb等）はコア装備に含めないでください

以下の形式で回答してください（英語で）:

DESCRIPTION:
[ビルドの概要。メイン攻撃スキル、戦闘スタイル（melee/ranged/caster/summoner）、
 特徴的なシナジーや仕組みを2-3文で説明]

PROS:
- [長所1]
- [長所2]
- [長所3]
(3-5個)

CONS:
- [短所1]
- [短所2]
- [短所3]
(3-5個)

CORE_EQUIPMENT:
- [コア装備/ユニークアイテム/ジュエル1]
- [コア装備/ユニークアイテム/ジュエル2]
(主要な装備を3-8個。通貨アイテムは含めないこと)

CLASS: [クラス名（英語）]
ASCENDANCY: [アセンダンシー名（英語）]

ページテキスト:
{truncated}"""

    print(f"  [LLM] {build_name}: Claude CLI呼び出し中...")
    output = _call_claude_cli(prompt)

    if not output:
        print(f"  [LLM] {build_name}: Claude CLIから応答なし")
        return _parse_llm_output("")

    print(f"  [LLM] {build_name}: 応答取得 ({len(output)}文字)")
    result = _parse_llm_output(output)

    # 抽出結果のサマリーログ
    filled = sum(1 for v in result.values() if v)
    print(f"  [LLM] {build_name}: {filled}/5フィールド抽出成功")

    return result
