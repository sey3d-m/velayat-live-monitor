-- Cloudflare D1: private state for ONLY the Bale editor bot.
CREATE TABLE IF NOT EXISTS sessions (
  user_id TEXT PRIMARY KEY,
  json TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS updates (
  update_id INTEGER PRIMARY KEY,
  status TEXT NOT NULL CHECK(status IN ('processing','ready','done')),
  lease_ms INTEGER NOT NULL,
  chat_id TEXT,
  reply TEXT,
  markup TEXT,
  callback_id TEXT
);
CREATE TABLE IF NOT EXISTS cache (
  id INTEGER PRIMARY KEY CHECK(id=1),
  json TEXT NOT NULL,
  updated_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS updates_status_idx ON updates(status);
