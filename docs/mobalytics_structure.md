# Mobalytics.gg/poe/builds サイト構造調査報告

調査日: 2026-02-12
調査対象: https://mobalytics.gg/poe/builds

---

## 1. ビルド一覧ページのHTML構造

### レンダリング方式
**サーバーサイドレンダリング（SSR）+ GraphQLハイドレーション方式**

- HTMLに `"isLoadedFromSSR":true` が記述されており、初期データがサーバー側で事前生成
- `window.__PRELOADED_STATE__` にGraphQLレスポンスデータが埋め込み済み
- クライアント側のReactアプリケーションが、preloadされたデータを使って動的UIを構築

### サンプルレスポンス構造（__PRELOADED_STATE__から抽出）

```javascript
{
  "NgfDocumentAuthor": {
    "name": "クリエイター名",
    "twitch": "twitchアカウント",
    "youtube": "youtubeチャンネル",
    "isLive": true/false
  },
  "PoeUGDocumentBuildStats": {
    "dps": "推定DPS値",
    "life": "ライフプール",
    "defense": "防御ステータス"
  },
  "tags": ["クラス", "アセンダンシー", "パッチバージョン", "ビルドタイプ"],
  "metadata": {
    "createdAt": "作成日時",
    "updatedAt": "更新日時",
    "favorites": "お気に入り数",
    "verified": true/false,
    "featured": true/false
  }
}
```

---

## 2. 一覧データを取得できるAPI/XHRエンドポイント

### GraphQL API
**エンドポイント**: `https://mobalytics.gg/api/poe/v1/graphql/query`

- 環境変数 `POE_GQL_HTTP_URL` で参照されている
- ビルド一覧、クリエイター情報、Twitchライブ状態等を取得
- 公式APIドキュメントは公開されていない（非公開API）

### 注意事項
利用規約（後述）により、**自動化されたツール・スクレイパー・ボットによるアクセスは明確に禁止**されています。このAPIへの直接アクセスは規約違反となる可能性が高い。

---

## 3. ビルド詳細ページのHTML構造

### サンプルURL
https://mobalytics.gg/poe/builds/cyclone-slayer-league-starter-to-endgame-step-by-step-guide-beginner-friendly

### データ格納場所

| 情報項目 | 格納方式 |
|---------|---------|
| ビルド名 | JSON-LD structured data（`<script type="application/ld+json">`）+ Redux preload |
| クラス/アセンダンシー | 画像要素として表示（Duelist、Slayer等） |
| スキル構成 | タブUIで複数Variant（レベル13〜100の進行段階別）を表示 |
| 装備情報 | 画像ベースUI + テキスト説明（スロット別: 武器/防具/グローブ等） |
| パッシブツリー | 専用ビジュアライザー（インタラクティブUI） |

### セクション構造
```
- Build Overview（概要）
- Strengths/Weaknesses（強み/弱み）
- Build Variants（複数の進行パターン）
  - Level 13 版
  - Level 50 版
  - Level 80 版
  - Endgame 版
- Equipment（装備）
  - 各スロット別の推奨アイテム
  - クラフト指示、影響（Influence）の優先度
- Passive Tree（パッシブスキルツリー）
- Skills（スキルとサポートジェム構成）
- Changelog（更新履歴）
```

### サンプルJSON-LD構造
```json
{
  "@context": "https://schema.org",
  "@type": "Guide",
  "name": "Cyclone Slayer League Starter to Endgame Step by Step Guide",
  "author": {
    "@type": "Person",
    "name": "FGKorbyn21"
  },
  "datePublished": "2024-12-XX",
  "dateModified": "2026-02-XX"
}
```

---

## 4. ページネーション方式

**"Show more" ボタン型のプログレッシブ読み込み**

- 初期表示: サーバー側で最初の数十件をSSRで配信
- 追加読み込み: ユーザーが "Show more" ボタンをクリックすると、GraphQL APIで次のセットを取得
- 無限スクロール形式ではなく、明示的なユーザーアクションが必要

---

## 5. 必要なHTTPヘッダー、Cookie、認証の有無

### 通常閲覧
- **認証不要**: ビルド一覧・詳細ページは誰でも閲覧可能
- **Cookie**: セッション管理用のCookieあり（`__cfduid`, `_ga`, `_gid` 等）
- **User-Agent**: 通常のブラウザUser-Agentで問題なく取得可能

### 特殊機能
- **お気に入り登録**: ログイン必須（Facebook/Twitter/Twitch/Steamアカウント連携）
- **ビルド投稿**: クリエイターアカウント必須

---

## 6. robots.txt / 利用規約のスクレイピング制約

### robots.txt
**URL**: https://mobalytics.gg/robots.txt

```
User-agent: *
Allow: /
Disallow: /api/tft
Sitemap: https://mobalytics.gg/sitemap.xml
```

**結論**: `/poe/builds` への明示的な禁止指示はなし。

---

### 利用規約（Terms of Service）
**URL**: https://mobalytics.gg/terms/
**最終更新**: 2023年1月30日

#### スクレイピング禁止条項

> "Attempt to access or search the Services or Content or download Content from the Services through the use of any **engine, software, tool, agent, device or mechanism** (including **spiders, robots, crawlers, data mining tools** or the like)"

#### リバースエンジニアリング禁止

> "Attempt to decipher, decompile, disassemble or **reverse engineer** any of the software used to provide the Services or Content"

#### システム干渉禁止

> "Access, tamper with, or use non-public areas of the Services, Gamers Net's computer systems, or the technical delivery systems"

#### 罰則
規約違反者に対し、**事前通知なしにアクセス停止**の権限を保有。

---

## 7. 推奨するスクレイピング手法

### ❌ 推奨しない方法
1. **requests + BeautifulSoup**
   → SSRでHTMLにデータは含まれているが、利用規約で自動化ツール禁止

2. **Playwright/Selenium**
   → 動的レンダリングに対応できるが、同様に規約違反

3. **GraphQL API直接アクセス**
   → 非公開APIへの直接アクセスは明確な規約違反

### ✅ 推奨する代替手段

#### A. 公式APIの利用（存在する場合）
現時点では公式APIドキュメントは見つからなかったが、Mobalytics運営に問い合わせて、開発者向けAPIの提供があるか確認する価値あり。

#### B. 手動収集
- 個人利用・研究目的であれば、ブラウザで手動閲覧しながらメモを取る
- Chrome拡張機能で閲覧中のビルドをローカル保存（ただし配布・商用利用は避ける）

#### C. オープンデータソースの利用
- Path of Exileの公式API（キャラクター情報、アイテム情報等）
- poe.ninjaなど、スクレイピングを許可しているコミュニティサイト

#### D. 利用許可の取得
Mobalytics運営に連絡し、非営利研究・個人プロジェクト目的での限定的なデータ利用許可を交渉する。

---

## 8. 技術的な実装可能性（参考情報）

もし規約が変更され、自動化が許可された場合の技術的アプローチ:

### Pattern 1: SSRコンテンツの解析
```python
import requests
from bs4 import BeautifulSoup
import json
import re

def get_builds(page=1):
    url = "https://mobalytics.gg/poe/builds"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, 'html.parser')

    # __PRELOADED_STATE__からデータ抽出
    scripts = soup.find_all('script')
    for script in scripts:
        if '__PRELOADED_STATE__' in script.text:
            match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*({.*?});', script.text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                return data
    return None
```

### Pattern 2: GraphQLクエリ（非推奨 - 規約違反）
```python
import requests

def query_builds_graphql():
    url = "https://mobalytics.gg/api/poe/v1/graphql/query"
    query = """
    query GetBuilds($limit: Int, $offset: Int) {
      poeBuilds(limit: $limit, offset: $offset) {
        id
        name
        class
        ascendancy
        author
        stats
      }
    }
    """
    # このアプローチは利用規約違反のため実行しないこと
```

---

## 9. まとめ

| 調査項目 | 結果 |
|---------|------|
| レンダリング方式 | SSR + GraphQLハイドレーション |
| API | 非公開GraphQL（規約により自動アクセス禁止）|
| ページネーション | "Show more" ボタン型 |
| 認証 | 閲覧は不要、投稿・お気に入りは要ログイン |
| robots.txt | 制限なし |
| 利用規約 | **自動化ツール・スクレイパー明確に禁止** |
| 推奨手法 | 公式API交渉 or 手動収集 or 代替データソース利用 |

**重要**: 現行の利用規約下では、自動スクレイピングによるデータ収集は規約違反となります。プロジェクト実施前に、必ず運営への問い合わせと許可取得を推奨します。

---

## 参考URL
- ビルド一覧: https://mobalytics.gg/poe/builds
- サンプル詳細ページ: https://mobalytics.gg/poe/builds/cyclone-slayer-league-starter-to-endgame-step-by-step-guide-beginner-friendly
- robots.txt: https://mobalytics.gg/robots.txt
- 利用規約: https://mobalytics.gg/terms/
