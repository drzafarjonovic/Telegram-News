-- ============================================================
--  Telegram-News — ma'lumotlar bazasi sxemasi (PostgreSQL / Supabase)
--  Ilova ishga tushganda avtomatik bajariladi (pool.py -> init_db).
-- ============================================================

-- Foydalanuvchilar
CREATE TABLE IF NOT EXISTS users (
    id              BIGINT PRIMARY KEY,                       -- Telegram user id
    username        TEXT,
    first_name      TEXT,
    timezone        TEXT NOT NULL DEFAULT 'Asia/Tashkent',
    max_channels    INTEGER,                                  -- NULL = global standart
    is_banned       BOOLEAN NOT NULL DEFAULT FALSE,
    banned_at       TIMESTAMPTZ,
    banned_by       BIGINT,
    last_active_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Kuzatilayotgan kanallar (umumiy, takrorlanmas)
CREATE TABLE IF NOT EXISTS channels (
    id              SERIAL PRIMARY KEY,
    tg_channel_id   BIGINT UNIQUE NOT NULL,                   -- Telethon kanal id
    username        TEXT,                                     -- @username (ochiq kanal)
    title           TEXT,
    access_hash     BIGINT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Obunalar (foydalanuvchi <-> kanal)
CREATE TABLE IF NOT EXISTS subscriptions (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel_id  INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, channel_id)
);

-- Digest jadvali (har foydalanuvchi uchun bitta)
CREATE TABLE IF NOT EXISTS schedules (
    user_id        BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    mode           TEXT NOT NULL DEFAULT 'interval',          -- 'interval' | 'daily'
    interval_hours INTEGER DEFAULT 6,                         -- interval rejimi uchun
    daily_times    TEXT[] DEFAULT '{}',                       -- daily rejimi, masalan {'09:00','18:00'}
    last_run_at    TIMESTAMPTZ,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Yig'ilgan postlar (userbot realtime saqlaydi)
CREATE TABLE IF NOT EXISTS posts (
    id             BIGSERIAL PRIMARY KEY,
    channel_id     INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    tg_message_id  BIGINT NOT NULL,
    text           TEXT,
    posted_at      TIMESTAMPTZ NOT NULL,
    collected_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (channel_id, tg_message_id)
);
CREATE INDEX IF NOT EXISTS idx_posts_channel_posted ON posts (channel_id, posted_at);

-- Yuborilgan digestlar tarixi
CREATE TABLE IF NOT EXISTS digests (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    period_start TIMESTAMPTZ,
    period_end   TIMESTAMPTZ,
    post_count   INTEGER NOT NULL DEFAULT 0,
    content      TEXT,
    sent_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_digests_user ON digests (user_id, sent_at);

-- Audit jurnali
CREATE TABLE IF NOT EXISTS audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    actor_id        BIGINT,                                   -- kim bajardi
    target_user_id  BIGINT,                                   -- kimga taalluqli (ixtiyoriy)
    action          TEXT NOT NULL,                            -- 'add_channel','remove_channel','set_schedule','ban','unban','broadcast','digest_sent','error', ...
    details         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs (action);

-- AI sarfini kuzatish
CREATE TABLE IF NOT EXISTS ai_usage (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT,
    provider     TEXT,
    model        TEXT,
    tokens_in    INTEGER NOT NULL DEFAULT 0,
    tokens_out   INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage (created_at);

-- Broadcast (e'lon) tarixi
CREATE TABLE IF NOT EXISTS broadcasts (
    id           BIGSERIAL PRIMARY KEY,
    admin_id     BIGINT,
    message      TEXT,
    total        INTEGER NOT NULL DEFAULT 0,
    delivered    INTEGER NOT NULL DEFAULT 0,
    failed       INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);



-- ============================================================
--  FAZA 1 — Cache pipeline (stories), dedup, health check
-- ============================================================

-- "Story" = bir xil yangilik (turli kanallardagi dublikatlar birlashtirilgan).
-- AI har story uchun FAQAT bir marta ishlaydi; natija shu yerda cache'lanadi.
CREATE TABLE IF NOT EXISTS stories (
    id                      BIGSERIAL PRIMARY KEY,
    summary                 TEXT,                          -- AI tayyorlagan mazmun
    category                TEXT,                          -- masalan: Iqtisod, Sport...
    importance              SMALLINT NOT NULL DEFAULT 3,   -- 1..5 (muhimlik bali)
    sentiment               TEXT,                          -- positive | negative | neutral
    lang                    TEXT,
    keywords                TEXT,                          -- dedup uchun kalit so'zlar (Jaccard)
    first_posted_at         TIMESTAMPTZ,
    post_count              INTEGER NOT NULL DEFAULT 1,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_stories_created ON stories (created_at);
CREATE INDEX IF NOT EXISTS idx_stories_importance ON stories (importance DESC);

-- posts jadvaliga cache pipeline ustunlari (idempotent)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS processed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS story_id  BIGINT;
CREATE INDEX IF NOT EXISTS idx_posts_unprocessed ON posts (posted_at) WHERE processed = FALSE;
CREATE INDEX IF NOT EXISTS idx_posts_story ON posts (story_id);

-- channels jadvaliga health-check ustunlari (idempotent)
ALTER TABLE channels ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ;
ALTER TABLE channels ADD COLUMN IF NOT EXISTS health_status   TEXT NOT NULL DEFAULT 'ok';
ALTER TABLE channels ADD COLUMN IF NOT EXISTS last_error      TEXT;



-- ============================================================
--  FAZA 2 — Qiziqishlar profili va muhimlik rejimi
-- ============================================================
-- interests: foydalanuvchi tanlagan kategoriyalar (bo'sh = hammasi)
ALTER TABLE users ADD COLUMN IF NOT EXISTS interests TEXT[] NOT NULL DEFAULT '{}';
-- importance_min: digestga tushadigan minimal muhimlik (1=hammasi, 3=muhim, 4=eng muhim)
ALTER TABLE users ADD COLUMN IF NOT EXISTS importance_min SMALLINT NOT NULL DEFAULT 1;


-- ============================================================
--  ENTERPRISE v2.0 — ingestion pipeline, media, raw log, edits
-- ============================================================

-- Har bir Telegram xabarining xom (raw) JSON ko'rinishi — audit / qayta ishlash uchun.
CREATE TABLE IF NOT EXISTS raw_messages (
    id             BIGSERIAL PRIMARY KEY,
    channel_id     INTEGER REFERENCES channels(id) ON DELETE CASCADE,
    tg_channel_id  BIGINT NOT NULL,
    tg_message_id  BIGINT NOT NULL,
    raw_data       JSONB,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tg_channel_id, tg_message_id)             -- idempotentlik kafolati
);
CREATE INDEX IF NOT EXISTS idx_raw_channel_msg ON raw_messages (channel_id, tg_message_id);

-- posts jadvaliga Enterprise ustunlari (idempotent, mavjud bazaga xavfsiz qo'shiladi)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS caption             TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS has_media           BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS grouped_id          BIGINT;       -- album (media group) id
ALTER TABLE posts ADD COLUMN IF NOT EXISTS is_forwarded        BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS fwd_from_channel    TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS reply_to_message_id BIGINT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS edited_at           TIMESTAMPTZ;  -- tahrirlangan vaqt
ALTER TABLE posts ADD COLUMN IF NOT EXISTS deleted_at          TIMESTAMPTZ;  -- o'chirilgan vaqt (tomb-stone)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS ocr_text            TEXT;         -- rasmdan OCR matni
ALTER TABLE posts ADD COLUMN IF NOT EXISTS transcript          TEXT;         -- audiodan matn (Whisper)
CREATE INDEX IF NOT EXISTS idx_posts_grouped ON posts (grouped_id) WHERE grouped_id IS NOT NULL;

-- Media fayllar metadata
CREATE TABLE IF NOT EXISTS media (
    id              BIGSERIAL PRIMARY KEY,
    post_id         BIGINT REFERENCES posts(id) ON DELETE CASCADE,
    channel_id      INTEGER REFERENCES channels(id) ON DELETE CASCADE,
    tg_message_id   BIGINT NOT NULL,
    file_id         TEXT,
    unique_file_id  TEXT,
    media_type      TEXT,                                  -- photo | video | document | audio | voice ...
    caption         TEXT,
    ocr_text        TEXT,
    transcript      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (channel_id, tg_message_id, unique_file_id)     -- takror media kiritilmaydi
);
CREATE INDEX IF NOT EXISTS idx_media_post ON media (post_id);

-- Qayta ishlash bosqichlari jurnali (audit / monitoring)
CREATE TABLE IF NOT EXISTS processing_logs (
    id          BIGSERIAL PRIMARY KEY,
    post_id     BIGINT,
    channel_id  INTEGER,
    stage       TEXT NOT NULL,       -- ingest | media | ocr | whisper | ai_analysis | backfill
    status      TEXT NOT NULL,       -- started | success | error | skipped
    error_msg   TEXT,
    logged_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_proclog_stage ON processing_logs (stage, status);
CREATE INDEX IF NOT EXISTS idx_proclog_logged ON processing_logs (logged_at DESC);

-- Backfill kuzatuvi
ALTER TABLE channels ADD COLUMN IF NOT EXISTS last_backfilled_at TIMESTAMPTZ;
