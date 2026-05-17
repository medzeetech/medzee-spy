# F1 — WhatsApp Ingestion

> Conectar o WhatsApp da clínica via QR Code e extrair o histórico dos últimos 30 dias, sem persistir conteúdo.

## Problem statement
Hoje a tela `/spy` gera um QR mockado que aponta para uma URL fixa e o fluxo nunca se conecta de fato ao WhatsApp do usuário. Sem essa conexão real, todo o resto do produto (cadastro, processamento, relatório autenticado) opera sobre dados fictícios e a entrega da task descrita em `contexto_medzee_spy.mc` fica inviável. Precisamos de uma fonte de mensagens reais (últimos 30 dias) entregue ao backend para que o pipeline de relatório tenha matéria-prima.

## Users
- **Médico/gestor da clínica** que lê o QR para liberar a análise — interage com `/spy`.
- **Backend FastAPI** — consumidor das mensagens extraídas para alimentar F2 (auth/persistence) e F3 (LLM).

## Success metrics
- ≥ 95% das tentativas de leitura de QR resultam em sessão `connected` em ≤ 60s (em rede estável).
- Extração de 30 dias devolve resultado em ≤ 90s para clínicas com ≤ 10.000 mensagens no período.
- 0 ocorrência de conteúdo de mensagem persistido em disco (auditoria por grep no DB e nos logs).
- 100% das sessões `extracted` são encerradas em ≤ 5min após o extract (cleanup garantido).

## User stories

### P1 — MVP (precisa entrar em M1)

**US-01 — Solicitar nova sessão de WhatsApp**
Como frontend `/spy`, quero pedir uma nova sessão ao backend e receber um QR Code para exibir, para que o médico consiga escanear.
- WPP-01: WHEN o frontend chama `POST /api/whatsapp/sessions` sem corpo, THEN o backend SHALL retornar `{ sessionId: uuid, qr: string (base64 png ou string-protocolo), status: "pending" }` em ≤ 5s.
- WPP-02: WHEN o sidecar Node não responde em 5s, THEN o backend SHALL retornar `503` com `detail: "sidecar_unavailable"`.
- WPP-03: WHEN o backend cria a sessão, THEN ele SHALL persistir um registro em `medzee_whatsapp_sessions` com `status="pending"`, `sidecar_session=<id do sidecar>`, `user_id=NULL`.

**US-02 — Atualização do QR e status em tempo real**
Como frontend, quero receber atualizações do estado da sessão (novo QR, conectado, extraindo, extraído, falhou) sem polling manual, para refletir progresso na UI.
- WPP-04: WHEN o frontend abre `GET /api/whatsapp/sessions/:id/events` (Server-Sent Events ou WS), THEN o backend SHALL repassar em tempo real os eventos vindos do sidecar: `qr-updated`, `connected`, `extracting`, `extracted`, `failed`, `expired`.
- WPP-05: WHEN o QR do sidecar expira (Baileys reemite a cada ~20s até a leitura), THEN o evento `qr-updated` SHALL carregar o novo QR em `data.qr`.
- WPP-06: WHEN a sessão atinge `connected`, THEN o evento SHALL incluir `{ status: "connected", phone: "<msisdn mascarado, ex.: +55 11 9****-1234>" }`. Número completo NÃO é exposto na resposta.

**US-03 — Extração das mensagens dos últimos 30 dias**
Como backend, quero pedir ao sidecar a extração de todas as conversas dos últimos 30 dias após `connected`, para alimentar o pipeline LLM em F3.
- WPP-07: WHEN a sessão atinge `connected`, THEN o backend SHALL chamar automaticamente `POST <sidecar>/sessions/:id/extract?days=30`.
- WPP-08: WHEN a extração termina, THEN o sidecar SHALL retornar `{ messageCount, conversationCount, conversations: [{ jid, contactName, messages: [{ ts, fromMe, type, text }] }] }` — apenas campos necessários para análise, sem mídia, sem location, sem áudios.
- WPP-09: WHEN o resultado chega ao backend, THEN ele SHALL armazenar o payload em cache em-memória com TTL = 15min, vinculado ao `sessionId`, e atualizar `medzee_whatsapp_sessions.status="extracted"`, `message_count`, `extracted_at`.
- WPP-10: O conteúdo bruto das mensagens NUNCA SHALL ser gravado em disco, log estruturado, ou banco. Auditável: logs só registram contagens e tempos.

**US-04 — Encerramento e cleanup**
Como sistema, quero garantir que toda sessão Baileys aberta seja encerrada após extração ou em caso de falha, para minimizar risco de banimento (R1) e exposição.
- WPP-11: WHEN `status = "extracted"` AND o payload é consumido por F2 (ou TTL expira), THEN o backend SHALL chamar `DELETE <sidecar>/sessions/:id` e marcar `status="consumed"`.
- WPP-12: WHEN ocorrer erro irrecuperável (sidecar 5xx, timeout, banimento detectado), THEN a sessão SHALL ir para `status="failed"`, sidecar é forçado a encerrar (`DELETE`), e o frontend recebe evento `failed` com `code` semântico (`timeout`, `banned`, `qr_expired`, `extract_failed`, `unknown`).
- WPP-13: O diretório de auth state do Baileys (`whatsapp-sidecar/sessions/<id>/`) SHALL ser removido pelo sidecar imediatamente após `DELETE`.

### P2 — Should have

**US-05 — Resiliência a desconexão**
- WPP-14: WHEN o WS frontend ↔ backend cai durante `pending`/`connected`/`extracting`, THEN o frontend SHALL poder reabrir `GET /api/whatsapp/sessions/:id/events` e receber o último estado conhecido como primeiro evento (`replay-last`).
- WPP-15: WHEN o frontend reabre uma sessão já em `extracted` ou posterior, THEN o backend SHALL responder com o último estado e fechar o stream.

**US-06 — Limite de sessões simultâneas por IP**
- WPP-16: WHEN o mesmo IP cria > 3 sessões `pending` em < 5min, THEN o backend SHALL retornar `429 too_many_sessions`.

### P3 — Nice to have

**US-07 — Métricas operacionais**
- WPP-17: Backend SHALL expor `GET /api/whatsapp/_metrics` (autenticado interno) com counts agregados de sessões por status — sem qualquer dado de mensagem.

## Out of scope (desta feature)
- Reaproveitamento da sessão entre dispositivos / persistência longa do `authState`.
- Múltiplos números por usuário.
- Filtros por contato/conversa.
- Envio de mensagens em nome do usuário.
- Extração de mídia, áudios, documentos, status.
- Detecção de "domínio saúde" — fica em F3 (Report Processing).
- Migration das tabelas Supabase (`medzee_whatsapp_sessions`) — entregue em F2 junto das outras tabelas para uma migration única, mas o **schema** já está descrito em `.specs/codebase/ARCHITECTURE.md` e nesta spec.

## Edge cases e tratamentos
- **EC-01** — Usuário não escaneia em 60s: sidecar emite `expired`; backend marca `failed (qr_expired)`; frontend mostra "Tentar novamente" que cria nova sessão.
- **EC-02** — Clínica sem mensagens nos últimos 30 dias: extract retorna `messageCount=0`; status vai para `extracted`; F3 (em outra feature) gera relatório com fallback "dados insuficientes".
- **EC-03** — Mais de 10k mensagens: extract limita a 30 dias mas não a count; se ultrapassar 60s, sidecar deve manter conexão e empurrar progresso (`extracting` com `{ collected: n }`).
- **EC-04** — Conexão derruba durante `extracting`: sidecar tenta `1x` reconectar; se falhar, evento `failed (extract_failed)`.
- **EC-05** — Sidecar reinicia: backend detecta via timeout no health-check e marca todas as sessões ativas como `failed (sidecar_restart)`.
- **EC-06** — Concurrent extract: ignorar segunda chamada de `/extract` no mesmo `sessionId`, retornar `409 already_extracting`.

## Dependências
- **Bloqueia:** F2 (signup precisa do `whatsappSessionId` para linkar `user_id` ao registro existente), F3 (precisa do payload em cache para processar), F4 (frontend `/spy` consome estes endpoints).
- **Não depende de:** F2/F3/F4. Pode ser desenvolvida e testada via Postman/curl isoladamente.
- **Pré-requisitos técnicos:**
  - Decisão D1 (Baileys via sidecar Node) confirmada.
  - Subprojeto `whatsapp-sidecar/` criado.
  - Variáveis `WHATSAPP_SIDECAR_URL`, `WHATSAPP_SIDECAR_TOKEN` adicionadas a `Settings`.

## Requirement traceability

| ID      | Story | Design (será preenchido) | Task (será preenchido) | Test | Status      |
| ------- | ----- | ------------------------ | ---------------------- | ---- | ----------- |
| WPP-01  | US-01 | —                        | —                      | —    | spec'd      |
| WPP-02  | US-01 | —                        | —                      | —    | spec'd      |
| WPP-03  | US-01 | —                        | —                      | —    | spec'd      |
| WPP-04  | US-02 | —                        | —                      | —    | spec'd      |
| WPP-05  | US-02 | —                        | —                      | —    | spec'd      |
| WPP-06  | US-02 | —                        | —                      | —    | spec'd      |
| WPP-07  | US-03 | —                        | —                      | —    | spec'd      |
| WPP-08  | US-03 | —                        | —                      | —    | spec'd      |
| WPP-09  | US-03 | —                        | —                      | —    | spec'd      |
| WPP-10  | US-03 | —                        | —                      | —    | spec'd      |
| WPP-11  | US-04 | —                        | —                      | —    | spec'd      |
| WPP-12  | US-04 | —                        | —                      | —    | spec'd      |
| WPP-13  | US-04 | —                        | —                      | —    | spec'd      |
| WPP-14  | US-05 | —                        | —                      | —    | spec'd (P2) |
| WPP-15  | US-05 | —                        | —                      | —    | spec'd (P2) |
| WPP-16  | US-06 | —                        | —                      | —    | spec'd (P2) |
| WPP-17  | US-07 | —                        | —                      | —    | spec'd (P3) |

## Open questions (gray areas → candidatos a `discuss.md`)
1. **Protocolo do stream frontend ↔ backend** — SSE (mais simples, unidirecional) vs WS (mais flexível, suporta `replay-last` via mensagem inicial). Proposta: **SSE em M1** e migrar para WS se F4 pedir mais interação.
2. **Storage do auth state Baileys** — filesystem local (mais simples) vs Supabase Storage (multi-instância). Proposta: **filesystem local em M1**; sidecar é stateful single-instance. Documentado em STATE.md/D1.
3. **Quem dispara `extract`** — automático ao `connected` (proposta atual, WPP-07) vs manual após signup. Proposta atual minimiza tempo total mas usa cache em memória até o consumo; ok dado o TTL 15min e EC-05.
4. **Mascaramento do número** — só msisdn parcial vs hash determinístico. Proposta: parcial humano-legível (`+55 11 9****-1234`) para a UI; nunca log do número completo.
