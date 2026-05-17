# Roadmap

**Current Milestone:** M1 — Fluxo ponta a ponta funcional
**Status:** In Progress (F1 ✅ done · F2 ✅ code complete, smoke pending · F3 next)

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

**F2 — Auth & User Persistence** — ✅ CODE COMPLETE (2026-05-17, smoke pendente em produção)
- Migration `f2_1_users_profile` aplicada: `medzee_spy.users_profile (user_id PK→auth.users, name, email, phone, ticket_medio, clinic_segment, ...)` + RLS owner-only + trigger updated_at
- `POST /api/auth/signup`: admin.create_user (email_confirm=True) → merge `app_metadata.projects = [..., 'spy']` → insert profile (rollback delete_user on failure) → bridge F1 (`consume_extracted` não-fatal, marca `report_pending=False` + `session_warning` se quebrar) → `sign_in_with_password` retorna o par access/refresh
- `POST /api/auth/login`: 401 indistinto pra invalid_credentials; 403 `user_not_in_spy` se user logado sem tag de projeto
- `GET /api/auth/me` + `PATCH /api/auth/me`: JWT via `get_current_user_id` em `core/security.py`; whitelist de campos no update (rejeita email + user_id)
- Frontend: `src/lib/{supabase,api}.js` (singleton + helper com auth header), `LoginScreen.jsx` standalone (rota `/login`, pre-fill via `?email=`, redirect signup 409 → /login), `LeadFormScreen` real (chama signup, mapeia 422 → field errors, 409 → redirect), botão **Login** top-right na `AgentScreen` (UX entry point pra usuário recorrente)
- 35 testes novos (16 service + 6 repo + 13 routes) — **suite total 91/91 verde**, F1 sem regressão

**Commits-chave:** `b1f3f67` (spec+design+tasks), `8b8cd44` (Wave 1: migration + schemas + exceptions), `5fe3c8c` (Wave 2: repo + security + scaffold + frontend lib), `2c0f177` (Wave 3: AuthService completo), `cd2a55f` (Wave 4: routes + router wiring), `99d29c1` (Waves 5+6: LoginScreen + LeadForm wire + 35 tests).

**F3 — Report Processing** — PLANNED
- Pipeline: mensagens brutas → normalização → agregação de métricas → prompt LLM → relatório estruturado
- Prompt principal focado em clínicas (saúde) + prompt fallback genérico
- Detecção de domínio (saúde vs. outro) por heurística sobre conteúdo das mensagens
- Persistência do relatório (`reports.payload jsonb`) vinculado ao `user_id`
- Endpoint `GET /api/reports/:id` autenticado retorna o payload

**F4 — Frontend Integration** — PLANNED
- `/spy` consome QR real do backend via WS/polling
- `GeneratingScreen` reflete progresso real do processamento
- `LeadFormScreen` envia `POST /api/auth/signup` e armazena sessão
- `ReportScreen` / `/app/reports/:id` consomem dados reais; mocks viram fallback de loading
- Guard de rota autenticada via Supabase session

**F5 — DX & Docs** — PLANNED
- README com setup local (backend + frontend + sidecar) e `.env` documentado
- Script único `make dev` ou `pnpm dev` que sobe os 3 serviços

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
