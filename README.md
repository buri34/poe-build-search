# ⚔️ PoE ビルド検索

Path of Exile 1のビルド情報を日本語で検索できるWebアプリケーションです。

## 概要

mobalytics.ggとmaxroll.ggから収集したビルド情報を、Claude Code CLIで日本語翻訳し、Streamlit製のWeb UIで全文検索できるようにしたツールです。

## 機能

- 🔍 日本語キーワードでのビルド全文検索（SQLite FTS5 trigram使用）
- 🎯 クラス/アセンダンシー/ソースサイトでのフィルタリング
- 📄 ビルド詳細表示（翻訳済み日本語 + 原文英語）
- 📊 37ビルド収録済み
  - mobalytics: 32件
  - maxroll: 5件

## 技術スタック

- **Python**: 3.11以上
- **Web UI**: Streamlit
- **データベース**: SQLite + FTS5 trigram（全文検索）
- **スクレイピング**: Playwright
- **翻訳**: Claude Code CLI
- **設定管理**: Pydantic Settings
- **パッケージ管理**: uv

## セットアップ

### 前提条件

- Python 3.11以上
- [uv](https://github.com/astral-sh/uv) パッケージマネージャ
- Claude Code CLI（翻訳機能を使用する場合）

### インストール手順

```bash
# 1. 依存パッケージをインストール
uv sync

# 2. Playwright ブラウザをインストール
uv run playwright install chromium

# 3. データベースを初期化（初回のみ）
uv run python scripts/init_db.py
```

### スクレイピングと翻訳

```bash
# ビルド情報をスクレイピング
uv run python -m scraper.mobalytics
uv run python -m scraper.maxroll

# 英語→日本語翻訳を実行（Claude Code CLI必要）
uv run python translator/claude_cli.py --all
```

### アプリケーション起動

```bash
# Streamlit Webアプリを起動
uv run streamlit run streamlit_app.py
```

ブラウザで http://localhost:8501 にアクセスすると、アプリが表示されます。

## Streamlit Cloudへのデプロイ

### デプロイ手順

1. **requirements.txtを作成**
   Streamlit Cloudはuvに対応していないため、pip用のrequirements.txtが必要です：

   ```bash
   uv pip compile pyproject.toml -o requirements.txt
   ```

2. **リポジトリをGitHubにpush**

   ```bash
   git add .
   git commit -m "Add README and requirements.txt for deployment"
   git push origin main
   ```

3. **Streamlit Cloudでデプロイ**

   - https://share.streamlit.io にアクセス
   - GitHubアカウントを連携
   - 「New app」をクリックして以下を設定：
     - Repository: `<your-username>/poe-build-search`
     - Branch: `main`
     - Main file path: `streamlit_app.py`
   - 「Deploy!」をクリック

### デプロイ時の注意事項

- ✅ SQLiteデータベース（`data/poe_builds.db`）はリポジトリに含まれています
- ⚠️ スクレイパーと翻訳パイプラインはローカル専用です（Streamlit Cloudでは実行されません）
- 🔄 データを更新する場合は、ローカルでスクレイピング・翻訳を実行してからgit pushしてください
- 💰 Streamlit Cloud無料枠の制限：
  - メモリ: 1GB
  - パブリックリポジトリのみ対応
  - 休止時間後は初回アクセス時に起動（数秒かかる）

## プロジェクト構造

```
poe-build-search/
├── streamlit_app.py          # メインWebアプリ（エントリーポイント）
├── pyproject.toml            # 依存関係定義（uv用）
├── requirements.txt          # Streamlit Cloud用依存定義（pip）
├── app/
│   ├── config.py             # 設定管理（Pydantic Settings）
│   ├── database.py           # 非同期DB接続
│   └── models/               # データモデル定義
│       ├── build.py          # ビルドモデル
│       └── search.py         # 検索モデル
├── scraper/
│   ├── base.py               # スクレイパー共通処理
│   ├── mobalytics.py         # mobalytics.gg スクレイパー
│   └── maxroll.py            # maxroll.gg スクレイパー
├── translator/
│   └── claude_cli.py         # Claude Code CLI翻訳パイプライン
├── db/
│   ├── schema.sql            # DBスキーマ定義（FTS5設定含む）
│   └── seed_terms.json       # PoE用語辞書
├── data/
│   └── poe_builds.db         # SQLiteデータベース
├── scripts/
│   └── init_db.py            # DB初期化スクリプト
├── docs/                     # 調査ドキュメント
│   ├── mobalytics_structure.md
│   └── maxroll_structure.md
└── tests/                    # テストコード
```

## データ更新フロー

```
1. スクレイピング   → scraper/*.py
2. 翻訳実行         → translator/claude_cli.py
3. DBに保存        → data/poe_builds.db
4. git commit/push → Streamlit Cloudに反映
```

## ライセンス

個人利用目的で作成されたプロジェクトです。
