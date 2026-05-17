# Roadmap

**Current Milestone:** M1 — Fluxo ponta a ponta funcional
**Status:** In Progress (F1 ✅ done, F2 next)

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

**F2 — Auth & User Persistence** — PLANNED
- Schema Supabase: tabelas `users_profile` e `reports` (prefixadas para coexistir com News)
- Endpoint `POST /api/auth/signup` cria usuário no Supabase Auth + perfil em `users_profile`
- Retorna sessão (`access_token` + `refresh_token`) para o frontend logar automaticamente
- Linka sessão ao `whatsapp_session_id` previamente gerado em F1

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
