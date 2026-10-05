-- Qwen workflow control plane schema (D1 / SQLite)
-- Designed for low write amplification on Workers Free.

CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL,
  password_enc TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active', -- active|disabled|invalid
  last_used_at INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY,                 -- API chat_id (UUID)
  account_id TEXT NOT NULL,
  qwen_chat_id TEXT,                   -- upstream /c/{id}
  title TEXT,
  modality TEXT NOT NULL DEFAULT 'text', -- text|image|video
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  chat_id TEXT,
  account_id TEXT NOT NULL,
  qwen_chat_id TEXT,
  kind TEXT NOT NULL,                  -- text|image|video
  status TEXT NOT NULL,                -- queued|running|succeeded|failed
  model TEXT,
  request_json TEXT NOT NULL,
  result_json TEXT,
  error TEXT,
  lease_owner TEXT,
  lease_until INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  finished_at INTEGER,
  FOREIGN KEY (chat_id) REFERENCES chats(id),
  FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  chat_id TEXT NOT NULL,
  job_id TEXT,
  role TEXT NOT NULL,                    -- user|assistant|system
  content TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (chat_id) REFERENCES chats(id)
);

-- Claim / listing helpers (avoid full scans)
CREATE INDEX IF NOT EXISTS idx_jobs_claim
  ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_chat
  ON jobs(chat_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chats_account
  ON chats(account_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_messages_created
  ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_messages_chat
  ON messages(chat_id, created_at);
CREATE INDEX IF NOT EXISTS idx_accounts_active
  ON accounts(status, last_used_at);
