# F4 — Forward-Capture & On-Demand Reports · Spec

> O quê + porquê. Design técnico em [design.md](design.md). Atomização em [tasks.md](tasks.md).

## Contexto

F1 era pull-history: scan QR → puxa últimos 30 dias do WhatsApp → gera relatório uma vez. Conceito elegante, dependia de `/chat/find` funcionar. **Falhou em produção** porque:
- uazapi free tier não suporta `/chat/find` (500 permanente — não é timing, é feature paga)
- uazapi paid tier suporta mas exige plano $$ + tem quota de instâncias que estourou nos testes

**F4 pivota** para forward-capture com uazapi paid:
1. User conecta WhatsApp uma vez (sessão persistente, sem TTL)
2. Cada mensagem nova (entrada e saída) → uazapi webhook → backend → `medzee_spy.captured_messages`
3. Quando user quiser, clica **"Gerar relatório agora"** e escolhe janela (7/15/30/60 dias)
4. Worker F3 (reusado) lê do DB → métricas + Claude → relatório

Trade-off explícito vs F1:
- ✅ Funciona com uazapi paid sem depender de `/chat/find`
- ✅ Suporta múltiplos relatórios ao longo do tempo (comparar 7 vs 30 dias, evolução)
- ⚠️ **Time-to-value**: primeira semana de dados vazia. Demo "scan e veja em 5 min" some.
- ⚠️ **Revoga D4** do STATE.md (msgs persistidas no DB). Mitigações abaixo.

Pré-requisitos confirmados pelo user:
- ✓ uazapi paid contratado (`UAZAPI_BASE_URL` + `UAZAPI_ADMIN_TOKEN` paid no Railway)
- ✓ Revogar D4 com TTL + RLS aceito
- ✓ Geração manual via botão (não cron)
- ✓ Reter mensagens entre relatórios (permite re-rodar)
- ✓ TTL: 30 dias após desconexão do WhatsApp
- ✓ Período do relatório: user escolhe 7/15/30/60 dias
- ✓ Criptografia: RLS + TLS nativos do Supabase (sem pgcrypto no MVP)

## User Stories

### US-01 — Conexão única e persistente
**Como** dono de clínica que já se cadastrou,
**quero** conectar meu WhatsApp **uma única vez** e manter ele coletando dados,
**para** não precisar reescanear QR toda vez que quiser um relatório.

**Acceptance:**
- Tela `/app/whatsapp` (já existe parcialmente) mostra QR quando desconectado
- Após scan, status muda pra "Conectado · X conversas · Y mensagens · há Z dias"
- Sessão sobrevive a reinícios do Railway (uazapi mantém vivo)
- Se uazapi cair, frontend detecta e mostra "Reconectar" sem perder dados anteriores

### US-02 — Cada mensagem nova é capturada
**Como** sistema,
**quero** receber webhook a cada mensagem WhatsApp do cliente da clínica,
**para** acumular o dataset que vai alimentar relatórios.

**Acceptance:**
- Webhook `EventType=messages` (ou equivalente) é tratado pelo backend
- Cada mensagem (entrada e saída) gera 1 row em `medzee_spy.captured_messages`
- Dedup via `(whatsapp_session_id, raw_message_id)` unique — webhook pode repetir sem duplicar
- Filtra mensagens não-texto (mídia, áudio, sticker — só metadata) no MVP

### US-03 — Dashboard com status de coleta
**Como** dono que volta ao app,
**quero** ver no dashboard **quantos dados já tenho coletados** e quanto falta pra um relatório útil,
**para** saber quando faz sentido gerar.

**Acceptance:**
- Card no `/app/dashboard` (ou `/app/whatsapp`): "Conectado há X dias · Y conversas · Z mensagens"
- Indica se já tem volume mínimo (ex: ≥ 30 msgs) pra relatório fazer sentido
- Botão **"Gerar relatório agora"** dispara fluxo da US-04

### US-04 — Gerar relatório on-demand com janela escolhida
**Como** dono,
**quero** clicar "Gerar relatório" e escolher se quero análise dos **últimos 7, 15, 30 ou 60 dias**,
**para** comparar evolução do atendimento ao longo do tempo.

**Acceptance:**
- Modal/dropdown: "Análise dos últimos: [7 / 15 / 30 / 60] dias"
- POST `/api/reports/generate {period_days: N}` cria row `status='generating'`
- Worker lê `captured_messages WHERE user_id=? AND ts > now() - N days`
- Pipeline F3 inteira (métricas, sampling, Claude, compose) rodando sobre a janela
- Frontend transita pra `/app/reports/<id>` com polling
- Janela do relatório fica gravada (`period_days` na row reports)

### US-05 — Re-rodar relatório sobre mesma janela
**Como** dono,
**quero** poder gerar **novos relatórios** sempre que quiser, mesmo sobre o mesmo período,
**para** ver se mudanças no atendimento melhoraram métricas.

**Acceptance:**
- Cada clique em "Gerar relatório" cria **novo** row em reports (não sobrescreve antigos)
- Lista `/app/reports` mostra todos historicamente, ordenados por data
- Cada item da lista mostra a `period_days` do relatório (ex: "Análise de 30 dias · 16 mai 2026")

### US-06 — Desconectar + TTL
**Como** dono que decide parar de usar,
**quero** desconectar o WhatsApp e ter meus dados removidos automaticamente após período razoável,
**para** privacidade.

**Acceptance:**
- Botão "Desconectar WhatsApp" em `/app/whatsapp` chama uazapi DELETE /instance + marca session disconnected
- Job de TTL (cron diário) deleta `captured_messages` cujo `whatsapp_session_id` está disconnected há > 30 dias
- Relatórios já gerados são **mantidos** (deletar relatórios seria perda de valor — só msgs originais somem)

### US-07 — Reconectar sem perder histórico
**Como** dono que desconectou por engano (ou uazapi caiu),
**quero** poder reconectar e continuar de onde parei,
**para** o histórico anterior não sumir.

**Acceptance:**
- "Reconectar" cria nova `whatsapp_session_id` linkada ao mesmo `user_id`
- Mensagens antigas (da session anterior) continuam acessíveis pela query `user_id`
- TTL só dispara se ficar **30 dias inteiros** sem reconectar (não em cada disconnect curto)

## Requirements (rastreáveis)

### Persistência

- **F4-01** — Tabela `medzee_spy.captured_messages`: PK `id uuid`, FK `user_id → auth.users(id) on delete cascade`, FK `whatsapp_session_id → whatsapp_sessions(id) on delete cascade`, `wa_chatid text not null`, `contact_name text`, `ts timestamptz not null`, `is_from_me boolean not null`, `message_type text default 'text'`, `text text`, `raw_message_id text`, `created_at timestamptz default now()`.
- **F4-02** — Unique index em `(whatsapp_session_id, raw_message_id)` pra dedup.
- **F4-03** — Index `(user_id, ts desc)` pra queries de relatório por janela.
- **F4-04** — RLS owner-only por `auth.uid() = user_id`. Service role pode insert (webhook não tem JWT do user).
- **F4-05** — Trigger updated_at em `captured_messages` (não estritamente necessário mas consistência).
- **F4-06** — Coluna nova em `reports`: `period_days int` (default 30, range [7, 60]).

### Webhook handler

- **F4-07** — Webhook handler reconhece `EventType=messages` (verificar shape real da uazapi paid — provável `data.messages[]` ou `messages[]`). Cada msg vira insert.
- **F4-08** — Filtra mensagens não-texto (`type != 'text'`) no MVP — só persiste counting. Mídia pode entrar em fase futura.
- **F4-09** — Webhook tolerante a payload variado (paid pode mandar shape diferente do free). Logger faz fingerprint do shape novo na primeira ocorrência pra debug.
- **F4-10** — Failover: erro no insert NÃO propaga 5xx pro webhook (always 200 OK) — uazapi senão entra em retry storm.

### Endpoint generate

- **F4-11** — `POST /api/reports/generate` autenticado. Body: `{period_days: int}` (7|15|30|60). Cria row `status='generating'`, dispara worker async, retorna `{report_id}` 200.
- **F4-12** — Rate limit no `/generate`: 1 por minuto por user (anti-abuse).
- **F4-13** — Worker F3 reusado: monta `ExtractedPayload` a partir das rows `captured_messages` da janela. Mesma pipeline metrics + Claude + compose.

### Status endpoint

- **F4-14** — `GET /api/whatsapp/status` autenticado. Retorna `{connected: bool, session_id?, connected_since?, message_count: int, conversation_count: int, last_message_at?}`. Frontend usa pra renderizar card do dashboard.

### TTL job

- **F4-15** — Cron diário (Railway cron job ou simple background task na startup): SELECT sessions com `status='disconnected' AND updated_at < now() - 30 days`; DELETE captured_messages WHERE whatsapp_session_id IN (...). Loga `cleanup.captured_messages.deleted count=N`.
- **F4-16** — TTL não toca `reports` (relatórios sobrevivem).

### Frontend

- **F4-17** — `/app/whatsapp` mostra card com:
  - Estado desconectado: QR + "Escaneie pra começar a coletar"
  - Estado conectado: "Conectado há X dias · Y conversas · Z mensagens · [Desconectar]"
  - Estado intermediário: skeleton enquanto polla `/api/whatsapp/status`
- **F4-18** — `/app/dashboard` ou `/app/reports` ganha botão **"Gerar relatório agora"** que abre modal/dropdown de janela (7/15/30/60). Submit → `POST /api/reports/generate` → navega pra `/app/reports/<id>`.
- **F4-19** — Lista `/app/reports` mostra `period_days` em cada item (ex: "Análise de 30 dias · 16 mai 2026").
- **F4-20** — `/spy` continua existindo mas agora é entry-point pra "primeira conexão" (user novo). Fluxo: QR → conecta → form signup → redireciona pra `/app/dashboard` com estado "conectado, ainda sem dados, aguardando primeiras mensagens".

### Decisões revogadas/alteradas

- **F4-21** — D4 do STATE.md revogado: mensagens **são** persistidas. Substituição: "Mensagens persistidas em `medzee_spy.captured_messages` com TTL de 30d após desconexão; conteúdo cifrado at-rest via Supabase storage encryption; RLS owner-only. Logs nunca incluem texto bruto."
- **F4-22** — F1 extract worker (`workers/extract.py::extract_30d_pipeline`) vira **deprecated** mas mantido como dead code por 1 ciclo (caso queiramos reabilitar pull-history pra paid). Documentar em STATE.md.

## Edge cases

- **EC-01** — User conecta, recebe N msgs, nunca clica "Gerar". Webhook continua acumulando indefinidamente até a janela TTL. OK.
- **EC-02** — User clica "Gerar" com **0 mensagens coletadas** (recém-conectou). Backend retorna 422 `not_enough_data` (mínimo: 10 msgs). Frontend mostra "Aguarde algumas conversas antes de gerar análise".
- **EC-03** — User clica "Gerar" 2× rápido. Segundo clique cai no rate-limit (F4-12) → 429. Frontend mostra "Aguarde 1 minuto entre relatórios".
- **EC-04** — Webhook entrega msg duplicada (uazapi retry). Unique index F4-02 silencia o duplicate insert.
- **EC-05** — uazapi paid cai, conexão WhatsApp morre. Webhook deixa de chegar. Frontend status fica "Conectado há X dias" mas `last_message_at` fica velho. UX: warning amarelo "Sem novas mensagens há 24h — verifique conexão" quando `last_message_at > 24h`.
- **EC-06** — User desconecta e reconecta no mesmo dia. Nova `whatsapp_session_id`, mas msgs antigas continuam acessíveis via `user_id`. TTL reseta (nada deletado porque user reconectou < 30 dias).
- **EC-07** — Múltiplos usuários sobre o mesmo WhatsApp (clínica com vários donos). MVP: 1 user → 1 WhatsApp. Multi-user em backlog.
- **EC-08** — Volume gigantesco (10k msgs/janela). Sampling de F3 já cobre via `sample_conversations(payload)` — corta no budget de 150k chars.
- **EC-09** — Webhook chega ANTES da row em `whatsapp_sessions` estar persistida (race rara). Insert falha por FK constraint → loga warning, joga fora. Próxima msg do mesmo chat vai funcionar.

## Out of scope (backlog)

- Geração automática de relatório (cron a cada 7 dias) — manual no MVP
- Aviso/notificação ao user quando "atingiu volume mínimo pra um relatório"
- Cripto column-level (pgcrypto) — backlog se compliance pedir
- Multi-WhatsApp por clínica (recepção 1, recepção 2)
- Export/download do relatório em PDF
- Comparativo temporal entre relatórios na mesma tela ("evolução do score")
- Filtros (excluir grupos específicos, ignorar contatos não-leads, etc)

## Cobertura por requisito

| F4 | User Story | Componente |
|---|---|---|
| F4-01..06 | US-02, US-06 | Migration `f4_1_captured_messages` |
| F4-07..10 | US-02 | Webhook handler extend |
| F4-11..13 | US-04, US-05 | Endpoint `/reports/generate` + worker adapter |
| F4-14 | US-03, US-07 | Endpoint `/whatsapp/status` |
| F4-15..16 | US-06 | Background TTL job |
| F4-17..20 | US-01, US-03, US-04, US-05 | Frontend `/app/whatsapp`, dashboard, reports |
| F4-21..22 | Governance | STATE.md update |
