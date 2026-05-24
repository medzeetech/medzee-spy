# F3 — Report Processing · Spec

> O quê + porquê. Sem código aqui — o "como" mora em [design.md](design.md).
> Atomização em tasks fica em [tasks.md](tasks.md).

## Contexto

F1 entrega um `ExtractedPayload` em memória (lista de conversations × messages dos últimos 30 dias do WhatsApp da clínica). F2 cria a identidade durável do dono da clínica (`auth.users` + `medzee_spy.users_profile`) e linka a sessão WhatsApp ao `user_id`. **F3 é onde o produto entrega valor**: pega as mensagens cruas, calcula métricas determinísticas, chama a LLM (Claude) pra extrair insights estruturados, e devolve um relatório comercial pro frontend exibir no `/app/reports/{id}`.

Pré-requisitos operacionais (confirmados):
- ✓ Anthropic API key configurada (`ANTHROPIC_API_KEY` já existe no `.env`, validada na startup do main)
- ✓ `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-4-6` configurados em `core/config.py`
- ✓ `users_profile.clinic_segment` já existe (F2) — fonte da segmentação prompt + benchmark
- ⏳ Habilitar leaked password protection no Supabase (B2) — backlog, não bloqueia F3

## User Stories

### US-01 — Dono da clínica vê o relatório real após signup
**Como** dono de uma clínica que acabou de conectar o WhatsApp + se cadastrar,
**quero** ver na tela `/app/reports/latest` o relatório real gerado a partir das minhas conversas dos últimos 30 dias,
**para** entender onde estou perdendo oportunidades, qual o tempo de resposta da equipe, e quais perguntas dos pacientes ficam sem resposta.

**Acceptance:**
- Em ≤ 60s após o sucesso do extract pipeline (F1), o relatório está pronto e visível.
- Se o LLM ainda estiver processando, o frontend mostra estado "Gerando análise…" com polling em 2s.
- Toda métrica determinística (counts, response time, heatmap, funnel) é calculada a partir das mensagens reais — sem mocks.
- Oportunidades, objeções, FAQs e diagnóstico vêm de LLM real com prompt segmentado por especialidade.

### US-02 — Relatório fica persistido e linkado ao usuário
**Como** dono que volta dias depois pelo `/login`,
**quero** acessar `/app/reports` e ver meus relatórios passados,
**para** revisar análises antigas e comparar com novos diagnósticos.

**Acceptance:**
- `medzee_spy.reports` tem 1 row por sessão WhatsApp consumida, com `user_id`, `whatsapp_session_id`, `payload jsonb`, `status`, `prompt_version`, `model`, `generated_at`.
- RLS owner-only: usuário só vê os próprios relatórios.

### US-03 — Frontend dashboard consome relatório real
**Como** usuário no dashboard `/app/reports/:id` e `/app/reports/latest`,
**quero** ver as 9 seções da UI populadas com dados reais (heatmap, funnel, response time, oportunidades, objeções, FAQs, sentiment, diagnóstico) e o benchmark setorial Medzee.
- `ReportsListPage` mostra a lista paginada do user (date, message_count, score).
- `ReportDetailPage` busca via `GET /api/reports/:id`.

### US-04 — Benchmark Medzee posicionado de forma honesta
**Como** usuário olhando a seção de Benchmark,
**quero** entender que os números de comparação são uma estimativa setorial baseada na rede Medzee, não um dado certificado da minha concorrência exata,
**para** confiar no produto sem ser enganado por números inventados.

**Acceptance:**
- Label do benchmark usa: **"média de clínicas de {especialidade} conectadas à Medzee*"**
- Asterisco no rodapé do card explicita: "*estimativa baseada em pesquisas setoriais da rede Medzee; atualizado periodicamente conforme a base cresce."
- Valores hardcoded em `app/modules/reports/benchmarks.py`, por `clinic_segment` (`saude`, `odonto`, `outro`).

### US-05 — Extract robusto contra timing do uazapi free (B3)
**Como** dono que acabou de scanear o QR,
**quero** que o extract pipeline funcione mesmo no plano free do uazapi,
**para** que o relatório real seja gerado sem precisar testar 3-4 vezes.

**Acceptance:**
- Após o webhook `connected` chegar, o extract aguarda **5 segundos** antes do primeiro `GET /chat/find`.
- Em 5xx do uazapi, retry com backoff exponencial (3 tentativas: 2s, 5s, 12s).
- Em caso de falha permanente, o relatório é gerado com `status=partial` se houver dados parciais, ou `status=failed` com `error_code='extract_failed'`.

## Requirements (rastreáveis)

### Persistência

- **REPORT-01** — `medzee_spy.reports` tem PK `id uuid`, FK `user_id → auth.users(id) on delete cascade`, FK `whatsapp_session_id → medzee_spy.whatsapp_sessions(id) on delete set null`, `status text not null check in (pending|generating|completed|partial|failed)`, `payload jsonb`, `prompt_version text`, `model text`, `clinic_segment text`, `error_code text`, `message_count int`, `score int`, `created_at timestamptz default now()`, `generated_at timestamptz`, `updated_at timestamptz`.
- **REPORT-02** — RLS habilitado. Política owner-select e owner-update por `auth.uid() = user_id`. Service role pode inserir (pré-JWT).
- **REPORT-03** — Índice em `(user_id, created_at desc)` pra acelerar `latest`.
- **REPORT-04** — Trigger `updated_at` reusando `medzee_spy.set_updated_at()`.

### Pipeline + métricas

- **REPORT-05** — Métricas determinísticas calculadas no backend (Python, sem LLM): `message_count`, `conversation_count`, `response_time_distribution` (buckets: <5min, 5-30min, 30min-2h, 2h-24h, >24h), `heatmap` (dia da semana × período do dia: madrugada/manhã/tarde/noite), `funnel` (4 estágios: leads_totais, respondidos, conversa_qualificada >3 mensagens trocadas, conversao_estimada — heurística baseada em palavras-chave de agendamento).
- **REPORT-06** — `score` (0-100) calculado por fórmula ponderada: response_time (35%) + funnel_conversao (30%) + response_rate (20%) + message_volume (15%). Normalização por buckets fixos.
- **REPORT-07** — LLM gera 5 seções estruturadas (JSON schema enforcado): `opportunities` (top 5 com `context`, `reason`, `value_brl`, `when`), `objections` (top 3 com `label`, `pct`, `count`), `faqs` (top 5 com `q`, `count`), `sentiment` (3 buckets: positive/neutral/negative com `value` 0-100), `diagnostic_summary` (parágrafo curto, 3-5 sentenças, tom consultivo).
- **REPORT-08** — LLM recebe contexto segmentado: prompt template varia por `clinic_segment` ('saude' | 'odonto' | 'outro'), com terminologia específica da área.
- **REPORT-09** — Sampling pra controle de custo: se `message_count > 800`, amostrar inteligente (top conversas por volume + amostra aleatória estratificada) antes de passar pra LLM. Hard cap: 60k tokens de input.
- **REPORT-10** — `prompt_version` persistido (semver tipo `v1.0.0`) pra reprodutibilidade quando trocarmos prompts.

### Trigger + worker

- **REPORT-11** — Geração disparada **async** logo após `extract_30d_pipeline` salvar o payload no `session_store`. Worker novo `app/workers/report.py::generate_report_pipeline(session_id, payload)` cria o row em `medzee_spy.reports` com `status='generating'`, roda métricas + LLM, persiste com `status='completed'` ou `status='failed'`.
- **REPORT-12** — `whatsapp.service.consume_extracted` (F2 bridge) agora ALSO faz link do `report.user_id`: se já existir um report com `whatsapp_session_id == sid`, popula seu `user_id`. Se não existir (raça: signup chegou antes do extract acabar), o worker cria o row já com o `user_id` linkado quando acabar.
- **REPORT-13** — Hard timeout de **120s** pra geração do relatório (LLM + métricas). Acima disso, `status='failed'`, `error_code='llm_timeout'`.

### B3 Fix

- **REPORT-14** — `extract_30d_pipeline` aplica `asyncio.sleep(5)` após confirmar `connected` antes do primeiro `/chat/find`.
- **REPORT-15** — Wrapper de retry no `uazapi.list_chats` e `uazapi.list_messages`: em 5xx, retry 3× com backoff exponencial (2s, 5s, 12s). 4xx propaga imediatamente.

### REST

- **REPORT-16** — `GET /api/reports/latest` autenticado (Bearer JWT). Retorna o report mais recente do user (`order by created_at desc limit 1`). 404 se nenhum existe. 200 `SuccessResponse[ReportPayload]` se sim.
- **REPORT-17** — `GET /api/reports/{id}` autenticado. RLS protege contra leitura de outro user; service também filtra explicitamente por `user_id` defesa em profundidade. 404 se inexistente ou de outro user (indistinto pra evitar enumeration).
- **REPORT-18** — `GET /api/reports/` autenticado. Lista paginada do user (default 20 por página, ordenada por `created_at desc`). Retorna campos resumidos (`id, created_at, message_count, score, status`), sem o `payload` completo.

### Frontend

- **REPORT-19** — `/app/reports/latest`: hook `useReportPolling(latest|id)` faz polling de **2s** em `GET /api/reports/latest` enquanto `status in ('pending', 'generating')`. Para de pollar quando atinge estado terminal (`completed`, `partial`, `failed`). Hook retorna `{ status, payload, elapsedMs, error }`.
- **REPORT-19a** — UI de carregamento (`ReportGeneratingState` component) NUNCA pode ser um spinner mudo. Apresenta:
  - **Mensagens rotativas baseadas em tempo decorrido client-side** (porque o backend não emite progresso fino do LLM):
    - 0-15s: *"Analisando suas conversas dos últimos 30 dias…"*
    - 15-45s: *"Identificando oportunidades e padrões de atendimento…"*
    - 45-90s: *"Quase lá — finalizando o diagnóstico…"*
    - \> 90s: *"Está demorando mais que o normal. Pode continuar aguardando ou tentar atualizar em alguns minutos."* + botão **Atualizar**
  - Barra de progresso fake crescendo de 0% → 80% nos primeiros 60s (curva ease-out), depois marca-passo lento até 95% — nunca chega a 100% até o backend confirmar `completed`.
  - Identidade visual coerente com `GeneratingScreen.jsx` do F1 (gradient dark/orange, brand consistente), mas mensagens deixam claro que **é uma fase nova** (análise IA, não download de mensagens).
- **REPORT-20** — `/app/reports/:id`: busca via `GET /api/reports/:id`, popula as 9 seções com dados reais do `payload`. Em `status='failed'`, mostra fallback gentil ("Não conseguimos gerar essa análise. Tente reconectar o WhatsApp em /spy.") + botão pra `/spy`. Em `status='partial'`, renderiza relatório completo + banner discreto no topo: "*análise baseada em parte das conversas (problema temporário de conexão com o WhatsApp)".
- **REPORT-21** — `/app/reports`: lista paginada via `GET /api/reports/`, cada item com link pro detalhe. Reports em `status='generating'` na lista também usam `ReportGeneratingState` em mini-versão (chip animado em vez do score).
- **REPORT-22** — `BenchmarkSection` recebe `clinic_segment` via prop e renderiza label "média de clínicas de {especialidade} conectadas à Medzee*" + asterisco no rodapé.

## Edge cases

- **EC-01** — Race: signup chega antes do extract terminar. F2 retorna `report_pending=true`; user navega pra `/app/reports/latest`; polling encontra o report quando ele aparecer.
- **EC-02** — Race: extract termina mas user nunca completa signup. Report fica `status='completed'` mas `user_id=null` por 24h, depois TTL job remove. (M1: cron manual ou simplesmente deixar até alguém limpar. Backlog: cleanup job.)
- **EC-03** — LLM retorna JSON malformado. Tentamos parse + 1 retry com prompt corretivo ("output was not valid JSON, please return only valid JSON matching the schema"). Se 2ª falha: `status='failed'`, `error_code='llm_invalid_json'`.
- **EC-04** — Extract falha 100% (B3 + retry esgotado). Worker grava `status='failed'`, `error_code='extract_failed'`. Frontend mostra fallback.
- **EC-05** — Extract retorna parcial (alguns chats deram 5xx, outros não). Worker gera relatório com o que tem + `status='partial'`. Frontend mostra warning sutil "*análise baseada em X de Y conversas".
- **EC-06** — User acessa `/api/reports/:id` de outro user. Service filtra por `user_id` → 404 (indistinto).
- **EC-07** — Anthropic API down ou rate limit. Retry 3× com backoff. Persistente: `status='failed'`, `error_code='llm_unavailable'`.
- **EC-08** — Clínica com volume baixo (<50 mensagens em 30 dias). Métricas duras ainda funcionam (com menos confiança estatística); LLM recebe contexto com aviso "amostra pequena, foque em padrões qualitativos". Frontend pode mostrar nota "*análise baseada em sample reduzido".

- **EC-09** — **User completa signup ANTES do LLM terminar** (cenário mais comum). Fluxo:
  1. F2 retorna `report_pending=true` no `SignupResponse`.
  2. LeadFormScreen navega pra `/app/reports/latest`.
  3. Hook `useReportPolling` consulta a cada 2s.
  4. Enquanto `status in ('pending', 'generating')`, `ReportGeneratingState` é renderizado com a sequência de mensagens rotativas (REPORT-19a).
  5. Quando o backend vira `completed`, próximo poll detecta → frontend renderiza relatório real sem refresh manual.
  6. Tempo típico esperado: 20-60s; com B3 fix + boa conexão, ~30s.

- **EC-10** — **User clica F5 / abre nova aba em `/app/reports/latest` durante a geração.** Polling reinicia do zero (sem persistência de `elapsedMs`). As mensagens rotativas recomeçam — aceitável porque é raro e o gain de complexidade pra persistir progresso não compensa. Apenas o `> 90s timeout` fica reciclado.

## Out of scope (backlog M2+)

- Cleanup job pra reports órfãos (sem user_id) — manual em M1
- Versionamento de relatórios (re-gerar relatório de uma sessão antiga) — 1 report por sessão em M1
- Comparativo temporal entre relatórios — backlog, depende de M2 (recurring reports)
- Export PDF — backlog
- Refresh manual de relatório existente (regenerar a partir do mesmo payload) — backlog
- LLM streaming pra UX progressiva — polling 2s é suficiente em M1
- Multi-idioma — só PT-BR

## Cobertura por requisito

| REPORT | User Story | Componente principal |
|---|---|---|
| REPORT-01..04 | US-02 | Migration + RLS |
| REPORT-05..06 | US-01 | metrics.py |
| REPORT-07..10 | US-01 | llm_client.py + prompts/ |
| REPORT-11..13 | US-01, EC-01, EC-02 | workers/report.py |
| REPORT-14..15 | US-05, B3 | extract.py + uazapi.py |
| REPORT-16..18 | US-02, US-03 | reports/routes.py |
| REPORT-19..22 | US-03, US-04 | frontend dashboard/* |
