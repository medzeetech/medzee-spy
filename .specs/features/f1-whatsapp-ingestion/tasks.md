# F1 — WhatsApp Ingestion · Tasks

> Quebra atômica do [design.md](design.md) em 15 tasks. Cada uma vira (idealmente) 1 commit. Tags `[P]` marcam tasks que podem rodar em paralelo via sub-agents.

## Pré-flight (já feito)

- ✓ Branch `feat/f1-whatsapp-ingestion` criada e pushada
- ✓ `.env` (backend + frontend) preenchidos
- ✓ Migration `f1_1_medzee_schema_and_whatsapp_sessions` aplicada no Supabase News
- ✓ Migration `f1_2_harden_set_updated_at_search_path` aplicada (hardening)

## Ordem de entrega (waves)

```
Wave 1 (fundação, sequencial)
  T1 → T2

Wave 2 (camadas independentes — paralelizáveis)
  T3 [P]  T4 [P]  T5 [P]  T6 [P]  T13 [P scaffold]

Wave 3 (orquestração)
  T7 → T8

Wave 4 (endpoints — paralelizáveis após T7)
  T9 [P]  T10 [P]  T11 [P]

Wave 5 (wiring + smoke)
  T12

Wave 6 (testes — paralelizáveis)
  T14 [P]  T15 [P]
```

---

## T1 — Bootstrap (deps + Settings)

**What:** Adicionar dependências de teste/dev (`respx`, `pytest-asyncio`, `anyio`) no `requirements.txt`. Extender `app/core/config.py` com todos os campos novos da F1.

**Where:**
- `backend/requirements.txt`
- `backend/app/core/config.py`

**Depends on:** — (Wave 1)

**Reuses:** padrão existente de `Settings(BaseSettings)`, `env_file=".env"`, `case_sensitive=True`.

**Done when:**
- [ ] `pip install -r requirements.txt` resolve sem erro
- [ ] `Settings` expõe: `API_BASE_URL`, `UAZAPI_BASE_URL`, `UAZAPI_ADMIN_TOKEN`, `LLM_PROVIDER`, `LLM_MODEL`, `ANTHROPIC_API_KEY`, `EXTRACT_DAYS_WINDOW=30`, `EXTRACT_PARALLELISM=5`, `EXTRACT_SOFT_TIMEOUT_S=90`, `EXTRACT_HARD_TIMEOUT_S=120`, `SESSION_TTL_MINUTES=15`, `UAZAPI_HTTP_TIMEOUT_S=8.0`
- [ ] `python -c "from app.core.config import settings; print(settings.UAZAPI_BASE_URL)"` imprime `https://naorpedroza.uazapi.com`
- [ ] Warning logado em startup se `API_BASE_URL` começa com `http://localhost` (webhook da uazapi não vai alcançar)

**Tests:** unit no fim (T14) — `test_config.py` validando defaults.

**Traceability:** infraestrutura para WPP-01..WPP-17.

---

## T2 — Schemas + provider types + errors

**What:** Criar todos os modelos pydantic e dataclasses do design (seções 4.1 e 8). Sem lógica — só shapes.

**Where:**
- `backend/app/clients/whatsapp/__init__.py` (vazio, marker package)
- `backend/app/clients/whatsapp/types.py` (`ProviderSession`, `Chat`, `Message` dataclasses)
- `backend/app/clients/whatsapp/errors.py` (`UazapiError`, `UazapiUnavailable`, `UazapiTimeout`, `UazapiBanned`, `UazapiQrExpired`, `UazapiUnknown`)
- `backend/app/modules/whatsapp/__init__.py` (vazio)
- `backend/app/modules/whatsapp/schemas.py` (`CreateSessionResponse`, `UazapiWebhookPayload`, `ConversationPayload`, `MessagePayload`, `ExtractedPayload`, `SSEEvent` types, `SessionStatus` enum)

**Depends on:** T1

**Reuses:** convenção de pydantic v2 (`BaseModel` + `model_config`), padrão de Enums.

**Done when:**
- [ ] `from app.modules.whatsapp.schemas import CreateSessionResponse, SessionStatus` funciona
- [ ] `ExtractedPayload(message_count=0, conversation_count=0, conversations=[]).model_dump_json()` retorna JSON válido
- [ ] `SessionStatus.PENDING.value == "pending"`
- [ ] Hierarquia de erros: `isinstance(UazapiTimeout(), UazapiError) is True`

**Tests:** smoke em T14.

**Traceability:** WPP-01, WPP-08 (formato do payload), WPP-12 (códigos de erro).

---

## T3 — Uazapi adapter `[P]`

**What:** Implementar `UazapiProvider` em `httpx.AsyncClient` com os 7 métodos do Protocol e parser de erros conforme tabela do design § 4.3.

**Where:**
- `backend/app/clients/whatsapp/uazapi.py`

**Depends on:** T2

**Reuses:** `Settings.UAZAPI_*` (T1), tipos de T2.

**Done when:**
- [ ] Classe `UazapiProvider` implementa `create_session`, `register_webhook`, `refresh_qr`, `get_status`, `list_chats`, `list_messages`, `disconnect`
- [ ] `create_session()` faz 2 calls (`/instance/create` com `admintoken`, `/instance/connect` com `token`) e retorna `ProviderSession(session_token, qr_base64)`
- [ ] Em `httpx.TimeoutException` → levanta `UazapiTimeout`
- [ ] Em 5xx → `UazapiUnavailable`
- [ ] Body com `provider_code: 463` → `UazapiBanned`
- [ ] `__aenter__/__aexit__` corretos (recurso fechado em erro)
- [ ] Timeout default vem de `settings.UAZAPI_HTTP_TIMEOUT_S`

**Tests:** T13 (adapter unit com `respx`).

**Traceability:** WPP-01, WPP-02, WPP-03, WPP-05, WPP-07, WPP-08, WPP-11, WPP-12.

---

## T4 — Provider Protocol + factory + mask helper `[P]`

**What:** Definir o Protocol `WhatsAppProvider` exportado pelo `__init__.py` do package, factory `get_provider()`, e helper `mask_phone(msisdn)`.

**Where:**
- `backend/app/clients/whatsapp/__init__.py` (`Protocol` + `get_provider`)
- `backend/app/modules/whatsapp/mask.py` (`mask_phone(jid_or_msisdn)`)

**Depends on:** T2 (tipos compartilhados)

**Reuses:** padrão de singleton lazy de `app/clients/supabase.py`.

**Done when:**
- [ ] `from app.clients.whatsapp import WhatsAppProvider, get_provider` funciona
- [ ] `get_provider()` retorna instância de `UazapiProvider` (T3)
- [ ] `mask_phone("5511987651234@s.whatsapp.net")` → `"+55 11 9****-1234"`
- [ ] `mask_phone("")` → `""` (defensivo)
- [ ] `mask_phone("invalid")` → `"+** ** *****-****"` (placeholder seguro)

**Tests:** T14 inclui casos de `mask_phone`.

**Traceability:** WPP-06.

---

## T5 — Repository `[P]`

**What:** CRUD da `medzee.whatsapp_sessions` via Supabase admin client. Função pura, sem regra de negócio.

**Where:**
- `backend/app/modules/whatsapp/repository.py`

**Depends on:** T2 (`SessionStatus`)

**Reuses:** `get_supabase_admin_client()` de `app/clients/supabase.py`.

**Done when:**
- [ ] `create(id, uazapi_token, status='pending') -> None`
- [ ] `mark_status(id, status, **extra)` (aceita `phone_masked`, `message_count`, `extracted_at`, `failed_code`)
- [ ] `mark_extracted(id, message_count)`
- [ ] `mark_failed(id, code)`
- [ ] `mark_consumed(id)`
- [ ] `link_user(id, user_id)` (será chamada por F2, mas deixar pronto)
- [ ] `get(id) -> dict | None` (para fallbacks)
- [ ] Todas as funções usam `schema('medzee').table('whatsapp_sessions')`
- [ ] Logs estruturados em cada operação: `{"op": "...", "session_id": "..."}` — **sem** logar token/conteúdo

**Tests:** T14 (mockar supabase client).

**Traceability:** WPP-03 (persistência inicial), WPP-09 (mark_extracted), WPP-11 (mark_consumed), WPP-12 (mark_failed).

---

## T6 — SessionStore + TTL expire loop `[P]`

**What:** State manager in-memory com pub/sub por sessão (replay-last) + loop de expiração TTL.

**Where:**
- `backend/app/modules/whatsapp/state.py`

**Depends on:** T2 (`SessionStatus`, `SSEEvent`)

**Reuses:** —

**Done when:**
- [ ] Classe `SessionState` (dataclass) com campos do design § 5.1
- [ ] Classe `SessionStore`:
  - `create(session_id, uazapi_token, qr_base64) -> SessionState`
  - `get(session_id) -> SessionState | None`
  - `update(session_id, **fields)` atomicamente (lock)
  - `publish(session_id, event)` escreve em `last_event` + faz broadcast pras queues de subscribers
  - `subscribe(session_id) -> AsyncIterator[SSEEvent]` (yield replay-last + novos eventos; fecha em terminal)
  - `consume(session_id) -> ExtractedPayload | None`
  - `set_payload(session_id, payload)`
- [ ] `start_expire_loop()` agendado no `lifespan` (T12); a cada 60s percorre sessões; se `age > SESSION_TTL_MINUTES` E status não-terminal → tenta `provider.disconnect`, publica `expired`, marca status `expired`
- [ ] Singleton exportado (`session_store = SessionStore()`)
- [ ] Locking adequado (`asyncio.Lock`) em `create`/`update`/`publish`

**Tests:** T14 (multi-subscriber, replay-last, TTL expire).

**Traceability:** WPP-04, WPP-14, WPP-15, EC-05.

---

## T7 — Service layer

**What:** Orquestrador que junta provider + repository + store. Single entry point chamado pelas routes.

**Where:**
- `backend/app/modules/whatsapp/service.py`

**Depends on:** T3, T4, T5, T6

**Reuses:** —

**Done when:**
- [ ] `class WhatsAppService` com construtor recebendo `provider, store, repository`
- [ ] `async create_session(client_ip)` → faz fluxo completo do design § 7.1: provider.create_session → register_webhook → repository.create → store.create → retorna `CreateSessionResponse`
- [ ] `async handle_webhook_event(session_id, payload: UazapiWebhookPayload)` → se `connection`+`loggedIn` → update status + publish `connected` + schedule extract task
- [ ] `async cancel_session(session_id)` → provider.disconnect best-effort + publish `expired (cancelled)`
- [ ] `async consume_extracted(session_id, user_id) -> ExtractedPayload | None` (entry-point pra F2): link_user + mark_consumed + provider.disconnect best-effort + retorna payload do cache
- [ ] Rate-limit por IP: `dict[ip, list[timestamp]]` em memória, TTL 5min; > 3 sessões em 5min → `RateLimitExceeded`
- [ ] Logs estruturados em cada método (op, session_id, elapsed_ms; sem secrets)

**Tests:** T14.

**Traceability:** WPP-01, WPP-03, WPP-06, WPP-11, WPP-12, WPP-16.

---

## T8 — Worker: extract pipeline

**What:** Implementar `extract_30d_pipeline(session_id)` exatamente como descrito no design § 6 — paginação `chat/find` → paralelo `message/find` com semáforo, corte por timestamp, progress events.

**Where:**
- `backend/app/workers/__init__.py` (vazio, já existe)
- `backend/app/workers/extract.py`

**Depends on:** T4 (provider), T5 (repo), T6 (store), T7 (service para `_fail`/`_finalize_partial`)

**Reuses:** —

**Done when:**
- [ ] Função `async extract_30d_pipeline(session_id: UUID)`:
  - Lê estado, valida `status == CONNECTED`
  - Update store/repo para `EXTRACTING`
  - `asyncio.timeout(EXTRACT_HARD_TIMEOUT_S)` envolvendo todo o pipeline
  - Itera `provider.list_chats` paginado (limit=100)
  - `asyncio.Semaphore(EXTRACT_PARALLELISM)` envolvendo cada chat
  - Para cada chat: `provider.list_messages` paginado, filtrar `m.type == "text" and m.text`, parar quando `ts < cutoff` OR `not has_more`
  - Progress event a cada 5 chats coletados (`extracting` com `collected`/`total_chats`)
  - Drop conversations vazias
  - Monta `ExtractedPayload`, salva via `store.set_payload`, `repo.mark_extracted`, `store.publish(extracted)`
- [ ] Tratamento de erros mapeando para SSE `failed` com `code` correto (timeout, banned, uazapi_unavailable, extract_failed)
- [ ] Em `asyncio.TimeoutError` (hard timeout) → finaliza com `partial=true` e ainda emite `extracted`
- [ ] **Nenhum** `log.info(message.text)` ou similar — só counts/elapsed

**Tests:** T14 (caminhos felizes, banned, timeout, clínica vazia).

**Traceability:** WPP-07, WPP-08, WPP-09, WPP-10, EC-02, EC-03, EC-04.

---

## T9 — Route `POST /api/whatsapp/sessions` `[P]`

**What:** Endpoint que recebe a request do frontend e chama `service.create_session`.

**Where:**
- `backend/app/modules/whatsapp/routes.py` (parcial — adiciona o POST /sessions)

**Depends on:** T7

**Reuses:** `SuccessResponse[T]` de `app/contracts/responses.py`.

**Done when:**
- [ ] `POST /sessions` retorna `200 SuccessResponse[CreateSessionResponse]` no happy path
- [ ] `503` com `{detail: "uazapi_unavailable"}` quando service levanta `UazapiUnavailable`/`UazapiTimeout`
- [ ] `429` com `{detail: "too_many_sessions"}` quando rate limit
- [ ] Captura `request.client.host` para o rate-limit
- [ ] OpenAPI bonito: `response_model`, `tags=["whatsapp"]`, summary curto

**Tests:** T15.

**Traceability:** WPP-01, WPP-02, WPP-16.

---

## T10 — Route `GET /api/whatsapp/sessions/:id/events` (SSE) `[P]`

**What:** Endpoint SSE com `StreamingResponse` que faz subscribe na store e empurra eventos.

**Where:**
- `backend/app/modules/whatsapp/routes.py` (adiciona o GET events)

**Depends on:** T6, T7

**Reuses:** `StreamingResponse` do Starlette.

**Done when:**
- [ ] `GET /sessions/:id/events` retorna `text/event-stream`
- [ ] `404` se sessão não existe
- [ ] Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`
- [ ] Formato wire: `event: <name>\ndata: <json>\n\n`
- [ ] Replay-last: primeiro evento empurrado é `last_event` se existir
- [ ] Fecha em terminal (`extracted`, `failed`, `expired`)
- [ ] Cliente desconectando cancela o generator (try/finally no `store.subscribe`)

**Tests:** T15 (com `httpx.AsyncClient(ASGITransport)`).

**Traceability:** WPP-04, WPP-05, WPP-14, WPP-15.

---

## T11 — Route `POST /api/whatsapp/webhook` + `DELETE /api/whatsapp/sessions/:id` `[P]`

**What:** Callback da uazapi + endpoint de cancelamento.

**Where:**
- `backend/app/modules/whatsapp/routes.py` (adiciona webhook + DELETE)

**Depends on:** T7, T8

**Reuses:** `BackgroundTasks` do FastAPI.

**Done when:**
- [ ] `POST /webhook?session_id=<uuid>` recebe `UazapiWebhookPayload`, retorna `200 {status: ok}` sempre em ≤ 5s
- [ ] Sessão desconhecida → ignora com `200 {status: ignored}` (não vaza 404)
- [ ] Em `connection.loggedIn=true` → schedule `extract_30d_pipeline` via `BackgroundTasks`
- [ ] `DELETE /sessions/:id` chama `service.cancel_session` + retorna `{status: cancelled}`
- [ ] `DELETE` em sessão já terminal → `{status: already_terminal}`
- [ ] Webhook **não** loga payload bruto (privacidade)

**Tests:** T15.

**Traceability:** WPP-06, WPP-07, WPP-12, EC-06.

---

## T12 — Router registration + lifespan wiring + smoke test

**What:** Plugar tudo no `main.py` e `api/router.py`. Validar que o servidor sobe e o health-check responde.

**Where:**
- `backend/app/main.py` (lifespan startup → `session_store.start_expire_loop()`; shutdown → cancela task)
- `backend/app/api/router.py` (`include_router(whatsapp_router, prefix="/whatsapp", tags=["whatsapp"])`)

**Depends on:** T9, T10, T11

**Reuses:** padrão existente do `lifespan` em `main.py`.

**Done when:**
- [ ] `uvicorn app.main:app --reload` sobe sem erro
- [ ] `GET /health` → `200 {"status": "ok"}`
- [ ] `GET /docs` mostra a tag `whatsapp` com 4 endpoints
- [ ] Em `Ctrl+C` o shutdown cancela o expire loop sem warnings
- [ ] Logs do startup mostram `[expire_loop] started` (se DEBUG=true)

**Tests:** T15 inclui smoke do `/health` e `/docs`.

**Traceability:** infraestrutura.

---

## T13 — Test scaffold + adapter tests `[P]`

**What:** Setup do test suite + cobertura completa do `UazapiProvider`.

**Where:**
- `backend/app/tests/whatsapp/__init__.py`
- `backend/app/tests/whatsapp/conftest.py` (fixtures: `client`, `mock_uazapi` via `respx`, `fresh_store`, `fake_admin_supabase`)
- `backend/app/tests/whatsapp/test_uazapi_adapter.py`
- `backend/pyproject.toml` ou `backend/pytest.ini` se precisar configurar `asyncio_mode = "auto"`

**Depends on:** T1 (deps), T3 (adapter para testar)

**Reuses:** `pytest`, `TestClient`, fixture existente `client` (mover para o conftest novo).

**Done when:**
- [ ] `pytest backend/app/tests/whatsapp/test_uazapi_adapter.py -q` passa
- [ ] Casos: happy path create_session (2 chamadas), parser de 5xx → UazapiUnavailable, parser de timeout → UazapiTimeout, parser de provider_code 463 → UazapiBanned, list_messages com `hasMore=false`, headers `token` vs `admintoken` corretos

**Tests:** este é o test.

**Traceability:** valida WPP-01, WPP-02, WPP-12.

---

## T14 — Tests: state + repository + service + worker `[P]`

**What:** Cobertura unit das camadas de orquestração.

**Where:**
- `backend/app/tests/whatsapp/test_state.py`
- `backend/app/tests/whatsapp/test_repository.py`
- `backend/app/tests/whatsapp/test_service.py`
- `backend/app/tests/whatsapp/test_extract.py`

**Depends on:** T6, T5, T7, T8

**Reuses:** fixtures do T13.

**Done when:**
- [ ] `test_state.py`: criar → publicar → subscribe (replay-last terminal fecha), multi-subscriber broadcast, TTL expire move pra `expired` + dispara provider.disconnect mockado
- [ ] `test_repository.py`: cada método chama supabase com os args certos (mockar `get_supabase_admin_client`)
- [ ] `test_service.py`: `create_session` happy + 503; rate-limit > 3 em 5min → 429; `handle_webhook_event` em loggedIn=true agenda task
- [ ] `test_extract.py`: corte por timestamp 30d (gera msgs com ts variados, conferir só os <30d entram); filtro `type=='text'`; hard timeout produz `partial=true`; clínica vazia → `extracted` com count=0; banned 463 → publish failed `banned`
- [ ] `test_mask.py`: helper `mask_phone` casos do design

**Tests:** este é o test.

**Traceability:** valida WPP-04, WPP-06, WPP-07-WPP-12, EC-02, EC-03, EC-04, EC-05.

---

## T15 — Tests: routes integration `[P]`

**What:** Smoke + integration das 4 rotas (POST/GET-SSE/POST-webhook/DELETE) via `httpx.AsyncClient(ASGITransport)`.

**Where:**
- `backend/app/tests/whatsapp/test_routes.py`

**Depends on:** T12

**Reuses:** fixtures do T13.

**Done when:**
- [ ] `POST /sessions` happy → 200 com QR no payload + cria row na store/repo (mockados)
- [ ] `POST /sessions` quando uazapi 5xx → 503
- [ ] `GET /sessions/:id/events` retorna SSE → parser dos 2 primeiros eventos chega corretamente
- [ ] `GET /sessions/:id/events` em sessão inexistente → 404
- [ ] `POST /webhook` event=connection loggedIn=true → publica `connected` + agenda extract (verificar via mock)
- [ ] `DELETE /sessions/:id` → cancela + retorna `cancelled`
- [ ] `GET /health` ainda funciona (não regredimos)

**Tests:** este é o test.

**Traceability:** valida WPP-01, WPP-02, WPP-04, WPP-06, EC-06.

---

## Cobertura final por requisito

| WPP | Onde é entregue | Onde é testado |
|---|---|---|
| WPP-01 | T7, T9 | T13, T15 |
| WPP-02 | T7, T9 | T13, T15 |
| WPP-03 | T5, T7 | T14 |
| WPP-04 | T6, T10 | T14, T15 |
| WPP-05 | T3, T10 | T13 |
| WPP-06 | T4, T7, T10 | T14, T15 |
| WPP-07 | T7, T8, T11 | T14, T15 |
| WPP-08 | T2, T8 | T14 |
| WPP-09 | T5, T6, T8 | T14 |
| WPP-10 | T5, T8 (code review) | T14 (asserts em logs) |
| WPP-11 | T5, T7 | T14 |
| WPP-12 | T3, T7, T8 | T13, T14 |
| WPP-13 | N/A | — |
| WPP-14 | T6, T10 | T14, T15 |
| WPP-15 | T6, T10 | T14 |
| WPP-16 | T7, T9 | T14 |
| WPP-17 | (P3 — pulado em M1) | — |

## Notas operacionais

- **Sub-agents:** Wave 2 e Wave 6 são candidatos óbvios. Cada task `[P]` recebe seu próprio sub-agent com: a task em si (this file recortada), [coding-principles do projeto](.specs/codebase/CONVENTIONS.md), o trecho relevante de [design.md](design.md), e [TESTING.md](.specs/codebase/TESTING.md).
- **Túnel pra webhook em dev:** quando chegarmos no T12, abrir `cloudflared tunnel --url http://localhost:8000`, copiar URL pública para `API_BASE_URL` no `.env`, reiniciar. Documentar no README final (entra na F5).
- **Smoke manual antes de T13+T14+T15:** em T12, com o servidor de pé e túnel ativo, fazer 1 `curl POST /api/whatsapp/sessions`, escanear o QR de verdade, ver os eventos SSE chegando. Vale 1000 testes unitários — confirma que a uazapi se comporta como o adapter espera. Documentar achados em STATE.md (lições).
