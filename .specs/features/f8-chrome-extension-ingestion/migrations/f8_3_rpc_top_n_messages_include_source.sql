-- F8 hotfix: top_n_messages_per_chat retornava 11 colunas mas a tabela
-- captured_messages tem 12 colunas após migration f8_1 (adicionou `source`).
-- Postgres rejeitava com 42P13 "return type mismatch in function declared
-- to return captured_messages".
--
-- Smoke confirmou via Railway logs (2026-05-24):
--   File "/app/app/modules/captured_messages/repository.py", line 307, in _run
--     .execute()
--   postgrest.exceptions.APIError: {'code': '42P13', 'details':
--     'Final statement returns too few columns.'}
--
-- Fix: recria a função incluindo `source` no SELECT final.

CREATE OR REPLACE FUNCTION medzee_spy.top_n_messages_per_chat(
  p_user_id uuid,
  p_n_per_chat integer DEFAULT 30
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
  )
  SELECT
    id, user_id, whatsapp_session_id, wa_chatid, contact_name,
    ts, is_from_me, message_type, text, raw_message_id, created_at,
    source
  FROM ranked
  WHERE rn <= GREATEST(LEAST(p_n_per_chat, 100), 1)
  ORDER BY wa_chatid ASC, ts ASC;
$function$;
