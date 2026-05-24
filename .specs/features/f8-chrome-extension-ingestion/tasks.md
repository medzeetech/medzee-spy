# F8 — Chrome Extension Ingestion · Tasks

**Design:** [`design.md`](./design.md)
**Spec:** [`spec.md`](./spec.md)
**Status:** Draft

Pipeline atômico, 27 tasks em 6 waves. Sub-agents executam tasks `[P]` em paralelo via `Agent` tool (Explore/general-purpose conforme nature).

---

## Execution Plan (visual)

```
Wave 1 ─ DB foundation (sequential)
    T1 (migration apply via Supabase MCP)

Wave 2 ─ Backend core (mostly parallel)
    T1 done, then:
        ├── T2 [P]   config + errors
        ├── T3 [P]   extension adapter
        ├── T4 [P]   extension module skeleton (schemas + security + repository)
        ├── T5 [P]   captured_messages.schemas.source field
        └── T6       auth.service extension token + /me endpoint  (sequential — touches shared AuthService)

Wave 3 ─ Extension endpoints (sequential after Wave 2)
    T7  service.py (pair, ingest, telemetry, mobile_lead)
    T8  routes.py (5 endpoints) + integration tests
    T9  router wiring + 410 Gone + integration tests

Wave 4 ─ Chrome Extension (after Wave 3 wire shape locked)
    T10 scaffold (package.json, manifest, vite config, build-icons)
    Then parallel:
        ├── T11 [P] lib/* (storage, api-client, chunker, types)
        ├── T12 [P] content-scripts/probe.ts
        └── T16 [P] popup/*
    Sequential after T11+T12:
        T13 service-worker.ts
        T14 page-world/wa-collector.ts
        T15 content-scripts/collector.ts (depends on T14)

Wave 5 ─ Frontend pivot (parallel with Wave 4, after Wave 2 done)
    Parallel:
        ├── T17 [P] lib/device.js
        ├── T18 [P] lib/extension.js
        ├── T19 [P] MobileBlockScreen.jsx
        └── T20 [P] ExtensionInstallScreen.jsx
    Sequential:
        T21 SpyFlowScreen.jsx (state machine)
        T22 App.jsx wiring (depends on T21)
        T23 lib/auth.js + LeadFormScreen.jsx (token consume)
        T24 GeneratingScreen.jsx (extension events)

Wave 6 ─ Smoke + Web Store + docs
    T25 Manual smoke E2E (side-load + report ponta-a-ponta)
    T26 Docs: README + STATE D11✅ + ROADMAP F8✅
    T27 Web Store listing draft + privacy policy markdown
```

---

## Wave 1 — DB Foundation

### T1 — Apply migration `f8_1_extension_support`

**What:** Aplicar migration que adiciona suporte completo da extensão (2 ALTERs + 3 tabelas novas).
**Where:** Migration via Supabase MCP → schema `medzee_spy`.
**Depends on:** None.
**Reuses:** Padrão de migrations F4 (`f4_1_captured_messages`) — RLS owner-only, GRANTs pros 4 roles (L1).
**Requirement:** Substrato pra CHX-01 a CHX-17 (todos dependem).

**Tools:**
- MCP: `mcp__supabase__apply_migration` (ou `mcp__supabase__execute_sql` pra validação)
- Skill: NONE

**Done when:**
- [ ] Migration `f8_1_extension_support` aplicada com sucesso
- [ ] `list_tables(schemas=['medzee_spy'])` confirma: `captured_messages.source` existe, `whatsapp_sessions.provider` existe + `uazapi_token` nullable, tabelas `extension_installs`, `mobile_redirect_leads`, `extension_telemetry` existem
- [ ] Smoke SQL: `SELECT count(*) FROM medzee_spy.whatsapp_sessions WHERE provider='uazapi'` retorna 6 (backfill via DEFAULT)
- [ ] Smoke SQL: `INSERT` direto em `mobile_redirect_leads` como `anon` funciona (GRANT correto)
- [ ] Smoke SQL: `INSERT` em `extension_installs` sem ser owner → RLS bloqueia (403/0 rows)

**Tests:** integration (via SQL smoke acima)
**Gate:** N/A (DB migration, validação por query)

**Verify:**
```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema='medzee_spy' AND table_name IN ('captured_messages','whatsapp_sessions')
ORDER BY table_name, ordinal_position;

SELECT table_name FROM information_schema.tables WHERE table_schema='medzee_spy';
```

**Commit:** `:hammer: db(F8-1): migration f8_1_extension_support (provider/source + 3 tabelas)`

---

## Wave 2 — Backend core

### T2 — Add `WHATSAPP_PROVIDER` setting + `ProviderNotApplicable` exception [P]

**What:** Feature flag + nova exception pro Strategy pattern.
**Where:**
- `backend/app/core/config.py` (add `WHATSAPP_PROVIDER: Literal['extension','uazapi'] = 'extension'`)
- `backend/app/clients/whatsapp/errors.py` (add `class ProviderNotApplicable(Exception)`)

**Depends on:** T1.
**Reuses:** `pydantic-settings` pattern já existente em `config.py`.
**Requirement:** CHX-13.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `Settings.WHATSAPP_PROVIDER` lê da env `WHATSAPP_PROVIDER` (default `extension`)
- [ ] `ProviderNotApplicable` exportada em `app.clients.whatsapp.errors`
- [ ] `pytest -q` passa (sem regressão; nenhum teste novo aqui — só infra)

**Tests:** unit (cobre via T3/T9)
**Gate:** quick (`cd backend && pytest -q`)

**Commit:** `:sparkles: feat(F8-2): WHATSAPP_PROVIDER flag + ProviderNotApplicable exception`

---

### T3 — Create `app/clients/whatsapp/extension.py` adapter + update factory [P]

**What:** Adapter Strategy pra provider `extension` (no-op pra most operations) + factory `get_provider()` dispatch.
**Where:**
- `backend/app/clients/whatsapp/extension.py` (novo, ~60 linhas)
- `backend/app/clients/whatsapp/__init__.py` (modify `get_provider()`)
- `backend/app/tests/clients/test_whatsapp_provider_factory.py` (novo)

**Depends on:** T2.
**Reuses:** `WhatsAppProvider` Protocol existente, `ProviderSession`/`Chat`/`Message` types.
**Requirement:** CHX-13.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `ExtensionProvider` implementa Protocol: métodos uazapi-specific raise `ProviderNotApplicable`, `get_status()` retorna `{"provider":"extension"}`
- [ ] `get_provider()` lê `settings.WHATSAPP_PROVIDER` e retorna instância correta
- [ ] Testes: `WHATSAPP_PROVIDER=extension` → `get_provider()` retorna `ExtensionProvider`; `=uazapi` → `UazapiProvider`
- [ ] `pytest -q` passa (suite total + 3 testes novos)

**Tests:** unit (testes pra factory + adapter)
**Gate:** quick

**Commit:** `:sparkles: feat(F8-3): ExtensionProvider adapter + factory dispatch`

---

### T4 — Create `app/modules/extension/` skeleton (schemas + security + repository) [P]

**What:** Módulo backend novo com 3 arquivos sem lógica de negócio ainda — só shape + auth + DB CRUD.
**Where:**
- `backend/app/modules/extension/__init__.py`
- `backend/app/modules/extension/schemas.py` (~120 linhas: `ExtensionMessageBatch`, `ExtensionMessage`, `ExtensionPairRequest`, `ExtensionPairResponse`, `ExtensionStatusResponse`, `ExtensionTelemetryEvent`, `ExtensionPairingTokenResponse`, `MobileRedirectLeadCreate`)
- `backend/app/modules/extension/security.py` (~40 linhas: `get_current_extension_user` JWT validator com `typ=extension_refresh`; `issue_refresh_token`; `decode_pairing_token`)
- `backend/app/modules/extension/repository.py` (~150 linhas: `upsert_install`, `get_install`, `get_or_create_extension_session`, `insert_telemetry`, `insert_mobile_lead`)
- `backend/app/tests/extension/test_schemas.py` + `test_security.py`

**Depends on:** T1, T2.
**Reuses:**
- `app.clients.supabase.get_supabase_admin_client` (pattern repository)
- `app.core.security` (JWT decode pattern do `get_current_user_id`)
- Convenção `_table()` lambda do `captured_messages.repository`

**Requirement:** CHX-01, CHX-02, CHX-04, CHX-08, CHX-15, CHX-16.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] Todos os Pydantic models validam exemplos do design (round-trip JSON)
- [ ] `ExtensionTelemetryEvent` rejeita campo extra `text`/`contact_name`/`wa_chatid` (Pydantic `model_config = {"extra":"forbid"}`)
- [ ] `decode_pairing_token` valida `typ=='extension_pairing'`; expiração; HS256
- [ ] `issue_refresh_token` emite JWT com `typ='extension_refresh'`, exp=+30d
- [ ] Repository functions: insert/select sem exception em smoke local
- [ ] `pytest -q` passa (suite + ~12 testes novos: 7 schemas + 5 security)

**Tests:** unit (schemas + security); repository testado via service em T7.
**Gate:** quick

**Commit:** `:sparkles: feat(F8-4): app/modules/extension skeleton (schemas + security + repo)`

---

### T5 — Add `source` field handling em `captured_messages.schemas` [P]

**What:** Atualizar `CapturedMessageInsert` + `CapturedMessage` pra incluir campo `source: Literal['webhook','extension']`.
**Where:**
- `backend/app/modules/captured_messages/schemas.py` (modify)
- `backend/app/modules/captured_messages/repository.py::_serialize` (modify pra incluir source)
- `backend/app/tests/captured_messages/test_schemas.py` (modify se existir; senão criar)

**Depends on:** T1.
**Reuses:** Schema existente F4 — só adiciona campo.
**Requirement:** CHX-04, CHX-05.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `CapturedMessageInsert.source: Literal['webhook','extension'] = 'webhook'` (default mantém compat)
- [ ] `_serialize()` propaga `source` no dict
- [ ] Repository `query_window_for_user` / `query_last_n_per_chat` continuam funcionando (source é informativo, não filtra)
- [ ] `pytest -q` passa (sem regressão F4/F5)

**Tests:** unit
**Gate:** quick

**Commit:** `:sparkles: feat(F8-5): captured_messages aceita source='extension'`

---

### T6 — Extend `AuthService.signup` + new `/api/auth/me/extension-pairing-token` endpoint

**What:** Após criar user, emite `extension_pairing_token` JWT 15min; novo endpoint idempotente pra re-emissão quando token expira.
**Where:**
- `backend/app/modules/auth/service.py` (modify: novo método `_issue_pairing_token`, chamado em `signup`)
- `backend/app/modules/auth/schemas.py` (modify: `AuthSignupResponse.extension_pairing_token: str`)
- `backend/app/modules/auth/routes.py` (modify: novo `POST /me/extension-pairing-token`)
- `backend/app/tests/auth/test_signup.py` (modify: assert token presente no response)
- `backend/app/tests/auth/test_me_extension_pairing_token.py` (novo)

**Depends on:** T4 (precisa de `extension.security.issue_pairing_token` ou inline aqui).
**Reuses:** `AuthService.signup` flow F2 existente; `get_current_user_id` security.
**Requirement:** CHX-01, CHX-15.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] Signup response inclui `extension_pairing_token` válido (claims sub=user_id, typ=extension_pairing, exp=+15min)
- [ ] `POST /api/auth/me/extension-pairing-token` retorna 200 + novo token quando user autenticado
- [ ] Endpoint retorna 401 sem auth header
- [ ] Token emitido é decodificável pelo `decode_pairing_token` (T4)
- [ ] Idempotente: chamar 3x retorna 3 tokens distintos (iat diferentes), todos válidos
- [ ] `pytest -q` passa (suite total + ~5 testes novos)

**Tests:** integration (route) + unit (service method)
**Gate:** full (`cd backend && pytest -q` deve ter zero regressão)

**Commit:** `:sparkles: feat(F8-6): signup emite extension_pairing_token + endpoint de re-emissão`

---

## Wave 3 — Extension routes + service

### T7 — `app/modules/extension/service.py` (pair, ingest_batch, telemetry, mobile_lead)

**What:** Lógica de negócio do módulo extension.
**Where:**
- `backend/app/modules/extension/service.py` (~200 linhas)
- `backend/app/tests/extension/test_service.py` (~15 testes)

**Depends on:** T4, T5, T6.
**Reuses:**
- `captured_messages.repository.insert_many` (com source='extension' — reaproveita L11 fix)
- `reports.service.trigger_generate(user_id, mode='last_n_per_chat')`
- `extension.security.issue_refresh_token` / `decode_pairing_token`

**Requirement:** CHX-01, CHX-04, CHX-05, CHX-08, CHX-16.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `pair_extension(pairing_token, install_id) -> ExtensionPairResponse` valida JWT, persiste install, retorna refresh_token
- [ ] `ingest_batch(user_id, batch) -> dict` mapeia ExtensionMessage→CapturedMessageInsert (source='extension'), garante session row, chama insert_many; quando `batch_index == total_batches-1`, dispara worker F3
- [ ] `record_telemetry(user_id, event)` aplica rate-limit em-memória 60/min/user; persiste em `extension_telemetry`; rejeita events com PII (validação Pydantic já em T4)
- [ ] `capture_mobile_lead(email, ua, source_url)` insere em `mobile_redirect_leads`, sem auth
- [ ] `get_status(user_id) -> ExtensionStatusResponse` agrega contagens
- [ ] Testes mockam Supabase client; assert chamadas e shape
- [ ] `pytest -q` passa (+15 testes)

**Tests:** unit (service)
**Gate:** quick

**Commit:** `:sparkles: feat(F8-7): ExtensionService (pair, ingest, telemetry, mobile_lead)`

---

### T8 — `app/modules/extension/routes.py` (5 endpoints) + integration tests

**What:** Endpoints HTTP pro módulo extension.
**Where:**
- `backend/app/modules/extension/routes.py` (~150 linhas)
- `backend/app/tests/extension/test_routes.py` (~15 testes integration)

**Depends on:** T7.
**Reuses:**
- FastAPI `APIRouter` pattern
- `SuccessResponse`/`ErrorResponse` contracts (`app.contracts`)
- `get_current_extension_user` (T4) pra `/messages`, `/status`, `/telemetry`
- `get_current_user_id` (existing) pra `/mobile-lead` opcional auth

**Requirement:** CHX-01, CHX-04, CHX-05, CHX-07, CHX-08, CHX-11, CHX-14, CHX-16.

**Endpoints:**
- `POST /api/extension/pair` (body: ExtensionPairRequest, no auth)
- `POST /api/extension/messages` (body: ExtensionMessageBatch, auth: refresh_token, 202 Accepted)
- `GET /api/extension/status` (auth: user JWT, retorna ExtensionStatusResponse)
- `POST /api/extension/telemetry` (body: ExtensionTelemetryEvent, auth: refresh_token, rate-limit 60/min)
- `POST /api/extension/mobile-lead` (body: MobileRedirectLeadCreate, no auth, ANON inserts)

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] Todos 5 endpoints respondem com shapes corretas pro caminho feliz
- [ ] `POST /messages` retorna 401 com `code='pairing_expired'` quando refresh_token inválido
- [ ] `POST /messages` retorna 409 com `code='extension_outdated'` quando `X-Extension-Version < min` (CHX-14)
- [ ] `POST /telemetry` retorna 422 quando payload tem campo PII (`text`, `wa_chatid`)
- [ ] `POST /telemetry` retorna 429 após 60 chamadas em 60s do mesmo user
- [ ] Teste e2e mock: signup → /pair → /messages (3 batches) → /reports/latest com status=completed
- [ ] `pytest -q` passa (+15 testes integration)

**Tests:** integration
**Gate:** full

**Commit:** `:sparkles: feat(F8-8): /api/extension/* endpoints (pair, messages, status, telemetry, mobile-lead)`

---

### T9 — Router wire-up + 410 Gone para uazapi quando `WHATSAPP_PROVIDER=extension`

**What:** Inclui extension router; uazapi routes ficam atrás da flag.
**Where:**
- `backend/app/api/router.py` (modify: add `extension_router`)
- `backend/app/modules/whatsapp/routes.py` (modify: gate behind flag; quando `=extension`, retorna 410 Gone com `{code:'provider_disabled', use:'/api/extension/*'}`)
- `backend/app/tests/whatsapp/test_provider_flag.py` (novo, ~5 testes)

**Depends on:** T8.
**Reuses:** `settings.WHATSAPP_PROVIDER` (T2); router pattern existing.
**Requirement:** CHX-13.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `WHATSAPP_PROVIDER=uazapi` → `/api/whatsapp/sessions` continua 200 (compat M1)
- [ ] `WHATSAPP_PROVIDER=extension` → `/api/whatsapp/sessions` retorna 410 Gone com body correto
- [ ] `/api/extension/*` funcionam em ambos modos (não dependem da flag)
- [ ] Test: flip env vars e re-instanciar settings (`@pytest.fixture(autouse=False)`)
- [ ] `pytest -q` passa (+5 testes)

**Tests:** integration
**Gate:** full

**Commit:** `:sparkles: feat(F8-9): provider flag dispatch + 410 Gone em uazapi routes`

---

## Wave 4 — Chrome Extension (após Wave 3 wire shape locked)

### T10 — Extension scaffold (manifest, vite, package.json, build-icons)

**What:** Estrutura inicial da extensão MV3 com tooling.
**Where:**
- `extension/package.json` (deps: typescript, vite, @crxjs/vite-plugin OR vite-plugin-web-extension, @wppconnect/wa-js, sharp)
- `extension/vite.config.ts`
- `extension/tsconfig.json`
- `extension/manifest.json` (MV3, conforme design §4.10)
- `extension/scripts/build-icons.mjs` (sharp: `logo-medzee-spy.svg` → `public/icons/icon-{16,48,128}.png`)
- `extension/.gitignore`
- `extension/README.md` (build, side-load instructions, Web Store sumbission notes)

**Depends on:** T8 (precisa wire shape backend pra mock client).
**Reuses:** `frontend/src/assets/logo-medzee-spy.svg` (source pros ícones).
**Requirement:** CHX-17.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `cd extension && npm install` completa sem erro
- [ ] `cd extension && npm run build:icons` gera 3 PNGs em `extension/public/icons/`
- [ ] `cd extension && npm run build` gera `dist/` com `manifest.json` + JS placeholders
- [ ] `chrome://extensions` Load unpacked aponta pra `extension/dist/` — sem erro de manifest
- [ ] Ícone aparece na barra do Chrome

**Tests:** manual + smoke (build success)
**Gate:** build (`cd extension && npm run build`)

**Commit:** `:tada: feat(F8-10): scaffold da Chrome extension MV3 (manifest + vite + sharp icons)`

---

### T11 — `extension/src/lib/*` (storage, api-client, chunker, messages types) [P]

**What:** Utilitários compartilhados sem dep de UI ou Chrome runtime.
**Where:**
- `extension/src/lib/storage.ts` (wrapper `chrome.storage.local` get/set/remove + types)
- `extension/src/lib/api-client.ts` (fetch wrapper com refresh_token + retry exponencial + 409/401 handling)
- `extension/src/lib/chunker.ts` (batcher 1000 msgs, gera batch_id v4)
- `extension/src/lib/messages.ts` (TypeScript types compartilhados frontend ↔ ext: `MedzeeMsg`, `ExtensionMessage`, `ExtensionEvent`)

**Depends on:** T10.
**Reuses:** `crypto.randomUUID()` para batch_id; tipos do backend espelhados (manualmente sync).
**Requirement:** CHX-04, CHX-14, CHX-16.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `tsc --noEmit` passa sem erro
- [ ] Cada arquivo é importável em isolamento (`import from '@/lib/storage'`)
- [ ] `chunker.split(messages, 1000)` retorna lista de batches com `batch_index`/`total_batches` corretos
- [ ] `api-client` faz retry 1s/3s/9s em 500/503; abort em 401 quando refresh_token inválido

**Tests:** unit (opcional, smoke via service worker em T13)
**Gate:** build

**Commit:** `:sparkles: feat(F8-11): extension/lib (storage, api-client, chunker, types)`

---

### T12 — `extension/src/content-scripts/probe.ts` [P]

**What:** Content script no domínio medzee — bridge entre frontend e service worker.
**Where:** `extension/src/content-scripts/probe.ts`

**Depends on:** T10, T11.
**Reuses:** `chrome.runtime.sendMessage`; `window.postMessage` cross-context.
**Requirement:** CHX-09, CHX-10.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] Escuta `window.postMessage({type:'medzee:probe'})` e responde `{type:'medzee:installed', paired, version}`
- [ ] Recebe `{type:'medzee:cmd', cmd}` e forwarda pra service worker via `chrome.runtime.sendMessage`
- [ ] Auto-pair quando `window.medzee_spy.pairing_token` presente
- [ ] Build (`npm run build`) gera `dist/probe.js` carregável

**Tests:** manual (validado em T25 smoke)
**Gate:** build

**Commit:** `:sparkles: feat(F8-12): probe content script (medzee ↔ extension bridge)`

---

### T13 — `extension/src/service-worker.ts` (pair, batch, HTTP, telemetry)

**What:** Background MV3 — orquestra pairing, coleta, batching, telemetry HTTP.
**Where:** `extension/src/service-worker.ts` (~200 linhas)

**Depends on:** T11, T12.
**Reuses:** `lib/storage`, `lib/api-client`, `lib/chunker`.
**Requirement:** CHX-01, CHX-02, CHX-04, CHX-09, CHX-15, CHX-16.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `chrome.runtime.onMessage` handlers: `medzee:get_state`, `medzee:pair`, `medzee:start`, `medzee:batch`, `medzee:telemetry`, `medzee:abort`
- [ ] Pair flow: recebe pairing_token → POST /api/extension/pair → guarda refresh_token + install_id em `chrome.storage.local`
- [ ] Start flow: abre/foca aba `web.whatsapp.com` (`chrome.tabs.create/update`)
- [ ] Batch flow: recebe batch do collector → POST /api/extension/messages com X-Extension-Version → retry exponencial
- [ ] Quando 401 `pairing_expired`: posta `medzee:event {event:'pairing_failed'}` → frontend re-emite pairing_token
- [ ] Quando 409 `extension_outdated`: posta `medzee:event {event:'extension_outdated'}`
- [ ] Telemetry emit ao receber `wa_needs_login`, `collect_failed`, etc.
- [ ] Build passa

**Tests:** manual (smoke em T25)
**Gate:** build

**Commit:** `:sparkles: feat(F8-13): service worker (pair + batch + telemetry)`

---

### T14 — `extension/src/page-world/wa-collector.ts` (wa-js integration)

**What:** Script que roda no page-world do `web.whatsapp.com` e acessa `WPP.chat`/`WPP.msg`.
**Where:**
- `extension/src/page-world/wa-collector.ts`
- `extension/public/` (wa-js bundle copiado durante build)

**Depends on:** T11.
**Reuses:** `@wppconnect/wa-js` (npm dep), `lib/chunker` (via bundle).
**Requirement:** CHX-03.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] Bundled standalone (vite build target = `web`, no ESM externals)
- [ ] Aguarda `WPP.webpack.onReady`
- [ ] Recebe `window.postMessage({from:'medzee:cmd', cmd:'collect'})` e dispara coleta
- [ ] Lista chats via `WPP.chat.list({onlyChats:true})`
- [ ] Itera chats, chama `WPP.chat.getMessages(id, {count:200})`, filtra ts >= now - 30d
- [ ] Map shape → ExtensionMessage; chunked 1000; postMessage pro content-script collector com `from:'medzee:wa-collector'`
- [ ] Emite eventos `collect_started`, `collect_completed`, `wa_needs_login` (quando detecta QR)
- [ ] Build passa (script bundled ≤ 500KB OK)

**Tests:** manual (smoke T25)
**Gate:** build

**Commit:** `:sparkles: feat(F8-14): page-world wa-collector com wa-js integration`

---

### T15 — `extension/src/content-scripts/collector.ts` (page-world bridge)

**What:** Content script em `web.whatsapp.com` que injeta o page-world e faz bridge com service worker.
**Where:** `extension/src/content-scripts/collector.ts`

**Depends on:** T13, T14.
**Reuses:** Padrão `chrome.runtime.sendMessage` + injeção via script tag.
**Requirement:** CHX-03, CHX-04.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] Injeta `wa-collector.js` no page-world via `<script src=chrome.runtime.getURL(...)>`
- [ ] Listen `window.postMessage` do page-world → forward `chrome.runtime.sendMessage({type:'medzee:batch'})`
- [ ] Listen `chrome.runtime.onMessage({type:'medzee:begin_collection'})` → posta `{from:'medzee:cmd', cmd:'collect'}` pro page-world
- [ ] Detecta close de tab (`window.beforeunload`) → emite `medzee:aborted`
- [ ] Build passa

**Tests:** manual (smoke T25)
**Gate:** build

**Commit:** `:sparkles: feat(F8-15): collector content script (wa-collector bridge)`

---

### T16 — `extension/src/popup/` UI mínima [P]

**What:** Popup ao clicar no ícone — mostra status (paired? collecting? last_collection_at).
**Where:**
- `extension/src/popup/popup.html`
- `extension/src/popup/popup.tsx`
- `extension/src/popup/popup.css`

**Depends on:** T10, T11.
**Reuses:** `lib/storage` (lê estado), `lib/messages` (types).
**Requirement:** CHX-09 (UX visibility).

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] Mostra 4 estados: "Não pareado" / "Pareado, sem coleta" / "Coletando…" / "Última análise: N msgs"
- [ ] Botão "Abrir Medzee Spy" link pra medzee.com/app
- [ ] Botão "Desconectar" limpa `chrome.storage.local` + emite `medzee:unpair`
- [ ] Build passa, ícone+popup carregam em side-load

**Tests:** manual
**Gate:** build

**Commit:** `:sparkles: feat(F8-16): extension popup com status visual`

---

## Wave 5 — Frontend pivot (paralelo com Wave 4, após Wave 2)

### T17 — `frontend/src/lib/device.js` (useIsMobile) [P]

**What:** Hook detecta mobile via UA + matchMedia.
**Where:** `frontend/src/lib/device.js`

**Depends on:** T1 (precisa só pra context, sem dep direto).
**Reuses:** `useEffect` pattern dos outros hooks `lib/`.
**Requirement:** CHX-07.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `useIsMobile()` retorna `boolean`
- [ ] Combina UA regex (`iPhone|iPad|Android|Mobile`) + `matchMedia('(pointer:coarse)')` + `screen.width < 900`
- [ ] `npm run lint` passa

**Tests:** none (frontend, M1 matrix)
**Gate:** quick (`cd frontend && npm run lint`)

**Commit:** `:sparkles: feat(F8-17): useIsMobile hook em lib/device.js`

---

### T18 — `frontend/src/lib/extension.js` (probe + events + token inject) [P]

**What:** Cliente JS frontend ↔ extensão.
**Where:** `frontend/src/lib/extension.js`

**Depends on:** T1.
**Reuses:** `window.postMessage` + `useEffect`/`useState` patterns.
**Requirement:** CHX-09, CHX-10, CHX-15.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `useExtensionDetected({timeoutMs:500})` retorna `{installed, paired, version}` (null = detecting)
- [ ] `sendToExtension(message)` faz `window.postMessage`
- [ ] `useExtensionEvents()` listener pra `{type:'medzee:event'}`
- [ ] `injectPairingToken(token)` escreve em `window.medzee_spy` + localStorage
- [ ] `requestNewPairingToken()` chama `POST /api/auth/me/extension-pairing-token` via lib/api
- [ ] `npm run lint` passa

**Tests:** none
**Gate:** quick

**Commit:** `:sparkles: feat(F8-18): lib/extension.js (probe + events + token mgmt)`

---

### T19 — `frontend/src/screens/MobileBlockScreen.jsx` [P]

**What:** Tela fullscreen pra mobile bloqueado.
**Where:** `frontend/src/screens/MobileBlockScreen.jsx`

**Depends on:** T17.
**Reuses:** Tailwind classes existentes, ícone `Smartphone` do `lucide-react`.
**Requirement:** CHX-07, CHX-08.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] Render conforme ASCII do design §4.6
- [ ] Botão "Copiar link" usa `navigator.clipboard.writeText`
- [ ] Form "Enviar pro email" valida email + chama `POST /api/extension/mobile-lead` + mostra success state
- [ ] `npm run lint` passa

**Tests:** none
**Gate:** quick

**Commit:** `:sparkles: feat(F8-19): MobileBlockScreen com email capture`

---

### T20 — `frontend/src/screens/ExtensionInstallScreen.jsx` [P]

**What:** Tela "instale a extensão" com polling pra detectar instalação.
**Where:** `frontend/src/screens/ExtensionInstallScreen.jsx`

**Depends on:** T18.
**Reuses:** Tailwind, `useExtensionDetected` polling.
**Requirement:** CHX-03, CHX-09.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] Mostra link pra Chrome Web Store (placeholder URL até publicação)
- [ ] Polling 1s pra detectar instalação
- [ ] Quando detecta + paired → `onPaired()` callback (transição)
- [ ] Estado loading visual ("Aguardando instalação… ⏳")
- [ ] `npm run lint` passa

**Tests:** none
**Gate:** quick

**Commit:** `:sparkles: feat(F8-20): ExtensionInstallScreen com auto-detect polling`

---

### T21 — `frontend/src/screens/SpyFlowScreen.jsx` (state machine reescrita)

**What:** Orquestrador do fluxo invertido `/spy` (cadastro → install → analyze → generating → done).
**Where:** `frontend/src/screens/SpyFlowScreen.jsx` (substitui código antigo do `/spy`)

**Depends on:** T17, T18, T19, T20.
**Reuses:** `LeadFormScreen` (signup form existente), `useExtensionDetected`, `useExtensionEvents`, `useReportPolling`, `GeneratingScreen` (refatorada em T24), `ScopeWarningBanner`.
**Requirement:** CHX-01, CHX-03, CHX-06, CHX-07, CHX-10, CHX-11.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] State machine: `START → SIGNUP → INSTALL → ANALYZE → GENERATING → DONE` + branches (`WA_NEEDS_LOGIN`, `ABORTED`)
- [ ] No mount: se `useIsMobile()` → redirect/render `MobileBlockScreen`
- [ ] Se já logado E extensão pareada → pula pra ANALYZE
- [ ] Após signup → grava `extension_pairing_token` via `injectPairingToken` + transição → INSTALL
- [ ] INSTALL → ExtensionInstallScreen; ao detectar pairing → transição → ANALYZE
- [ ] ANALYZE → botão "Analisar meu WhatsApp" → `sendToExtension({cmd:'start_collection'})` → transição → GENERATING
- [ ] GENERATING → consome `useExtensionEvents` pra exibir progresso real
- [ ] `useReportPolling` em paralelo; quando `reports/latest.status='completed'` → DONE → redirect `/app/reports/:id`
- [ ] `npm run lint` passa

**Tests:** none (cobertura por smoke T25)
**Gate:** quick

**Commit:** `:sparkles: feat(F8-21): SpyFlowScreen state machine invertida (signup-first)`

---

### T22 — `frontend/src/App.jsx` (wire novo /spy + mobile guard)

**What:** Rotas atualizadas; `/spy/*` apontam pro `SpyFlowScreen`.
**Where:** `frontend/src/App.jsx`

**Depends on:** T21.
**Reuses:** react-router-dom routing pattern.
**Requirement:** CHX-07.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `/` → mantém AgentScreen
- [ ] `/spy` + `/spy/*` → `SpyFlowScreen`
- [ ] `/app/*` mobile → redirect `MobileBlockScreen` (com flag `reason='mobile'`)
- [ ] Rotas antigas (`/qr`, `/lead-form` standalone) removidas ou redirecionam pro novo flow
- [ ] `npm run lint` passa

**Tests:** none
**Gate:** quick

**Commit:** `:sparkles: feat(F8-22): wiring /spy + mobile guard em App.jsx`

---

### T23 — `lib/auth.js` + `LeadFormScreen.jsx` consume `extension_pairing_token`

**What:** Após signup ok, lib/auth retorna o token; LeadFormScreen injeta.
**Where:**
- `frontend/src/lib/auth.js` (modify: response shape `{user, session, extension_pairing_token}`)
- `frontend/src/screens/LeadFormScreen.jsx` (modify: chama `injectPairingToken` após signup ok)

**Depends on:** T6, T18, T21.
**Reuses:** Existing `lib/auth` + signup pattern F2.
**Requirement:** CHX-01.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `signup()` retorna `extension_pairing_token` no response object
- [ ] `LeadFormScreen` chama `injectPairingToken(token)` antes do callback `onSignupComplete`
- [ ] `npm run lint` passa

**Tests:** none
**Gate:** quick

**Commit:** `:sparkles: feat(F8-23): LeadForm injeta extension_pairing_token pós-signup`

---

### T24 — `GeneratingScreen.jsx` consome eventos da extensão

**What:** Substitui polling `uazapi-stats` por eventos da extensão.
**Where:** `frontend/src/screens/GeneratingScreen.jsx` (modify) + `screens/dashboard/ReportGeneratingState.jsx` (mesmo padrão)

**Depends on:** T18, T21.
**Reuses:** `useAnimatedCount` (existente), `useExtensionEvents` (T18), `useReportPolling`.
**Requirement:** CHX-06.

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] Mostra progresso real: "X/Y conversas processadas · Z mensagens enviadas"
- [ ] Quando recebe `wa_needs_login` event → transiciona pra tela "Logue no WhatsApp Web"
- [ ] Quando recebe `aborted` event → mostra "Coleta interrompida, tentar de novo?"
- [ ] Quando `report.status='completed'` → redirect
- [ ] `npm run lint` passa

**Tests:** none
**Gate:** quick

**Commit:** `:sparkles: feat(F8-24): GeneratingScreen consome eventos reais da extensão`

---

## Wave 6 — Smoke + Web Store + docs

### T25 — Manual smoke E2E (side-load + signup + WA Web + report)

**What:** Validar fluxo ponta-a-ponta numa instalação dev real.
**Where:** Smoke ad-hoc; documentar resultado em `.specs/features/f8-chrome-extension-ingestion/SMOKE_REPORT.md`

**Depends on:** T9, T16, T22, T23, T24.
**Reuses:** WhatsApp Web do dev local, side-load extension dist.
**Requirement:** ALL CHX-01..CHX-17 (validação cruzada).

**Tools:**
- MCP: `mcp__supabase__execute_sql` (validar rows persistidas)
- Skill: `verify` (validação real-world)

**Done when:**
- [ ] Backend rodando local com `WHATSAPP_PROVIDER=extension`
- [ ] Frontend rodando local em Chrome
- [ ] Extensão side-loaded de `extension/dist/`
- [ ] Acessar `/spy` em Chrome desktop → completa signup
- [ ] Detecta extensão → pareia
- [ ] Clica "Analisar" → abre web.whatsapp.com → coleta dispara
- [ ] Backend logs mostram batches recebidos
- [ ] `captured_messages` populada com `source='extension'`
- [ ] Worker F3 termina → `reports.payload` preenchido
- [ ] Frontend transiciona pra ReportDetailPage
- [ ] Acessar `/spy` em DevTools mobile emulation → ver `MobileBlockScreen`
- [ ] Documenta findings + bugs em SMOKE_REPORT.md

**Tests:** manual + smoke
**Gate:** full E2E

**Commit:** `:white_check_mark: test(F8-25): smoke E2E ponta-a-ponta com side-load`

---

### T26 — Update docs (README + STATE D11✅ + ROADMAP F8✅)

**What:** Documentação final pós-smoke.
**Where:**
- `README.md` (raiz: section "Chrome Extension" com instruções side-load + Web Store)
- `.specs/project/STATE.md` (D11 status ✅ + lições novas se houver)
- `.specs/project/ROADMAP.md` (F8 ✅ COMPLETE)
- `.specs/features/f8-chrome-extension-ingestion/spec.md` (atualiza traceability table todas as IDs CHX → "Verified")

**Depends on:** T25.
**Reuses:** Padrões docs F4/F5.
**Requirement:** N/A (documentação).

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] README tem section "Chrome Extension" com `cd extension && npm install && npm run build` + side-load steps
- [ ] STATE.md D11 marcada ✅ COMPLETE; lições L15+ adicionadas se smoke revelou algo
- [ ] ROADMAP.md F8 entry com commits-chave + resumo
- [ ] spec.md traceability table atualizada (17/17 verified)

**Tests:** none
**Gate:** N/A

**Commit:** `:memo: docs(F8-26): F8 ✅ COMPLETE — Chrome Extension ingestion shipping`

---

### T27 — Web Store listing draft + privacy policy

**What:** Materiais pra submissão Chrome Web Store.
**Where:**
- `extension/STORE_LISTING.md` (descrição, screenshots, permissões justificativa)
- `frontend/public/extension-privacy.md` OU rota static `/extension/privacy` no frontend
- 3-5 screenshots em `extension/store-assets/screenshots/`

**Depends on:** T25.
**Reuses:** Texto base do design §10.
**Requirement:** Distribuição (design §11.1).

**Tools:**
- MCP: NONE
- Skill: NONE

**Done when:**
- [ ] `STORE_LISTING.md` cobre: short_description (132 chars), detailed_description, justifications pras 4 permissões, support email/URL
- [ ] Privacy policy publicável em URL acessível
- [ ] Screenshots 1280×800 ou 640×400 em PNG
- [ ] Submissão fica como checklist humano (não automatizável)

**Tests:** none
**Gate:** N/A (humano submete)

**Commit:** `:memo: docs(F8-27): Chrome Web Store listing + privacy policy`

---

## Task Granularity Check

| Task | Scope | Status |
|---|---|---|
| T1 | 1 migration | ✅ |
| T2 | 1 setting + 1 exception | ✅ (cohesive infra) |
| T3 | 1 adapter + factory update | ✅ |
| T4 | 1 module skeleton (3 files) | ✅ (cohesive scaffold) |
| T5 | 1 field addition | ✅ |
| T6 | 1 endpoint + 1 method | ✅ (cohesive auth) |
| T7 | 1 service file | ✅ |
| T8 | 1 routes file (5 endpoints) | ⚠️ Borderline — 5 endpoints num arquivo é cohesive RESTful; manter unified |
| T9 | 1 wiring + 1 gate | ✅ |
| T10 | 1 scaffold (tooling) | ✅ |
| T11 | 4 lib files | ⚠️ Borderline — small utilities, cohesive group |
| T12 | 1 content script | ✅ |
| T13 | 1 service worker | ✅ |
| T14 | 1 page-world script | ✅ |
| T15 | 1 content script | ✅ |
| T16 | 1 popup | ✅ |
| T17 | 1 hook | ✅ |
| T18 | 1 lib (4 utilities cohesive) | ✅ |
| T19 | 1 component | ✅ |
| T20 | 1 component | ✅ |
| T21 | 1 component (state machine) | ✅ |
| T22 | 1 wiring | ✅ |
| T23 | 2 modifies (cohesive) | ✅ |
| T24 | 1-2 components | ✅ |
| T25-T27 | smoke / docs | ✅ |

**Resultado:** todos atômicos ou cohesivos. T8 e T11 borderline mas mantidos (split criaria mais fricção que benefício).

---

## Diagram-Definition Cross-Check

| Task | Body deps | Diagram arrows | Match |
|---|---|---|---|
| T1 | None | — | ✅ |
| T2 | T1 | T1 → T2 | ✅ |
| T3 | T2 | T2 → T3 | ✅ |
| T4 | T1, T2 | T1+T2 → T4 (via Wave 1+2) | ✅ |
| T5 | T1 | T1 → T5 | ✅ |
| T6 | T4 | T4 → T6 | ✅ |
| T7 | T4, T5, T6 | Wave 3 sequential | ✅ |
| T8 | T7 | T7 → T8 | ✅ |
| T9 | T8 | T8 → T9 | ✅ |
| T10 | T8 | T8 → T10 (wire shape locked) | ✅ |
| T11 | T10 | T10 → T11 [P] | ✅ |
| T12 | T10, T11 | T10+T11 → T12 [P] | ✅ |
| T13 | T11, T12 | T11+T12 → T13 (sequential) | ✅ |
| T14 | T11 | T11 → T14 | ✅ |
| T15 | T13, T14 | T13+T14 → T15 | ✅ |
| T16 | T10, T11 | T10+T11 → T16 [P] | ✅ |
| T17 | T1 | Wave 5 root | ✅ |
| T18 | T1 | Wave 5 root | ✅ |
| T19 | T17 | T17 → T19 [P] | ✅ |
| T20 | T18 | T18 → T20 [P] | ✅ |
| T21 | T17, T18, T19, T20 | Wave 5 mid | ✅ |
| T22 | T21 | T21 → T22 | ✅ |
| T23 | T6, T18, T21 | (cross-wave, registrado) | ✅ |
| T24 | T18, T21 | T21 → T24 | ✅ |
| T25 | T9, T16, T22, T23, T24 | All converge → T25 | ✅ |
| T26 | T25 | T25 → T26 | ✅ |
| T27 | T25 | T25 → T27 | ✅ |

**Resultado:** 27/27 ✅.

---

## Test Co-location Validation (TESTING.md matrix)

| Task | Code Layer | Matrix Requires | Task Says | Status |
|---|---|---|---|---|
| T1 | DB migration | none (smoke SQL) | integration smoke | ✅ |
| T2 | infra (setting + exception) | none | unit (cobre via T3) | ✅ |
| T3 | clients/whatsapp adapter | unit (via service) | unit | ✅ |
| T4 | schemas + security + repository | unit (schemas+security), none (repo direto) | unit | ✅ |
| T5 | schemas | unit | unit | ✅ |
| T6 | service + endpoint | unit + integration | integration | ✅ |
| T7 | service | unit | unit | ✅ |
| T8 | endpoints (routes) | integration | integration | ✅ |
| T9 | wiring + endpoints | integration | integration | ✅ |
| T10–T16 | Chrome extension | "Manual + smoke" (sidecar matrix) | manual | ✅ |
| T17–T24 | Frontend | "adiar para v2" (none) | none | ✅ |
| T25 | E2E ponta-a-ponta | smoke | manual + smoke | ✅ |
| T26, T27 | docs | none | none | ✅ |

**Resultado:** 27/27 ✅. Todas as code layers respeitam a matriz F4/F5.

---

## Parallel Execution Map

```
Wave 1: T1 (1 sequential)
        ↓
Wave 2: T2 [P], T3 [P], T4 [P], T5 [P] all start  (4 parallel sub-agents)
        ↓ (after T4)
        T6 (sequential — touches AuthService)
        ↓
Wave 3: T7 → T8 → T9 (3 sequential)
        ↓
Wave 4: T10 (sequential, scaffold)
        ↓
        T11 [P], T12 [P], T16 [P] (3 parallel)
        ↓ (after T11+T12)
        T13 → T14 (or T14 first; T11 satisfies dep)
        ↓
        T15 (after T13+T14)

(parallel to Wave 4) Wave 5: T17 [P], T18 [P] (2 parallel, after T1)
                              ↓
                              T19 [P], T20 [P] (2 parallel, after T17+T18)
                              ↓
                              T21 → T22 → T23 + T24 (sequential)

Wave 6: T25 → T26 + T27 [P] (T26, T27 paralelos no final)
```

**Max parallelism in any wave:** 4 (Wave 2 start).

---

## MCP & Skills allocation

Pergunta do user antes de Execute:

> Pra cada task, quais ferramentas usar?

**MCPs disponíveis no projeto:**
- `mcp__supabase__*` — usado em T1 (apply_migration), T25 (execute_sql)
- Nenhum outro necessário pras outras tasks (são edits de código)

**Skills disponíveis:**
- `tlc-spec-driven` (essa) — coordena execução
- `verify` (skill instalada) — usado em T25 pra smoke E2E real

**Sub-agent strategy (durante Execute):**
- Tasks com edits triviais: sub-agent `general-purpose`
- Tasks com exploração de código existente: sub-agent `Explore`
- Tasks paralelas (`[P]`): N sub-agents simultâneos via Agent calls num único message

---

## Commit strategy

- **1 commit por task** (já especificado nas tasks)
- Após Wave 3, smoke do uazapi continua passando — flag `WHATSAPP_PROVIDER=uazapi` ativa
- Após Wave 6, cutover: env `WHATSAPP_PROVIDER=extension` + `VITE_USE_EXTENSION_FLOW=true`

---

## Risks & mitigations

| Risk | Wave | Mitigation |
|---|---|---|
| wa-js incompatível com WhatsApp Web atual | T14 | Pin version range + smoke em T25; plano B DOM scraping (futuro P3) |
| MV3 service worker dorme no meio da coleta | T13 | Persistir progresso em `chrome.storage.local`, retomar em onWakeup |
| PostgREST 42P10 regressão | T7 | Reusar `insert_many` existente (já tem fix L11) |
| RLS bloqueando anon insert em `mobile_redirect_leads` | T1 | GRANT INSERT pro `anon` no migration |
| Test count silenciosamente diminui | T6/T7/T8/T9 | Done-when assert "test count: N tests pass" |
| Chrome Web Store rejeitando manifest | T27 | Privacy policy + justifications detalhadas |

---

**Total:** 27 tasks · 6 waves · max paralelismo 4 · 17 CHX cobertos
