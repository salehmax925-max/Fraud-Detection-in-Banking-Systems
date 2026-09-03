-- =============================================================================
-- db_migration.sql
-- Fraud Detection System — Full Schema Migration
-- Al-Balqa Applied University | 2026
-- =============================================================================
-- Run this script against your PostgreSQL database to:
--   1. Fix the missing true_label column bug
--   2. Ensure all transaction columns exist
--   3. Create all new auth & governance tables
--   4. Seed the 5 system users with bcrypt hashed passwords
-- =============================================================================
-- Usage:
--   psql -U fraud -d frauddb -f db_migration.sql
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- PART 1: FIX THE TRANSACTIONS TABLE (true_label bug + all columns)
-- ---------------------------------------------------------------------------

-- Ensure true_label exists (THE CRITICAL FIX)
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS true_label INTEGER DEFAULT NULL;

-- Ensure v_features is JSONB (better performance than JSON)
-- Note: If it already exists as JSON, this is a safe no-op due to IF NOT EXISTS
-- To migrate from JSON→JSONB you would need to: ALTER TABLE transactions ALTER COLUMN v_features TYPE JSONB USING v_features::JSONB;
-- We skip that in-place cast to avoid locking issues; it is handled by ORM on new rows.

-- Verify all other required columns (safe ADD IF NOT EXISTS for any that may be missing)
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS transaction_uuid VARCHAR(36);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS synthetic_user_id VARCHAR(50);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS time_val FLOAT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS amount FLOAT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS tx_freq_1h FLOAT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS tx_freq_24h FLOAT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS amount_deviation_z FLOAT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS time_of_day_risk INTEGER;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS velocity_change FLOAT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS location_entropy INTEGER;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS xgb_score FLOAT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS if_score FLOAT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS final_score FLOAT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS decision_tier VARCHAR(10);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS is_simulation BOOLEAN DEFAULT FALSE;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- ---------------------------------------------------------------------------
-- PART 2: AUTH USERS TABLE
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS auth_users (
    id                SERIAL PRIMARY KEY,
    username          VARCHAR(50) UNIQUE NOT NULL,
    display_name      VARCHAR(100) NOT NULL,
    password_hash     VARCHAR(256) NOT NULL,
    role              VARCHAR(20) NOT NULL DEFAULT 'user',
                      -- 'admin' | 'user' | 'ceo'
    is_active         BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login        TIMESTAMP WITH TIME ZONE
);

-- ---------------------------------------------------------------------------
-- PART 3: USER PERMISSIONS TABLE (CEO-controlled)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS user_permissions (
    id                          SERIAL PRIMARY KEY,
    user_id                     INTEGER REFERENCES auth_users(id) ON DELETE CASCADE,
    can_view_personal_data      BOOLEAN DEFAULT FALSE,
    can_edit_thresholds         BOOLEAN DEFAULT TRUE,
    can_view_all_transactions   BOOLEAN DEFAULT FALSE,
    updated_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- PART 4: THRESHOLD AUDIT TABLE
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS threshold_audit (
    id                      SERIAL PRIMARY KEY,
    updated_by_username     VARCHAR(50) NOT NULL,
    updated_by_display_name VARCHAR(100) NOT NULL,
    previous_threshold_block FLOAT NOT NULL,
    previous_threshold_review FLOAT NOT NULL,
    new_threshold_block     FLOAT NOT NULL,
    new_threshold_review    FLOAT NOT NULL,
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- PART 5: GOVERNANCE AUDIT LOG
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS governance_audit (
    id              SERIAL PRIMARY KEY,
    changed_by      VARCHAR(50) NOT NULL,
    target_username VARCHAR(50) NOT NULL,
    change_type     VARCHAR(50) NOT NULL,
    previous_value  VARCHAR(200),
    new_value       VARCHAR(200),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- PART 6: SYSTEM LOGS TABLE
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS system_logs (
    id           SERIAL PRIMARY KEY,
    log_level    VARCHAR(10) DEFAULT 'INFO',
    event_type   VARCHAR(50) NOT NULL,
    username     VARCHAR(50),
    display_name VARCHAR(100),
    description  TEXT,
    metadata     JSONB,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- PART 7: USER PREFERENCES TABLE
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS user_preferences (
    id               SERIAL PRIMARY KEY,
    user_id          INTEGER REFERENCES auth_users(id) ON DELETE CASCADE UNIQUE,
    last_date_filter VARCHAR(50),
    last_tab         VARCHAR(50),
    ui_preferences   JSONB,
    updated_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- PART 8: INDEXES FOR PERFORMANCE
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_auth_users_username ON auth_users(username);
CREATE INDEX IF NOT EXISTS idx_system_logs_event_type ON system_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_system_logs_created_at ON system_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_governance_audit_created_at ON governance_audit(created_at);
CREATE INDEX IF NOT EXISTS idx_threshold_audit_updated_at ON threshold_audit(updated_at);
CREATE INDEX IF NOT EXISTS idx_transactions_true_label ON transactions(true_label);

-- ---------------------------------------------------------------------------
-- PART 9: SEED AUTH USERS (5 system accounts with bcrypt hashed passwords)
-- ---------------------------------------------------------------------------
-- Passwords hashed with bcrypt (cost factor 12):
--   saleh   → SalehAdmin2026!
--   amin    → AminAdmin2026!
--   hussein → HusseinUser2026!
--   ali     → AliUser2026!
--   ceo     → CEO_DataManager2026!
-- ---------------------------------------------------------------------------

INSERT INTO auth_users (username, display_name, password_hash, role)
VALUES
    ('saleh',
     'Saleh Ghannmah',
     '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj4J/HS.iK7C',
     'admin'),
    ('amin',
     'Amin Saleh',
     '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW',
     'admin'),
    ('hussein',
     'Hussein Al-Ahmer',
     '$2b$12$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi',
     'user'),
    ('ali',
     'Ali Nasser',
     '$2b$12$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi',
     'user'),
    ('ceo',
     'Data Manager',
     '$2b$12$92IXUNpkjO0rOQ5byMi.Ye4oKoEa3Ro9llC/.og/at2.uheWG/igi',
     'ceo')
ON CONFLICT (username) DO NOTHING;

-- Insert default permissions for each auth user
INSERT INTO user_permissions (user_id, can_view_personal_data, can_edit_thresholds, can_view_all_transactions)
SELECT id,
    CASE WHEN role IN ('admin', 'ceo') THEN TRUE ELSE FALSE END,
    CASE WHEN role != 'ceo' THEN TRUE ELSE FALSE END,
    CASE WHEN role = 'admin' THEN TRUE ELSE FALSE END
FROM auth_users
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- NOTE: The bcrypt hashes above are PLACEHOLDERS.
-- The application's startup seed function generates REAL bcrypt hashes.
-- Run the backend once and it will replace these with properly hashed values.
-- OR run: python scripts/seed_users.py
-- ---------------------------------------------------------------------------

COMMIT;

-- =============================================================================
-- VERIFICATION QUERIES (run manually to confirm migration success)
-- =============================================================================
-- SELECT column_name, data_type FROM information_schema.columns
--   WHERE table_name = 'transactions' AND column_name = 'true_label';
-- SELECT count(*) FROM auth_users;
-- SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;
-- =============================================================================
