# Roadmap

**Current Milestone:** M1 — Fluxo ponta a ponta funcional
**Status:** ✅ COMPLETE smoke E2E em prod (2026-05-19). F1 deprecated · F2/F3/F4/F5/F6 ✅ done · F7 (route guards opcional) pendente.

---

## M1 — Fluxo ponta a ponta funcional

**Goal:** Usuário lê o QR em `/spy`, conecta o WhatsApp, preenche cadastro, e chega autenticado no relatório real gerado pelos dados dos últimos 30 dias.
**Target:** entrega da task descrita em `contexto_medzee_spy.mc`.

### Features

**F1 — WhatsApp Ingestion** — ✅ COMPLETE (2026-05-17)
- ~~Sidecar Node.js com Baileys~~ → trocado por uazapi.com SaaS (D1)
- Geração de sessão via `POST /instance/create` + `/instance/connect` (admin token + per-instance token)
- QR Code base64 PNG retornado direto pra `QRScreen.jsx`
- SSE stream `GET /sessions/:id/events` publica `connected` via webhook callback
- Cleanup automático via `DELETE /instance` libera slot do tier (F1.3)
- Smoke ponta-a-ponta validado: scan → uazapi webhook → SSE → frontend transiciona pra `GeneratingScreen`
- Extract pipeline pronto (paralelizado, com hard timeout); failing no free tier por timing do history sync da uazapi — addressed em F3 (ver B3 em STATE.md)
- 56/56 testes verdes; 17 commits + 4 migrations Supabase

**Commits-chave:** `aa173ef` (pivot uazapi), `b1efae4` (Wave 1+2 core), `381094c` (Wave 3 service+worker), `1b27f55` (routes), `2191622` (wiring), `c9f2f23` (tests), `da27eef` (Railway), `618f2d1`+`d064f46` (F1.3 delete), `03002d8` (QRScreen wire), `6a7e0aa` (webhook shape fix).

**Status realista pós-F4**: o `extract_30d_pipeline` ficou como dead code
mantido pra reabilitar futuro (vide F4-22). uazapi free não entrega
`/chat/find` (vide B3 RESOLVIDO em STATE.md). F4 pivotou pra
forward-capture; toda a pipeline F3 (worker, prompts, Claude) é reusada
sem mudança.

**F2 — Auth & User Persistence** — ✅ CODE COMPLETE (2026-05-17, smoke pendente em produção)
- Migration `f2_1_users_profile` aplicada: `medzee_spy.users_profile (user_id PK→auth.users, name, email, phone, ticket_medio, clinic_segment, ...)` + RLS owner-only + trigger updated_at
- `POST /api/auth/signup`: admin.create_user (email_confirm=True) → merge `app_metadata.projects = [..., 'spy']` → insert profile (rollback delete_user on failure) → bridge F1 (`consume_extracted` não-fatal, marca `report_pending=False` + `session_warning` se quebrar) → `sign_in_with_password` retorna o par access/refresh
- `POST /api/auth/login`: 401 indistinto pra invalid_credentials; 403 `user_not_in_spy` se user logado sem tag de projeto
- `GET /api/auth/me` + `PATCH /api/auth/me`: JWT via `get_current_user_id` em `core/security.py`; whitelist de campos no update (rejeita email + user_id)
- Frontend: `src/lib/{supabase,api}.js` (singleton + helper com auth header), `LoginScreen.jsx` standalone (rota `/login`, pre-fill via `?email=`, redirect signup 409 → /login), `LeadFormScreen` real (chama signup, mapeia 422 → field errors, 409 → redirect), botão **Login** top-right na `AgentScreen` (UX entry point pra usuário recorrente)
- 35 testes novos (16 service + 6 repo + 13 routes) — **suite total 91/91 verde**, F1 sem regressão

**Commits-chave:** `b1f3f67` (spec+design+tasks), `8b8cd44` (Wave 1: migration + schemas + exceptions), `5fe3c8c` (Wave 2: repo + security + scaffold + frontend lib), `2c0f177` (Wave 3: AuthService completo), `cd2a55f` (Wave 4: routes + router wiring), `99d29c1` (Waves 5+6: LoginScreen + LeadForm wire + 35 tests).

**F3 — Report Processing** — ✅ COMPLETE (smoke E2E confirmado 2026-05-19 via F4+F5)
- Pipeline: mensagens brutas → normalização → agregação de métricas → prompt LLM → relatório estruturado
- Prompt principal focado em clínicas (saúde) + addendums (odonto / outro)
- Detecção de domínio agora via `scope_warning` no LLM (F5) — relatório sempre gera, com banner amarelo quando segmento ≠ saúde/odonto
- Persistência do relatório (`reports.payload jsonb`) vinculado ao `user_id` + RLS owner-only
- Endpoint `GET /api/reports/:id` autenticado retorna o payload
- **Smoke validado 2026-05-19**: user gerou relatório real com 241 msgs / 32 conversas / score 45/100, diagnóstico longo e útil identificando segmento real (número pessoal misturando trabalho), sem alucinação

**F4 — Forward-Capture & On-Demand Reports** — ✅ COMPLETE (smoke 2026-05-19)
- Migration `f4_1_captured_messages` (RLS owner-only, TTL 30d após disconnect via job background)
- Webhook handler estende uazapi `event=messages` (3 shapes) + persiste em batch via upsert dedup
- `GET /api/whatsapp/status`: counts em tempo real (msgs/conversas/last_message_at)
- `POST /api/reports/generate`: trigger on-demand com janela 7/15/30/60 dias + rate limit 1/min + mínimo 10 msgs
- Worker F3 reusado via `report_id` opcional + adapter `_build_extracted_payload` que monta `ExtractedPayload` direto do `captured_messages`
- TTL cleanup loop 24h em background (`workers/ttl_cleanup.py`)
- Frontend: `WhatsAppPage` com 4 estados visuais (loading/disconnected/connected_no_messages/connected_with_data + warning 24h), `GenerateReportModal` com radio 7/15/30/60, `ReportsListPage` mostra `period_days` por item, `useWhatsappStatus` polling 5s
- Original F4 "Frontend Integration" do plano antigo foi absorvido por F2+F3 (~80%, falta só route guard) — renomeada pra esta feature de pivot.

**Bugs resolvidos no smoke (2026-05-18..19):**
- `42P10` no insert_many: PostgREST `upsert(on_conflict='cols')` não casa com partial unique index `WHERE raw_message_id IS NOT NULL` → trocado por plain INSERT + dedup batch em Python + fallback row-by-row em 23505 (commit `3ca748e`).
- Instâncias morrendo 1-2min pós-connect: `extract_30d_pipeline` legado (F1 deprecated) ainda disparava no handler `connected` e chamava `delete_instance` em qualquer 500 do `/chat/find` → callsite removido + `_fail` só deleta em `code='banned'` (commit `3ca748e`).
- Webhook URL com `addUrlEvents`/`addUrlTypesMessages: true` gerava 404 — corrigido pra `false` (commits anteriores).

**Commits-chave:** `abb01aa` (specs), `689e797`...`7612d0e` (Waves 1-5), `3ca748e` (fixes smoke).

**F5 — Last-N per Chat & Always-Generates Report** — ✅ COMPLETE (smoke 2026-05-19)
- **Por quê**: F4 quase passou, mas três portões mataram a UX: threshold `min 10 msgs` na route, short-circuit `< 5 msgs` no worker, prompt instruindo "recuse se não é saúde". Resultado: user conecta WhatsApp → tela "gerando" → 0 relatório → abandona. F5 destrava removendo TODOS esses portões.
- **Pull strategy nova** (`pull_last_n_per_chat`): em vez de filtrar por janela temporal (que uazapi paid recusa), pega as últimas N msgs de CADA conversa. Default 30. Funciona em qualquer tier.
- **Relatório sempre gera**: route não bloqueia mais por volume; worker só pula LLM quando exatamente 0 mensagens; prompt reescrito pra produzir diagnóstico mesmo com sample mínima.
- **`scope_warning` field**: quando segmento detectado != saúde/odonto, LLM preenche 1 sentença descrevendo o segmento real (ex: "Detectamos atendimento de pet shop"), frontend mostra banner amarelo acima do HeroCard, relatório existe mesmo assim.
- **Observabilidade**: `ReportGeneratingState` (tela "gerando") agora pola `/api/whatsapp/uazapi-stats` a cada 3s e mostra "X conversas detectadas · Y mensagens lidas" em tempo real. Sem timer falso.
- **Modal redesenhado**: `GenerateReportModal` troca 7/15/30/60 dias por 10/20/30/50 msgs por conversa.

**Arquivos-chave:** specs em `.specs/features/f5-last-n-per-chat/`. Backend: `app/workers/extract.py` (+pull_last_n_per_chat), `app/modules/captured_messages/repository.py` (+query_last_n_per_chat via RPC), `app/modules/captured_messages/schemas.py` (ReportMode/ReportNPerChat), `app/modules/reports/{service,routes,schemas,prompts/*}.py`, `app/workers/report.py`. Frontend: `lib/reports.js`, `lib/whatsapp.js` (intervalMs override), `screens/dashboard/{GenerateReportModal,ReportGeneratingState,ReportDetailPage,DashboardPage,WhatsAppPage}.jsx`, `components/report/ReportTopbar.jsx`.

**Bugs resolvidos no smoke (2026-05-19):**
- Relatório gerava sempre "10 msgs em 2 conversas" mesmo com 8.6k msgs no DB: `query_last_n_per_chat` fazia `.order(wa_chatid).limit(implicit 1000)` em Python — top chat com 2861 msgs dominava primeira página alfabética → só 7 chats vistos → 2 sobreviviam ao filtro de grupos. **Fix arquitetural**: migration `f5_1_top_n_messages_per_chat_rpc` (window function `ROW_NUMBER() OVER (PARTITION BY wa_chatid ORDER BY ts DESC)`) — query agora devolve 858 msgs em 47 chats (commit `ad64b99`).
- Dashboard mostrava "1.000 mensagens" com 8.6k reais: PostgREST default Range 0-999 trunca todo `.select()` sem `count="exact"`. **Fix**: stats_for_session/stats_for_user usam `count="exact"` header (commit `fe1ea8c`).
- ReportTopbar com mock "Clínica São Bento • Cardiologia • 4 atendentes • 28 dias" → dados reais via useMe + payload (commit `191f0e8`).
- Contagem "0 mensagens" travada na tela de geração → animação 0→total via `useAnimatedCount` ease-out 3s (commit `85f88df`).
- `reports_period_days_check` violation com `n_per_chat=50` → service só atualiza `period_days` quando `mode='window_days'` (commit `fe1ea8c`).

**Commits-chave:** `abb01aa` (F4 specs), `e0c06f9` (F5 spec+code), `3ca748e` (fixes smoke F4), `351ec41` (dashboard LiveStats), `fe1ea8c` (stats count exact + period_days fix), `ad64b99` (RPC window function), `191f0e8` (ReportTopbar real), `85f88df` (contagem animada).

**F6 — DX & Docs** — ✅ COMPLETE (2026-05-19)
- `README.md` na raiz: visão geral, stack, setup local passo-a-passo, migrações, estrutura, fluxos, comandos úteis, deploy, troubleshooting
- `backend/.env.example` e `frontend/.env.example` refinados com todos os campos atuais + comentários explicativos + referências a decisões/lições do STATE
- `package.json` raiz com `npm run dev` (sobe backend + frontend em paralelo via `concurrently`) + scripts `install:all`, `test:backend`, `lint:frontend`, `build:frontend`
- `.gitignore` atualizado pra `node_modules/`, `frontend/dist/`, logs

**F7 — Route guards (opcional)** — guard de rota autenticada em /app/*. Resíduo do plano original F4 "Frontend Integration" não absorvido por F2/F3. Pequeno (~30 min). Não bloqueia M1 mas vale fazer antes de prod pública.

---

## M2 — Polimento e relatórios recorrentes (pós-task)

**Goal:** Tornar a UI já existente do dashboard funcional com dados reais e habilitar geração recorrente.

### Features
- **Recurring Reports** — PLANNED — usar a UI existente em `/app/reports` (toggle 7/15/30/60 dias) para agendar regenerações.
- **Dashboard Real Data** — PLANNED — substituir mocks de `/app/dashboard` pela agregação dos relatórios persistidos.
- **WhatsApp Reconnect UX** — PLANNED — `/app/whatsapp` reflete estado real da sessão e permite desconectar/reconectar.

---

## Future Considerations

- Multi-WhatsApp por clínica (recepção 1, recepção 2…)
- Integração com CRMs (HubSpot, RD Station) para empurrar leads automaticamente.
- Agente de IA da Medzee respondendo no WhatsApp da clínica (CTA do relatório vira produto).
- Análise de sentimento por atendente (quem performa melhor).
- Export PDF do relatório.
