# STATE — Memória persistente entre sessões

> Decisões, blockers, lições, todos e ideias adiadas. Atualizar ao final de cada sessão e ao registrar qualquer escolha relevante.

## Decisões

- **D11 (2026-05-19 — F7) — Composição "signup + auto-generate" vive no frontend, não no backend.**
  Por quê: o relatório precisa aparecer IMEDIATAMENTE após signup (coração do produto). Como F1 extract_30d_pipeline foi deprecated (D8 + Bug 2 de 3ca748e: matava instâncias), alguém precisa orquestrar o `POST /api/reports/generate` pós-signup. Alternativas avaliadas: (1) backend signup chamar reports.service — acopla auth a reports, anti-padrão; (2) background task FastAPI — invisível pro frontend, sem report_id pra navegar imediato; (3) frontend orquestra após signup — escolhido.
  Como aplicar: `LeadFormScreen.handleSubmit` dispara `generateReport({n_per_chat: 30})` logo após `setSession`, navega pra `/app/reports/{report_id}`. Fallback graceful se falhar (`/app/reports/latest`). `auth.service` continua single-purpose.
  Trade-off aceito: 1 round-trip extra no signup (+200-500ms). Vale por manter boundaries de módulo limpos e dar UX imediata.

- **D9 (2026-05-18 — F5 pivot) — Coleta por "últimas N mensagens de cada conversa" em vez de janela temporal.**
  Por quê: empiricamente, uazapi paid não entrega histórico antigo via `cutoff_ts`. `/chat/find` lista conversas; `/message/history-sync` popula o cache; `/message/find` lê o que foi sincronizado — mas com sincronização limitada às últimas N mensagens por chat (não retroativa). Filtrar por dias descartava quase tudo. Estratégia nova: pedir as últimas N (default 30) de CADA conversa, sem janela temporal. Funciona em qualquer tier.
  Como aplicar: pipeline `pull_last_n_per_chat(provider, token, *, n_per_chat=30)` em `app/workers/extract.py`. ReportService aceita `mode='last_n_per_chat'|'window_days'` (default last_n). Modal frontend mostra 10/20/30/50 msgs por conversa em vez de 7/15/30/60 dias.
  Trade-offs aceitos: conversas longas (50+ trocas) ficam capadas em 30 msgs — amostra suficiente pra diagnóstico comercial, não pra auditoria forense. Custo LLM cresce com nº de chats (sample_conversations já tem budget Claude).

- **D10 (2026-05-18 — F5) — Relatório SEMPRE gera; "fora-de-escopo" é informado via banner, não bloqueante.**
  Por quê: o pipeline anterior tinha 3 portões que mataram a UX: (a) route 422 `not_enough_data` quando < 10 msgs; (b) worker short-circuit insufficient quando < 5 msgs OU 0 conversas; (c) prompt instruía "recuse se não for saúde". Resultado: user conectava WhatsApp, gerava 0 relatório, via tela vazia, abandonava. Pivot: relatório sempre dispara, prompt sempre devolve algo útil; quando segmento não é saúde, o LLM preenche `scope_warning` e o frontend mostra banner amarelo no topo — relatório existe nos dois casos.
  Como aplicar: removido threshold rígido na route `/api/reports/generate`; worker short-circuit relaxado pra `message_count == 0`; `BASE_SYSTEM` reescrito com "SEMPRE gere o relatório"; novo campo `scope_warning: str|null` em `ReportPayload` + `LLM_TOOL_SCHEMA`; `ScopeWarningBanner` no `ReportDetailPage`.

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

- **D4 (REVOGADA 2026-05-17 pelo F4-21) — Mensagens persistidas com TTL e RLS.**
  Substitui a decisão anterior ("nenhuma mensagem persistida") que se tornou
  inviável quando F1 pull-history falhou no uazapi free e o paid tem quota
  limitada. F4 forward-capture exige persistir mensagens entre coleta e
  relatório.
  Mitigações:
    - TTL: 30 dias após a session whatsapp desconectar (job background diário
      em `app/workers/ttl_cleanup.py`).
    - RLS owner-only em `medzee_spy.captured_messages`.
    - Supabase storage encryption nativo (at-rest) + TLS em trânsito.
    - Logs NUNCA incluem o campo `text` ou `contact_name`; só counts +
      UUIDs + time ranges.
  Decisão antiga preservada na seção "Decisões obsoletas" pra histórico.

- **D5 (2026-05-17) — Stream backend ↔ frontend = SSE (Server-Sent Events).**
  Por quê: uso unidirecional (status → frontend); FastAPI suporta nativamente via `StreamingResponse`; `EventSource` no browser auto-reconecta.
  Como aplicar: endpoint `GET /api/whatsapp/sessions/:id/events` retorna `StreamingResponse(generator, media_type="text/event-stream")`. Eventos: `qr-updated`, `connected`, `extracting`, `extracted`, `failed`, `expired`.

- **D6 (2026-05-17) — Extração automática disparada pelo webhook da uazapi.**
  Por quê: minimiza o tempo total (não espera o signup); cache TTL 15min em memória cobre a janela até o usuário completar o cadastro; reduz fricção de UX.
  Como aplicar: callback `/api/whatsapp/webhook` recebe `EventType=connection` com `instance.status=connected`, marca sessão como `connected`, dispara task assíncrona de extração.

- **D7 (2026-05-17) — Execução em container separado já no dev/staging.**
  Aplicado: Railway hospedando FastAPI via Procfile + nixpacks. Frontend `npm run dev` local apontando pro Railway via `VITE_API_BASE_URL`.

- **D8 (2026-05-17 — F4 pivot) — Ingestão via forward-capture, não pull-history.**
  Webhook da uazapi captura cada mensagem nova em `medzee_spy.captured_messages`.
  Relatório é on-demand: user clica "Gerar agora" e escolhe janela
  (7/15/30/60 dias). Worker F3 (`generate_report_pipeline`) é reusado
  via novo `report_id` opcional que permite reusar uma row criada
  upstream.
  Por quê: única estratégia viável dado que uazapi free não suporta
  /chat/find e o paid tem quota apertada de instâncias.
  Trade-off aceito: tempo-pra-primeiro-relatório vai de "5 min" pra
  "N dias" (depende da janela escolhida); UX de demo perde impacto mas
  a tese de produto continua viva.

## Decisões obsoletas

- **~~Storage do auth state do Baileys (Supabase Storage)~~** — N/A: uazapi gerencia o auth state nos servidores deles (D1). Pergunta inicial perdeu sentido.

- **~~D4 original (2026-05-17) — Nenhuma mensagem persistida no banco/log/disco.~~** (REVOGADA pelo D8 + F4-21 em 2026-05-17)
  Por quê: privacidade prometida na landing + risco LGPD para dados de saúde.
  Como aplicar: pipeline lê em memória → gera relatório → descarta mensagens. Persiste apenas o relatório estruturado em `medzee_spy.reports.payload` (jsonb) e metadados agregados (counts, médias) em `medzee_spy.whatsapp_sessions`. Logs registram só counts e tempos.

## Blockers

- **B1 (aberto) — Validação LGPD/DPA para tráfego via uazapi.**
  Antes de produção precisamos: (a) confirmar política de retenção da uazapi; (b) localização do data center (deve ser BR se possível); (c) ter DPA/contrato adequado já que dados sensíveis de saúde passam pela infra deles. Não bloqueia desenvolvimento local; bloqueia deploy público.

- **B2 (aberto) — Supabase Auth: `leaked_password_protection` desabilitada (project-wide).**
  Advisor detectou que o Supabase Auth do projeto News não tem proteção contra senhas vazadas. Habilitar via Dashboard → Authentication antes do F2 ir pra produção.

- **B3 (RESOLVIDO 2026-05-17 — abandonando pull-history) — uazapi free
  `/chat/find` não disponível no tier gratuito.**
  Empiricamente confirmado: mesmo após 220s de retry budget (10/30/60/120s
  backoff) o endpoint continua devolvendo 500. Não é timing de history sync
  — é feature paga. F4 pivota pra forward-capture (webhook → DB) que
  funciona em qualquer tier que entregue webhook de mensagens.
  Implicação: F1 extract worker mantido como dead code reabilitável
  (F4-22), todo o pipeline F3 reusado intacto (vide F4 design § 1).

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

- **L10 (2026-05-17 — F4 lesson) — Adapter Protocol + worker desacoplado pagam
  o pivô completo de ingestão em ~3 dias.**
  F1 design abstraiu `WhatsAppProvider` Protocol e F3 design fez
  `generate_report_pipeline(session_id, payload, *, user_id, llm, report_id)`
  aceitar payload em vez de construir do nada. Resultado: F4 trocou COMO os
  dados chegam (webhook em vez de pull) sem tocar metrics, sampling, prompts,
  Claude integration ou schemas. Single-day refactor em vez de rewrite.
  Lição: invest em abstração no design phase paga muito quando o produto
  pivota.

- **L11 (2026-05-19) — PostgREST `upsert(on_conflict='cols')` exige índice unique NORMAL — partial index NÃO casa.**
  `medzee_spy.captured_messages` tinha `CREATE UNIQUE INDEX ... WHERE raw_message_id IS NOT NULL` (partial). PostgREST traduz `.upsert(on_conflict='whatsapp_session_id,raw_message_id')` em `ON CONFLICT (cols)` que exige índice unique **não-partial**. Erro: `42P10 there is no unique or exclusion constraint matching the ON CONFLICT specification`. Resultado: webhook `messages` perdia TODAS as inserções → `captured_messages` ficava eternamente vazia.
  Fix: trocar pra plain `INSERT` + dedup batch em memória + fallback row-by-row tratando `23505`. Índice partial fica como defesa em profundidade.
  Pra próximas tabelas: ou usa índice unique full (force raw_message_id NOT NULL) ou aceita lidar com 23505 no caller.

- **L12 (2026-05-19) — PostgREST default Range 0-999 trunca TODA query `.select()` sem `count="exact"` ou `.limit()` explícito.**
  `stats_for_session` baixava todas as rows e contava `len(rows)`. Com 8.6k msgs reais → contou 1000 (truncado). Dashboard exibia "1.000 mensagens" em vez do total real.
  Fix: usar `.select(..., count="exact")` (PostgREST manda header `Prefer: count=exact` e devolve total no `result.count`) + `.limit(1000)` explícito pra amostra usada em derivações (distinct chats, last_message_at).
  Pra qualquer COUNT em scale: nunca confie no `len(rows)`.

- **L13 (2026-05-19) — Top-N por grupo em Python falha quando 1 chave domina; precisa window function PostgreSQL.**
  `query_last_n_per_chat` fazia `.order(wa_chatid asc).order(ts desc)` e top-N em loop. Combinado com truncate 1000 (L12), o top chat com 2861 msgs sozinho dominava a primeira página alfabética → só 7 chats aparece de 47 totais → relatório sempre dava "10 msgs em 2 conversas".
  Fix arquitetural: migration `f5_1_top_n_messages_per_chat_rpc` cria função SQL com `ROW_NUMBER() OVER (PARTITION BY wa_chatid ORDER BY ts DESC) WHERE rn <= n_per_chat`. Repository chama via `.rpc('top_n_messages_per_chat', {...})`.
  Regra: top-N por grupo em volume não-trivial = window function direto no DB, nunca em Python.

- **L15 (2026-05-19) — Estado terminal de "consumed" no signup é anti-padrão pós-pivot F5.**
  O `consume_extracted` original do F2 marcava a session como `consumed` + chamava `delete_instance` no provider logo após o signup. Fazia sentido no F1+F2 (extract auto rodava antes do signup, relatório já estava pronto, libera o slot). Pós-F5, relatório é on-demand: a session precisa SOBREVIVER ao signup pra (a) webhook continuar capturando msgs em `captured_messages` e (b) user gerar quantos relatórios quiser. Symptom em prod: user fazia signup, dashboard logo mostrava "WhatsApp não conectado" porque o status no DB ficava `consumed` (terminal) e `/api/whatsapp/uazapi-stats` devolvia 409.
  Fix: `consume_extracted` agora SÓ linka user_id + cria placeholder de report. NÃO chama `mark_consumed`, NÃO chama `release_provider_slot`. Status fica `connected`/`extracted` indefinidamente até user desconectar manualmente.
  Lição mais ampla: ao pivotar de "pipeline batch único pós-signup" pra "pipeline on-demand recorrente", revisar TODOS os release-of-resources do flow antigo — eles assumem que o trabalho terminou, mas no novo paradigma o trabalho continua.

- **L14 (2026-05-19) — Auto-disparar pipeline pesado no webhook `connected` + brutalismo em `_fail` (delete_instance) = instância morre 1-2min após cada conexão.**
  `service._handle_connection_event` disparava `extract_30d_pipeline` no `connected`. O extract chamava `/chat/find` → uazapi devolve 500 nos primeiros 60s (history sync inicial) → `_fail` chamava `delete_instance` pra "liberar slot" → uazapi destruía a instância → user tinha que re-scanear QR.
  Fix: não disparar pipeline automático no connect (F5 deixa explícito: relatório só roda quando user clica "Gerar agora"). Defesa em profundidade: `_fail` só deleta em `code='banned'`.
  Lição: cleanup automático no caminho de erro só faz sentido quando o erro é DEFINITIVO. Pra erros transitórios (uazapi 500 temporário), preservar a instância sempre.

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
- [x] ~~F4 forward-capture implementado~~ — migration f4_1, captured_messages module, webhook event=messages, GET /whatsapp/status, POST /reports/generate, TTL job, frontend WhatsAppPage + GenerateReportModal.
- [x] ~~F4 smoke E2E em produção~~ — confirmado 2026-05-19 após fixes de 5 bugs (L11-L14). User gerou relatório real com 241 msgs / 32 conversas / score 45 / diagnóstico longo identificando segmento real.
- [ ] **B2 follow-up** — habilitar leaked password protection no Supabase (1 clique no Dashboard) antes de prod pública.
- [x] ~~F5 last-N per chat + relatório sempre gera~~ — 2026-05-18. Spec em `.specs/features/f5-last-n-per-chat/`. Backend + frontend completos.
- [x] ~~F5 smoke E2E~~ — confirmado 2026-05-19 (mesmo run do F4 smoke).
- [x] ~~**F6 — DX & Docs**~~ — 2026-05-19. README raiz, .env.example refinados, `package.json` raiz com `npm run dev` (concurrently), .gitignore atualizado.
- [x] ~~**F7 — Auto-Generate Report on Signup**~~ — 2026-05-19. Branch `feat/f7-auto-generate-on-signup`. LeadFormScreen orquestra signup → generate → navigate. Coração do produto restaurado.
- [ ] **F8 — Route guards (opcional)** — guard de rota autenticada em `/app/*`. Pequeno (~30min). Não bloqueia M1.

## Ideias adiadas

- Cache do relatório entre re-execuções no mesmo período (evita refazer LLM).
- Score de "saúde comercial" persistente para evolução temporal real (hoje mockado em `/app/dashboard`).
- Detectar pico de demanda fora do expediente e sugerir agente de IA (gancho de upsell).
- Comparativo entre atendentes (requer identificação por número/handle).
- Webhook global da uazapi (`/globalwebhook` admin) compartilhado entre todas as sessões — simplifica registro mas exige roteamento por `instance` no payload. Avaliar quando passar de 100 sessões simultâneas.

## Preferences

_(será preenchido quando o usuário sinalizar preferências de modelo, estilo de commit, etc.)_
