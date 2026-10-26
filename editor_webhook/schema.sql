-- Apply with a migration account before setting the webhook.
CREATE TABLE IF NOT EXISTS didban_editor_sessions (
  session_key TEXT PRIMARY KEY,
  state JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS didban_editor_updates (
  update_id BIGINT PRIMARY KEY,
  response JSONB,
  sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS didban_editor_cache (
  singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton),
  content TEXT NOT NULL
);
