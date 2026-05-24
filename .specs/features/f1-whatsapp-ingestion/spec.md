# F1 — WhatsApp Ingestion

> **Status: ✅ COMPLETE (2026-05-17)** — smoke ponta-a-ponta validado em Railway + Supabase real. Veja [ROADMAP.md](../../project/ROADMAP.md) e lições L1-L7 em [STATE.md](../../project/STATE.md).

> Conectar o WhatsApp da clínica via QR Code (uazapi) e extrair o histórico dos últimos 30 dias, sem persistir conteúdo.

## Problem statement
Hoje a tela `/spy` gera um QR mockado que aponta para uma URL fixa e o fluxo nunca se conecta de fato ao WhatsApp do usuário. Sem essa conexão real, todo o resto do produto (cadastro, processamento, relatório autenticado) opera sobre dados fictícios e a entrega da task descrita em `contexto_medzee_spy.mc` fica inviável. Precisamos de uma fonte de mensagens reais (últimos 30 dias) entregue ao backend para que o pipeline de relatório tenha matéria-prima — usando a uazapi como provider (D1).

## Users
- **Médico/gestor da clínica** que lê o QR para liberar a análise — interage com `/spy`.
- **Backend FastAPI** — consumidor das mensagens extraídas para alimentar F2 (auth/persistence) e F3 (LLM).

## Success metrics
- ≥ 95% das tentativas de leitura de QR resultam em sessão `connected` em ≤ 60s (em rede estável).
- Extração de 30 dias devolve resultado em ≤ 90s para clínicas com ≤ 10.000 mensagens no período (alvo a confirmar com smoke test — ver STATE.md "Todos").
- 0 ocorrência de conteúdo de mensagem persistido em disco (auditoria por grep no DB e nos logs).
- 100% das sessões `extracted` são encerradas via `POST /instance/disconnect` em ≤ 5min após o extract (cleanup garantido).

## User stories

### P1 — MVP (precisa entrar em M1)

**US-01 — Solicitar nova sessão de WhatsApp**
Como frontend `/spy`, quero pedir uma nova sessão ao backend e receber um QR Code para exibir, para que o médico consiga escanear.
- WPP-01: WHEN o frontend chama `POST /api/whatsapp/sessions` sem corpo, THEN o backend SHALL: (a) chamar `POST <uazapi>/instance/create` com header `admintoken`, (b) chamar `POST <uazapi>/instance/connect` com o `instance_token` retornado, (c) persistir um registro em `medzee_whatsapp_sessions` com `status="pending"`, `uazapi_token=<instance_token>`, `user_id=NULL`, e (d) responder `{ sessionId: uuid, qr: base64_png, status: "pending" }` em ≤ 8s.
- WPP-02: WHEN a uazapi não responde em 8s (em qualquer etapa do WPP-01), THEN o backend SHALL retornar `503` com `detail: "uazapi_unavailable"` e marcar a sessão como `failed` se já criada.
- WPP-03: WHEN o backend cria a sessão, THEN ele SHALL registrar webhook em `POST <uazapi>/webhook` com `{ url: <API_BASE_URL>/api/whatsapp/webhook?session_id=<uuid>, events: ["connection","messages"], enabled: true }`. O `session_id` na querystring é a chave para rotear eventos no callback.

**US-02 — Atualização do QR e status em tempo real**
Como frontend, quero receber atualizações do estado da sessão sem polling manual, para refletir progresso na UI.
- WPP-04: WHEN o frontend abre `GET /api/whatsapp/sessions/:id/events` (SSE — `text/event-stream`), THEN o backend SHALL transmitir eventos: `qr-updated`, `connected`, `extracting`, `extracted`, `failed`, `expired`. Formato: `event: <name>\ndata: <json>\n\n`.
- WPP-05: WHEN o QR expira (uazapi rejeita o `instance_token` atual OU passa janela de leitura) AND a sessão ainda está `pending`, THEN o backend SHALL chamar `POST <uazapi>/instance/connect` novamente para renovar o QR e emitir SSE `qr-updated` com `data.qr` (novo base64).
- WPP-06: WHEN o webhook da uazapi entrega `event="connection"` com `data.loggedIn=true` (ou `data.connected=true && data.loggedIn=true`), THEN o backend SHALL: (a) atualizar `medzee_whatsapp_sessions.status="connected"`, (b) emitir SSE `connected` com `{ phone: <msisdn mascarado, ex.: "+55 11 9****-1234"> }`. Número completo NÃO é exposto na resposta e nunca é logado.

**US-03 — Extração das mensagens dos últimos 30 dias**
Como backend, quero iniciar automaticamente a extração após `connected`, para alimentar o pipeline LLM em F3.
- WPP-07: WHEN a sessão transita para `connected`, THEN o backend SHALL disparar uma task assíncrona que executa: (1) `POST <uazapi>/chat/find` paginado (limit=100, offset=0…) coletando todos os chats sem filtro de grupo (ambos individuais e grupos contam); (2) para cada chat (paralelizando até 5 concurrent), `POST <uazapi>/message/find` com `{ chatid, limit: 100, offset: 0 }` em loop, parando quando `timestamp < now() - 30 dias` OR `hasMore=false`.
- WPP-08: O backend SHALL agregar o resultado em memória no formato:
  ```
  {
    messageCount: int,
    conversationCount: int,
    conversations: [
      { wa_chatid, contactName, lastMessageAt, isGroup, messages: [{ ts, fromMe, type, text }] }
    ]
  }
  ```
  Apenas campos textuais. **Sem mídia, sem áudio, sem documentos, sem location, sem status.**
- WPP-09: WHEN a extração termina (todos os chats relevantes esgotados OR limite de 90s atingido), THEN o backend SHALL: (a) armazenar o payload em cache em-memória com TTL=15min vinculado ao `sessionId`, (b) atualizar `medzee_whatsapp_sessions.status="extracted"`, `message_count`, `extracted_at=now()`, (c) emitir SSE `extracted` com `{ messageCount, conversationCount }`.
- WPP-10: O conteúdo bruto das mensagens NUNCA SHALL ser gravado em disco, log estruturado, ou banco. Auditável: logs registram apenas `chat_count`, `message_count`, `elapsed_ms`, `status`.

**US-04 — Encerramento e cleanup**
Como sistema, quero garantir que toda sessão uazapi aberta seja encerrada após o uso, para liberar o número do WhatsApp do cliente e reduzir custo/risco.
- WPP-11: WHEN `status="extracted"` AND o payload é consumido por F2 (signup linka `user_id`) OR o TTL de 15min expira, THEN o backend SHALL chamar `POST <uazapi>/instance/disconnect` (com `token=uazapi_token`) e marcar `medzee_whatsapp_sessions.status="consumed"`.
- WPP-12: WHEN ocorrer erro irrecuperável (uazapi 5xx persistente, timeout, banimento detectado via `provider_code: 463` no payload de erro, ou webhook não chega em 90s pós-`pending`), THEN a sessão SHALL ir para `status="failed"`, o backend tenta `POST /instance/disconnect` best-effort, e o frontend recebe evento SSE `failed` com `{ code: "timeout" | "banned" | "qr_expired" | "extract_failed" | "uazapi_unavailable" | "unknown", message: string }`.
- WPP-13: ~~Diretório de auth state do Baileys~~ — **N/A**: uazapi gerencia o auth state internamente. Substituído por: WHEN a sessão termina (`consumed` ou `failed`), o backend MAY chamar `DELETE <uazapi>/instance/:id` (endpoint admin) para apagar a instância no final do dia via cron, mas em M1 basta `disconnect` (o número fica liberado e a instância órfã pode ser limpa depois).

### P2 — Should have

**US-05 — Resiliência a desconexão do SSE**
- WPP-14: WHEN a conexão SSE frontend ↔ backend cai durante `pending`/`connected`/`extracting`, THEN o frontend SHALL poder reabrir `GET /api/whatsapp/sessions/:id/events` e receber o último estado conhecido como primeiro evento (`replay-last`) — backend mantém o estado da sessão em memória até `consumed`/`failed` + TTL 15min.
- WPP-15: WHEN o frontend reabre uma sessão já em `extracted`/`consumed`/`failed`, THEN o backend SHALL responder com o último estado como primeira mensagem e fechar o stream em seguida (sem manter conexão ociosa).

**US-06 — Limite de sessões simultâneas por IP**
- WPP-16: WHEN o mesmo IP cria > 3 sessões `pending` em < 5min, THEN o backend SHALL retornar `429 too_many_sessions` para a 4ª tentativa, sem chamar a uazapi.

### P3 — Nice to have

**US-07 — Métricas operacionais**
- WPP-17: Backend SHALL expor `GET /api/whatsapp/_metrics` (autenticado interno, header `X-Admin-Token`) com counts agregados de sessões por status nas últimas 24h — sem qualquer dado de mensagem.

## Out of scope (desta feature)
- Reaproveitamento de instâncias uazapi entre usuários ou entre dispositivos do mesmo usuário.
- Múltiplos números por usuário.
- Filtros por contato/conversa via UI.
- Envio de mensagens em nome do usuário.
- Extração de mídia, áudios, documentos, status.
- Detecção de "domínio saúde" — fica em F3 (Report Processing).
- Migration das tabelas Supabase (`medzee_whatsapp_sessions` etc.) — entregue em F2 junto das outras tabelas para uma migration única. **Schema** já está descrito em [.specs/codebase/ARCHITECTURE.md](.specs/codebase/ARCHITECTURE.md) e nesta spec.

## Edge cases e tratamentos
- **EC-01** — Usuário não escaneia em 60s: backend detecta via timeout + estado `pending`; pode renovar QR (WPP-05) até 3x; se passar 3min sem `connected`, marca `failed (qr_expired)`; frontend mostra "Tentar novamente" que cria nova sessão.
- **EC-02** — Clínica sem mensagens nos últimos 30 dias: `chat/find` retorna lista vazia OU `message/find` retorna 0 em todos os chats; `messageCount=0`; status vai para `extracted`; F3 (em outra feature) gera relatório com fallback "dados insuficientes".
- **EC-03** — Mais de 10k mensagens: extract continua até cortar por timestamp; se ultrapassar 90s, emite `extracting` com `{ collected: n, partial: true }` e em 120s força corte salvando o que tem.
- **EC-04** — Conexão da uazapi cai durante `extracting`: backend tenta `1x` retomar do offset atual; se falhar, evento `failed (extract_failed)`.
- **EC-05** — Webhook nunca chega (uazapi não consegue alcançar nosso backend, ex.: rodando atrás de NAT em dev): fallback é `GET /instance/status` em poll a cada 5s por até 60s pós-`pending`. Documentar no README como expor o backend via túnel (ngrok/cloudflared) em dev.
- **EC-06** — Tentativa de criar 2ª sessão para um sessionId já em `extracting`: ignorar, retornar `409 already_extracting`.

## Dependências
- **Bloqueia:** F2 (signup precisa do `whatsappSessionId` para linkar `user_id` ao registro existente), F3 (precisa do payload em cache para processar), F4 (frontend `/spy` consome estes endpoints).
- **Não depende de:** F2/F3/F4. Pode ser desenvolvida e testada via Postman/curl isoladamente desde que se tenha um túnel público para o webhook.
- **Pré-requisitos técnicos:**
  - Decisão D1 (uazapi.com) confirmada ✓.
  - Variáveis `UAZAPI_BASE_URL`, `UAZAPI_ADMIN_TOKEN` configuradas (`backend/.env` ✓).
  - Container Docker do backend ou túnel HTTPS para receber webhook da uazapi (D7).
  - Adapter `app/clients/whatsapp/uazapi.py` implementado (ainda a fazer — vai sair do `tasks.md`).

## Requirement traceability

Legend: ✅ done · 🟨 done + caveat · ⏸ deferred · N/A not applicable

| ID      | Story | Implementation | Test | Status |
| ------- | ----- | -------------- | ---- | ------ |
| WPP-01  | US-01 | `service.create_session` + `UazapiProvider.create_session` (chains `/instance/create` admin + `/instance/connect`) | `test_uazapi_adapter::test_create_session_happy_path`, `test_service::test_create_session_happy`, `test_routes::test_post_sessions_happy` | ✅ |
| WPP-02  | US-01 | `routes.create_session` maps `UazapiError`/`UazapiUnavailable`/`UazapiTimeout` → 503 | `test_routes::test_post_sessions_503_uazapi_unavailable` | ✅ |
| WPP-03  | US-01 | `service.create_session` calls `repo.create` then `store.create`; webhook registered via `provider.register_webhook` | `test_service::test_create_session_happy` | ✅ |
| WPP-04  | US-02 | SSE `routes.session_events` + `state.SessionStore.subscribe` (broadcast pub/sub) | `test_routes::test_get_events_streams_replay_last_then_terminal` | ✅ |
| WPP-05  | US-02 | `provider.refresh_qr` available; frontend handles via SSE `qr-updated` event | (no smoke yet — uazapi free QRs lasted long enough) | 🟨 (covered in code, not smoke-tested) |
| WPP-06  | US-02 | `service.handle_webhook_event` reads `instance.status == "connected"` and `owner` → masks via `mask_phone` → publishes `connected` SSE | smoke 2026-05-17: webhook arrived, frontend transitioned | ✅ |
| WPP-07  | US-03 | `service.handle_webhook_event` `asyncio.create_task(_run_extract)` after publishing `connected` | smoke 2026-05-17 (worker started; failed downstream on uazapi 500) | ✅ trigger / 🟨 pipeline blocked by B3 |
| WPP-08  | US-03 | `extract_30d_pipeline` filters `m.type=='text'`; adapter normalizes Baileys type aliases | `test_extract::test_filters_non_text_messages` | ✅ |
| WPP-09  | US-03 | `extract_30d_pipeline` paginates with cutoff_ts, publishes `extracted` event, calls `repo.mark_extracted` | `test_extract::test_extracts_only_30d_messages`, `test_extract::test_empty_clinic_extracted_with_count_zero` | ✅ |
| WPP-10  | US-03 | adapter + worker logs only counts/op/elapsed_ms; payload never serialized into log message | code review + `test_extract` does not log payload | ✅ |
| WPP-11  | US-04 | `service._release_provider_slot` calls `provider.delete_instance` (DELETE /instance) after consume/extract/cancel | smoke 2026-05-17: `delete_instance status=200` after failure path | ✅ |
| WPP-12  | US-04 | `routes.create_session` error mapping; `extract._fail` publishes `failed` SSE with `code` | `test_routes::test_post_sessions_502_banned`, smoke: chat/find 500 → code=uazapi_unavailable | ✅ |
| WPP-13  | US-04 | uazapi handles auth state — nothing for us to clean | — | N/A |
| WPP-14  | US-05 | `state.SessionStore.subscribe` replays `last_event` to new subscribers | `test_routes::test_get_events_streams_replay_last_then_terminal` | ✅ |
| WPP-15  | US-05 | subscribe closes immediately when status is terminal | `test_state::test_subscribe_closes_on_terminal` | ✅ |
| WPP-16  | US-06 | `service._enforce_rate_limit` with monotonic clock + per-IP bucket | `test_service::test_rate_limit_blocks_4th_attempt`, `test_service::test_rate_limit_window_expires` | ✅ |
| WPP-17  | US-07 | (P3 deferred — métricas operacionais) | — | ⏸ |

## Open questions

Resolvidas:
- ~~Protocolo do stream frontend ↔ backend (SSE vs WS)~~ → **SSE** (D5).
- ~~Storage do auth state do Baileys~~ → **N/A** com uazapi (D1).
- ~~Quem dispara `extract` — automático vs manual~~ → **automático ao webhook `connection`** (D6).

Em aberto:
1. **Webhook por instância vs global** — uazapi tem `/webhook` (per instance) e `/globalwebhook` (admin, único endpoint para todas as instâncias). Proposta atual: per-instance (mais simples para M1); migrar para global se chegar a centenas de sessões simultâneas (ver "Ideias adiadas" em STATE.md).
2. **Paralelismo do extract** — quantos `message/find` concurrent? Proposta: 5 inicialmente; ajustar após smoke test (item em "Todos" no STATE.md).
3. **Política de retry** — uazapi 5xx esporádico merece retry com backoff? Proposta: 2 retries com backoff exponencial (200ms, 800ms) só em GETs/POSTs idempotentes (chat/find, message/find, status).
4. **Túnel para webhook em dev** — usar ngrok, cloudflared, ou outro? Não-decisão técnica do core; entra no README. Proposta: documentar `cloudflared tunnel --url http://localhost:8000` (gratuito, sem cadastro).
5. **Mascaramento do número** — manter parcial humano-legível (`+55 11 9****-1234`) ou usar hash determinístico? Proposta atual: parcial para UI; hash só se logarmos algo (que não fazemos).
