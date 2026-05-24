# F4 — Forward-Capture & On-Demand Reports · Tasks

> Quebra atômica do [design.md](design.md) em 21 tasks. Tags `[P]` rodam em paralelo via sub-agents.

## Pré-flight

- ✓ uazapi paid contratado e env vars trocadas no Railway (`UAZAPI_BASE_URL` + `UAZAPI_ADMIN_TOKEN`)
- ✓ D4 do STATE.md revogado com mitigações documentadas (T15)
- ✓ Branch `feat/f4-forward-capture` criada a partir de `feat/f3-report-processing`
- ⏳ Validar shape real do webhook `messages` da uazapi paid (T5 documenta no primeiro hit)

## Ordem de entrega (waves)

```
Wave 1 (fundação — sequencial)
  T1 → T2 → T3

Wave 2 (camadas independentes — paralelizáveis)
  T4 [P]  T5 [P]  T6 [P]  T7 [P]  T8 [P]

Wave 3 (worker adapter — sequencial)
  T9

Wave 4 (endpoint generate — sequencial)
  T10

Wave 5 (frontend — paralelizáveis após T6+T10)
  T11 → (T12 [P]  T13 [P]  T14 [P])

Wave 6 (governança + cleanup — paralelizáveis)
  T15 [P]  T16 [P]

Wave 7 (testes — paralelizáveis)
  T17 [P]  T18 [P]  T19 [P]  T20 [P]  T21 [P]
```

---

## T1 — Migration `f4_1_captured_messages`

**What:** Aplicar a migration que cria `medzee_spy.captured_messages` + adiciona `period_days` em `medzee_spy.reports` + adiciona `connected_at` em `medzee_spy.whatsapp_sessions`.

**Where:** Supabase remoto via `mcp__supabase__apply_migration`.

**Depends on:** —

**Reuses:** Padrão de RLS owner-only do F2.

**Done when:**
- [ ] Migration aplicada (success: true)
- [ ] `list_tables schemas=["medzee_spy"]` mostra `captured_messages`
- [ ] `reports` tem coluna `period_days` (default 30, check em 7|15|30|60)
- [ ] `whatsapp_sessions` tem coluna `connected_at timestamptz`
- [ ] `get_advisors security` sem warnings novos
- [ ] Smoke: `select count(*) from medzee_spy.captured_messages` → 0

**SQL exato:** seção 3 do design.md + ALTER em `whatsapp_sessions` adicionando `connected_at`.

**Traceability:** F4-01..06.

---

## T2 — Schemas pydantic (`captured_messages/schemas.py`)

**What:** Models `CapturedMessage`, `CapturedMessageInsert`, `WhatsappStatusResponse`, `GenerateReportRequest`, `GenerateReportResponse`.

**Where:**
- `backend/app/modules/captured_messages/__init__.py` (marker + docstring)
- `backend/app/modules/captured_messages/schemas.py`

**Depends on:** T1 (lógica)

**Reuses:** pydantic BaseModel, padrão das specs anteriores.

**Done when:**
- [ ] `python -c "from app.modules.captured_messages.schemas import CapturedMessage, CapturedMessageInsert, WhatsappStatusResponse, GenerateReportRequest, GenerateReportResponse; print('ok')"`
- [ ] `GenerateReportRequest(period_days=30)` aceita; `GenerateReportRequest(period_days=999)` rejeita com ValidationError
- [ ] `CapturedMessageInsert` aceita `message_type='text'`; rejeita type aleatório

**Traceability:** F4-01..06.

---

## T3 — `SessionStore.user_id` (campo novo)

**What:** Adicionar campo `user_id: UUID | None` ao `SessionState` em memória. F2 `consume_extracted` (que vai sumir) era quem linkava — vamos linkar antes, dentro do `signup` direto. Necessário pra webhook saber a quem atribuir cada msg.

**Where:**
- `backend/app/modules/whatsapp/state.py` (campo `user_id`)
- `backend/app/modules/auth/service.py` (signup faz `whatsapp.store.update(session_id, user_id=...)`)

**Depends on:** T2 (não bloqueante)

**Done when:**
- [ ] `SessionState` tem `user_id: UUID | None = None`
- [ ] `session_store.update(session_id, user_id=uuid)` funciona
- [ ] Em `AuthService.signup`, após criar user no Supabase, **se** `req.whatsapp_session_id` existe, chama `session_store.update(session_id, user_id=user_id)`
- [ ] F2 `consume_extracted` ainda existe (não vamos quebrar F3 branch); apenas o signup ganha o link adicional via store
- [ ] Suite F1/F2 ainda verde

**Tests:** T17.

**Traceability:** F4-07 (state.user_id é precondição pro webhook handler).

---

## T4 — Repository `captured_messages/repository.py` `[P]`

**What:** Async CRUD + queries por janela + stats + delete por session.

**Where:** `backend/app/modules/captured_messages/repository.py`

**Depends on:** T1, T2

**Reuses:** Padrão de `auth/repository.py` (asyncio.to_thread + logs sem PII).

**Done when:**
- [ ] `async def insert_many(items: list[CapturedMessageInsert]) -> int` usa supabase bulk insert; ignora silenciosamente conflitos do unique index (`raw_message_id` duplicado)
- [ ] `async def query_window_for_user(user_id, *, since, until=None) -> list[CapturedMessage]` SELECT por user_id + range de ts ordenado ascendente
- [ ] `async def stats_for_user(user_id) -> dict` retorna `{message_count, conversation_count (distinct wa_chatid), last_message_at}`
- [ ] `async def stats_for_session(session_id) -> dict` idem mas filtrado por session
- [ ] `async def delete_for_session(session_id) -> int` retorna count deletado
- [ ] Logs `repo.captured.insert_many count=N`, `repo.captured.query_window count=N`. **NUNCA** loga `text`.
- [ ] `py_compile` zero erros + import smoke

**Tests:** T17.

**Traceability:** F4-01..04, F4-15.

---

## T5 — Webhook handler extension `[P]`

**What:** Estender `whatsapp/service.py::handle_webhook_event` pra tratar `event=messages` (e variações: `messages.upsert`, `message`). Parser tolerante a 3+ shapes diferentes da uazapi.

**Where:**
- `backend/app/modules/whatsapp/service.py` — `_handle_messages_event` + `_parse_uazapi_message`

**Depends on:** T2, T4, T3 (user_id no state)

**Reuses:** Padrão do `_handle_connection_event` existente; lazy import do captured_repo pra evitar ciclo.

**Done when:**
- [ ] `handle_webhook_event` faz triagem: `connection` → existing path; `messages*` → novo path; outros → debug log + return
- [ ] `_parse_uazapi_message(raw, session_id, user_id)` lida com 3 shapes conhecidos:
  - `message.conversation` (texto simples)
  - `message.extendedTextMessage.text` (texto com formatação/reply)
  - `message.imageMessage.caption` (foto com legenda — message_type='image')
  - Outros → message_type='other', text=None
- [ ] `_handle_messages_event` ignora silenciosamente se `state.user_id is None` (caso edge race signup-antes-link)
- [ ] Insert via `captured_repo.insert_many(...)` em batch (lista de uma vez, não 1×1)
- [ ] Webhook **sempre** retorna 200 mesmo se insert falhar (não pode causar retry storm da uazapi)
- [ ] Loga `service.webhook.messages count=N user_id=X session_id=Y` (sem text)
- [ ] No primeiro hit em produção, loga 1× a shape completa (com text redacted) pra documentar formato real do paid → marcar TODO em STATE.md L-X

**Tests:** T18.

**Traceability:** F4-07..10.

---

## T6 — Endpoint `GET /api/whatsapp/status` `[P]`

**What:** Retorna status atual do WhatsApp do user autenticado.

**Where:**
- `backend/app/modules/whatsapp/routes.py` — adicionar endpoint
- `backend/app/modules/whatsapp/repository.py` — adicionar `get_active_for_user(user_id) -> dict | None` (SELECT * WHERE user_id=? ORDER BY created_at DESC LIMIT 1)

**Depends on:** T2, T4

**Reuses:** `get_current_user_id` (F2), padrão `SuccessResponse[T]`.

**Done when:**
- [ ] `GET /api/whatsapp/status` retorna `WhatsappStatusResponse`
- [ ] Se nenhuma session ainda: `{connected: false}` 200
- [ ] Se session existe: agrega counts via `captured_repo.stats_for_session`
- [ ] `connected_since` lê de `whatsapp_sessions.connected_at`
- [ ] Sem JWT: 401 (via `get_current_user_id`)
- [ ] Registrado no `api/router.py`

**Tests:** T19.

**Traceability:** F4-14.

---

## T7 — TTL cleanup worker `[P]`

**What:** Background loop que roda 1× por dia, deleta `captured_messages` cujas sessions disconnect há > 30 dias.

**Where:**
- `backend/app/workers/ttl_cleanup.py` (novo)
- `backend/app/main.py` (start no lifespan)
- `backend/app/modules/whatsapp/repository.py` — adicionar `find_disconnected_before(cutoff: datetime) -> list[UUID]`

**Depends on:** T4

**Reuses:** Padrão de `session_store.start_expire_loop()` em `state.py`.

**Done when:**
- [ ] `ttl_cleanup_loop()` async function — while True com `asyncio.sleep(24*3600)`
- [ ] `_run_once()` lista disconnected_before(now-30d), itera deletando captured
- [ ] Lifespan inicia o task; cancela no shutdown (similar `session_store`)
- [ ] Constante `_TTL_DAYS` lê de env var `CAPTURED_MESSAGES_TTL_DAYS` (default 30) pra testes/dev poderem reduzir
- [ ] Loga `ttl_cleanup.cycle_complete total_deleted=N`
- [ ] Catch genérico em volta de `_run_once` — falha não derruba o loop

**Tests:** T20.

**Traceability:** F4-15, F4-16.

---

## T8 — Test scaffold `[P]`

**What:** Conftest + fixtures pra F4.

**Where:**
- `backend/app/tests/captured_messages/__init__.py`
- `backend/app/tests/captured_messages/conftest.py`

**Depends on:** —

**Reuses:** padrão lazy string-path monkeypatch de F2/F3.

**Fixtures necessárias:**

| Fixture | O que faz |
|---|---|
| `fake_captured_repo` | SimpleNamespace com AsyncMocks pras 5 funcs de `captured_messages.repository.*` |
| `sample_captured_messages` | Factory `make(*, count=20, days=7, user_id=..., session_id=...)` que retorna lista de `CapturedMessage` realista |
| `sample_uazapi_message_raw` | Factory de payload raw uazapi nos 3 shapes (text, extendedText, image+caption) |
| `mock_session_state_with_user` | Helper que insere SessionState com `user_id` set no SessionStore |

**Done when:**
- [ ] `pytest backend/app/tests/captured_messages/ --collect-only -q` → "no tests collected", sem erros
- [ ] F1/F2/F3 suites ainda verdes (não interferiu)

**Traceability:** infra dos testes F4.

---

## T9 — Worker adapter (`reports/service.py` extension)

**What:** Adicionar ao `ReportService`:
- `trigger_generate(user_id, *, period_days)` — cria row reports + dispara worker async
- `_build_and_run(report_id, user_id, period_days)` — lê captured_messages, monta `ExtractedPayload`, chama `generate_report_pipeline`
- `_build_extracted_payload(captured: list[CapturedMessage]) -> ExtractedPayload`

E pequeno refactor em `workers/report.py`:
- `generate_report_pipeline(session_id, payload, *, user_id, report_id=None)` — se `report_id` for passado, pula `create_generating`/`get_existing_for_session` e usa o id direto.

**Where:**
- `backend/app/modules/reports/service.py`
- `backend/app/workers/report.py`
- `backend/app/modules/reports/repository.py` — adicionar `update_period_days(report_id, period_days)`

**Depends on:** T2, T4

**Reuses:** TUDO do F3 — métricas, prompts, Claude client, LLM_TOOL_SCHEMA, schemas de relatório.

**Done when:**
- [ ] `trigger_generate` cria row via `create_generating`, chama `update_period_days(period_days)`, dispara `asyncio.create_task(_build_and_run(...))`, retorna `report_id`
- [ ] `_build_and_run` faz `query_window_for_user(user_id, since=now-period_days)`, agrupa por `wa_chatid` em ConversationPayload, monta ExtractedPayload, chama `generate_report_pipeline` com `report_id=` setado
- [ ] `generate_report_pipeline` aceita `report_id` opcional: se passado, pula etapa de criar row
- [ ] F3 tests existentes continuam verdes (refactor é additive)
- [ ] Logs `service.reports.trigger_generate user_id=X period_days=N report_id=Y`

**Tests:** T17, T19.

**Traceability:** F4-11, F4-13.

---

## T10 — Endpoint `POST /api/reports/generate`

**What:** Trigger relatório on-demand sobre janela escolhida.

**Where:** `backend/app/modules/reports/routes.py`

**Depends on:** T9

**Reuses:** `get_current_user_id`, `SuccessResponse[T]`, padrão de error mapping.

**Done when:**
- [ ] `POST /api/reports/generate` autenticado, body `GenerateReportRequest`
- [ ] Rate limit 1/min/user via simple in-memory `dict[user_id, last_call_ts]` (similar ao WPP-16 per-IP). Override via env var `REPORTS_GENERATE_RATE_S` (default 60)
- [ ] Pré-check via `captured_repo.stats_for_user(user_id)`: se `message_count < 10` → 422 `not_enough_data`
- [ ] Cria report via `service.trigger_generate(user_id, period_days=req.period_days)` → retorna `GenerateReportResponse(report_id, status='generating')` 200
- [ ] Sem JWT → 401
- [ ] Body inválido (period_days=999) → 422 (pydantic)

**Tests:** T19.

**Traceability:** F4-11, F4-12, EC-02, EC-03.

---

## T11 — Frontend `lib/whatsapp.js` (hook + helpers) `[P]`

**What:** Hook `useWhatsappStatus()` com polling 5s + helper `disconnectWhatsapp()`.

**Where:** `frontend/src/lib/whatsapp.js`

**Depends on:** T6 (endpoint existe)

**Reuses:** `callApi` (F2), `useEffect`/`useState`/`useRef` (padrão de F3 `useReportPolling`).

**Done when:**
- [ ] `useWhatsappStatus()` polla `/api/whatsapp/status` a cada 5s, retorna `{loading, status, error}`
- [ ] Para de polling no unmount
- [ ] `disconnectWhatsapp()` chama `POST /api/whatsapp/sessions/disconnect` (endpoint a criar OU reusar `DELETE /sessions/:id` existente)
- [ ] `npm run build` clean

**Traceability:** F4-14, F4-17.

---

## T12 — Frontend `lib/reports.js` extension `[P]`

**What:** Helper `generateReport(periodDays)`.

**Where:** `frontend/src/lib/reports.js`

**Depends on:** T10

**Done when:**
- [ ] Exporta `generateReport(periodDays)` que chama `POST /api/reports/generate` com `body: {period_days: periodDays}`
- [ ] Retorna `{report_id, status}` (passa pra navegar no caller)
- [ ] Build clean

**Traceability:** F4-11, F4-18.

---

## T13 — `WhatsAppPage.jsx` (status card) `[P]`

**What:** Refazer a página `/app/whatsapp` pra mostrar 3 estados: loading, desconectado (CTA conectar), conectado (counts + disconnect).

**Where:** `frontend/src/screens/dashboard/WhatsAppPage.jsx`

**Depends on:** T11

**Reuses:** `useWhatsappStatus`, padrão visual do dashboard (`COLORS.paper`, hairline, etc).

**Done when:**
- [ ] Estado desconectado: mensagem clara + botão "Conectar WhatsApp agora" → navigate("/spy")
- [ ] Estado conectado: card com "Conectado · há X dias · Y conversas · Z mensagens" + botão "Desconectar"
- [ ] Estado loading: skeleton enxuto
- [ ] Warning amarelo se `last_message_at` > 24h: "Sem novas mensagens há mais de 24h — verifique a conexão"
- [ ] Build clean

**Traceability:** F4-17, EC-05.

---

## T14 — `GenerateReportModal` + `ReportsListPage` wire `[P]`

**What:** Modal/dropdown pra escolher janela 7/15/30/60. Botão "Gerar relatório agora" na `ReportsListPage` agora abre o modal. Cada item da lista mostra `period_days`.

**Where:**
- `frontend/src/screens/dashboard/GenerateReportModal.jsx` (novo)
- `frontend/src/screens/dashboard/ReportsListPage.jsx` (alterar)

**Depends on:** T12

**Reuses:** estilo do dashboard, lucide-react icons.

**Done when:**
- [ ] Modal mostra 4 radio buttons (Últimos 7 / 15 / 30 / 60 dias), default 30
- [ ] "Gerar agora" → `generateReport(period)` → navigate(`/app/reports/${id}`) → polling de F3 já cuida do resto
- [ ] Erro 422 `not_enough_data`: modal mostra "Aguarde algumas conversas chegarem (mínimo: 10)"
- [ ] Erro 429: "Aguarde 1 minuto entre relatórios"
- [ ] Cada item de `ReportsListPage` exibe "Análise de {period_days} dias · {date}"
- [ ] Build clean

**Traceability:** F4-18, F4-19, EC-02, EC-03.

---

## T15 — STATE.md + ROADMAP.md update `[P]`

**What:** Refletir realidade:
- D4 revogado oficialmente (com mitigações descritas)
- ROADMAP: marcar F4 como "Forward-Capture (pivot do plano original 'Frontend Integration')"
- B3 reformulado: não é "timing", é "feature paga" no uazapi
- Adicionar L9 (uazapi free `/chat/find` confirmadamente não disponível)
- F1 extract worker marcado como "dead code mantido pra reabilitar com paid"

**Where:**
- `.specs/project/STATE.md`
- `.specs/project/ROADMAP.md`

**Depends on:** —

**Done when:**
- [ ] D4 reescrito com referência F4-21
- [ ] B3 reescrito com diagnóstico real
- [ ] ROADMAP M1 reordenado: F4 forward-capture, F5 DX&Docs (mantido), F6 route guards opcional
- [ ] Sem perda de informação histórica (B3 antigo vai pra "Lições" L9)

**Traceability:** F4-21, F4-22.

---

## T16 — Marca `extract.py` como deprecated `[P]`

**What:** Comentário no topo do `workers/extract.py` + `_kick_off_report` no `_finalize_*` mantém comportamento (não chama em prod porque nenhuma webhook conexão dispara essa cadeia em F4 — só ficaria órfão se reabilitarmos).

**Where:** `backend/app/workers/extract.py`

**Depends on:** —

**Done when:**
- [ ] Docstring no topo cita F4-22 + razão (uazapi free não suporta history)
- [ ] Função `extract_30d_pipeline` ganha decorator `@deprecated` (via warnings.warn) ou comentário grande
- [ ] Tests do F1 (test_extract.py) continuam verdes — não estamos quebrando, só sinalizando

**Traceability:** F4-22.

---

## T17 — Tests: repository + service `[P]`

**What:** Cobertura unit do repository e do `_build_extracted_payload`.

**Where:**
- `backend/app/tests/captured_messages/test_repository.py`
- `backend/app/tests/captured_messages/test_service.py`

**Depends on:** T4, T9, T8

**Casos prioritários:**

`test_repository.py`:
- `test_insert_many_inserts_rows`
- `test_insert_many_dedup_via_unique_index` (mesmos raw_message_id ignorados)
- `test_query_window_filters_by_user` (cross-user nunca aparece)
- `test_query_window_filters_by_ts_range`
- `test_query_window_orders_asc_by_ts`
- `test_stats_for_user_counts_distinct_chatids`
- `test_stats_for_session_filters_by_session`
- `test_delete_for_session_returns_count`

`test_service.py` (focused on `_build_extracted_payload`):
- `test_build_groups_by_wa_chatid`
- `test_build_preserves_order_within_chat`
- `test_build_marks_is_group_correctly` (sufixo `@g.us`)
- `test_build_picks_contact_name_first_occurrence`
- `test_build_empty_captured_returns_empty_payload`

**Done when:**
- [ ] ≥ 13 tests verdes
- [ ] F1/F2/F3 suites preservadas

**Traceability:** F4-01..04, F4-13.

---

## T18 — Tests: webhook message handler `[P]`

**What:** Cobre `_handle_messages_event` + `_parse_uazapi_message` com os 3 shapes.

**Where:** `backend/app/tests/whatsapp/test_webhook_messages.py` (novo)

**Depends on:** T5, T8

**Casos:**
- `test_parse_text_message_conversation_shape`
- `test_parse_text_message_extended_shape`
- `test_parse_image_message_with_caption`
- `test_parse_skips_unknown_message_type` (audio/sticker → message_type='other', text=None)
- `test_parse_returns_none_when_no_key`
- `test_handle_messages_event_no_user_linked_skips_silently`
- `test_handle_messages_event_inserts_batch`
- `test_handle_messages_event_swallows_repo_failure` (webhook sempre 200)
- `test_handle_webhook_event_routes_messages_to_handler`

**Done when:**
- [ ] ≥ 9 tests verdes

**Traceability:** F4-07..10.

---

## T19 — Tests: status + generate endpoints `[P]`

**What:** Route-level tests via TestClient.

**Where:**
- `backend/app/tests/whatsapp/test_status_endpoint.py`
- `backend/app/tests/reports/test_generate_endpoint.py`

**Depends on:** T6, T10, T8

**Casos `test_status_endpoint.py`:**
- `test_status_no_session_returns_disconnected`
- `test_status_with_active_session_returns_connected_and_counts`
- `test_status_without_token_401`

**Casos `test_generate_endpoint.py`:**
- `test_generate_happy_returns_report_id`
- `test_generate_invalid_period_days_422`
- `test_generate_with_zero_messages_422_not_enough_data`
- `test_generate_rate_limit_429_on_second_call`
- `test_generate_without_token_401`

**Done when:**
- [ ] ≥ 8 tests verdes

**Traceability:** F4-11, F4-12, F4-14, EC-02, EC-03.

---

## T20 — Tests: TTL cleanup worker `[P]`

**What:** Testa o `_run_once()` do TTL com dataset controlado.

**Where:** `backend/app/tests/workers/test_ttl_cleanup.py`

**Depends on:** T7, T8

**Casos:**
- `test_ttl_run_once_deletes_expired_sessions`
- `test_ttl_run_once_preserves_recent_sessions`
- `test_ttl_run_once_preserves_connected_sessions`
- `test_ttl_run_once_zero_expired_logs_zero_deleted`

**Done when:**
- [ ] ≥ 4 tests verdes
- [ ] Cleanup respeita o env var `CAPTURED_MESSAGES_TTL_DAYS`

**Traceability:** F4-15, F4-16.

---

## T21 — Tests: F2 signup link `[P]`

**What:** Validar que `AuthService.signup` agora chama `session_store.update(session_id, user_id=...)` quando `whatsapp_session_id` está presente.

**Where:** `backend/app/tests/auth/test_auth_service.py` (adicionar caso)

**Depends on:** T3

**Casos:**
- `test_signup_with_whatsapp_session_links_user_to_session_store`
- `test_signup_without_whatsapp_session_skips_store_link`

**Done when:**
- [ ] ≥ 2 tests novos verdes
- [ ] Suite auth toda ainda passa

**Traceability:** F4-07 (precondição).

---

## Smoke E2E (manual, pós-Wave 7)

Não é uma task formal. Gate final antes de fechar F4:

### Setup
1. Confirma uazapi paid no Railway env vars
2. Restart do service pra zerar rate limit do nosso lado
3. Frontend rodando localmente (`npm run dev`) apontando pro Railway

### Fluxo
1. **Primeira conexão**: vai pra `/spy` → escaneia QR → preenche form → signup → redireciona pra `/app/dashboard`
2. **Verifica conectado**: no `/app/whatsapp` ou `/app/dashboard` aparece "Conectado · 0 mensagens"
3. **Envia/recebe ~5 mensagens reais** no WhatsApp da clínica
4. **Verifica no log do Railway**: `service.webhook.messages count=N user_id=X session_id=Y` aparece a cada msg
5. **Verifica no Supabase**: `select count(*) from medzee_spy.captured_messages where user_id='...'` → reflete o que você mandou
6. **No `/app/whatsapp`**: counter atualiza após 5s (polling)
7. **Tenta gerar relatório com <10 msgs**: clica "Gerar relatório" → modal → "Gerar agora" → frontend mostra "Aguarde algumas conversas (mínimo: 10)" (422 esperado)
8. **Envia mais N mensagens até passar de 10**, espera webhooks chegarem
9. **Gera relatório**: clica "Gerar relatório" → escolhe "Últimos 7 dias" → "Gerar agora"
10. **Verifica logs**: `worker.report.llm_call.start` + `worker.report.llm_call.done` + `worker.report.exit status=completed`
11. **No Supabase**: `select model, prompt_version, score, period_days from medzee_spy.reports order by created_at desc limit 1` mostra `claude-sonnet-4-6`, `v1.0.0`, score real, `period_days=7`
12. **Frontend redireciona pra `/app/reports/<id>`**: vê o `ReportGeneratingState` (briefly), depois o relatório real com mensagens das suas conversas reais
13. **Gera segundo relatório com janela diferente** (30d): cria nova row, ambos relatórios aparecem em `/app/reports`
14. **Desconecta WhatsApp**: botão → confirma → session vira `disconnected` no DB
15. **TTL (manual test)**: temporariamente seta `CAPTURED_MESSAGES_TTL_DAYS=0` via env var, restart, observa cleanup loop deletar captured msgs da session disconnected. **Reverter env var depois.**

Se tudo passar limpo: **F4 ✅ DONE** + merge → `dev` + atualizar STATE.md "M1 closed".

## Cobertura por requisito

| F4 | Implementação | Teste |
|---|---|---|
| F4-01..06 | T1, T2 | T17 |
| F4-07 | T3, T5 | T18, T21 |
| F4-08..10 | T5 | T18 |
| F4-11..13 | T9, T10 | T17, T19 |
| F4-14 | T6 | T19 |
| F4-15..16 | T7 | T20 |
| F4-17..20 | T11..T14 | smoke |
| F4-21..22 | T15, T16 | n/a |

## Notas operacionais

- **Sub-agents na Wave 2 (5 [P])** e Wave 7 (5 [P]) são os candidatos óbvios pra paralelização.
- **uazapi webhook shape paid**: a 1ª chamada real vai logar o payload completo. Documentar em STATE.md L-X depois do smoke.
- **Não merge F3 antes de F4**: F3 sozinho não funciona em uazapi free (smoke trava). F4 destrava. Merge F3+F4 juntos quando F4 smoke passar.
- **F1 dead code**: mantido em `workers/extract.py`. Não usar em produção; reabilitar se um dia o pull-history fizer sentido (multi-provider, paid já com data, etc).
- **Custos**: cada relatório ~$0.10-0.25 (Claude Sonnet 4.6). Com 1 user gerando 5 relatórios/mês = ~$1.25/mês. Cabe no budget.

## Estimativa de esforço

| Wave | Esforço |
|---|---|
| 1 (fundação) | ~3h (migration + schemas + state.user_id) |
| 2 [P] (5 tasks) | ~6h paralelizadas (1 dev) ou ~2-3h via sub-agents |
| 3 (worker adapter) | ~3h |
| 4 (generate endpoint) | ~1h |
| 5 [P] (frontend) | ~4h paralelizadas |
| 6 [P] (docs + dead code) | ~1h |
| 7 [P] (5 tests) | ~3-4h paralelizadas |
| Smoke | ~30min |
| **Total** | **~20h ≈ 2-3 dias** com sub-agents, ~4-5 dias sem |
