#!/usr/bin/env python3
"""バリデーション関数のテスト"""
import sys
sys.path.insert(0, "/Users/thiroki34/poe-build-search")

from scraper.base import is_garbage_text, validate_build_semantically

# Test 1: is_garbage_text()
print("=== Test 1: is_garbage_text() ===")

test_cases = [
    ("Normal build description text", False),
    ('{"__typename": "Build", "edges": [...]}', True),
    ("This build focuses on Cyclone with high DPS", False),
    ("__APOLLO_STATE__ graphql edges node", True),
    ("", True),  # 空文字列
    ('{"apolloState": {"data": {}}}', True),
]

for text, expected in test_cases:
    result = is_garbage_text(text)
    status = "✓" if result == expected else "✗"
    print(f"{status} '{text[:50]}...' → {result} (expected: {expected})")

# Test 2: validate_build_semantically()
print("\n=== Test 2: validate_build_semantically() ===")
print("Claude CLIを1件だけ呼び出してテスト...")

sample_build = {
    "name_en": "Cyclone Slayer",
    "description_en": "A powerful melee build that uses Cyclone to deal massive physical damage. Great for mapping and bossing.",
    "pros_cons_en": "Pros:\n- High DPS\n- Tanky\nCons:\n- Expensive gear",
    "core_equipment_en": "Starforge, Abyssus, Kaom's Heart",
}

try:
    result = validate_build_semantically(sample_build)
    print(f"結果: {result}")
    print(f"valid: {result.get('valid', 'N/A')}")
    print(f"issues: {result.get('issues', [])}")
except Exception as e:
    print(f"エラー: {e}")

print("\n=== テスト完了 ===")
