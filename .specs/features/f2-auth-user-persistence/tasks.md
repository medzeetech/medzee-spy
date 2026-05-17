# F2 — Auth & User Persistence · Tasks

> Quebra atômica do [design.md](design.md) em 12 tasks. Tags `[P]` rodam em paralelo via sub-agents.

## Pré-flight (one-shot do usuário — confirmados)

- ✓ Supabase Auth: **Email confirmations DESLIGADO** (signup direto, sem clicar email)
- ✓ `frontend/.env`: `VITE_SUPABASE_URL` e `VITE_SUPABASE_ANON_KEY` preenchidos (já aplicado localmente)
- ⏳ Wave 5 vai pedir: `cd frontend && npm install @supabase/supabase-js`

## Ordem de entrega (waves)

```
Wave 1 (fundação — sequencial)
  T1 → T2

Wave 2 (camadas independentes — paralelizáveis)
  T3 [P]  T4 [P]  T5 [P]  T6 [P]

Wave 3 (orquestração — sequencial)
  T7

Wave 4 (endpoints — sequencial)
  T8

Wave 5 (frontend — paralelizáveis após T6+T8)
  T9 [P]  T10 [P]

Wave 6 (testes — paralelizáveis)
  T11 [P]  T12 [P]
```

---

## T1 — Migration `f2_1_users_profile`

**What:** Aplicar a migration que cria a tabela `medzee_spy.users_profile` + RLS + trigger updated_at.

**Where:** Supabase remoto via `mcp__supabase__apply_migration` (não há diretório local de migrations).

**Depends on:** — (Wave 1)

**Reuses:** `medzee_spy.set_updated_at()` (criada na F1.4 — função `security invoker` com `search_path=''`).

**Done when:**
- [ ] Migration aplicada com sucesso (success: true)
- [ ] `mcp__supabase__list_tables schemas=["medzee_spy"]` mostra `whatsapp_sessions` E `users_profile`
- [ ] `mcp__supabase__get_advisors security` não introduz novos warnings (RLS ativa, função sem search_path mutável — já estamos reusando a function da F1)
- [ ] Smoke direto REST: `curl -H "Authorization: Bearer <SERVICE_ROLE>" -H "Accept-Profile: medzee_spy" https://<URL>/rest/v1/users_profile?select=user_id&limit=1` retorna 200 `[]`

**SQL exato:** seção 3 do design.md.

**Traceability:** AUTH-07, AUTH-08.

---

## T2 — Schemas + exceptions (`schemas.py` + parte do `service.py`)

**What:** Definir todos os tipos pydantic do módulo auth + a hierarquia de exceções que o service vai usar.

**Where:**
- `backend/app/modules/auth/__init__.py` (marker)
- `backend/app/modules/auth/schemas.py` — todos os Request/Response models da seção 4 do design.md
- `backend/app/modules/auth/service.py` — **só** a seção de exceções (`AuthError`, `EmailAlreadyRegistered`, `InvalidCredentials`, `UserNotInSpy`, `ProfileNotFound`, `ProfileCreationFailed`, `SupabaseAuthError`). O resto fica em T7.

**Depends on:** T1 (não bloqueante, mas faz sentido depois — schemas referenciam o domínio que a migration cria)

**Reuses:** `SuccessResponse[T]` de `app/contracts/responses.py` (não importar aqui — é o route que envelopa).

**Done when:**
- [ ] `python -c "from app.modules.auth.schemas import SignupRequest, LoginRequest, SignupResponse, LoginResponse, MeResponse, UpdateMeRequest, SessionPayload, UserPayload; print('ok')"` imprime ok
- [ ] `python -c "from app.modules.auth.service import AuthError, EmailAlreadyRegistered, InvalidCredentials, UserNotInSpy, ProfileNotFound, ProfileCreationFailed, SupabaseAuthError; print('ok')"` imprime ok
- [ ] `SignupRequest(name='Dr X', email='x@y.com', phone='5511999999999', password='abc123').email == 'x@y.com'` (EmailStr aceita)
- [ ] `SignupRequest(name='', ...)` levanta `ValidationError` (min_length=2 funcionando)

**Tests:** smoke em T11.

**Traceability:** AUTH-01..AUTH-17 (todos os endpoints usam estes schemas).

---

## T3 — Repository `[P]`

**What:** CRUD assíncrono pra `medzee_spy.users_profile` via supabase-py (`asyncio.to_thread`).

**Where:** `backend/app/modules/auth/repository.py`

**Depends on:** T1 (tabela tem que existir), T2 (tipos)

**Reuses:**
- Padrão de F1 `app/modules/whatsapp/repository.py` (mesma forma — `_table()` helper, `asyncio.to_thread`, logs sem PII)
- `get_supabase_admin_client()` de `app/clients/supabase.py`

**Done when:**
- [ ] `async def create_profile(user_id: UUID, *, name, email, phone, ticket_medio)` — INSERT em `medzee_spy.users_profile`
- [ ] `async def get_profile(user_id: UUID) -> dict | None` — SELECT por user_id, retorna primeira row ou None
- [ ] `async def update_profile(user_id: UUID, **fields: Any)` — UPDATE com whitelist de campos permitidos (`name`, `phone`, `ticket_medio`, `clinic_segment`). Rejeita `email` e `user_id` (PII/imutável).
- [ ] `async def delete_profile(user_id: UUID)` — DELETE (usado no rollback se algum dia precisar)
- [ ] Logs estruturados: `repo.auth.create_profile`, `repo.auth.get_profile`, etc. Email logado **só** como `email_domain` (parte após `@`); nunca o local-part nem completo.
- [ ] `py_compile` zero erros
- [ ] Type hints completos

**Tests:** T11 (mock supabase client).

**Traceability:** AUTH-07.

---

## T4 — Security helper `get_current_user_id` `[P]`

**What:** Adicionar helper que extrai e valida o JWT e retorna o UUID do usuário, em cima do `get_current_user` existente.

**Where:** `backend/app/core/security.py` — adicionar função (NÃO substituir a existente — `get_current_user` continua útil pra quem precisa do objeto completo).

**Depends on:** — (T1 não bloqueia)

**Reuses:** `bearer_scheme`, `get_current_user`, `get_supabase_client` já existentes em `security.py`.

**Done when:**
- [ ] `async def get_current_user_id(credentials = Depends(bearer_scheme)) -> UUID` retorna `UUID(user.id)` ou levanta `HTTPException(401, "not_authenticated")`
- [ ] Se o JWT for inválido, Supabase devolve erro → mapeamos para 401 com detail `"invalid_token"` (não vazar a mensagem upstream)
- [ ] Type hint: `from uuid import UUID; -> UUID`

**Tests:** T12 (envia JWT inválido → 401).

**Traceability:** AUTH-16, AUTH-17 (necessário pros endpoints autenticados).

---

## T5 — Backend test scaffold `[P]`

**What:** Criar fixtures compartilhadas pros testes do módulo auth, espelhando o padrão da F1.

**Where:**
- `backend/app/tests/auth/__init__.py` (empty marker)
- `backend/app/tests/auth/conftest.py`

**Depends on:** — (não bloqueia, pode rodar paralelo)

**Reuses:** padrão de `backend/app/tests/whatsapp/conftest.py` (respx, MagicMock, monkeypatch).

**Fixtures que devem existir:**

| Fixture | O que faz |
|---|---|
| `fake_supabase_admin` | `MagicMock(spec=Client)` com `auth.admin.create_user`, `auth.admin.delete_user`, `auth.admin.update_user_by_id`, `auth.sign_in_with_password`. Cada um retorna `SimpleNamespace` parecido com a estrutura real do gotrue (user com id, email, app_metadata; session com access_token, refresh_token, expires_in). |
| `fake_admin_supabase_factory` | monkeypatch `app.clients.supabase.get_supabase_admin_client` pra retornar o `fake_supabase_admin` |
| `fake_repository` | monkeypatch `app.modules.auth.repository.<func>` pra ter `AsyncMock` em cada função |
| `fake_whatsapp_service` | monkeypatch `app.modules.whatsapp.service.get_service` pra retornar mock com `consume_extracted=AsyncMock()` (default sucesso). Casos podem sobrescrever pra raise/None. |
| `valid_signup_request` | factory de `SignupRequest` válida (usável em vários testes) |

**Done when:**
- [ ] `pytest backend/app/tests/auth/ --collect-only` lista as fixtures sem erro
- [ ] `pytest backend/app/tests/whatsapp/ -q` ainda passa (não interferiu na suite F1)

**Tests:** este IS o scaffold.

**Traceability:** infra dos testes AUTH-*.

---

## T6 — Frontend `supabase.js` + `api.js` `[P]`

**What:** Cliente Supabase singleton + helper de chamada HTTP que envelopa autenticação.

**Where:**
- `frontend/src/lib/supabase.js`
- `frontend/src/lib/api.js`

**Depends on:** — (paralelo total ao backend)

**Reuses:** `import.meta.env.VITE_*` (já configurado em `frontend/.env`).

**Done when:**
- [ ] `npm install @supabase/supabase-js` instalado (será executado por mim ou usuário)
- [ ] `frontend/src/lib/supabase.js` exporta `supabase` singleton com config: `persistSession: true, autoRefreshToken: true, detectSessionInUrl: false`
- [ ] `frontend/src/lib/api.js` exporta `api` com pelo menos `signup`, `login`, `me` apontando pra `VITE_API_BASE_URL`. Throws com `{ status, detail, body }` em respostas não-OK.
- [ ] Helper `callApi(path, { auth: true })` puxa `access_token` via `supabase.auth.getSession()` e seta `Authorization: Bearer <token>`
- [ ] `npm run dev` sobe sem erro (`frontend/eslint.config.js` compatível)

**Tests:** smoke manual no browser na Wave 5.

**Traceability:** AUTH-02, AUTH-14 (storage de session + chamadas autenticadas).

---

## T7 — AuthService (signup + login + me + update_me)

**What:** Implementar a classe `AuthService` inteira (todos os métodos da seção 6 do design).

**Where:** `backend/app/modules/auth/service.py` — adicionar ao arquivo onde T2 já colocou as exceptions.

**Depends on:** T2 (schemas + exceptions), T3 (repository), T1 (tabela)

**Reuses:**
- `get_supabase_admin_client()` (constructor)
- `repository.*` (T3)
- `whatsapp.service.get_service` lazy import (bridge F1)
- Padrão de logs estruturados (sem PII bruta)

**Métodos:**

```python
class AuthService:
    def __init__(self, supabase: Client | None = None) -> None: ...

    async def signup(self, req: SignupRequest) -> SignupResponse:
        # 1. normalize email; 2. admin.create_user (email_confirm=True);
        # 3. merge app_metadata.projects; 4. repo.create_profile (rollback se falhar);
        # 5. _maybe_consume_whatsapp_session; 6. sign_in_with_password;
        # 7. return SignupResponse
        ...

    async def login(self, req: LoginRequest) -> LoginResponse:
        # sign_in_with_password → 401 invalid_credentials;
        # check app_metadata.projects ⊇ ['spy'] → 403 user_not_in_spy
        ...

    async def get_me(self, user_id: UUID) -> MeResponse: ...
    async def update_me(self, user_id: UUID, req: UpdateMeRequest) -> MeResponse: ...

    async def _maybe_consume_whatsapp_session(
        self, session_id: UUID | None, user_id: UUID
    ) -> tuple[bool, str | None]: ...   # (report_pending, session_warning)

    @staticmethod
    def _merge_projects(app_metadata: dict | None, new: str) -> dict: ...


def get_auth_service() -> AuthService:
    """Factory (lazy singleton, mesma cara do whatsapp.service.get_service)."""
    ...
```

**Done when:**
- [ ] `py_compile` zero erros
- [ ] Imports lazy do whatsapp.service (dentro do método, não topo do arquivo)
- [ ] Catch específico `AuthApiError` do gotrue (ou supabase_auth) com message contendo "already registered" → raise `EmailAlreadyRegistered`
- [ ] Catch genérico de `AuthApiError` → raise `SupabaseAuthError(str(exc))`
- [ ] Rollback de `delete_user` no except do `create_profile` — best-effort, log mesmo se falhar
- [ ] App_metadata merge não duplica `'spy'` se já presente
- [ ] Logs nunca incluem `password`, `access_token`, `refresh_token`, nem email completo

**Tests:** T11 (extensivos — happy + rollback + 409 + 401 + 403 + ProfileNotFound).

**Traceability:** AUTH-01, AUTH-03, AUTH-05, AUTH-06, AUTH-09, AUTH-10, AUTH-11, AUTH-12, AUTH-13, AUTH-16, AUTH-17.

---

## T8 — Routes + api/router.py wiring

**What:** Expor o `AuthService` via HTTP em `/api/auth/*` e registrar no router raiz.

**Where:**
- `backend/app/modules/auth/routes.py`
- `backend/app/api/router.py` (adicionar `include_router(auth_router, prefix="/auth")`)

**Depends on:** T7 (service), T4 (security helper pra `/me`)

**Endpoints:**

| Método | Path | Auth | Body | Sucesso | Erros principais |
|---|---|---|---|---|---|
| POST | `/auth/signup` | — | `SignupRequest` | `200 SuccessResponse[SignupResponse]` | 422 (body), 409 (email duplicado), 400 (Supabase), 500 (profile rollback) |
| POST | `/auth/login` | — | `LoginRequest` | `200 SuccessResponse[LoginResponse]` | 401 invalid_credentials, 403 user_not_in_spy, 400 (outros) |
| GET | `/auth/me` | Bearer | — | `200 SuccessResponse[MeResponse]` | 401 not_authenticated, 404 profile_not_found |
| PATCH | `/auth/me` | Bearer | `UpdateMeRequest` (partial) | `200 SuccessResponse[MeResponse]` | 401, 422, 404 |

**Done when:**
- [ ] `cd backend && ./.venv/Scripts/python.exe -c "from app.main import app; print([r.path for r in app.routes if hasattr(r,'path') and '/auth' in r.path])"` lista os 4 endpoints
- [ ] `pytest backend/app/tests/whatsapp/ -q` ainda passa (router include não quebrou F1)
- [ ] `uvicorn app.main:app --port 8765 &; curl -X POST localhost:8765/api/auth/signup -d '{}' ; kill %1` retorna 422 (validação do body vazio)

**Tests:** T12 (integration).

**Traceability:** AUTH-01..AUTH-17 nos endpoints.

---

## T9 — Frontend `LoginScreen.jsx` + rota `/login` `[P]`

**What:** Tela de login standalone + rota no `App.jsx`. Estilo visual reusando padrão do `LeadFormScreen` (dark/orange/corners).

**Where:**
- `frontend/src/screens/LoginScreen.jsx` (novo)
- `frontend/src/App.jsx` (adicionar `<Route path="/login" element={<LoginScreen />} />`)

**Depends on:** T6 (api.js + supabase.js), T8 (backend `/auth/login` precisa estar no ar — pode usar Railway redeploy ou local backend)

**Reuses:** padrão visual de `LeadFormScreen.jsx` (cores, ícones lucide, animação fadeup), `useNavigate` + `useSearchParams` do react-router-dom.

**Done when:**
- [ ] Form com email + password, validação local básica (email com `@`, password ≥ 1 char)
- [ ] On submit: chama `api.login({ email, password })` → no sucesso `supabase.auth.setSession()` → `navigate('/app/reports')`
- [ ] Pre-fill do email via `useSearchParams().get('email')` (vem do redirect do signup 409)
- [ ] States visuais: `idle`, `submitting` (botão "Entrando…" desabilitado), `error` (mostra mensagem)
- [ ] Mensagens por status code:
  - 401 → "Email ou senha incorretos."
  - 403 → "Sua conta ainda não tem acesso ao Spy. Faça o diagnóstico em /spy."
  - outros → "Não foi possível entrar. Tente novamente em instantes."
- [ ] Link de fallback "Esqueci minha senha" — placeholder (target `#` ou alert "Em breve") — P3
- [ ] Link "Quero gerar um relatório" → `/spy`
- [ ] `eslint` passa, sem warnings novos

**Tests:** manual smoke via `npm run dev` na Wave 6.

**Traceability:** AUTH-14, AUTH-15 (parcial — o redirect do signup é T10).

---

## T10 — Wire `LeadFormScreen` ao backend real `[P]`

**What:** Trocar o `onSubmit` mockado do `LeadFormScreen` por uma chamada `api.signup`, com tratamento de erros e propagação do `whatsapp_session_id`.

**Where:**
- `frontend/src/screens/LeadFormScreen.jsx` (alterar `handleSubmit`, adicionar state de erro)
- `frontend/src/screens/QRScreen.jsx` (adicionar prop `onSessionCreated` que dispara setter no MainFlow — pequeno ajuste; QRScreen já chama `POST /sessions` e tem `sessionId` em state, só precisamos elevar)
- `frontend/src/App.jsx` (`MainFlow` mantém state `whatsappSessionId`; passa pra `LeadFormScreen`)
- `frontend/src/screens/SpyFlow.jsx` (mesma coisa do MainFlow, fluxo paralelo)

**Depends on:** T6 (api.js), T8 (backend `/auth/signup`)

**Reuses:** estrutura existente do `LeadFormScreen` (campos, máscaras, validação de 2 etapas).

**Done when:**
- [ ] `MainFlow` em `App.jsx` mantém `whatsappSessionId` em `useState` e passa pra `LeadFormScreen`
- [ ] `QRScreen` aceita prop `onSessionCreated(sessionId)` e chama no sucesso do `POST /sessions`
- [ ] `LeadFormScreen.handleSubmit`:
  - Coleta `name, email, phone, password, ticket_medio?`
  - Normaliza email pra lowercase
  - Chama `api.signup({...payload, whatsapp_session_id: whatsappSessionId})`
  - Sucesso: `supabase.auth.setSession(result.session)` → `navigate('/app/reports/latest')` (mantém comportamento atual)
  - 409: `navigate(\`/login?email=${encodeURIComponent(email)}\`)`
  - 422: parse `body.errors` → mostra mensagem por campo
  - outros: estado global de erro
- [ ] Botão "Criar conta" mostra estado `submitting` (já existe)
- [ ] Se `whatsappSessionId == null` (caso `/login` direto ou state perdido), backend aceita (`report_pending=false`) — frontend não bloqueia

**Tests:** smoke manual na Wave 6 (signup happy + 409 + 422).

**Traceability:** AUTH-01, AUTH-04, AUTH-05, AUTH-15.

---

## T11 — Backend tests: service + repository `[P]`

**What:** Cobertura unit do AuthService (todos os caminhos) + repository.

**Where:**
- `backend/app/tests/auth/test_auth_service.py`
- `backend/app/tests/auth/test_auth_repository.py`

**Depends on:** T5 (scaffold), T7 (service), T3 (repository)

**Casos:**

`test_auth_service.py`:
- `test_signup_happy_path` — cria user → app_metadata merge → profile → consume_extracted (mocked sucesso) → sign_in → retorna SignupResponse com report_pending=True
- `test_signup_normalizes_email` — `' Foo@BAR.COM '` → `'foo@bar.com'` em `auth.admin.create_user`
- `test_signup_email_already_registered_raises` — fake_supabase.create_user raises AuthApiError("User already registered") → service raises EmailAlreadyRegistered
- `test_signup_profile_creation_failure_rolls_back` — fake_repository.create_profile raises → service calls fake_supabase.admin.delete_user(user_id) → raises ProfileCreationFailed
- `test_signup_app_metadata_merges_with_existing` — user já tem `projects: ['news']` → fica `['news', 'spy']` (sem duplicar 'spy' se já presente)
- `test_signup_whatsapp_session_expired` — `fake_whatsapp_service.consume_extracted` raises → SignupResponse.report_pending=False, session_warning='whatsapp_session_unavailable'
- `test_signup_whatsapp_session_none` — `whatsapp_session_id=None` → report_pending=False, session_warning=None
- `test_signup_password_too_weak_from_supabase` — fake raises AuthApiError("Password is too weak") → SupabaseAuthError com mensagem original
- `test_login_happy_path` — sign_in_with_password sucesso + user.app_metadata.projects=['spy'] → LoginResponse
- `test_login_invalid_credentials_raises_401` — AuthApiError("Invalid login credentials") → InvalidCredentials
- `test_login_user_not_in_spy_raises_403` — app_metadata.projects=['news'] → UserNotInSpy
- `test_get_me_returns_profile` — repository.get_profile retorna dict → MeResponse construída
- `test_get_me_profile_missing_raises` — repository retorna None → ProfileNotFound
- `test_update_me_calls_repo_with_filtered_fields` — UpdateMeRequest com 2 campos → repository.update_profile chamado com só esses 2

`test_auth_repository.py`:
- `test_create_profile_inserts_correct_payload` — verifica chamada `_table().insert(row)` com schema medzee_spy + tabela users_profile
- `test_get_profile_returns_first_row` — mock data=[{...}] → retorna dict
- `test_get_profile_empty_returns_none` — mock data=[] → retorna None
- `test_update_profile_rejects_immutable_fields` — passar `user_id=X` ou `email=Y` → raises ValueError
- `test_delete_profile_eq_user_id` — chama delete().eq("user_id", str(uuid))

**Done when:**
- [ ] `pytest backend/app/tests/auth/ -q` ≥ 18 testes verdes
- [ ] `pytest backend/app/tests/whatsapp/ -q` ainda 56 verdes (sem regressão)

**Traceability:** AUTH-01, AUTH-03, AUTH-05, AUTH-06, AUTH-07, AUTH-09, AUTH-10, AUTH-11, AUTH-12, AUTH-13, AUTH-16.

---

## T12 — Backend tests: routes integration `[P]`

**What:** Integration tests dos 4 endpoints HTTP via `TestClient`/`AsyncClient`.

**Where:** `backend/app/tests/auth/test_auth_routes.py`

**Depends on:** T5 (scaffold), T8 (routes)

**Casos:**

- `test_post_signup_happy` — `dependency_overrides[get_auth_service] = lambda: mock_service` retornando SignupResponse → 200 SuccessResponse envelope com `data.user`, `data.session`
- `test_post_signup_invalid_body_422` — body vazio → 422
- `test_post_signup_email_duplicate_409` — mock service raises EmailAlreadyRegistered → 409 detail=email_already_registered
- `test_post_signup_profile_failure_500` — ProfileCreationFailed → 500 detail=profile_creation_failed
- `test_post_signup_supabase_error_400` — SupabaseAuthError → 400 com detail repassado
- `test_post_login_happy` — 200 envelope
- `test_post_login_invalid_credentials_401` — InvalidCredentials → 401 detail=invalid_credentials
- `test_post_login_user_not_in_spy_403` — UserNotInSpy → 403 detail=user_not_in_spy
- `test_get_me_without_token_401` — sem Authorization header → 401 not_authenticated
- `test_get_me_with_invalid_token_401` — mock supabase.auth.get_user raises → 401 invalid_token
- `test_get_me_authenticated_200` — mock `get_current_user_id` retornando UUID + service retornando MeResponse → 200 envelope
- `test_patch_me_partial_200` — body parcial `{phone: '...'}` → service.update_me chamado com só esse field

**Done when:**
- [ ] `pytest backend/app/tests/auth/test_auth_routes.py -q` ≥ 12 testes verdes
- [ ] Suite total verde (56 F1 + 18 service/repo + 12 routes = **86 alvo**)
- [ ] `GET /health` ainda 200 (regression smoke)

**Traceability:** AUTH-01..AUTH-17 nos endpoints.

---

## Smoke ponta-a-ponta (manual, pós-Wave 6)

Não é uma task formal, mas o gate final antes de fechar F2:

1. `cd frontend && npm run dev` → abre `/spy` no browser
2. Scaneia QR → escaneia no celular → frontend transiciona (mecanismo F1 já validado)
3. `LeadFormScreen`: preenche nome, email, telefone, ticket, senha
4. Clica "Criar conta e ver relatório":
   - Network tab mostra `POST /api/auth/signup` → 200
   - Console mostra `supabase.auth.setSession` sem erro
   - Frontend navega pra `/app/reports/latest`
   - Página `/app/reports/latest` carrega (mesmo que ainda com mocks — F3 substitui)
5. Verifica no Supabase:
   - `auth.users` tem novo row com `raw_app_meta_data.projects=['spy']`
   - `medzee_spy.users_profile` tem novo row com PK = `auth.users.id`
   - `medzee_spy.whatsapp_sessions` mudou pra `status='consumed'`, `user_id=<novo uuid>`
6. Tenta signup de novo com mesmo email → 409 → frontend redireciona pra `/login?email=...`
7. No `/login`: digita senha errada → 401 + mensagem. Digita senha certa → entra logado.
8. Logout (manual via DevTools `supabase.auth.signOut()` ou botão se F4 tiver implementado) → repete login funciona.

Se tudo isso passar limpo: **F2 ✅ DONE**.

## Cobertura por requisito

| AUTH | Implementação | Teste |
|---|---|---|
| AUTH-01 | T7 + T8 | T11, T12, smoke |
| AUTH-02 | T7 (sign_in_with_password retorna tokens) + T6 (frontend setSession) | smoke |
| AUTH-03 | T7 `_maybe_consume_whatsapp_session` | T11 |
| AUTH-04 | T2 + T8 | T12 |
| AUTH-05 | T7 + T8 + T10 (frontend redirect) | T11, T12, smoke |
| AUTH-06 | T7 + T8 | T11, T12 |
| AUTH-07 | T1 + T3 | T11 |
| AUTH-08 | T1 (policy SQL) | DB inspect via MCP |
| AUTH-09 | T7 rollback | T11 |
| AUTH-10 | T7 `_merge_projects` | T11 |
| AUTH-11 | T7 + T8 | T11, T12 |
| AUTH-12 | T7 + T8 | T11, T12 |
| AUTH-13 | T7 + T8 | T11, T12 |
| AUTH-14 | T9 | smoke |
| AUTH-15 | T10 (signup 409 → redirect) | smoke |
| AUTH-16 | T4 + T7 + T8 | T12 |
| AUTH-17 | T7 + T8 | T12 |

## Notas operacionais

- **Sub-agents:** Wave 2 (T3, T4, T5, T6) e Wave 6 (T11, T12) são candidatos óbvios. Wave 5 (T9, T10) também, **mas** dependem do backend estar deployado (T8 no Railway). Se preferir, fazemos Wave 5 manualmente após verificar smoke.
- **Supabase auth lib:** o pacote pode aparecer como `gotrue` (versão antiga) ou `supabase_auth` (atual) — o supabase-py 2.9 deprecou `gotrue` mas ainda funciona. Verificar warning no startup; se vier, ajustar imports.
- **Reset de senha (P3):** o `LoginScreen` já tem placeholder "Esqueci senha". Implementação real fica pra um próximo ciclo — usa `supabase.auth.resetPasswordForEmail(email)` (lib client lida com isso direto, não precisa backend).
- **Smoke F1 ainda funcional?** Antes de começar F2 código, rodar `pytest backend/app/tests/whatsapp/ -q` pra garantir que F1 segue 56/56 verde. Se quebrou por mudança upstream, prioriza fix antes de F2.
