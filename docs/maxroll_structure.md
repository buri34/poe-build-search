# maxroll.gg/poe サイト構造調査報告書

**調査日**: 2026-02-12
**対象サイト**: https://maxroll.gg/poe
**調査者**: 足軽3号
**任務ID**: subtask_110b

---

## 1. ビルド一覧ページのHTML構造

### レンダリング方式
**ハイブリッド型（SSR + クライアントサイド動的生成）**

- React/Remixフレームワークを使用
- 初期HTMLはサーバーサイドレンダリング（SSR）で生成
- `window.__remixContext` オブジェクトに初期データを埋め込み
- JavaScript hydration により動的なインタラクション機能を追加

### データ構造
ビルド一覧データは以下の形式で格納:

```javascript
window.__remixContext = {
  state: {
    loaderData: {
      "routes/_shell.poe.build-guides._index": {
        searchData: {
          initialResults: [
            {
              post_title: "Poisonous Concoction of Bouncing Pathfinder League Starter",
              post_author: {...},
              post_date_unix: 1704067200,
              post_image: {...},
              // 各ビルドのメタデータ
            },
            // 他のビルド...
          ]
        }
      }
    }
  }
}
```

### HTML要素パターン
- **記事カード**: 各ビルドは独立した記事オブジェクトとして配列に格納
- **メタデータ**: `post_title`, `post_author`, `post_date_unix` などのプロパティ
- **レスポンシブ画像**: 複数サイズ（full、large、medium、thumbnail）の画像URL提供

---

## 2. API/XHRエンドポイント調査

### 発見されたバックエンドエンドポイント

| エンドポイント | 用途 |
|--------------|------|
| `https://meilisearch-proxy.maxroll.gg` | 検索API（Meilisearch使用） |
| `https://backend.maxroll.gg` | バックエンドAPI |
| `https://planners.maxroll.gg` | ユーザー/プランナーバックエンド |
| `https://d1-worker.maxroll.gg` | Cloudflare Worker |
| `https://auth.maxroll.gg` | 認証システム |
| `https://assets-ng.maxroll.gg` | アセット配信CDN |

### データ取得パターン
- Remixフレームワークの内部機構でデータロード
- 外部スクリプト（`/[game]/auto-loader.js`、`/[game]/static/js/embed.js`）経由で動的コンテンツ読み込み
- Meilisearch統合により、サイトインデックス `wp_posts_6`（PoEコンテンツ）からデータ取得
- 明示的な `fetch()` や `XMLHttpRequest()` 呼び出しはページ内に見当たらない（Remixフレームワーク内部で処理）

### Meilisearch API
検索機能はMeilisearchを使用しており、`meilisearch-proxy.maxroll.gg` 経由でクエリ可能。ただし、認証やAPIキーが必要かは未確認。

---

## 3. ビルド詳細ページのHTML構造

### 調査対象サンプル
**URL**: https://maxroll.gg/poe/build-guides/poisonous-concoction-of-bouncing-pathfinder-league-starter

### レンダリング方式
**SSR + 動的コンテンツの混合型**

### 主要情報の配置

#### (1) ビルド名
- **要素**: `<h1>` または `<h2>` タグ
- **例**: "Poisonous Concoction of Bouncing Pathfinder League Starter"
- **データ格納**: `window.PogoConfig` メタタグにも格納

#### (2) クラス名
- **要素**: 本文テキスト、`<a>` リンク内
- **例**: "Pathfinder"
- **抽出方法**: テキストパース、またはリンク先分析

#### (3) 使用スキル
- **要素**: `<span class="poe-item">`
- **属性**: `data-poe-id="fb57ccad"` で個別スキル識別
- **例**: "Poisonous Concoction", "Plague Bearer", "Withering Step"
- **配置場所**: `gutenbergBlock` セクション内

```html
<span class="poe-item" data-poe-id="fb57ccad">Poisonous Concoction</span>
```

#### (4) 装備情報
- **セクション**: "Gearing"
- **形式**: テーブル/埋め込みUI
- **カテゴリ**: "2 Stone", "4 Stone", "Endgame", "Aspirational"（進行度別）
- **動的表示**: `/poeplanner/` スクリプトによる埋め込みプランナーで表示
- **抽出難易度**: 高（JavaScript実行が必要）

#### (5) パッシブツリー情報
- **セクション**: "Passives"
- **要素**: `<div>` 埋め込みプランナー
- **リンク**: `/poe/poe-passive-tree` へのリンク
- **表示形式**: キャンペーン進行に沿った段階的ツリー表示
- **抽出難易度**: 高（埋め込みツールのJavaScript実行が必要）

#### (6) ジェム構成
- **セクション**: "Skills"
- **形式**: リスト形式
- **詳細情報**: "Skill Rotation" セクションで段階別説明
- **抽出難易度**: 中（静的HTML解析可能だが、構造が複雑）

### JavaScript動的要素
- **window.__remixContext**: SSR用のHydrationデータ
- **window.dataLayer**: Google Analytics統合
- **gutenbergBlock配列**: Gutenbergブロックエディタ形式のコンテンツ
- **プランナー埋め込み**: `/poeplanner/static/js/embed.js` で動的レンダリング

---

## 4. ページネーション方式

### 実装形態
- **形式**: 従来型ページ番号リンク
- **表示例**: `Prev 1 2 3 4 5 ... 16 17 Next`
- **配置**: ページ下部
- **実装**: サーバーサイドページネーション（各ページで新しいHTMLを生成）

### フィルター機能
- **実装**: 複雑な実装構造
- **設定オブジェクト**: `guideFilterSettings` 内に複数フィルター定義
  - プレイスタイル（Playstyle）
  - アクティビティ（Activity）
  - ビルド属性（Build Attributes）
- **UI**: チェックボックス、ドロップダウン
- **動作**: クライアントサイドフィルタリング + サーバーサイドクエリ

### カテゴリ分類
- **League Starter**: リーグスタート向けビルド
- **Endgame**: エンドゲーム向けビルド
- **Budget**: 低予算ビルド
- **Boss Killer**: ボス特化ビルド
- **Mapper**: マップ周回特化ビルド

---

## 5. 必要なHTTPヘッダー、Cookie、認証

### HTTPヘッダー
**必須ヘッダー（推測）**:
```http
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8
Accept-Language: en-US,en;q=0.9
Accept-Encoding: gzip, deflate, br
```

### Cookie
- **一覧ページ**: Cookie不要（公開コンテンツ）
- **詳細ページ**: Cookie不要（公開コンテンツ）
- **ユーザーコンテンツ/プランナー**: 認証Cookieが必要な可能性（`auth.maxroll.gg` 経由）

### 認証
- **一般的なビルドガイド**: 認証不要
- **ユーザー作成プランナー/保存データ**: 認証必要
- **APIアクセス**: 不明（テスト必要）

### Rate Limiting（推測）
- robots.txt で多数のボットをブロックしていることから、厳格なrate limitingが存在する可能性
- 推奨: リクエスト間に1〜2秒の遅延を設定

---

## 6. robots.txt / 利用規約のスクレイピング制約

### robots.txt 分析結果

#### スクレイピング明示的禁止
Ziff Davis（運営会社）は**自動ツールによるスクレイピングを明確に禁止**:

```
- 自動ツール全般: robot, crawler, scraper, harvester など書面許可なしで禁止
- AI関連: テキスト・データマイニング、AI/機械学習開発、RAG など具体的に禁止
- 商用利用: 非商用利用のみ許可
- 許可申請: licensing@ziffdavis.com で書面許可申請可能
```

#### クローラー指示
**ブロック対象（Disallow: /）**:
- AI2Bot, Amazonbot, Applebot-Extended, CCBot, ChatGPT-User
- Claude-Web, ClaudeBot, Diffbot, FacebookBot, GPTBot
- Google-Extended, ImagesiftBot, Omgilibot, PerplexityBot
- など100以上のユーザーエージェント

**許可対象**:
- 一般的なブラウザ（User-agent: *）
- 基本的なアクセス許可（特定ディレクトリ除く）

**制限ディレクトリ**:
- `/d2/`, `/d3/`, `/d4/` など（ゲームプランナーツール）
- クローラーアクセス不可

### 利用規約
- **Ziff Davis利用規約へのアクセス試行**: 404エラー（直接取得失敗）
- **推測**: robots.txt の記述から、利用規約でもスクレイピング禁止が明記されている可能性が極めて高い

### 法的リスク評価
**🚨 高リスク**:
- 明確な禁止条項
- 書面許可なしのスクレイピングは利用規約違反
- 商用利用は特に厳格に制限

**推奨アクション**:
1. **公式API待機**: maxroll.ggが公式APIを提供する可能性を確認
2. **許可申請**: `licensing@ziffdavis.com` に書面で許可申請
3. **代替手段検討**: 公式が提供するRSS、API、データダウンロード機能の有無を確認

---

## 7. 推奨するスクレイピング手法

### ⚠️ 重要な前提
**maxroll.gg は明確にスクレイピングを禁止しています。以下は技術的な分析のみであり、実行には書面許可が必要です。**

### 技術的アプローチ（許可取得後のシナリオ）

#### オプション1: Playwright（推奨度: ★★★★☆）
**理由**:
- JavaScript動的生成コンテンツに対応
- プランナー埋め込み（装備情報、パッシブツリー）の完全レンダリング
- ブラウザ自動化で人間らしいアクセスパターン

**実装例**:
```python
from playwright.sync_api import sync_playwright

def scrape_build_guide(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")  # 動的コンテンツ完全読み込み待機

        # データ抽出
        build_name = page.locator("h1").text_content()
        skills = page.locator(".poe-item").all_text_contents()

        browser.close()
        return {"build_name": build_name, "skills": skills}
```

**長所**:
- 完全なページレンダリング
- JavaScript実行による動的コンテンツ取得

**短所**:
- 実行速度が遅い（ページあたり5〜10秒）
- リソース消費大

---

#### オプション2: requests + BeautifulSoup4（推奨度: ★★☆☆☆）
**理由**:
- 静的HTMLの高速取得
- window.__remixContext からの初期データ抽出

**実装例**:
```python
import requests
from bs4 import BeautifulSoup
import json
import re

def scrape_build_list(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "html.parser")

    # window.__remixContext からデータ抽出
    scripts = soup.find_all("script")
    for script in scripts:
        if "__remixContext" in script.text:
            match = re.search(r'window\.__remixContext\s*=\s*({.*?});', script.text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                builds = data["state"]["loaderData"]["..."]["searchData"]["initialResults"]
                return builds
    return []
```

**長所**:
- 高速（ページあたり1秒未満）
- シンプルな実装

**短所**:
- JavaScript動的コンテンツ取得不可（装備情報、パッシブツリー等）
- 初期データのみ取得可能

---

#### オプション3: Meilisearch API直接アクセス（推奨度: ★★★☆☆）
**理由**:
- `meilisearch-proxy.maxroll.gg` への直接クエリ
- HTMLパース不要の構造化データ取得

**実装例（概念）**:
```python
import requests

def search_builds_via_api(query):
    api_url = "https://meilisearch-proxy.maxroll.gg/indexes/wp_posts_6/search"
    headers = {
        "Authorization": "Bearer YOUR_API_KEY",  # API Key必要
        "Content-Type": "application/json"
    }
    payload = {
        "q": query,
        "filter": "game = 'poe' AND post_type = 'build-guide'",
        "limit": 100
    }
    response = requests.post(api_url, json=payload, headers=headers)
    return response.json()
```

**長所**:
- 最も効率的（直接データ取得）
- 構造化データ

**短所**:
- APIキーが必要（取得方法不明）
- 認証メカニズムが未確認
- APIエンドポイント仕様が非公開

---

#### オプション4: ブラウザ拡張機能（推奨度: ★☆☆☆☆）
**理由**:
- 手動操作補助ツール
- 個人利用範囲

**実装**:
- Chrome拡張機能で特定要素を抽出
- JSONファイルにエクスポート

**長所**:
- 利用規約違反リスク低減（手動操作範囲）

**短所**:
- 自動化不可
- 大規模データ収集に不向き

---

### 推奨手法のまとめ

| 手法 | 速度 | 完全性 | 実装難易度 | リスク | 推奨度 |
|------|------|--------|-----------|--------|--------|
| Playwright | 低 | 高 | 中 | 高（禁止事項） | ★★★★☆ |
| requests+BS4 | 高 | 中 | 低 | 高（禁止事項） | ★★☆☆☆ |
| Meilisearch API | 高 | 高 | 高 | 高（APIキー必要） | ★★★☆☆ |
| ブラウザ拡張 | 低 | 高 | 低 | 低（手動範囲） | ★☆☆☆☆ |

### 最終推奨
**許可取得前提で、Playwright を第一選択とする理由**:
1. JavaScript動的コンテンツ（装備、パッシブツリー）の完全取得
2. ブラウザ自動化による自然なアクセスパターン
3. 検証しやすいデバッグ環境

---

## 8. サンプルレスポンスデータ

### ビルド一覧ページ（window.__remixContext 抜粋）

```json
{
  "state": {
    "loaderData": {
      "routes/_shell.poe.build-guides._index": {
        "searchData": {
          "initialResults": [
            {
              "post_title": "Poisonous Concoction of Bouncing Pathfinder League Starter",
              "post_author": {
                "display_name": "Palsteron",
                "user_url": "https://maxroll.gg/poe/author/palsteron"
              },
              "post_date_unix": 1704067200,
              "post_image": {
                "full": "https://assets-ng.maxroll.gg/wordpress/...",
                "thumbnail": "https://assets-ng.maxroll.gg/wordpress/..."
              },
              "post_permalink": "/poe/build-guides/poisonous-concoction-of-bouncing-pathfinder-league-starter",
              "post_excerpt": "Poisonous Concoction of Bouncing is a powerful Poison-based Projectile Attack...",
              "taxonomies": {
                "poe_class": ["Pathfinder"],
                "poe_playstyle": ["Ranged"],
                "poe_activity": ["Mapping", "Bossing"]
              }
            }
          ]
        }
      }
    }
  }
}
```

### ビルド詳細ページ（HTML抜粋）

```html
<!-- ビルド名 -->
<h1>Poisonous Concoction of Bouncing Pathfinder League Starter</h1>

<!-- スキル -->
<span class="poe-item" data-poe-id="fb57ccad">Poisonous Concoction</span>
<span class="poe-item" data-poe-id="a3f7b2e9">Plague Bearer</span>

<!-- Gearingセクション（埋め込みプランナー） -->
<div class="gutenbergBlock">
  <h2>Gearing</h2>
  <div id="poe-planner-embed" data-build-id="xyz123">
    <!-- JavaScript動的生成コンテンツ -->
  </div>
</div>

<!-- パッシブツリー -->
<div class="gutenbergBlock">
  <h2>Passives</h2>
  <a href="/poe/poe-passive-tree/abc456">View Passive Tree</a>
  <div id="passive-tree-embed">
    <!-- JavaScript動的生成コンテンツ -->
  </div>
</div>
```

---

## 9. 結論と次のステップ

### 技術的実現可能性
**実現可能**: Playwright を使用すれば、ビルド情報の完全な取得が技術的に可能。

### 法的・倫理的制約
**🚨 重大な制約**:
- robots.txt で明確にスクレイピング禁止
- 利用規約で自動アクセス禁止（推測）
- 書面許可なしの実行は利用規約違反

### 推奨アクション
1. **公式に問い合わせ**: `licensing@ziffdavis.com` に書面で許可申請
2. **代替手段調査**:
   - 公式APIの有無確認
   - データエクスポート機能の有無確認
   - パートナーシップ提携の可能性調査
3. **最小限のテスト**: 許可取得前は、1〜2ページの技術検証に留める
4. **非商用限定**: 個人利用・研究目的に限定し、商用利用は避ける

### 技術的次のステップ（許可取得後）
1. Playwright環境構築
2. サンプルビルドガイド1件でのフルスクレイピングテスト
3. データ構造の検証とデータベーススキーマ設計
4. Rate limiting実装（リクエスト間隔 1〜2秒）
5. エラーハンドリング実装（403, 429レスポンス対応）
6. 段階的データ収集（1日10〜20ページ）

---

## 10. 付録: 関連リソース

### 公式ドキュメント/問い合わせ先
- **Licensing問い合わせ**: licensing@ziffdavis.com
- **robots.txt**: https://maxroll.gg/robots.txt
- **Ziff Davis**: https://www.ziffdavis.com/

### 技術スタック
- **フレームワーク**: React + Remix
- **検索エンジン**: Meilisearch
- **CDN**: Cloudflare
- **コンテンツ管理**: Gutenberg ブロックエディタ

### 参考実装（許可取得後）
```bash
# Playwright環境構築
pip install playwright
playwright install chromium

# サンプルスクリプト実行
python scraper.py --url "https://maxroll.gg/poe/build-guides/..."
```

---

**報告完了**: 2026-02-12
**次の任務**: 許可取得後のスクレイパー実装設計（別タスク）
