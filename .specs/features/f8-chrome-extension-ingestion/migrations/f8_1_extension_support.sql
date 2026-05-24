-- F8: Chrome Extension support
-- Migration applied via Supabase MCP on 2026-05-24.
-- Recorded here for version control / future replay.
--
-- Project: itghmlcipjloirsyhare (News, shared instance)
-- Schema:  medzee_spy
--
-- Changes:
--   1. captured_messages.source TEXT NOT NULL DEFAULT 'webhook' (CHECK webhook|extension)
--   2. whatsapp_sessions.provider TEXT NOT NULL DEFAULT 'uazapi' (CHECK uazapi|extension)
--   3. whatsapp_sessions.uazapi_token: DROP NOT NULL (extension provider has no token)
--   4. UNIQUE INDEX (user_id) WHERE provider='extension' on whatsapp_sessions
--   5. NEW TABLE medzee_spy.extension_installs (Chrome ext pairing registry)
--   6. NEW TABLE medzee_spy.mobile_redirect_leads (ANON insert allowed)
--   7. NEW TABLE medzee_spy.extension_telemetry (no-PII observability)
--
-- Rollback: see footer.

-- ============================================
-- captured_messages.source (webhook | extension)
-- ============================================
ALTER TABLE medzee_spy.captured_messages
  ADD COLUMN source TEXT NOT NULL DEFAULT 'webhook'
  CHECK (source IN ('webhook', 'extension'));

CREATE INDEX ix_captured_messages_source
  ON medzee_spy.captured_messages (user_id, source, ts DESC);

COMMENT ON COLUMN medzee_spy.captured_messages.source IS
  'F8: Origin of the captured message — webhook (legacy uazapi) or extension (Chrome ext).';

-- ============================================
-- whatsapp_sessions.provider (uazapi | extension)
-- ============================================
ALTER TABLE medzee_spy.whatsapp_sessions
  ADD COLUMN provider TEXT NOT NULL DEFAULT 'uazapi'
  CHECK (provider IN ('uazapi', 'extension'));

ALTER TABLE medzee_spy.whatsapp_sessions
  ALTER COLUMN uazapi_token DROP NOT NULL;

CREATE UNIQUE INDEX ux_whatsapp_sessions_extension_per_user
  ON medzee_spy.whatsapp_sessions (user_id)
  WHERE provider = 'extension';

COMMENT ON COLUMN medzee_spy.whatsapp_sessions.provider IS
  'F8: WhatsApp ingestion provider — uazapi (legacy SaaS) or extension (Chrome ext).';

-- ============================================
-- extension_installs
-- ============================================
CREATE TABLE medzee_spy.extension_installs (
  install_id TEXT PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  paired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  extension_version TEXT,
  user_agent TEXT
);

CREATE INDEX ix_extension_installs_user
  ON medzee_spy.extension_installs (user_id);

ALTER TABLE medzee_spy.extension_installs ENABLE ROW LEVEL SECURITY;

CREATE POLICY extension_installs_owner ON medzee_spy.extension_installs
  FOR ALL TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY extension_installs_service ON medzee_spy.extension_installs
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE, DELETE
  ON medzee_spy.extension_installs
  TO authenticator, authenticated, service_role;

COMMENT ON TABLE medzee_spy.extension_installs IS
  'F8: Chrome extension installation registry. install_id is generated client-side (uuid v4).';

-- ============================================
-- mobile_redirect_leads (capture-only; ANON insert allowed)
-- ============================================
CREATE TABLE medzee_spy.mobile_redirect_leads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL,
  user_agent TEXT,
  source_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_mobile_redirect_leads_email
  ON medzee_spy.mobile_redirect_leads (email);

ALTER TABLE medzee_spy.mobile_redirect_leads ENABLE ROW LEVEL SECURITY;

CREATE POLICY mobile_redirect_leads_anon_insert ON medzee_spy.mobile_redirect_leads
  FOR INSERT TO anon
  WITH CHECK (true);

CREATE POLICY mobile_redirect_leads_service_all ON medzee_spy.mobile_redirect_leads
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

GRANT INSERT ON medzee_spy.mobile_redirect_leads
  TO anon, authenticator;
GRANT SELECT, INSERT, UPDATE, DELETE ON medzee_spy.mobile_redirect_leads
  TO service_role;

COMMENT ON TABLE medzee_spy.mobile_redirect_leads IS
  'F8: Capture-only of mobile users redirected to desktop. ANON can INSERT; only service_role can SELECT.';

-- ============================================
-- extension_telemetry
-- ============================================
CREATE TABLE medzee_spy.extension_telemetry (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  event TEXT NOT NULL CHECK (event IN (
    'collect_failed', 'collect_started', 'collect_completed',
    'wa_needs_login', 'service_worker_woke', 'pairing_failed'
  )),
  extension_version TEXT NOT NULL,
  reason TEXT,
  chats_total INT,
  chats_processed INT,
  duration_ms INT,
  ua TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_extension_telemetry_user_created
  ON medzee_spy.extension_telemetry (user_id, created_at DESC);

CREATE INDEX ix_extension_telemetry_event_failed
  ON medzee_spy.extension_telemetry (event, created_at DESC)
  WHERE event = 'collect_failed';

ALTER TABLE medzee_spy.extension_telemetry ENABLE ROW LEVEL SECURITY;

CREATE POLICY extension_telemetry_owner ON medzee_spy.extension_telemetry
  FOR ALL TO authenticated
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY extension_telemetry_service ON medzee_spy.extension_telemetry
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

GRANT SELECT, INSERT ON medzee_spy.extension_telemetry
  TO authenticator, authenticated, service_role;

COMMENT ON TABLE medzee_spy.extension_telemetry IS
  'F8: Extension observability events (no PII). Rate-limited 60/min/user at app layer.';

-- ============================================
-- ROLLBACK (reverse migration, paste if needed)
-- ============================================
-- DROP TABLE medzee_spy.extension_telemetry;
-- DROP TABLE medzee_spy.mobile_redirect_leads;
-- DROP TABLE medzee_spy.extension_installs;
-- DROP INDEX medzee_spy.ux_whatsapp_sessions_extension_per_user;
-- DROP INDEX medzee_spy.ix_captured_messages_source;
-- ALTER TABLE medzee_spy.whatsapp_sessions ALTER COLUMN uazapi_token SET NOT NULL;
-- ALTER TABLE medzee_spy.whatsapp_sessions DROP COLUMN provider;
-- ALTER TABLE medzee_spy.captured_messages DROP COLUMN source;
