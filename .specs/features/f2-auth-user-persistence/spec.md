# F2 — Auth & User Persistence

> Transformar a sessão WhatsApp efêmera (F1) em uma identidade durável: signup com Supabase Auth, perfil em `medzee_spy.users_profile`, link com o `whatsapp_session_id` e devolução de tokens pra logar o usuário automaticamente no `/app/*`.

## Problem statement

Hoje, ao final do fluxo F1, o backend tem em memória um `ExtractedPayload` rico (mensagens dos últimos 30 dias) e uma row em `medzee_spy.whatsapp_sessions` com `user_id=NULL`. O frontend está em `LeadFormScreen`, recebe os dados do médico (nome, email, telefone, ticket médio, senha), e hoje chama um `onSubmit` mockado que navega direto pro `/app/reports/latest` sem persistir nada. Resultado: cada smoke gera um payload órfão, o usuário não tem login, e os relatórios não podem ser linkados a ninguém.

F2 fecha esse gap: o submit do formulário vira um signup real no Supabase Auth, cria o perfil, linka a sessão WhatsApp pendente ao usuário recém-criado, marca a sessão como `consumed` (libera o slot da uazapi e finaliza o ciclo F1), e devolve `access_token` + `refresh_token` pro frontend autenticar a sessão Supabase no browser.

## Users

- **Médico/gestor da clínica** preenche o formulário e espera entrar logado direto na tela de relatório.
- **F3 (Report Processing)** consome `ExtractedPayload` retornado pelo signup pra disparar o pipeline LLM. (Se F3 não estiver pronto, o backend só persiste a sessão e o payload — F3 entra depois sem mudar este contrato.)
- **F4 (Frontend Integration)** wire-up de `LeadFormScreen.onSubmit` + auth client `@supabase/supabase-js` no browser. Hoje a F1 wired apenas o `QRScreen`; F4 completa.

## Success metrics

- ≥ 95% dos submits válidos (form passou validação local) resultam em `200` do signup em ≤ 3s.
- 100% dos signups bem-sucedidos retornam tokens válidos (`access_token` + `refresh_token` aceitos pelo `supabase.auth.setSession` sem erro).
- Após signup, **o usuário está autenticado** no frontend (Supabase session ativa, JWT no header `Authorization` em chamadas subsequentes).
- A sessão WhatsApp original transita pra `consumed` no banco (verificável: `select status from medzee_spy.whatsapp_sessions where id=<id>` → `consumed`).
- Instância uazapi correspondente é **deletada** (slot livre) — confirmado pelo log `delete_instance status=200`.
- 0 ocorrência de email duplicado criando perfil duplicado (idempotência / 409 explícito).

## User stories

### P1 — MVP (precisa entrar em M1)

**US-01 — Signup e link de sessão**
Como médico que acabou de escanear o QR, quero preencher meu cadastro e entrar direto no relatório, sem fazer login separado.
- AUTH-01: WHEN o frontend chama `POST /api/auth/signup` com body válido `{ name, email, phone, password, ticket_medio?, whatsapp_session_id }`, THEN o backend SHALL:
  1. Criar usuário via Supabase Auth (`supabase.auth.sign_up`).
  2. Setar `app_metadata.projects = ['spy']` via Admin API.
  3. Inserir perfil em `medzee_spy.users_profile`.
  4. Linkar `medzee_spy.whatsapp_sessions.user_id` ao novo `user.id` (usar `service.consume_extracted` já existente).
  5. Marcar a sessão como `consumed` e disparar `provider.delete_instance` (cleanup uazapi).
  6. Responder `200 SuccessResponse[SignupResponse]` com `{ user: { id, email }, session: { access_token, refresh_token, expires_in }, report_pending: bool }`.
- AUTH-02: A resposta SHALL conter tokens válidos que o frontend usa em `supabase.auth.setSession({ access_token, refresh_token })` sem erro.
- AUTH-03: WHEN o `whatsapp_session_id` não existe / TTL expirou / já está `consumed`, THEN o backend SHALL ainda criar o usuário e perfil normalmente, mas responder `report_pending=false` e `session_warning="whatsapp_session_unavailable"` (não bloquear o cadastro só porque a sessão F1 expirou — o usuário pode tentar gerar de novo).

**US-02 — Validação de input + email duplicado**
Como sistema, quero rejeitar inputs inválidos antes de chamar o Supabase, e tratar email duplicado de forma humana.
- AUTH-04: WHEN o body falhar validação pydantic (email inválido, password < 6 chars, phone < 10 dígitos, etc.), THEN o backend SHALL retornar `422` com `errors` enumerando os campos inválidos.
- AUTH-05: WHEN `supabase.auth.sign_up` retornar erro de email já existente (`user_already_exists` ou similar), THEN o backend SHALL retornar `409 Conflict` com `detail: "email_already_registered"`. Frontend mostra mensagem orientando login.
- AUTH-06: WHEN qualquer outro erro de Supabase Auth (rate limit, password muito fraca, etc.), THEN backend SHALL retornar `400 Bad Request` com `detail` mapeado a partir do erro do Supabase.

**US-03 — Persistência do perfil**
Como sistema, quero gravar o perfil de forma consistente, com a relação certa pra `auth.users`.
- AUTH-07: A tabela `medzee_spy.users_profile` SHALL existir com colunas: `user_id uuid PK references auth.users(id) on delete cascade`, `name text not null`, `email text not null`, `phone text not null`, `ticket_medio numeric`, `clinic_segment text` (deixado null em M1; F3 preenche), `created_at timestamptz default now()`, `updated_at timestamptz default now() + trigger`.
- AUTH-08: RLS SHALL estar habilitada com policy `owner_select_update`: cada user só lê/atualiza o próprio perfil. Backend usa `service_role` pra criar (bypass RLS).
- AUTH-09: WHEN o `INSERT` em `users_profile` falhar (constraint, network, etc.) DEPOIS do `sign_up` ter sucesso no Supabase Auth, THEN o backend SHALL **deletar o auth.users recém-criado** via Admin API pra evitar usuário órfão sem perfil. Retorna `500` com `detail: "profile_creation_failed"`.

**US-04 — Tag de projeto na auth.users**
Como sistema, quero identificar quais usuários pertencem ao Spy (vs ao News, que compartilha o mesmo `auth.users`).
- AUTH-10: O signup SHALL setar `auth.users.raw_app_meta_data` para incluir `{"projects": ["spy"]}` (merge com valores existentes se o user já estiver em outro projeto futuramente). Backend usa `supabase.auth.admin.update_user_by_id(user_id, app_metadata={...})`.

**US-05 — Login com email/senha (rota standalone)**
Como usuário que já tem conta (cadastrou ontem, ou tentou cadastrar com email duplicado), quero acessar via email/senha sem refazer o fluxo do QR.
- AUTH-11: WHEN o frontend chama `POST /api/auth/login` com `{ email, password }`, THEN o backend SHALL chamar `supabase.auth.sign_in_with_password`, e responder `200 SuccessResponse[LoginResponse]` com `{ user: { id, email }, session: { access_token, refresh_token, expires_in } }` em caso de sucesso.
- AUTH-12: WHEN as credenciais forem inválidas (email não existe OU senha errada), THEN o backend SHALL retornar `401` com `detail: "invalid_credentials"`. Não diferenciar (evita enumeration de emails).
- AUTH-13: WHEN o usuário existir mas **não estiver tagueado** `app_metadata.projects` incluindo `'spy'` (caso: subscriber do News tentando logar no Spy), THEN backend SHALL retornar `403` com `detail: "user_not_in_spy"`. Frontend orienta a fazer o fluxo `/spy` primeiro.
- AUTH-14: Frontend SHALL ter uma rota `/login` com `LoginScreen.jsx` — formulário simples (email + password + botão "Entrar" + link "Esqueci senha" placeholder pra P2). Após sucesso, navega pra `/app/reports` (lista de relatórios do user).
- AUTH-15: Quando o signup falhar com `409 email_already_registered` (AUTH-05), frontend SHALL mostrar mensagem + botão "Entrar com sua conta" que navega pra `/login` preenchendo o email já digitado.

### P2 — Should have

**US-06 — Endpoint de "me"**
Pra o frontend reidratar perfil em refresh.
- AUTH-16: `GET /api/auth/me` autenticado retorna `{ user_id, name, email, phone, ticket_medio, clinic_segment }` da `medzee_spy.users_profile`. Requer JWT válido. 401 se ausente.

**US-07 — Atualização de perfil**
- AUTH-17: `PATCH /api/auth/me` aceita `{ name?, phone?, ticket_medio?, clinic_segment? }` e atualiza o perfil do usuário autenticado. RLS já garante isolamento.

### P3 — Nice to have (fica pós-M1)

- AUTH-18: Reset de senha (Supabase Auth tem fluxo nativo via `reset_password_for_email`). O `LoginScreen` já tem link placeholder.
- AUTH-19: OAuth (Google, Apple) — backlog.
- AUTH-20: Re-send confirmation email (não aplicável enquanto `confirm_signup=false`).

## Out of scope (desta feature)

- Geração do relatório (F3). F2 só consome o `ExtractedPayload` e entrega pra próxima feature.
- UI completa de signup error states (campo a campo) — F4 cuida do polimento.
- Reset de senha (P3 — Supabase tem fluxo nativo, link já fica no LoginScreen apontando placeholder).
- Verificação de email (link de confirmação). Em M1, signup é direto, sem confirmação. Supabase Auth tem essa feature mas vamos deixar `confirm_signup=false` em config (decisão Q3 das gray areas).
- Multi-fator (TOTP, SMS).
- Soft delete / re-ativação de conta.
- OAuth (Google, Apple).

## Edge cases e tratamentos

- **EC-01** — Usuário preenche form depois do TTL de 15min da sessão WhatsApp:
  signup ainda funciona, mas `report_pending=false` e `session_warning`. Frontend mostra: "Sua sessão expirou — entre no app e gere um novo relatório."
- **EC-02** — Email já cadastrado:
  409 com `email_already_registered`. Frontend orienta login. (Login só vem em P3 — em M1, mostra mensagem "Já cadastrado — entre em contato com suporte" ou similar.)
- **EC-03** — Senha < 6 chars:
  Bloqueia no frontend (LeadFormScreen já tem validação). Se passar, backend retorna 422 com campo `password`.
- **EC-04** — `sign_up` ok mas `users_profile` falha:
  Roll back: delete `auth.users.id` via admin (AUTH-09). Retorna 500.
- **EC-05** — `consume_extracted` falha (sessão sumiu do store):
  Não bloqueia signup. Marca `report_pending=false`. Loga warning. F3 vai gerar um relatório vazio / placeholder quando o user clicar "Gerar".
- **EC-06** — Email com whitespace / casing:
  Backend normaliza (`email.strip().lower()`) antes de Supabase. Trigger no DB também pode normalizar mas mantém simples no app.
- **EC-07** — `app_metadata` falha de update (raríssimo):
  Loga warning, não bloqueia. O perfil em `medzee_spy.users_profile` já é source-of-truth pra "user é do Spy".

## Dependências

- **Depende de:** F1 (`medzee_spy.whatsapp_sessions`, `service.consume_extracted`, `service.delete_instance`).
- **Bloqueia:** F3 (Report Processing precisa do `user_id` da sessão); F4 (Frontend depende do contrato de signup pra wire o LeadFormScreen).
- **Pré-requisitos técnicos:**
  - Migration `f2_1_users_profile` criando tabela + RLS + trigger updated_at.
  - Supabase Auth project-level config: `disable_signup=false`, `confirm_signup=false`, password policy ≥ 6 chars (defaults da Supabase). Esses já devem estar OK no projeto News compartilhado.
  - Adicionar `app/clients/supabase.py` getter pra `supabase.auth.admin` (já existe `get_supabase_admin_client` que retorna o client completo).
  - Frontend: instalar `@supabase/supabase-js` no `frontend/package.json` (entrará na F4).

## Requirement traceability

| ID       | Story | Implementation (a definir em design.md) | Test | Status |
| -------- | ----- | --------------------------------------- | ---- | ------ |
| AUTH-01  | US-01 | `app/modules/auth/service.py::signup` | `test_auth_service::test_signup_happy_path` | spec'd |
| AUTH-02  | US-01 | retorno do signup envelopa Supabase session | smoke F2 final | spec'd |
| AUTH-03  | US-01 | `try service.consume_extracted; except → set session_warning` | `test_auth_service::test_signup_with_expired_whatsapp_session` | spec'd |
| AUTH-04  | US-02 | pydantic validation em `SignupRequest` | `test_auth_routes::test_signup_invalid_body_422` | spec'd |
| AUTH-05  | US-02 | catch `user_already_exists` → 409 + frontend redirect to /login | `test_auth_service::test_signup_email_duplicated_409` | spec'd |
| AUTH-06  | US-02 | catch genérico de SupabaseError → 400 | `test_auth_service::test_signup_supabase_error_400` | spec'd |
| AUTH-07  | US-03 | migration `f2_1_users_profile` | `test_auth_repository::test_create_profile_inserts_row` | spec'd |
| AUTH-08  | US-03 | policy SQL na migration | DB inspect via MCP `list_tables verbose=true` | spec'd |
| AUTH-09  | US-03 | `signup_service.create_user_and_profile` com rollback no except | `test_auth_service::test_profile_creation_failure_rolls_back_auth_user` | spec'd |
| AUTH-10  | US-04 | `supabase.auth.admin.update_user_by_id(app_metadata=...)` | `test_auth_service::test_signup_sets_app_metadata_projects` | spec'd |
| AUTH-11  | US-05 | `app/modules/auth/service.py::login` + `POST /api/auth/login` | `test_auth_service::test_login_happy_path` | **spec'd (P1)** |
| AUTH-12  | US-05 | catch invalid credentials → 401 (indistinto pra evitar enumeration) | `test_auth_service::test_login_invalid_credentials_401` | spec'd |
| AUTH-13  | US-05 | check `app_metadata.projects` contém 'spy' → senão 403 | `test_auth_service::test_login_user_not_in_spy_403` | spec'd |
| AUTH-14  | US-05 | `LoginScreen.jsx` + rota `/login` em `App.jsx` | manual smoke (browser); F4 polish | spec'd |
| AUTH-15  | US-05 | LeadForm error-state com botão "Entrar" → /login | manual smoke | spec'd |
| AUTH-16  | US-06 | `GET /api/auth/me` | `test_auth_routes::test_get_me_authenticated` | spec'd (P2) |
| AUTH-17  | US-07 | `PATCH /api/auth/me` | `test_auth_routes::test_patch_me_updates_profile` | spec'd (P2) |
| AUTH-18..AUTH-20 | US-P3 | — | — | deferred |

## Open questions — todas resolvidas 2026-05-17

1. **Onde devolver o `ExtractedPayload`?** → **(B)** Mantém no `SessionStore` em memória. Signup retorna só `report_pending=true`. F3 puxará via `session_id` (F3 chama `service.consume_extracted` ou similar). Evita poluir response/logs com KB-MB de mensagens.

2. **Disparo do `delete_instance`?** Mantém em `service.consume_extracted` (já implementado em F1). Falha não bloqueia signup.

3. **Como o `whatsapp_session_id` chega no `LeadFormScreen`?** → **(B)** Props através de `MainFlow`/`SpyFlow` em `App.jsx`. F4 wireja: `QRScreen.onConnected(sessionId)` → `MainFlow` guarda em state → passa pra `LeadFormScreen` como prop.

4. **Confirm signup do Supabase Auth?** **Desligar.** Em M1 signup é direto, sem clicar link no email. Pré-requisito operacional: Dashboard → Auth → Email confirmations OFF (validar que já está assim, é default de projetos novos). Ação manual única.

5. **`access_token` storage no browser?** localStorage (padrão Supabase, gerenciado pelo `@supabase/supabase-js`). Sem httpOnly cookies por enquanto.

6. **Política de password?** Manter ≥ 6 chars (Supabase default + LeadForm já valida). Endurecer só se exigência aparecer.

7. **Login form?** **Incluído em P1** — `LoginScreen.jsx` em `/login`, com fluxo "email já cadastrado → redirect" partindo do signup. Reset de senha fica P3 (link placeholder).

## Pré-requisitos operacionais (one-shot do usuário)

- [ ] Confirmar Supabase Dashboard → **Auth → Email confirmations** está **DESLIGADO** (signup direto)
- [ ] Adicionar `frontend/.env`: `VITE_SUPABASE_URL=https://itghmlcipjloirsyhare.supabase.co` e `VITE_SUPABASE_ANON_KEY=<anon>` (precisa pra `@supabase/supabase-js` no browser)
- [ ] `cd frontend && npm install @supabase/supabase-js` (a Wave 1 vai pedir)
