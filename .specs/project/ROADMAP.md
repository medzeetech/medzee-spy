# Roadmap

**Current Milestone:** M1 — Fluxo ponta a ponta funcional
**Status:** In Progress

---

## M1 — Fluxo ponta a ponta funcional

**Goal:** Usuário lê o QR em `/spy`, conecta o WhatsApp, preenche cadastro, e chega autenticado no relatório real gerado pelos dados dos últimos 30 dias.
**Target:** entrega da task descrita em `contexto_medzee_spy.mc`.

### Features

**F1 — WhatsApp Ingestion** — IN PROGRESS
- Sidecar Node.js com Baileys que expõe REST + WebSocket para o FastAPI
- Geração de sessão por usuário e emissão do QR Code para o frontend
- Detecção de leitura do QR e abertura da sessão
- Extração de mensagens dos últimos 30 dias de todas as conversas
- Cleanup da sessão após extração (descarte de tokens, sem persistência de conteúdo)

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
