# F3 — Report Processing · Tasks

> Quebra atômica do [design.md](design.md) em 23 tasks. Tags `[P]` rodam em paralelo via sub-agents.

## Pré-flight (confirmados)

- ✓ `ANTHROPIC_API_KEY` configurada (.env + Railway)
- ✓ `LLM_PROVIDER=anthropic`, `LLM_MODEL=claude-sonnet-4-6` em `core/config.py`
- ✓ `users_profile.clinic_segment` existe (F2) — fonte do segmento
- ✓ Branch `feat/f3-report-processing` criado a partir de `dev`
- ⏳ Confirmar que Anthropic API tem crédito disponível antes do smoke

## Ordem de entrega (waves)

```
Wave 1 (fundação — sequencial)
  T1 → T2

Wave 2 (camadas independentes — paralelizáveis)
  T3 [P]  T4 [P]  T5 [P]  T6 [P]  T7 [P]  T8 [P]  T9 [P]

Wave 3 (B3 fix + orquestrador)
  T10 → T11

Wave 4 (HTTP — sequencial, em paralelo lógico com Wave 3)
  T12

Wave 5 (integração — sequencial)
  T13 → T14

Wave 6 (frontend — paralelizáveis após T12 + T15)
  T15 → (T16 [P]  T17 [P]  T18 [P])

Wave 7 (testes — paralelizáveis)
  T19 [P]  T20 [P]  T21 [P]  T22 [P]  T23 [P]
```

---

## T1 — Migration `f3_1_reports`

**What:** Aplicar a migration que cria `medzee_spy.reports` + indexes + RLS + trigger updated_at.

**Where:** Supabase remoto via `mcp__supabase__apply_migration`.

**Depends on:** — (Wave 1)

**Reuses:** `medzee_spy.set_updated_at()` (F1).

**Done when:**
- [ ] Migration aplicada (success: true)
- [ ] `mcp__supabase__list_tables schemas=["medzee_spy"]` mostra `whatsapp_sessions`, `users_profile`, `reports`
- [ ] `mcp__supabase__get_advisors security` não introduz novos warnings
- [ ] Smoke REST: `curl ... /rest/v1/reports?select=id&limit=1` retorna 200 `[]`

**SQL exato:** seção 3 do design.md.

**Traceability:** REPORT-01, REPORT-02, REPORT-03, REPORT-04.

---

## T2 — Schemas (`reports/schemas.py`)

**What:** Pydantic models de `ReportPayload` + sub-models (Funnel, ResponseTime, Heatmap, Opportunity, Objection, FAQ, Sentiment, Benchmark) + enums `ReportStatus` + response wrappers.

**Where:**
- `backend/app/modules/reports/__init__.py` (marker + docstring)
- `backend/app/modules/reports/schemas.py`

**Depends on:** T1 (lógica, não bloqueante).

**Reuses:** `pydantic.BaseModel`, `SuccessResponse` (não importa aqui — o route envelopa).

**Done when:**
- [ ] `python -c "from app.modules.reports.schemas import ReportPayload, ReportStatus, ReportResponse, ReportSummary, ReportListResponse, FunnelStage, ResponseTimeBucket, HeatmapPeriod, Opportunity, Objection, FAQ, SentimentSlice, BenchmarkMetric; print('ok')"` imprime ok
- [ ] `ReportPayload(...)` aceita um dict completo (sem erros de validação) — smoke num REPL
- [ ] `ReportStatus.COMPLETED.value == 'completed'`
- [ ] Field constraint funciona: `score` rejeita 101 com `ValidationError`

**Tests:** smoke em T19; cobertura indireta em todos os outros testes.

**Traceability:** REPORT-01..REPORT-22 (todos os endpoints/worker usam estes schemas).

---

## T3 — LLM client `[P]`

**What:** Protocol `LLMClient` + adapter `AnthropicClient` usando Messages API + `tool_use` pra forçar JSON estruturado.

**Where:** `backend/app/clients/llm.py`

**Depends on:** — (paralelo)

**Reuses:** `settings.ANTHROPIC_API_KEY`, `settings.LLM_MODEL`, `settings.LLM_PROVIDER` (já em `core/config.py`); `httpx` (já instalado).

**Done when:**
- [ ] `LLMClient` Protocol com `complete_json(system, user, schema, max_tokens, temperature) -> dict`
- [ ] `AnthropicClient` implementa via POST `https://api.anthropic.com/v1/messages` com body que inclui `tools=[{name:'submit_report', input_schema: schema}]` e `tool_choice={type:'tool', name:'submit_report'}`
- [ ] Exceções: `LLMUnavailable` (5xx, timeout, network, 429), `LLMInvalidResponse` (sem bloco tool_use), `LLMError` (4xx ≠ 429)
- [ ] `get_llm_client()` factory: retorna `AnthropicClient` se `LLM_PROVIDER='anthropic'`, senão `NotImplementedError`
- [ ] `py_compile` zero erros
- [ ] Type hints completos

**Tests:** T22 (com `respx`).

**Traceability:** REPORT-07, REPORT-10, EC-07.

---

## T4 — Metrics `[P]`

**What:** Funções puras que computam métricas determinísticas a partir de um `ExtractedPayload`.

**Where:** `backend/app/modules/reports/metrics.py`

**Depends on:** T2 (tipos), `whatsapp.schemas.ExtractedPayload` (F1, já existe)

**Reuses:** nada — funções puras stdlib + datetime + regex.

**Done when:**
- [ ] `compute_message_count(payload) -> int`
- [ ] `compute_conversation_count(payload) -> int` (exclui groups)
- [ ] `compute_response_time_distribution(payload) -> list[ResponseTimeBucket]` — 6 buckets fixos com colors
- [ ] `compute_heatmap(payload) -> list[HeatmapPeriod]` — 4 períodos × 7 dias, valores como média msgs/dia
- [ ] `compute_funnel(payload) -> list[FunnelStage]` — 5 estágios, regex KW_VALUE + KW_BOOKED em `_keywords.py`
- [ ] `compute_score(message_count, response_time_dist, funnel) -> int` — fórmula ponderada 0-100
- [ ] Edge cases tratados: payload vazio (0 msgs), só leads sem resposta, conversa única
- [ ] `py_compile` zero erros

**Tests:** T19.

**Traceability:** REPORT-05, REPORT-06.

---

## T5 — Sampling `[P]`

**What:** Função `sample_conversations(payload) -> list[ConversationPayload]` que filtra grupos, ordena por volume desc, e corta no budget de caracteres (estimativa de tokens).

**Where:** `backend/app/modules/reports/sampling.py`

**Depends on:** T2, `whatsapp.schemas` (F1)

**Reuses:** —

**Done when:**
- [ ] `sample_conversations(payload)` exclui `is_group=True`
- [ ] Ordena por `len(messages)` desc; greedy add até estourar `_MAX_CONVERSATION_CHARS=150_000`
- [ ] Sempre inclui pelo menos 1 conversa mesmo que estoure (defensive)
- [ ] `_truncate_if_needed(conv)` mantém head 10 + tail 20 quando `len(messages) > 30`
- [ ] `_estimate_chars(conv)` soma `len(m.text or '')`
- [ ] Funções helper são privadas (`_` prefix)
- [ ] Type hints completos

**Tests:** T19.

**Traceability:** REPORT-09.

---

## T6 — Benchmarks `[P]`

**What:** Hardcoded `_BENCHMARKS_BY_SEGMENT` + factory `build_benchmarks(...)` que injeta valores da clínica nas 4 métricas conhecidas.

**Where:** `backend/app/modules/reports/benchmarks.py`

**Depends on:** T2

**Reuses:** —

**Done when:**
- [ ] `_BENCHMARKS_BY_SEGMENT` dict com keys `'saude'`, `'odonto'`, `'outro'`, cada um com 4 `BenchmarkMetric` (Tempo 1ª resposta / Taxa conversão / Mensagens sem resposta / Follow-up pós-orçamento) — valores conforme design.md §8
- [ ] `build_benchmarks(clinic_segment, clinic_response_time_h, clinic_conversion_pct, clinic_unanswered_pct, clinic_followup_pct) -> list[BenchmarkMetric]`
- [ ] Segment desconhecido fallback pra `'outro'`
- [ ] Imutabilidade preservada: `.model_copy(update={'clinic': v})` em cada metric
- [ ] Comentário no header citando fontes ("Sebrae 2023, RD Station 2024")

**Tests:** T19 (smoke nos 3 segmentos + fallback).

**Traceability:** REPORT-22.

---

## T7 — Prompts `[P]`

**What:** System prompt base + 3 addenda por especialidade + builder do user prompt + JSON schema do tool.

**Where:**
- `backend/app/modules/reports/prompts/__init__.py` (exports + `build_user_prompt`)
- `backend/app/modules/reports/prompts/base.py` (system prompt comum)
- `backend/app/modules/reports/prompts/saude.py`
- `backend/app/modules/reports/prompts/odonto.py`
- `backend/app/modules/reports/prompts/outro.py`
- `backend/app/modules/reports/prompts/schema.py` (JSON schema do tool — derivado de pydantic via `model_json_schema()` filtrado pros 5 campos LLM)

**Depends on:** T2 (schemas), nothing else.

**Reuses:** `ConversationPayload` (F1)

**Done when:**
- [ ] System prompt base define o papel (Marina, consultora Medzee) e as 5 regras duras + 5 campos do tool
- [ ] `get_system_prompt(clinic_segment) -> str` retorna base + addendum apropriado
- [ ] `build_user_prompt(*, clinic_segment, metrics_snapshot, sampled_conversations) -> str` formata:
  - Seção `## MÉTRICAS DURAS` com counts + percentuais
  - Seção `## CONVERSAS (top-volume + amostra)` com cada conv como `### Conversa P-XXXX (N msgs)` + lista `[ts] LEAD: ...` / `[ts] CLÍNICA: ...`
  - Tag `P-XXXX` gerada deterministicamente a partir do `wa_chatid` (hash → 4 dígitos)
- [ ] `LLM_TOOL_SCHEMA` em `schema.py` é um dict JSON Schema válido cobrindo só `diagnostic_summary, opportunities, objections, faqs, sentiment` com type hints estritos (arrays com `minItems`/`maxItems`, strings com `description`)
- [ ] `PROMPT_VERSION = "v1.0.0"` exportado
- [ ] Tudo PT-BR, tom consultivo

**Tests:** T20 (verifica que prompt sai bem formatado pro input mock; schema é válido).

**Traceability:** REPORT-07, REPORT-08, REPORT-10.

---

## T8 — Repository `[P]`

**What:** CRUD assíncrono pra `medzee_spy.reports`.

**Where:** `backend/app/modules/reports/repository.py`

**Depends on:** T1 (tabela), T2 (tipos)

**Reuses:** `get_supabase_admin_client()`, padrão da `whatsapp/repository.py` (asyncio.to_thread + logs estruturados sem PII).

**Done when:**
- [ ] `async def create_generating(*, whatsapp_session_id, user_id, clinic_segment) -> UUID` — INSERT com status='generating', retorna o uuid criado
- [ ] `async def update_completed(report_id, *, payload, model, prompt_version, message_count, score) -> None` — UPDATE com status='completed' + generated_at=now()
- [ ] `async def update_partial(...)` — análogo mas status='partial'
- [ ] `async def update_failed(report_id, *, error_code) -> None` — status='failed' + error_code, sem payload
- [ ] `async def link_user(whatsapp_session_id, user_id) -> int` — UPDATE SET user_id WHERE whatsapp_session_id=? AND user_id IS NULL, retorna rows afetadas
- [ ] `async def get_by_id(report_id, *, user_id) -> dict | None` — filtra por user_id (defesa em profundidade)
- [ ] `async def get_latest_for_user(user_id) -> dict | None` — order by created_at desc limit 1
- [ ] `async def list_for_user(user_id, *, page, page_size) -> tuple[list[dict], int]` — paginação + count
- [ ] Logs estruturados: `repo.reports.<func>`, sem PII
- [ ] `py_compile` zero erros

**Tests:** T21 (com fake supabase).

**Traceability:** REPORT-01..04, REPORT-11, REPORT-12, REPORT-16..18.

---

## T9 — Test scaffold `[P]`

**What:** Fixtures compartilhadas pros testes do módulo reports.

**Where:**
- `backend/app/tests/reports/__init__.py` (empty marker)
- `backend/app/tests/reports/conftest.py`

**Depends on:** — (paralelo)

**Reuses:** padrão de `tests/auth/conftest.py` (lazy monkeypatch) e `tests/whatsapp/conftest.py`.

**Fixtures necessárias:**

| Fixture | Função |
|---|---|
| `fake_llm` | `AsyncMock(spec=LLMClient)` com `complete_json` retornando um dict válido (5 campos LLM com sample data realista) |
| `fake_llm_factory` | monkeypatch `app.clients.llm.get_llm_client` |
| `fake_repository` | monkeypatch funcs em `app.modules.reports.repository.*` para AsyncMock |
| `sample_extracted_payload` | factory PARAMETRIZÁVEL — `sample_extracted_payload(message_count=200, conversation_count=20, days=30, with_groups=False)` retorna um `ExtractedPayload` realista com timestamps distribuídos na janela |
| `sample_report_payload` | `ReportPayload` válido pra usar em testes de routes/service |

**Done when:**
- [ ] `pytest backend/app/tests/reports/ --collect-only -q` → "no tests collected", sem erros
- [ ] `pytest backend/app/tests/auth/ -q` ainda passa (não interferiu)
- [ ] `pytest backend/app/tests/whatsapp/ -q` ainda passa

**Traceability:** infra dos testes REPORT-*.

---

## T10 — B3 fix (extract.py + uazapi.py)

**What:** Delay de 5s no início do extract + retry com backoff exponencial em 5xx do uazapi.

**Where:**
- `backend/app/workers/extract.py` (uma linha de sleep no início)
- `backend/app/clients/whatsapp/uazapi.py` (wrapper `_retry_5xx` aplicado nos call sites `list_chats` e `list_messages`)

**Depends on:** — (Wave 3, mas independente do T11)

**Reuses:** `UazapiUnavailable`, `asyncio.sleep`, padrão existente do adapter.

**Done when:**
- [ ] `extract.py` início do pipeline: `await asyncio.sleep(5)` com comentário citando B3
- [ ] `uazapi.py` define `_RETRY_DELAYS_S = [2, 5, 12]` e helper `async def _retry_5xx(call, op, **log_extra)`
- [ ] `list_chats` e `list_messages` envolvidos via helper. 4xx propaga imediatamente. 5xx retentado até esgotar; última falha re-raise `UazapiUnavailable`.
- [ ] Cada retry loga warning estruturado com `op`, `attempt`, `delay_next`, sem token
- [ ] `pytest backend/app/tests/whatsapp/test_extract.py -q` ainda passa (testes existentes não devem quebrar — só vão demorar mais 5s no happy path; vale ajustar fixture pra `_DELAY_S = 0` em modo de teste se ficar muito lento)

**Tests:** T23 (cobertura específica do retry).

**Traceability:** REPORT-14, REPORT-15, US-05 (B3).

---

## T11 — Worker `generate_report_pipeline`

**What:** Orquestrador async fire-and-forget que cria report row, computa métricas, chama LLM, persiste resultado.

**Where:** `backend/app/workers/report.py`

**Depends on:** T2, T3, T4, T5, T6, T7, T8.

**Reuses:** Padrão do `extract_30d_pipeline`: estrutura try/except no top + `_kick_off_*` lazy import elsewhere; `asyncio.wait_for` pra hard timeout.

**Métodos/funções:**

```python
async def generate_report_pipeline(
    session_id: UUID, payload: ExtractedPayload, *, user_id: UUID | None = None,
) -> None: ...

async def _generate_report_inner(...) -> None: ...   # contém a lógica, envolvido com wait_for

async def _resolve_clinic_segment(user_id: UUID | None) -> str: ...
def compose(...) -> ReportPayload: ...
```

**Done when:**
- [ ] `generate_report_pipeline` NUNCA propaga exception (log + persist failure)
- [ ] Captura `asyncio.TimeoutError` → `update_failed(error_code='llm_timeout')`
- [ ] Captura `LLMUnavailable` → `update_failed(error_code='llm_unavailable')`
- [ ] Captura `LLMInvalidResponse` (com 1 retry corretivo) → `update_failed(error_code='llm_invalid_json')`
- [ ] Captura `Exception` genérica → `update_failed(error_code='internal_error')` + `logger.exception`
- [ ] `compose()` une métricas determinísticas + 5 campos LLM + benchmarks (com valores reais da clínica)
- [ ] Em `payload.partial=True`, usa `update_partial` em vez de `update_completed`
- [ ] `_resolve_clinic_segment` busca `users_profile.clinic_segment` via repository auth quando `user_id` setado, senão `'outro'`
- [ ] Hard timeout 120s via `asyncio.wait_for`
- [ ] `py_compile` zero erros

**Tests:** T20.

**Traceability:** REPORT-11, REPORT-13, EC-03, EC-04, EC-05, EC-07.

---

## T12 — Service + Routes + wiring

**What:** `ReportService` fininho + 3 endpoints HTTP + inclusão no `api/router.py`.

**Where:**
- `backend/app/modules/reports/service.py`
- `backend/app/modules/reports/routes.py`
- `backend/app/api/router.py` (adicionar `include_router(reports_router, prefix="/reports")`)

**Depends on:** T2, T8. Pode rodar em paralelo lógico com T10+T11.

**Reuses:** `SuccessResponse[T]`, `get_current_user_id` (F2).

**Endpoints:**

| Método | Path | Auth | Sucesso | Erros |
|---|---|---|---|---|
| GET | `/reports/latest` | Bearer | `200 SuccessResponse[ReportResponse]` | 401, 404 `report_not_found` |
| GET | `/reports/{id}` | Bearer | `200 SuccessResponse[ReportResponse]` | 401, 404 |
| GET | `/reports/` | Bearer | `200 SuccessResponse[ReportListResponse]` (query `?page=1&page_size=20`) | 401 |

**Done when:**
- [ ] `cd backend && ./.venv/Scripts/python.exe -c "from app.main import app; print([r.path for r in app.routes if hasattr(r,'path') and '/reports' in r.path])"` lista os 3 endpoints
- [ ] `pytest app/tests/whatsapp/ -q` + `pytest app/tests/auth/ -q` ainda passam
- [ ] Smoke local: `curl -H "Authorization: Bearer <bad>" .../api/reports/latest` → 401

**Tests:** T21.

**Traceability:** REPORT-16, REPORT-17, REPORT-18.

---

## T13 — F1 integration (extract → trigger worker)

**What:** Em `_finalize_success` e `_finalize_partial` do `extract.py`, disparar `generate_report_pipeline` fire-and-forget.

**Where:** `backend/app/workers/extract.py`

**Depends on:** T11.

**Reuses:** padrão de `_run_extract` em `whatsapp/service.py` (lazy import + asyncio.create_task).

**Done when:**
- [ ] Após `await session_store.set_payload(...)` em `_finalize_success` (e `_finalize_partial`), chama `_kick_off_report(session_id, payload)`
- [ ] `_kick_off_report` faz lazy import de `app.workers.report.generate_report_pipeline`
- [ ] Resolve user_id via `repo.get_session(session_id).user_id` se já estiver linkado (signup chegou antes)
- [ ] Wrap em `asyncio.create_task(...)` com name `report-<sid>` pra observabilidade
- [ ] Falha do create_task NÃO propaga (já isolado por design)
- [ ] `pytest app/tests/whatsapp/ -q` ainda passa

**Tests:** T23 (caso novo: extract success aciona create_task com nome esperado).

**Traceability:** REPORT-11, EC-01, EC-02.

---

## T14 — F2 integration (consume_extracted → link reports.user_id)

**What:** Após `repository.link_user(session_id, user_id)` em `whatsapp.service.consume_extracted`, adicionar `reports_repository.link_user(session_id, user_id)` com tratamento best-effort.

**Where:** `backend/app/modules/whatsapp/service.py`

**Depends on:** T8.

**Reuses:** lazy import de `app.modules.reports.repository`.

**Done when:**
- [ ] Bloco `try/except` envolvendo a chamada, com `logger.warning` em caso de falha
- [ ] Chamada lazy-imported pra evitar circular dep
- [ ] `pytest app/tests/whatsapp/ -q` ainda passa (com novo teste em T23)

**Tests:** T23.

**Traceability:** REPORT-12, EC-01.

---

## T15 — Frontend `lib/reports.js` (hook + fetchers)

**What:** Hook `useReportPolling(idOrLatest)` + helpers fetch.

**Where:** `frontend/src/lib/reports.js`

**Depends on:** T12 (endpoints existem).

**Reuses:** `callApi` (F2), `useEffect/useState/useRef`.

**Done when:**
- [ ] `useReportPolling('latest' | uuid)` retorna `{ status, payload, error, elapsedMs }`
- [ ] Polling de 2s; para em estado terminal (`completed`, `partial`, `failed`)
- [ ] Recupera de blip de rede (continua tentando)
- [ ] Cleanup do timer no unmount via ref `aliveRef`
- [ ] `listReports({ page, pageSize })` helper que chama `/api/reports/?page=...&page_size=...`
- [ ] `cd frontend && npm run build` succeed sem erros

**Tests:** smoke manual na Wave 6.

**Traceability:** REPORT-19, REPORT-19a, EC-09.

---

## T16 — `ReportGeneratingState` component `[P]`

**What:** Componente que renderiza a UI de "gerando relatório" com mensagens rotativas + barra de progresso fake.

**Where:** `frontend/src/screens/dashboard/ReportGeneratingState.jsx`

**Depends on:** T15.

**Reuses:** padrão visual de `GeneratingScreen.jsx` (F1) — gradient dark→ink, orange accent, lucide icons.

**Done when:**
- [ ] Recebe `elapsedMs` via prop; `onRetry` callback opcional
- [ ] Renderiza mensagem baseada em `pickStep(elapsedMs)`:
  - 0-15s: "Analisando suas conversas dos últimos 30 dias…"
  - 15-45s: "Identificando oportunidades e padrões de atendimento…"
  - 45-90s: "Quase lá — finalizando o diagnóstico…"
  - \> 90s: "Está demorando mais que o normal..." + botão "Atualizar"
- [ ] Barra de progresso fake (`fakeProgress(elapsedMs)`): ease-out 0→80% em 60s, depois marca-passo até 95%
- [ ] Identidade visual coerente (não idêntica à F1 GeneratingScreen — título "Análise IA em curso" deixa claro que é fase nova)
- [ ] `npm run build` sem erros, sem warnings novos

**Tests:** smoke manual.

**Traceability:** REPORT-19a.

---

## T17 — Wire dashboard pages (List + Detail) `[P]`

**What:** Substituir mocks em `ReportsListPage` e `ReportDetailPage` por dados reais da API.

**Where:**
- `frontend/src/screens/dashboard/ReportsListPage.jsx`
- `frontend/src/screens/dashboard/ReportDetailPage.jsx`

**Depends on:** T15, T16.

**Reuses:** `listReports`, `useReportPolling` do T15; `ReportGeneratingState` do T16; componentes existentes (`FunnelSection`, `OpportunitiesSection`, etc) que já consomem os shapes corretos.

**Done when:**
- [ ] `ReportsListPage`: substitui `mockReports` por `listReports({ page: 1 })`. Items em `status='generating'` renderizam chip animado no lugar do `score`.
- [ ] `ReportDetailPage`:
  - Se rota for `/app/reports/latest`, usa `useReportPolling('latest')`.
  - Se for `/app/reports/:id`, usa `useReportPolling(id)`.
  - Enquanto `status in ('pending', 'generating')`: renderiza `<ReportGeneratingState elapsedMs={elapsedMs} />`.
  - Em `status='completed'`: passa `payload` pros componentes das 9 seções com props (Funnel recebe `payload.funnel`, Heatmap recebe `payload.heatmap_periods` + `payload.heatmap_days`, etc).
  - Em `status='partial'`: renderiza completo + banner discreto "*análise baseada em parte das conversas".
  - Em `status='failed'`: fallback "Não conseguimos gerar essa análise. [Tentar reconectar o WhatsApp]" linkando pra `/spy`.
- [ ] `npm run build` sem erros

**Tests:** smoke manual.

**Traceability:** REPORT-19, REPORT-20, REPORT-21, EC-09, EC-10.

---

## T18 — `BenchmarkSection` segment-aware `[P]`

**What:** Receber `clinic_segment` via prop, montar label "média de clínicas de {especialidade} conectadas à Medzee*" + footnote no rodapé.

**Where:** `frontend/src/screens/dashboard/components/BenchmarkSection.jsx` (path real pode variar — confirmar)

**Depends on:** T17 (passa o prop).

**Reuses:** estrutura existente do componente.

**Done when:**
- [ ] Aceita props `benchmarks` (array) e `clinicSegment` (string)
- [ ] `SEGMENT_LABEL` mapping: `saude→Saúde`, `odonto→Odonto`, `outro→sua área`
- [ ] Subtitle do card: `Média de clínicas de ${SEGMENT_LABEL[clinicSegment]} conectadas à Medzee*`
- [ ] Footnote no rodapé do card (texto pequeno cinza): `*estimativa baseada em pesquisas setoriais da rede Medzee; atualizado periodicamente conforme a base cresce.`
- [ ] Comportamento existente preservado (renderização das 4 métricas, comparação visual com cor)
- [ ] `npm run build` sem erros

**Tests:** smoke manual.

**Traceability:** REPORT-22, US-04.

---

## T19 — Tests: metrics + sampling + benchmarks `[P]`

**What:** Cobertura unitária das funções puras.

**Where:**
- `backend/app/tests/reports/test_metrics.py`
- `backend/app/tests/reports/test_sampling.py`
- `backend/app/tests/reports/test_benchmarks.py`

**Depends on:** T4, T5, T6, T9.

**Casos prioritários:**

`test_metrics.py`:
- `test_message_count_basic`
- `test_conversation_count_excludes_groups`
- `test_response_time_distribution_classic` — 6 buckets, total bate com pares lead/clinic
- `test_response_time_only_leads_no_responses` — todos 0
- `test_heatmap_period_grouping` — msgs em horários conhecidos caem nos buckets esperados
- `test_funnel_5_stages` — fixture com mensagens contendo "R$ 500" e "agendado" detecta estágios 4 e 5
- `test_funnel_empty_payload`
- `test_score_low_volume` — <50 msgs → score baixo previsível
- `test_score_perfect_clinic` — respostas <5min, conversão 25% → score >85

`test_sampling.py`:
- `test_sample_excludes_groups`
- `test_sample_orders_by_volume`
- `test_sample_respects_budget` — input gigante → corta
- `test_truncate_long_conversation` — 100 msgs → 30 retornadas (head 10 + tail 20)
- `test_short_conversation_passes_through` — <30 msgs sem truncar
- `test_always_returns_at_least_one` — defensive

`test_benchmarks.py`:
- `test_build_benchmarks_saude`
- `test_build_benchmarks_odonto`
- `test_build_benchmarks_outro_fallback` — segment inválido cai pra 'outro'
- `test_market_values_immutable` — `build_benchmarks` não muta `_BENCHMARKS_BY_SEGMENT`

**Done when:**
- [ ] `pytest app/tests/reports/test_metrics.py app/tests/reports/test_sampling.py app/tests/reports/test_benchmarks.py -q` ≥ 16 testes verdes

**Traceability:** REPORT-05, REPORT-06, REPORT-09, REPORT-22.

---

## T20 — Tests: worker + prompts `[P]`

**What:** Cobertura do orquestrador + verificação que o prompt sai bem formatado e o JSON schema é válido.

**Where:**
- `backend/app/tests/reports/test_worker.py`
- `backend/app/tests/reports/test_prompts.py`

**Depends on:** T7, T11, T9.

**Casos prioritários:**

`test_worker.py`:
- `test_worker_happy_path` — fake_llm retorna dict válido → repo.create_generating + update_completed; payload composto bate com schemas
- `test_worker_partial_payload_persists_partial` — `payload.partial=True` → status='partial'
- `test_worker_llm_unavailable_persists_failed` — fake_llm raise `LLMUnavailable` → update_failed('llm_unavailable')
- `test_worker_llm_invalid_json_retries_then_fails` — primeiro raise `LLMInvalidResponse`, segundo igual → update_failed('llm_invalid_json'). Verifica 2 calls.
- `test_worker_llm_invalid_first_then_valid` — primeiro raise, segundo válido → update_completed
- `test_worker_timeout_persists_failed` — fake_llm com sleep > 120 → update_failed('llm_timeout')
- `test_worker_generic_exception_persists_failed` — fake_repo raise no UPDATE → captura, log.exception, update_failed('internal_error')
- `test_worker_clinic_segment_from_user` — user_id setado + clinic_segment='saude' → benchmarks de saúde

`test_prompts.py`:
- `test_get_system_prompt_saude_appends_addendum`
- `test_get_system_prompt_unknown_segment_falls_back_outro`
- `test_build_user_prompt_includes_metrics_and_conversations`
- `test_llm_tool_schema_is_valid_jsonschema` — parse com `jsonschema.Draft7Validator.check_schema()` se a lib estiver disponível, senão asserts manuais (`required` é list, `properties` é dict, etc)

**Done when:**
- [ ] `pytest app/tests/reports/test_worker.py app/tests/reports/test_prompts.py -q` ≥ 12 testes verdes

**Traceability:** REPORT-07, REPORT-08, REPORT-10, REPORT-11, REPORT-13, EC-03, EC-07.

---

## T21 — Tests: service + routes + repository `[P]`

**What:** Cobertura HTTP dos 3 endpoints + service + repository.

**Where:**
- `backend/app/tests/reports/test_service.py`
- `backend/app/tests/reports/test_routes.py`
- `backend/app/tests/reports/test_repository.py`

**Depends on:** T8, T12, T9.

**Casos prioritários:**

`test_repository.py`:
- `test_create_generating_inserts_row`
- `test_update_completed_sets_payload_and_generated_at`
- `test_update_failed_sets_error_code_no_payload`
- `test_link_user_updates_row_when_user_null`
- `test_link_user_no_op_when_already_linked`
- `test_link_user_no_op_when_session_not_found`
- `test_get_by_id_filters_by_user_id` — outro user_id retorna None
- `test_get_latest_for_user`
- `test_list_for_user_pagination`

`test_service.py`:
- `test_get_latest_happy`
- `test_get_latest_returns_404_when_none`
- `test_get_by_id_other_user_returns_404` — não vazar 403
- `test_list_for_user`

`test_routes.py`:
- `test_get_latest_200`
- `test_get_latest_404` — service raises ReportNotFound
- `test_get_by_id_200`
- `test_get_by_id_404_other_user`
- `test_get_list_200`
- `test_get_list_pagination`
- `test_get_without_token_returns_401_or_403`

**Done when:**
- [ ] `pytest app/tests/reports/test_repository.py app/tests/reports/test_service.py app/tests/reports/test_routes.py -q` ≥ 18 testes verdes

**Traceability:** REPORT-16, REPORT-17, REPORT-18, US-02, US-03.

---

## T22 — Tests: LLM Anthropic adapter `[P]`

**What:** Mockar Anthropic API via `respx` e cobrir os 4 cenários principais.

**Where:** `backend/app/tests/reports/test_llm_anthropic.py`

**Depends on:** T3, T9.

**Casos prioritários:**
- `test_anthropic_returns_tool_use_block` — mock 200 com `content=[{type:'tool_use', name:'submit_report', input:{...}}]` → retorna dict
- `test_anthropic_no_tool_use_raises_invalid` — 200 mas sem tool_use → `LLMInvalidResponse`
- `test_anthropic_500_raises_unavailable`
- `test_anthropic_429_raises_unavailable`
- `test_anthropic_400_raises_error` — outros 4xx
- `test_anthropic_timeout_raises_unavailable`
- `test_anthropic_payload_includes_tool_choice` — verifica body do request inclui `tool_choice: {type:'tool', name:'submit_report'}`

**Done when:**
- [ ] `pytest app/tests/reports/test_llm_anthropic.py -q` ≥ 7 testes verdes

**Traceability:** REPORT-07, EC-07.

---

## T23 — Tests: ajustes nos testes whatsapp `[P]`

**What:** Adicionar/ajustar testes nos suites existentes pra cobrir as integrações novas.

**Where:**
- `backend/app/tests/whatsapp/test_extract.py` (caso pro delay + retry 5xx)
- `backend/app/tests/whatsapp/test_service.py` (caso pro link_user em reports)
- `backend/app/tests/whatsapp/test_uazapi_adapter.py` (caso pro `_retry_5xx`)

**Depends on:** T10, T13, T14.

**Casos:**

`test_extract.py`:
- `test_extract_waits_5s_before_first_chat_find` — ajustar fixture pra `_DELAY_S=0` no modo de teste e/ou usar `freezegun`/monkeypatch direto na constante
- `test_extract_kicks_off_report_generation` — após `_finalize_success`, verifica que `asyncio.create_task` foi chamado com name `report-<sid>`

`test_service.py`:
- `test_consume_extracted_links_user_in_reports` — verifica que `reports.repository.link_user` foi chamado com `(session_id, user_id)` corretos
- `test_consume_extracted_swallows_reports_link_failure` — `reports.repository.link_user` raises → service não propaga, só warning

`test_uazapi_adapter.py`:
- `test_list_chats_retries_on_5xx` — respx serve 500, 500, 200 → retorna no 3º
- `test_list_chats_retry_exhausted` — 4× 500 → raise `UazapiUnavailable`
- `test_list_chats_4xx_no_retry` — 400 → raise imediato

**Done when:**
- [ ] `pytest app/tests/whatsapp/ -q` ≥ 60+ testes verdes (era 56, +4-5 novos)

**Traceability:** REPORT-11, REPORT-12, REPORT-14, REPORT-15, US-05.

---

## Smoke ponta-a-ponta (manual, pós-Wave 7)

Não é uma task formal. Gate final antes de fechar F3:

1. `cd frontend && npm run dev` (ou Railway deployado) → abre `/spy`
2. Scaneia QR no celular real (ou usa instância de teste do uazapi)
3. Aguarda `connected` → frontend transiciona pra `GeneratingScreen` (F1)
4. Preenche `LeadFormScreen` → submit
5. **Frontend vai pra `/app/reports/latest`**:
   - Se LLM ainda gerando: aparece `ReportGeneratingState` com mensagens rotativas
   - Em 30-60s: vira o relatório real com 9 seções populadas
6. Verifica no Supabase:
   - `medzee_spy.reports` tem row com `user_id` do signup, `status='completed'`, `payload` jsonb populado, `model='claude-sonnet-4-6'`, `prompt_version='v1.0.0'`
7. Vai pra `/app/reports/` → lista mostra o report novo
8. Clica → `/app/reports/:id` → renderiza igual ao `latest`
9. **Cenário negativo:** desliga ANTHROPIC_API_KEY temporariamente, tenta de novo → report fica `status='failed'`, frontend mostra fallback gentil + link pra `/spy`

Se tudo passar: **F3 ✅ DONE**.

## Cobertura por requisito

| REPORT | Implementação | Teste |
|---|---|---|
| REPORT-01..04 | T1 | T21 |
| REPORT-05..06 | T4 | T19 |
| REPORT-07 | T3, T7, T11 | T20, T22 |
| REPORT-08 | T7 | T20 |
| REPORT-09 | T5 | T19 |
| REPORT-10 | T7, T11 | T20 |
| REPORT-11 | T11, T13 | T20, T23 |
| REPORT-12 | T14 | T23 |
| REPORT-13 | T11 | T20 |
| REPORT-14 | T10 | T23 |
| REPORT-15 | T10 | T23 |
| REPORT-16 | T12 | T21 |
| REPORT-17 | T12 | T21 |
| REPORT-18 | T12 | T21 |
| REPORT-19 | T15, T17 | smoke |
| REPORT-19a | T15, T16 | smoke |
| REPORT-20 | T17 | smoke |
| REPORT-21 | T17 | smoke |
| REPORT-22 | T6, T18 | T19, smoke |

## Notas operacionais

- **Sub-agents:** Wave 2 (T3..T9) é o maior candidato (7 [P]). Wave 6 frontend (T16..T18). Wave 7 testes (T19..T23). Cuidado com Wave 2: T9 (scaffold) deve sair em paralelo mas as fixtures importam `app.modules.reports.repository.*` que podem não existir ainda — usar `monkeypatch.setattr` com string-path resolve isso (mesmo padrão da F2).
- **LLM cost:** rodar smoke local com 1-2 sessões antes do deploy. Cada relatório custa ~$0.10-0.25 com Claude Sonnet 4.6 dependendo do volume. Monitorar `prompt_tokens` em prod no futuro.
- **Smoke F1+F2 ainda funcional?** Antes de começar F3 código, rodar `pytest backend/app/tests/ -q` → deve ser 95/95.
- **Anthropic SDK ou httpx?** Optamos por httpx direto pra não adicionar dependência. SDK só faria sentido se usarmos features avançadas (streaming, prompt caching) — backlog.
- **Pula T18 se BenchmarkSection.jsx não existe** ainda como arquivo isolado — em alguns mocks o conteúdo do benchmark vive inline no `ReportDetailPage`. Confirmar via grep antes do agent começar.
