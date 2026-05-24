-- F8 — isolamento de relatórios por coleta.
--
-- Problema: 2 cliques em "Gerar relatório" produziam 2 relatórios fundidos
-- (mesma pool de captured_messages). RPC top_n_messages_per_chat filtrava
-- só por user_id, então o worker do 2º relatório via dados do 1º run + 2º.
--
-- Fix: cada execução de coleta tem um batch_id (UUID v4 gerado pelo
-- wa-collector — único por execução, compartilhado entre todos os batches
-- da mesma run). Persistir esse batch_id em captured_messages e filtrar
-- por ele no worker isola cada relatório à sua coleta.
--
-- Mudanças:
--   1. ADD COLUMN batch_id TEXT (nullable pra rows pré-f8_4)
--   2. Index parcial (user_id, batch_id) WHERE batch_id IS NOT NULL
--   3. RPC top_n_messages_per_chat recebe p_batch_id opcional;
--      quando NULL, mantém comportamento legado (histórico todo);
--      quando preenchido, escopa a 1 coleta específica.

ALTER TABLE medzee_spy.captured_messages
  ADD COLUMN batch_id TEXT;

CREATE INDEX ix_captured_messages_batch_id
  ON medzee_spy.captured_messages (user_id, batch_id)
  WHERE batch_id IS NOT NULL;

COMMENT ON COLUMN medzee_spy.captured_messages.batch_id IS
  'F8: UUID v4 gerado pelo wa-collector por execução de coleta (único pra todos os batches da mesma execução). Worker do relatório filtra por este campo pra isolar dados de cada Gerar relatório.';

CREATE OR REPLACE FUNCTION medzee_spy.top_n_messages_per_chat(
  p_user_id uuid,
  p_n_per_chat integer DEFAULT 30,
  p_batch_id text DEFAULT NULL
)
RETURNS SETOF medzee_spy.captured_messages
LANGUAGE sql
STABLE
SET search_path TO 'medzee_spy', 'pg_catalog'
AS $function$
  WITH ranked AS (
    SELECT
      cm.*,
      ROW_NUMBER() OVER (PARTITION BY cm.wa_chatid ORDER BY cm.ts DESC) AS rn
    FROM medzee_spy.captured_messages cm
    WHERE cm.user_id = p_user_id
      AND (p_batch_id IS NULL OR cm.batch_id = p_batch_id)
  )
  SELECT
    id, user_id, whatsapp_session_id, wa_chatid, contact_name,
    ts, is_from_me, message_type, text, raw_message_id, created_at,
    source, batch_id
  FROM ranked
  WHERE rn <= GREATEST(LEAST(p_n_per_chat, 100), 1)
  ORDER BY wa_chatid ASC, ts ASC;
$function$;

-- Rollback (paste invertido):
-- DROP INDEX medzee_spy.ix_captured_messages_batch_id;
-- ALTER TABLE medzee_spy.captured_messages DROP COLUMN batch_id;
-- (e recriar a função sem p_batch_id, vide f8_3 record)
