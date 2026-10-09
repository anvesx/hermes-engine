-- token-metrics leaderboard. Idempotent: safe to run again.
CREATE TABLE IF NOT EXISTS users (
  id           BIGSERIAL PRIMARY KEY,
  email        TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  handle       TEXT NOT NULL UNIQUE,
  card_fields  JSONB NOT NULL DEFAULT '{"name":true,"level":true,"badges":true,"streak":true,"tokens":true,"hours":true,"spend":true}',
  lifetime     JSONB,                       -- the latest payload's lifetime block
  client       TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_sync_at TIMESTAMPTZ
);

-- one row per sign-in: the CLI and the website each hold their own token
CREATE TABLE IF NOT EXISTS tokens (
  token_hash TEXT PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK (kind IN ('cli', 'web')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS login_codes (
  id         BIGSERIAL PRIMARY KEY,
  email      TEXT NOT NULL,
  code_hash  TEXT NOT NULL,
  ip         TEXT,
  attempts   INT NOT NULL DEFAULT 0,
  used       BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS login_codes_email ON login_codes (email, created_at);
CREATE INDEX IF NOT EXISTS login_codes_ip ON login_codes (ip, created_at);

-- one row per user and ISO week (the user's local calendar), replaced on every sync
CREATE TABLE IF NOT EXISTS weekly_stats (
  user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  week        TEXT NOT NULL,
  payload     JSONB NOT NULL,
  first_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, week)
);

-- one-time links the CLI opens in the browser to sign the website in (`share.py dashboard`)
CREATE TABLE IF NOT EXISTS login_links (
  token_hash TEXT PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  used       BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL
);

-- added in 1.5.0: the latest payload's per-day token totals (a rolling window, replaced on each sync)
ALTER TABLE users ADD COLUMN IF NOT EXISTS days JSONB;

-- one-time codes that hand a Google sign-in from the browser to the CLI (`share.py join` with no email)
CREATE TABLE IF NOT EXISTS cli_codes (
  code_hash  TEXT PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  used       BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL
);
