# STATE — Memória persistente entre sessões

> Decisões, blockers, lições, todos e ideias adiadas. Atualizar ao final de cada sessão e ao registrar qualquer escolha relevante.

## Decisões

- **D1 (2026-05-17, revisada) — WhatsApp via uazapi.com (REST + webhook), abstraído em `WhatsAppProvider`.**
  Por quê: uazapi entrega QR como base64 PNG direto (`POST /instance/connect`), webhook nativo, gerencia o auth state internamente (sem sidecar Node/Baileys/Puppeteer), e oferece `/chat/find` + `/message/find` para o histórico.
  Como aplicar: `app/clients/whatsapp/__init__.py` com protocol `WhatsAppProvider` e adapter `uazapi.py`. Backend usa `UAZAPI_BASE_URL` e `UAZAPI_ADMIN_TOKEN`; cada sessão grava seu `uazapi_token` em `medzee_spy.whatsapp_sessions`.
  Trade-offs aceitos: vendor lock-in (mitigado pela camada de adapter), dado sensível trafega por terceiro (ver blocker B1), sem filtro nativo por data (paginação manual com corte por timestamp).

- **D2 (2026-05-17) — LLM provider-agnostic, default Anthropic Claude (`claude-sonnet-4-6`).**
  Por quê: prompt envolve análise textual extensa em PT-BR; Claude tem janela grande e bom desempenho. Mantém abstração para trocar provider sem reescrever pipeline.
  Como aplicar: `app/clients/llm.py` com interface `async def complete(messages, model, max_tokens) -> str` e adapter Anthropic em primeiro. Vars `LLM_PROVIDER`, `LLM_MODEL`, `ANTHROPIC_API_KEY` já estão no `.env`.

- **D3 (2026-05-17, revisada 2x) — Reutilizar instância Supabase do projeto "News" (`itghmlcipjloirsyhare`) com schema isolado `medzee_spy`. Reuso apenas de `auth.users` (compartilhado).**
  Por quê: o projeto News é uma newsletter médica diária; suas tabelas (`public.subscribers`, `articles`, `triagens` etc.) são tightly-coupled ao pipeline editorial — reusar `subscribers` exigiria ALTER e teria efeito colateral grave (lead Spy entraria na lista de envio do newsletter). Schema dedicado evita conflito total.
  Histórico de renomeação: inicialmente `medzee` (f1_1, f1_2), depois renomeado para `medzee_spy` (f1_3) pra clareza de namespace (não é "qualquer projeto Medzee", é especificamente o Spy). Migration `f1_4` recriou com grants completos (vide L1 nas Lições).
  Como aplicar: schema `medzee_spy.*`; migrations criam `medzee_spy.whatsapp_sessions` (F1, **aplicada**), `medzee_spy.users_profile` (F2, **aplicada**), `medzee_spy.reports` (F3). Identidade compartilhada via `auth.users(id)`. Tag soft em `auth.users.raw_app_meta_data.projects = ['spy']` aplicada no signup do F2 via `auth.admin.update_user_by_id`.
  Migrations aplicadas: `f1_1` (criação), `f1_2` (hardening), `f1_3` (rename), `f1_4` (recreate com grants pra `authenticator`), `f1_5` (placeholder `medzee` vazio pra destravar PostgREST), `f2_1_users_profile` (perfil + RLS owner-only + trigger updated_at).

- **D4 (2026-05-17) — Nenhuma mensagem persistida no banco/log/disco.**
  Por quê: privacidade prometida na landing + risco LGPD para dados de saúde.
  Como aplicar: pipeline lê em memória → gera relatório → descarta mensagens. Persiste apenas o relatório estruturado em `medzee_spy.reports.payload` (jsonb) e metadados agregados (counts, médias) em `medzee_spy.whatsapp_sessions`. Logs registram só counts e tempos.

- **D5 (2026-05-17) — Stream backend ↔ frontend = SSE (Server-Sent Events).**
  Por quê: uso unidirecional (status → frontend); FastAPI suporta nativamente via `StreamingResponse`; `EventSource` no browser auto-reconecta.
  Como aplicar: endpoint `GET /api/whatsapp/sessions/:id/events` retorna `StreamingResponse(generator, media_type="text/event-stream")`. Eventos: `qr-updated`, `connected`, `extracting`, `extracted`, `failed`, `expired`.

- **D6 (2026-05-17) — Extração automática disparada pelo webhook da uazapi.**
  Por quê: minimiza o tempo total (não espera o signup); cache TTL 15min em memória cobre a janela até o usuário completar o cadastro; reduz fricção de UX.
  Como aplicar: callback `/api/whatsapp/webhook` recebe `EventType=connection` com `instance.status=connected`, marca sessão como `connected`, dispara task assíncrona de extração.

- **D7 (2026-05-17) — Execução em container separado já no dev/staging.**
  Aplicado: Railway hospedando FastAPI via Procfile + nixpacks. Frontend `npm run dev` local apontando pro Railway via `VITE_API_BASE_URL`.

## Decisões obsoletas

- **~~Storage do auth state do Baileys (Supabase Storage)~~** — N/A: uazapi gerencia o auth state nos servidores deles (D1). Pergunta inicial perdeu sentido.

## Blockers

- **B1 (aberto) — Validação LGPD/DPA para tráfego via uazapi.**
  Antes de produção precisamos: (a) confirmar política de retenção da uazapi; (b) localização do data center (deve ser BR se possível); (c) ter DPA/contrato adequado já que dados sensíveis de saúde passam pela infra deles. Não bloqueia desenvolvimento local; bloqueia deploy público.

- **B2 (aberto) — Supabase Auth: `leaked_password_protection` desabilitada (project-wide).**
  Advisor detectou que o Supabase Auth do projeto News não tem proteção contra senhas vazadas. Habilitar via Dashboard → Authentication antes do F2 ir pra produção.

- **B3 (aberto) — uazapi free tier devolve 500 em `/chat/find` logo após `connected`.**
  Observado no smoke F1: o webhook chega com `instance.status=connected` em ~20s após o scan, mas se chamamos `/chat/find` no mesmo momento, uazapi devolve 500. Provavelmente o history sync interno do uazapi ainda não terminou. **Plano**: na implementação real de F3, adicionar delay de ~5s entre `connected` e o start do extract pipeline, mais retry com backoff em 5xx. Pode ser exclusivo do tier free (paid talvez já tenha o history pronto). Não bloqueia F2 (auth/persist independem do extract); bloqueia o relatório real funcionar.

## Lições

- **L1 (2026-05-17) — `ALTER SCHEMA ... RENAME TO` preserva grants existentes mas NÃO adiciona grants pra novos roles que possam ter sido omitidos no original.**
  No `f1_1` original, o `grant usage on schema medzee to authenticated, service_role` esqueceu o role **`authenticator`** (que o PostgREST do Supabase usa pra construir o schema cache). Durante o rename para `medzee_spy`, isso ficou latente. Depois um pause/resume do Supabase fez PostgREST tentar recarregar o cache → `PGRST002 Could not query the database for the schema cache` → REST inteiro do projeto fica 503 (não só nosso schema, **todo** o projeto). Fix: `f1_4` recria o schema com `grant usage to authenticator, authenticated, anon, service_role`. **Para futuras migrations de schema novo**, sempre incluir os 4 roles.

- **L2 (2026-05-17) — Supabase Dashboard "Exposed schemas" persiste schemas que não existem mais.**
  Renomeei `medzee` → `medzee_spy` via `ALTER SCHEMA`. O dashboard ainda referenciava `medzee` no setting `db-schemas`, e PostgREST tentava introspectar um schema fantasma → cache build falhava globalmente. Fix de emergência: `f1_5` recriou `medzee` como schema placeholder vazio só pra destravar. **Para futuras renomeações**: atualizar o Dashboard ANTES de dropar o schema antigo, ou criar placeholder vazio até a config ser corrigida.

- **L3 (2026-05-17) — uvicorn no Railway não toca o root logger; `logger.info()` por default NÃO aparece nos Deploy Logs.**
  Root logger threshold default é `WARNING`. Bibliotecas usam `logging.getLogger(__name__)` que herda do root → INFO silenciosamente descartado. Fix em `app/main.py`: `logging.basicConfig(level=logging.INFO, force=True)` no startup. Sem isso, debug em prod fica impossível.

- **L4 (2026-05-17) — A wire shape real do webhook uazapi free é diferente da doc.**
  Doc sugeria `{ event, instance: <id>, data: { loggedIn, jid } }`. **Realidade observada** (capturada via log sanitizado em produção): `{ EventType, instance: { name, status }, instanceName, owner, token, type? }` — `instance` é DICT (não id), o status fica em `instance.status` (não `data.loggedIn`), o JID está em `owner` top-level, e `type: "LoggedOut"` aparece em desconexões. Documentar isso em INTEGRATIONS.md pra próximo provider/migração.

- **L5 (2026-05-17) — Railway env vars: campo individual no Dashboard mantém aspas literais; Raw Editor faz parse dotenv-style.**
  Se você cola `KEY="value"` no campo individual, Railway armazena o valor LITERAL com aspas, e `httpx.AsyncClient(base_url='"https://..."')` falha sem mensagem clara. Sempre usar Raw Editor ou colar sem aspas externas.

- **L6 (2026-05-17) — uazapi `/instance/create` exige `name` no body, mesmo no free tier.**
  Doc não explicitava. Sem `name`, devolve `400 "Missing Name or instanceName in payload"`. Adapter agora gera `medzee-spy-<8hex>` automaticamente.

- **L7 (2026-05-17) — uazapi destroy real é `DELETE /instance` (sem ID na URL, header `token`), não `POST /instance/reset`.**
  Reset reseta connection state mas NÃO remove a instância do tenant → slot continua ocupado. DELETE faz disconnect + remoção atômicos. Crítico pro slot recycling em prod.

- **L8 (2026-05-17, F2) — `MagicMock(spec=supabase.Client)` quebra a chain `.auth.admin.create_user`.**
  Em supabase-py 2.x, `Client.auth` é um `@cached_property`. O `spec=` do MagicMock inspeciona os atributos *de classe*, não as descriptors resolvidas, e bloqueia o acesso a `.auth` → `AttributeError: Mock object has no attribute 'auth'`. Fix nos testes do F2: fixture `fake_supabase_admin` constrói um `MagicMock()` sem spec e configura manualmente os subpaths (`fake.auth.admin.create_user.return_value = ...`). Documentar em CONVENTIONS.md se outros módulos forem mockar o Client.

- **L9 (2026-05-17, F2) — Detecção de "email duplicado" no Supabase Auth precisa do code E da mensagem.**
  `auth.admin.create_user` levanta `gotrue.errors.AuthApiError` com formatos variados conforme versão: às vezes `code="user_already_exists"`, às vezes `code="email_address_already_in_use"`, às vezes só mensagem `"User already registered"` sem `code`. AuthService faz fingerprint em ambos os eixos (`code in {...}` OR substring no `message`) pra ser robusto. Mesmo padrão usado pra `invalid_credentials` no login.

## Todos (cross-sessão)

- [x] ~~Confirmar modelo LLM default~~ → D2 ratificada (Anthropic Claude).
- [x] ~~Confirmar storage de sessão Baileys~~ → D1 trocou para uazapi, ponto obsoleto.
- [x] ~~**Migration Supabase F1**: criar schema + whatsapp_sessions~~ — aplicada via `f1_1`...`f1_5`.
- [x] ~~Smoke ponta-a-ponta F1~~ → validado 2026-05-17 (frontend recebe `connected`, transiciona para LeadForm).
- [ ] **B3 follow-up**: adicionar delay + retry no extract pipeline pra contornar 500 do chat/find no free tier (na F3).
- [ ] **Benchmark de extração**: rodar smoke com plano pago / volume real medindo tempo. Alvo: ≤ 90s.
- [ ] **Validar política LGPD/DPA da uazapi** (B1).
- [ ] Limpar Dashboard Supabase: remover schema `medzee` placeholder dos "Exposed schemas" quando seguro (atualmente mantido pra evitar L2 recorrente).
- [x] ~~**Migration F2**: `medzee_spy.users_profile (user_id PK→auth.users, name, phone, ticket_medio, clinic_segment, ...)`~~ — aplicada via `f2_1_users_profile` (RLS owner-only + trigger updated_at).
- [ ] **Smoke F2 ponta-a-ponta** em produção (Railway): signup real → `auth.users` com `projects=['spy']` → `users_profile` populada → `whatsapp_sessions.status='consumed'`; signup duplicado → 409 → redirect `/login?email=`; login wrong/right; entrar autenticado em `/app/reports`.
- [ ] **Migration F3**: `medzee_spy.reports (id, user_id, session_id, status, payload jsonb, prompt_version, model, ...)`.
- [ ] Mover `AGENT_ID` da Marina (ElevenLabs) de hardcode para `import.meta.env.VITE_ELEVENLABS_AGENT_ID` em `AgentScreen.jsx` (CONCERNS R8).
- [ ] (Opcional, pós-MVP) State persistence — hoje `SessionStore` é in-memory; redeploy do Railway perde sessões abertas. Considerar Redis ou rehidratação via DB no startup quando volume justificar.

## Ideias adiadas

- Cache do relatório entre re-execuções no mesmo período (evita refazer LLM).
- Score de "saúde comercial" persistente para evolução temporal real (hoje mockado em `/app/dashboard`).
- Detectar pico de demanda fora do expediente e sugerir agente de IA (gancho de upsell).
- Comparativo entre atendentes (requer identificação por número/handle).
- Webhook global da uazapi (`/globalwebhook` admin) compartilhado entre todas as sessões — simplifica registro mas exige roteamento por `instance` no payload. Avaliar quando passar de 100 sessões simultâneas.

## Preferences

_(será preenchido quando o usuário sinalizar preferências de modelo, estilo de commit, etc.)_
