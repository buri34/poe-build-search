-- PoE ビルド検索 DBスキーマ

CREATE TABLE IF NOT EXISTS builds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,           -- 'mobalytics' or 'maxroll'
    source_id TEXT NOT NULL,
    source_url TEXT NOT NULL,

    -- 英語原文
    name_en TEXT NOT NULL,
    class_en TEXT NOT NULL,
    ascendancy_en TEXT,
    skills_en TEXT,                  -- JSON配列
    description_en TEXT,

    -- 日本語翻訳
    name_ja TEXT,
    class_ja TEXT,
    ascendancy_ja TEXT,
    skills_ja TEXT,                  -- JSON配列
    description_ja TEXT,

    -- メタデータ
    patch TEXT,
    build_types TEXT,               -- JSON配列 (e.g. ["League Starter", "Boss Killer"])
    author TEXT,

    -- mobalytics固有
    favorites INTEGER DEFAULT 0,
    verified INTEGER DEFAULT 0,     -- 0/1
    hc INTEGER DEFAULT 0,           -- Hardcore 0/1
    ssf INTEGER DEFAULT 0,          -- SSF 0/1

    -- maxroll固有
    playstyle TEXT,                  -- JSON配列
    activities TEXT,                 -- JSON配列
    cost_tier TEXT,
    damage_types TEXT,              -- JSON配列

    -- 詳細情報
    combat_style TEXT,             -- 戦闘スタイル: melee/ranged/caster/summoner/hybrid
    specialty TEXT,                 -- 得意分野 JSON配列: ["league_starter","boss_killer","map_farmer"]等
    pros_cons_en TEXT,              -- 長所短所(英語)
    pros_cons_ja TEXT,              -- 長所短所(日本語)
    core_equipment_en TEXT,         -- コア装備・ジュエル(英語)
    core_equipment_ja TEXT,         -- コア装備・ジュエル(日本語)

    -- 管理
    translation_status TEXT DEFAULT 'pending' CHECK(translation_status IN ('pending', 'completed', 'failed')),
    scraped_at TEXT DEFAULT (datetime('now')),
    translated_at TEXT,
    updated_at TEXT DEFAULT (datetime('now')),

    UNIQUE(source, source_id)
);

-- 日本語全文検索用 FTS5（trigramトークナイザ）
CREATE VIRTUAL TABLE IF NOT EXISTS builds_fts USING fts5(
    name_ja,
    class_ja,
    ascendancy_ja,
    skills_ja,
    description_ja,
    pros_cons_ja,
    core_equipment_ja,
    name_en,
    class_en,
    ascendancy_en,
    skills_en,
    content=builds,
    content_rowid=id,
    tokenize='trigram'
);

-- FTS同期トリガー
CREATE TRIGGER IF NOT EXISTS builds_ai AFTER INSERT ON builds BEGIN
    INSERT INTO builds_fts(rowid, name_ja, class_ja, ascendancy_ja, skills_ja, description_ja, pros_cons_ja, core_equipment_ja, name_en, class_en, ascendancy_en, skills_en)
    VALUES (new.id, new.name_ja, new.class_ja, new.ascendancy_ja, new.skills_ja, new.description_ja, new.pros_cons_ja, new.core_equipment_ja, new.name_en, new.class_en, new.ascendancy_en, new.skills_en);
END;

CREATE TRIGGER IF NOT EXISTS builds_ad AFTER DELETE ON builds BEGIN
    INSERT INTO builds_fts(builds_fts, rowid, name_ja, class_ja, ascendancy_ja, skills_ja, description_ja, pros_cons_ja, core_equipment_ja, name_en, class_en, ascendancy_en, skills_en)
    VALUES ('delete', old.id, old.name_ja, old.class_ja, old.ascendancy_ja, old.skills_ja, old.description_ja, old.pros_cons_ja, old.core_equipment_ja, old.name_en, old.class_en, old.ascendancy_en, old.skills_en);
END;

CREATE TRIGGER IF NOT EXISTS builds_au AFTER UPDATE ON builds BEGIN
    INSERT INTO builds_fts(builds_fts, rowid, name_ja, class_ja, ascendancy_ja, skills_ja, description_ja, pros_cons_ja, core_equipment_ja, name_en, class_en, ascendancy_en, skills_en)
    VALUES ('delete', old.id, old.name_ja, old.class_ja, old.ascendancy_ja, old.skills_ja, old.description_ja, old.pros_cons_ja, old.core_equipment_ja, old.name_en, old.class_en, old.ascendancy_en, old.skills_en);
    INSERT INTO builds_fts(rowid, name_ja, class_ja, ascendancy_ja, skills_ja, description_ja, pros_cons_ja, core_equipment_ja, name_en, class_en, ascendancy_en, skills_en)
    VALUES (new.id, new.name_ja, new.class_ja, new.ascendancy_ja, new.skills_ja, new.description_ja, new.pros_cons_ja, new.core_equipment_ja, new.name_en, new.class_en, new.ascendancy_en, new.skills_en);
END;

-- インデックス
CREATE INDEX IF NOT EXISTS idx_builds_source ON builds(source);
CREATE INDEX IF NOT EXISTS idx_builds_class ON builds(class_en);
CREATE INDEX IF NOT EXISTS idx_builds_ascendancy ON builds(ascendancy_en);
CREATE INDEX IF NOT EXISTS idx_builds_translation ON builds(translation_status);
CREATE INDEX IF NOT EXISTS idx_builds_favorites ON builds(favorites DESC);

-- Reddit評価テーブル
CREATE TABLE IF NOT EXISTS reddit_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id INTEGER,                    -- buildsテーブルのid（マッチした場合）
    build_name_matched TEXT NOT NULL,     -- マッチしたビルド名
    score INTEGER DEFAULT 0,             -- upvote合算スコア
    weighted_score REAL DEFAULT 0,       -- score × upvote_ratio 合算
    mention_count INTEGER DEFAULT 0,     -- 言及投稿数
    comment_count INTEGER DEFAULT 0,     -- 議論活発度（num_comments合算）
    sentiment TEXT DEFAULT 'positive',   -- positive のみ保存
    summary_en TEXT,                     -- 評価サマリー（英語）
    summary_ja TEXT,                     -- 評価サマリー（日本語、翻訳後）
    source_urls TEXT,                    -- 言及投稿URL（JSON配列）
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (build_id) REFERENCES builds(id)
);
CREATE INDEX IF NOT EXISTS idx_reddit_build ON reddit_ratings(build_id);

-- PoE用語辞書テーブル
CREATE TABLE IF NOT EXISTS terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,         -- 'class', 'ascendancy', 'skill', 'keyword'
    term_en TEXT NOT NULL,
    term_ja TEXT NOT NULL,
    UNIQUE(category, term_en)
);
